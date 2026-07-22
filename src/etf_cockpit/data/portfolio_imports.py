"""Local-first, append-only portfolio import staging and reconciliation.

The ledger deliberately stores imported evidence separately from calculated
holdings.  Holdings and cash are projections rebuilt from zero, which makes
rollback and corrected broker statements deterministic and auditable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping
import uuid
from xml.etree import ElementTree
from xml.sax.saxutils import escape
import zipfile

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.data.identity_master import (
    IdentityMasterSchemaError,
    IdentityMasterStore,
)
from etf_cockpit.data.import_export import ImportPreview, ImportService
from etf_cockpit.data.local_storage import StorageSchemaError, TransactionalStore


PORTFOLIO_IMPORT_CONTRACT = "portfolio-import.v1"
_BATCH_TYPE = "portfolio_import_batch_v1"
_EVENT_TYPE = "portfolio_import_event_v1"
_ROLLBACK_TYPE = "portfolio_import_rollback_v1"

RECORD_TYPES = frozenset(
    {
        "price",
        "account",
        "cash",
        "transaction",
        "transfer",
        "fee",
        "tax",
        "fx",
        "lot",
        "income",
        "corporate_action",
    }
)
_INSTRUMENT_RECORDS = frozenset(
    {"price", "transaction", "lot", "income", "corporate_action"}
)
_CASH_RECORDS = frozenset({"cash", "transaction", "transfer", "fee", "tax", "income"})
_ALIASES = {
    "type": "record_type",
    "event_type": "record_type",
    "transaction_type": "record_type",
    "trade_date": "occurred_at",
    "date": "occurred_at",
    "timestamp": "occurred_at",
    "account": "account_id",
    "account_number": "account_id",
    "symbol": "instrument_id",
    "ticker": "instrument_id",
    "security_id": "instrument_id",
    "source_reference": "source_id",
    "transaction_id": "source_id",
    "trade_id": "source_id",
    "units": "quantity",
    "shares": "quantity",
    "amount": "cash_amount",
    "net_amount": "settlement_cash",
    "face": "face_value",
    "face_amount": "face_value",
    "notional": "notional_value",
}
_RECORD_TYPE_ALIASES = {
    "buy": "transaction",
    "sell": "transaction",
    "trade": "transaction",
    "dividend": "income",
    "distribution": "income",
    "deposit": "cash",
    "withdrawal": "cash",
    "commission": "fee",
    "withholding_tax": "tax",
    "split": "corporate_action",
    "fx_conversion": "fx",
}
CANONICAL_COLUMNS = (
    "record_type",
    "source_id",
    "occurred_at",
    "account_id",
    "instrument_id",
    "currency",
    "quantity",
    "cash_amount",
    "settlement_cash",
    "price",
    "adjusted_close",
    "fx_rate",
    "from_currency",
    "from_amount",
    "to_currency",
    "to_amount",
    "face_value",
    "notional_value",
    "clean_price",
    "accrued_interest",
    "corporate_action_type",
    "description",
)


class PortfolioImportError(RuntimeError):
    """Raised when portfolio evidence cannot be safely staged or committed."""


@dataclass(frozen=True)
class PortfolioCommitResult:
    batch_id: str
    accepted: int
    quarantined: int
    duplicates: int
    corrections: int
    status: str = "committed"
    execution_allowed: bool = False


@dataclass(frozen=True)
class PortfolioRebuild:
    holdings: pd.DataFrame
    cash: pd.DataFrame
    active_events: pd.DataFrame
    quarantined: pd.DataFrame
    balanced: bool
    execution_allowed: bool = False


_PREVIEWS: dict[str, ImportPreview] = {}


class PortfolioImportStore:
    """Durable portfolio import store backed by the canonical ACID database."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def preview(self, path: Path, *, source_format: str = "canonical") -> ImportPreview:
        source = Path(path).resolve()
        preview_id = f"portfolio_{uuid.uuid4().hex[:12]}"
        try:
            raw = _read_table(source)
            frame = _normalise_frame(raw, source_format=source_format)
            frame = self._classify(frame)
            errors: list[str] = []
            if frame.empty:
                errors.append("empty_file")
            checksum = _frame_checksum(frame)
            source_checksum = _file_checksum(source)
            warnings = (
                f"source_sha256:{source_checksum}",
                f"accepted:{int(frame['staging_status'].isin(['accepted', 'correction']).sum()) if not frame.empty else 0}",
                f"quarantined:{int(frame['staging_status'].eq('quarantined').sum()) if not frame.empty else 0}",
                f"duplicates:{int(frame['staging_status'].eq('duplicate').sum()) if not frame.empty else 0}",
                "execution_allowed=false",
            )
            preview = ImportPreview(
                preview_id=preview_id,
                import_type="portfolio_history",
                path=source,
                valid=not errors,
                rows=len(frame),
                columns=tuple(str(column) for column in frame.columns),
                errors=tuple(errors),
                frame=frame.copy(deep=True),
                warnings=warnings,
                checksum=checksum,
            )
        except Exception as exc:
            preview = ImportPreview(
                preview_id,
                "portfolio_history",
                source,
                False,
                0,
                (),
                (f"read_failed:{type(exc).__name__}:{exc}",),
                pd.DataFrame(),
            )
        _PREVIEWS[preview.preview_id] = preview
        # Reuse the established preview registry contract. Portfolio commits
        # remain here because the generic service has no historical ledger.
        ImportService(self.root).register(preview)
        return preview

    def commit(self, preview: ImportPreview | str) -> PortfolioCommitResult:
        item = _PREVIEWS.get(preview) if isinstance(preview, str) else preview
        if item is None or not item.valid or item.import_type != "portfolio_history":
            raise PortfolioImportError("a valid portfolio dry-run preview is required")
        if _frame_checksum(item.frame) != item.checksum:
            raise PortfolioImportError("portfolio preview checksum verification failed")
        batch_id = f"batch-{item.checksum[:24]}"
        with TransactionalStore(self.root) as store:
            if store.get(_BATCH_TYPE, batch_id) is not None:
                statuses = item.frame["staging_status"]
                return PortfolioCommitResult(
                    batch_id=batch_id,
                    accepted=int(statuses.isin(["accepted", "correction"]).sum()),
                    quarantined=int(statuses.eq("quarantined").sum()),
                    duplicates=int(statuses.eq("duplicate").sum()),
                    corrections=int(statuses.eq("correction").sum()),
                    status="idempotent",
                )
        expected_source = _warning_value(item.warnings, "source_sha256")
        if not item.path.is_file() or _file_checksum(item.path) != expected_source:
            raise PortfolioImportError(
                "portfolio source changed after preview; run dry-run again"
            )
        validated = self._classify(
            _normalise_frame(_read_table(item.path), source_format="canonical")
        )
        if _frame_checksum(validated) != item.checksum:
            raise PortfolioImportError(
                "portfolio source content no longer matches the staged preview"
            )

        rows = item.frame.to_dict(orient="records")
        event_records: list[tuple[str, str, Mapping[str, Any]]] = []
        event_ids: list[str] = []
        for row in rows:
            clean = _json_row(row)
            content_hash = str(clean["content_hash"])
            event_id = hashlib.sha256(
                f"{batch_id}\0{clean['source_id']}\0{content_hash}".encode()
            ).hexdigest()
            clean.update(
                {
                    "contract": PORTFOLIO_IMPORT_CONTRACT,
                    "batch_id": batch_id,
                    "event_id": event_id,
                    "execution_allowed": False,
                }
            )
            event_ids.append(event_id)
            event_records.append((_EVENT_TYPE, event_id, clean))
        batch = {
            "contract": PORTFOLIO_IMPORT_CONTRACT,
            "batch_id": batch_id,
            "source_name": item.path.name,
            "source_sha256": expected_source,
            "preview_checksum": item.checksum,
            "event_ids": event_ids,
            "execution_allowed": False,
        }
        try:
            with TransactionalStore(self.root) as store:
                store.put_many(
                    ((_BATCH_TYPE, batch_id, batch), *event_records), immutable=True
                )
        except (StorageSchemaError, OSError, ValueError) as exc:
            raise PortfolioImportError(
                f"portfolio commit rejected atomically: {exc}"
            ) from exc
        statuses = item.frame["staging_status"]
        return PortfolioCommitResult(
            batch_id=batch_id,
            accepted=int(statuses.isin(["accepted", "correction"]).sum()),
            quarantined=int(statuses.eq("quarantined").sum()),
            duplicates=int(statuses.eq("duplicate").sum()),
            corrections=int(statuses.eq("correction").sum()),
        )

    def rollback(self, batch_id: str, *, reason: str) -> bool:
        batch_key = str(batch_id).strip()
        explanation = str(reason).strip()
        if not batch_key or not explanation:
            raise ValueError("batch_id and rollback reason are required")
        with TransactionalStore(self.root) as store:
            if store.get(_BATCH_TYPE, batch_key) is None:
                raise KeyError(f"portfolio import batch unavailable: {batch_key}")
            rollback_id = hashlib.sha256(
                f"{batch_key}\0{explanation}".encode()
            ).hexdigest()
            store.put_many(
                (
                    (
                        _ROLLBACK_TYPE,
                        rollback_id,
                        {
                            "contract": PORTFOLIO_IMPORT_CONTRACT,
                            "batch_id": batch_key,
                            "reason": explanation,
                            "execution_allowed": False,
                        },
                    ),
                ),
                immutable=True,
            )
        return True

    def rebuild(self) -> PortfolioRebuild:
        events = self._active_events()
        quarantined = events.loc[
            events.get("staging_status", pd.Series(dtype=str)).eq("quarantined")
        ].copy()
        active = events.loc[
            events.get("staging_status", pd.Series(dtype=str)).isin(
                ["accepted", "correction"]
            )
        ].copy()
        holdings: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
        cash: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for row in active.sort_values(
            ["occurred_at", "source_id", "content_hash"], kind="stable"
        ).to_dict(orient="records"):
            record_type = str(row["record_type"])
            account_id = str(row.get("account_id") or "default")
            instrument_id = str(row.get("instrument_id") or "")
            currency = str(row.get("currency") or "").upper()
            if (
                record_type in {"transaction", "lot", "corporate_action"}
                and instrument_id
            ):
                holdings[(account_id, instrument_id)] += _decimal(
                    row.get("quantity"), default=Decimal(0)
                )
            if record_type in _CASH_RECORDS and currency:
                amount = (
                    row.get("settlement_cash")
                    if record_type == "transaction"
                    else row.get("cash_amount")
                )
                cash[(account_id, currency)] += _decimal(amount, default=Decimal(0))
            if record_type == "fx":
                from_currency = str(row.get("from_currency") or "").upper()
                to_currency = str(row.get("to_currency") or "").upper()
                if from_currency:
                    cash[(account_id, from_currency)] += _decimal(
                        row.get("from_amount"), default=Decimal(0)
                    )
                if to_currency:
                    cash[(account_id, to_currency)] += _decimal(
                        row.get("to_amount"), default=Decimal(0)
                    )
        holdings_frame = pd.DataFrame(
            [
                {
                    "account_id": account,
                    "instrument_id": instrument,
                    "quantity": float(quantity),
                }
                for (account, instrument), quantity in sorted(holdings.items())
                if quantity != 0
            ],
            columns=["account_id", "instrument_id", "quantity"],
        )
        cash_frame = pd.DataFrame(
            [
                {
                    "account_id": account,
                    "currency": currency,
                    "cash_balance": float(amount),
                }
                for (account, currency), amount in sorted(cash.items())
                if amount != 0
            ],
            columns=["account_id", "currency", "cash_balance"],
        )
        return PortfolioRebuild(
            holdings_frame, cash_frame, active, quarantined, quarantined.empty
        )

    def export_canonical(self, destination: Path) -> Path:
        rebuilt = self.rebuild()
        frame = rebuilt.active_events.reindex(columns=CANONICAL_COLUMNS).copy()
        for column in frame.select_dtypes(include=["object", "string"]).columns:
            frame[column] = frame[column].map(_spreadsheet_safe)
        target = Path(destination)
        if target.suffix.lower() not in {".csv", ".xlsx"}:
            raise ValueError("canonical portfolio export must be CSV or XLSX")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() == ".csv":
            atomic_write_bytes(
                target,
                frame.to_csv(index=False).encode("utf-8"),
                lambda path: pd.read_csv(path),
            )
        else:
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp.xlsx")
            try:
                _write_xlsx(temporary, frame)
                _read_xlsx(temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    def batches(self) -> tuple[dict[str, Any], ...]:
        with TransactionalStore(self.root) as store:
            rolled_back = {
                str(record.payload["batch_id"]) for record in store.list(_ROLLBACK_TYPE)
            }
            return tuple(
                dict(record.payload) | {"rolled_back": record.entity_id in rolled_back}
                for record in store.list(_BATCH_TYPE)
            )

    def _active_events(self) -> pd.DataFrame:
        try:
            with TransactionalStore(self.root) as store:
                integrity = store.integrity()
                if not integrity.ok:
                    raise PortfolioImportError(
                        "portfolio storage integrity check failed"
                    )
                rollbacks = {
                    str(record.payload["batch_id"])
                    for record in store.list(_ROLLBACK_TYPE)
                }
                batch_order = {
                    record.entity_id: (record.created_at, record.entity_id)
                    for record in store.list(_BATCH_TYPE)
                }
                rows = [
                    dict(record.payload)
                    for record in store.list(_EVENT_TYPE)
                    if str(record.payload.get("batch_id")) not in rollbacks
                ]
        except (StorageSchemaError, sqlite3.DatabaseError, OSError) as exc:
            raise PortfolioImportError(f"portfolio storage unavailable: {exc}") from exc
        if not rows:
            return pd.DataFrame(
                columns=(
                    *CANONICAL_COLUMNS,
                    "staging_status",
                    "content_hash",
                    "batch_id",
                )
            )
        # Corrections are append-only. Select the latest surviving evidence for
        # each provider source ID; rolling back a correction reactivates the
        # preceding surviving version.
        rows.sort(
            key=lambda row: (
                *batch_order.get(str(row["batch_id"]), ("", "")),
                str(row["content_hash"]),
            )
        )
        latest: dict[str, dict[str, Any]] = {}
        quarantined: dict[str, dict[str, Any]] = {}
        for row in rows:
            status = str(row.get("staging_status"))
            if status in {"accepted", "correction"}:
                latest[str(row["source_id"])] = row
            elif status == "quarantined":
                quarantined[str(row["event_id"])] = row
        return pd.DataFrame([*latest.values(), *quarantined.values()])

    def _classify(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.assign(
                staging_status=pd.Series(dtype=str),
                quarantine_reason=pd.Series(dtype=str),
                content_hash=pd.Series(dtype=str),
            )
        existing = self._existing_by_source()
        seen: dict[str, str] = {}
        statuses: list[str] = []
        reasons: list[str] = []
        hashes: list[str] = []
        identity_store: IdentityMasterStore | None = None
        try:
            identity_store = IdentityMasterStore(self.root)
        except (IdentityMasterSchemaError, OSError):
            identity_store = None
        try:
            for row in frame.to_dict(orient="records"):
                content_hash = _content_hash(row)
                hashes.append(content_hash)
                source_id = str(row["source_id"])
                reason = _row_error(row)
                if not reason and str(row["record_type"]) in _INSTRUMENT_RECORDS:
                    reason = _identity_error(
                        identity_store,
                        str(row.get("instrument_id") or ""),
                        str(row["occurred_at"]),
                    )
                if reason:
                    statuses.append("quarantined")
                    reasons.append(reason)
                elif source_id in seen:
                    statuses.append(
                        "duplicate"
                        if seen[source_id] == content_hash
                        else "quarantined"
                    )
                    reasons.append(
                        "duplicate_in_file"
                        if seen[source_id] == content_hash
                        else "conflicting_source_id_in_file"
                    )
                elif source_id in existing:
                    statuses.append(
                        "duplicate"
                        if existing[source_id] == content_hash
                        else "correction"
                    )
                    reasons.append(
                        "same_source_and_content"
                        if existing[source_id] == content_hash
                        else "supersedes_prior_content"
                    )
                else:
                    statuses.append("accepted")
                    reasons.append("")
                seen[source_id] = content_hash
        finally:
            if identity_store is not None:
                identity_store.close()
        result = frame.copy()
        result["staging_status"] = statuses
        result["quarantine_reason"] = reasons
        result["content_hash"] = hashes
        result["execution_allowed"] = False
        return result

    def _existing_by_source(self) -> dict[str, str]:
        frame = self._active_events()
        if frame.empty:
            return {}
        return {
            str(row["source_id"]): str(row["content_hash"])
            for row in frame.to_dict(orient="records")
        }


def _read_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=object)
    if suffix == ".xlsx":
        try:
            return pd.read_excel(path, dtype=object)
        except ImportError:
            return _read_xlsx(path)
    if suffix == ".xls":
        raise ValueError(
            "legacy binary XLS is unsupported; save as canonical XLSX or CSV"
        )
    raise ValueError("portfolio imports support canonical or broker CSV/XLSX only")


def _normalise_frame(frame: pd.DataFrame, *, source_format: str) -> pd.DataFrame:
    if str(source_format).strip().lower() not in {
        "canonical",
        "broker",
        "broker_csv",
        "canonical_csv",
        "canonical_xlsx",
    }:
        raise ValueError(f"unsupported portfolio source format: {source_format}")
    renamed: dict[object, str] = {}
    for column in frame.columns:
        key = str(column).strip().lower().replace(" ", "_").replace("-", "_")
        renamed[column] = _ALIASES.get(key, key)
    result = frame.rename(columns=renamed).copy()
    duplicate_columns = result.columns[result.columns.duplicated()].tolist()
    if duplicate_columns:
        raise ValueError(
            f"duplicate canonical columns after mapping: {duplicate_columns}"
        )
    if (
        "record_type" not in result
        or "source_id" not in result
        or "occurred_at" not in result
    ):
        raise ValueError(
            "portfolio import requires record_type, source_id and occurred_at"
        )
    for column in CANONICAL_COLUMNS:
        if column not in result:
            result[column] = None
    result = result.loc[:, list(CANONICAL_COLUMNS)]
    for column in result.columns:
        result[column] = result[column].map(_clean_value)
    result["record_type"] = result["record_type"].map(_normalise_record_type)
    result["source_id"] = result["source_id"].map(lambda value: str(value).strip())
    timestamps = pd.to_datetime(result["occurred_at"], errors="coerce", utc=True)
    result["occurred_at"] = timestamps.map(
        lambda value: value.isoformat() if not pd.isna(value) else ""
    )
    for column in (
        "quantity",
        "cash_amount",
        "settlement_cash",
        "price",
        "adjusted_close",
        "fx_rate",
        "from_amount",
        "to_amount",
        "face_value",
        "notional_value",
        "clean_price",
        "accrued_interest",
    ):
        result[column] = result[column].map(_normalise_number)
    return result


def _row_error(row: Mapping[str, Any]) -> str:
    record_type = str(row.get("record_type") or "")
    if record_type not in RECORD_TYPES:
        return "unsupported_record_type"
    if not str(row.get("source_id") or ""):
        return "missing_source_id"
    if not str(row.get("occurred_at") or ""):
        return "invalid_occurred_at"
    if record_type != "price" and not str(row.get("account_id") or ""):
        return "missing_account_id"
    if record_type in _INSTRUMENT_RECORDS and not str(row.get("instrument_id") or ""):
        return "missing_instrument_identity"
    if record_type in _CASH_RECORDS and not str(row.get("currency") or ""):
        return "missing_currency"
    if record_type == "price" and row.get("adjusted_close") is None:
        return "missing_adjusted_close"
    if record_type == "transaction":
        if _missing(row.get("quantity")) or _missing(row.get("settlement_cash")):
            return "unbalanced_transaction"
    if record_type in {"cash", "transfer", "fee", "tax", "income"} and _missing(
        row.get("cash_amount")
    ):
        return "unbalanced_cash_event"
    if record_type == "fx":
        if any(
            _missing(row.get(name))
            for name in ("from_currency", "from_amount", "to_currency", "to_amount")
        ):
            return "unbalanced_fx"
        if (
            _decimal(row.get("from_amount"), default=Decimal(0))
            * _decimal(row.get("to_amount"), default=Decimal(0))
            >= 0
        ):
            return "unbalanced_fx_signs"
    bond_values = [
        row.get(name)
        for name in ("face_value", "notional_value", "clean_price", "accrued_interest")
    ]
    if any(not _missing(value) for value in bond_values):
        notional = (
            row.get("face_value")
            if _missing(row.get("notional_value"))
            else row.get("notional_value")
        )
        if any(
            _missing(value)
            for value in (
                notional,
                row.get("clean_price"),
                row.get("accrued_interest"),
                row.get("settlement_cash"),
            )
        ):
            return "incomplete_bond_settlement"
        quantity = _decimal(row.get("quantity"), default=Decimal(0))
        direction = Decimal(-1) if quantity >= 0 else Decimal(1)
        expected = direction * (
            _decimal(notional) * _decimal(row.get("clean_price")) / Decimal(100)
            + _decimal(row.get("accrued_interest"))
        )
        actual = _decimal(row.get("settlement_cash"))
        if abs(expected - actual) > max(
            Decimal("0.01"), abs(expected) * Decimal("0.000001")
        ):
            return "unbalanced_bond_settlement"
    return ""


def _normalise_record_type(value: object) -> str:
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return _RECORD_TYPE_ALIASES.get(key, key)


def _identity_error(
    store: IdentityMasterStore | None, instrument_id: str, occurred_at: str
) -> str:
    if store is None:
        return "identity_master_unavailable"
    try:
        resolution = store.resolve(
            instrument_id, effective_at=occurred_at, decision_time=occurred_at
        )
    except (KeyError, ValueError, IdentityMasterSchemaError):
        return "identity_unresolved"
    if resolution.requires_manual_review or resolution.resolution_state != "resolved":
        return "identity_ambiguous"
    return ""


def _content_hash(row: Mapping[str, Any]) -> str:
    payload = {column: _json_value(row.get(column)) for column in CANONICAL_COLUMNS}
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _frame_checksum(frame: pd.DataFrame) -> str:
    payload = (
        frame.reset_index(drop=True)
        .sort_index(axis=1)
        .to_json(orient="records", date_format="iso", date_unit="ns")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _warning_value(warnings: Iterable[str], key: str) -> str:
    prefix = f"{key}:"
    return next(
        (warning[len(prefix) :] for warning in warnings if warning.startswith(prefix)),
        "",
    )


def _clean_value(value: object) -> object:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return value.strip() if isinstance(value, str) else value


def _missing(value: object) -> bool:
    return (
        value is None
        or value == ""
        or (not isinstance(value, str) and bool(pd.isna(value)))
    )


def _normalise_number(value: object) -> float | None:
    if value is None or value == "" or (not isinstance(value, str) and pd.isna(value)):
        return None
    try:
        return float(Decimal(str(value).replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def _decimal(value: object, *, default: Decimal | None = None) -> Decimal:
    if value is None or value == "" or (not isinstance(value, str) and pd.isna(value)):
        if default is not None:
            return default
        raise ValueError("numeric value is required")
    return Decimal(str(value))


def _json_value(value: object) -> object:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _json_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in row.items()}


def _spreadsheet_safe(value: object) -> object:
    if not isinstance(value, str):
        return value
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def _read_xlsx(path: Path) -> pd.DataFrame:
    """Read the first worksheet from an OOXML workbook without optional deps."""

    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.text or "" for node in item.iter(f"{namespace}t"))
                    for item in root
                ]
            sheet_name = sorted(
                name
                for name in names
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )[0]
            sheet = ElementTree.fromstring(archive.read(sheet_name))
    except (IndexError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError(f"invalid canonical XLSX workbook: {exc}") from exc
    rows: list[dict[int, object]] = []
    for row in sheet.iter(f"{namespace}row"):
        values: dict[int, object] = {}
        for cell in row.findall(f"{namespace}c"):
            reference = str(cell.attrib.get("r", "A1"))
            column_index = _column_index(
                "".join(character for character in reference if character.isalpha())
            )
            kind = cell.attrib.get("t", "n")
            value_node = cell.find(f"{namespace}v")
            if kind == "inlineStr":
                inline = cell.find(f"{namespace}is")
                value: object = (
                    ""
                    if inline is None
                    else "".join(
                        node.text or "" for node in inline.iter(f"{namespace}t")
                    )
                )
            elif value_node is None:
                value = None
            elif kind == "s":
                value = shared[int(value_node.text or "0")]
            elif kind in {"str", "b"}:
                value = value_node.text or ""
            else:
                raw = value_node.text or ""
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
            values[column_index] = value
        rows.append(values)
    if not rows:
        return pd.DataFrame()
    width = max((max(row, default=-1) for row in rows), default=-1) + 1
    header = [str(rows[0].get(index, "")).strip() for index in range(width)]
    if any(not name for name in header):
        raise ValueError("canonical XLSX header contains blank columns")
    return pd.DataFrame(
        [{header[index]: row.get(index) for index in range(width)} for row in rows[1:]],
        columns=header,
    )


def _write_xlsx(path: Path, frame: pd.DataFrame) -> None:
    """Write one canonical inline-string OOXML worksheet without macros."""

    rows = [
        list(map(str, frame.columns)),
        *frame.where(pd.notna(frame), None).values.tolist(),
    ]
    xml_rows: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_number, value in enumerate(row, start=1):
            if value is None:
                continue
            reference = f"{_column_name(column_number)}{row_number}"
            if isinstance(value, bool):
                cells.append(f'<c r="{reference}" t="b"><v>{int(value)}</v></c>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + "".join(xml_rows)
        + "</sheetData></worksheet>"
    )
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Portfolio History" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload.encode("utf-8"))


def _column_index(name: str) -> int:
    result = 0
    for character in name.upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name
