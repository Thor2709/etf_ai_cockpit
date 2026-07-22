"""Local-first, append-only portfolio import staging and reconciliation.

The ledger deliberately stores imported evidence separately from calculated
holdings.  Holdings and cash are projections rebuilt from zero, which makes
rollback and corrected broker statements deterministic and auditable.
"""

from __future__ import annotations

from collections import defaultdict
import base64
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping
import uuid
from datetime import datetime, timezone
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
_STAGE_TYPE = "portfolio_import_stage_v1"
_IDENTITY_CLAIM_TYPE = "identity_claim_v1"
_MAX_RAW_SOURCE_BYTES = 25 * 1024 * 1024
_CURRENCY_REGISTRY_VERSION = "ISO4217-local-2026-07"
_ACTIVE_CURRENCIES = frozenset(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XDR XOF XPD XPF XPT XSU XUA YER ZAR ZMW ZWG".split()
)
_WITHDRAWN_CURRENCIES = {
    "DEM": "2002-03-01T00:00:00Z",
    "FRF": "2002-03-01T00:00:00Z",
    "ITL": "2002-03-01T00:00:00Z",
    "RUR": "1998-01-01T00:00:00Z",
    "ZWL": "2024-09-01T00:00:00Z",
}
_CURRENCY_ALIASES = {
    "US DOLLAR": ("USD",),
    "EURO": ("EUR",),
    "$": ("AUD", "CAD", "NZD", "USD"),
}

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
    "symbol": "ticker",
    "ticker": "ticker",
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
    "action": "side",
    "buy_sell": "side",
    "commission_amount": "fee_amount",
    "taxes": "tax_amount",
    "venue": "mic",
    "exchange": "mic",
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
    "provider_id",
    "source_system",
    "record_type",
    "source_id",
    "predecessor_content_hash",
    "predecessor_revision",
    "source_revision",
    "occurred_at",
    "decision_time",
    "account_id",
    "instrument_id",
    "raw_instrument_id",
    "ticker",
    "isin",
    "listing_id",
    "mic",
    "currency",
    "currency_identity",
    "side",
    "quantity",
    "cash_amount",
    "settlement_cash",
    "fee_amount",
    "tax_amount",
    "price",
    "adjusted_close",
    "fx_rate",
    "from_currency",
    "from_currency_identity",
    "from_amount",
    "to_currency",
    "to_currency_identity",
    "to_amount",
    "face_value",
    "notional_value",
    "clean_price",
    "accrued_interest",
    "corporate_action_type",
    "ratio_numerator",
    "ratio_denominator",
    "lot_role",
    "transfer_id",
    "transfer_leg",
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
    reconciliation_errors: tuple[str, ...] = ()
    execution_allowed: bool = False


_PREVIEWS: dict[str, ImportPreview] = {}


class PortfolioImportStore:
    """Durable portfolio import store backed by the canonical ACID database."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def preview(
        self,
        path: Path,
        *,
        source_format: str = "canonical",
        numeric_locale: str = "en_US",
        source_system: str | None = None,
        provider_id: str | None = None,
    ) -> ImportPreview:
        source = Path(path).resolve()
        preview_id = f"portfolio_{uuid.uuid4().hex}"
        decision_time = datetime.now(timezone.utc).isoformat()
        try:
            raw_bytes = source.read_bytes()
            if len(raw_bytes) > _MAX_RAW_SOURCE_BYTES:
                raise ValueError(
                    "portfolio source exceeds the 25 MiB local staging limit"
                )
            raw = _read_table(source)
            frame = _normalise_frame(
                raw,
                source_format=source_format,
                numeric_locale=numeric_locale,
                source_system=source_system,
                provider_id=provider_id,
                decision_time=decision_time,
            )
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
                f"numeric_locale:{numeric_locale}",
                f"source_format:{source_format}",
                f"decision_time:{decision_time}",
                f"currency_registry:{_CURRENCY_REGISTRY_VERSION}",
                "mapping_version:1",
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
            self._persist_stage(
                preview,
                raw_bytes=raw_bytes,
                source_format=source_format,
                numeric_locale=numeric_locale,
                mapping_version=1,
                mapping_decisions=(),
                parent_preview_id="",
                decision_time=decision_time,
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
        supplied = None if isinstance(preview, str) else preview
        preview_id = preview if isinstance(preview, str) else preview.preview_id
        item = self._load_stage_preview(preview_id)
        if item is None or not item.valid or item.import_type != "portfolio_history":
            raise PortfolioImportError("a valid portfolio dry-run preview is required")
        stage = self._verified_stage(item.preview_id)
        if supplied is not None and not _preview_matches_stage(supplied, item):
            raise PortfolioImportError(
                "supplied portfolio preview does not match the verified durable stage"
            )
        if _frame_checksum(item.frame) != item.checksum:
            raise PortfolioImportError("portfolio preview checksum verification failed")
        expected_source = _warning_value(item.warnings, "source_sha256")
        raw_bytes = base64.b64decode(str(stage["raw_source_base64"]), validate=True)
        if hashlib.sha256(raw_bytes).hexdigest() != expected_source:
            raise PortfolioImportError(
                "staging integrity failure: raw source checksum mismatch"
            )
        if item.path.is_file() and _file_checksum(item.path) != expected_source:
            raise PortfolioImportError(
                "portfolio source changed after preview; run dry-run again"
            )
        statuses = item.frame["staging_status"]
        if statuses.eq("duplicate").all():
            return PortfolioCommitResult(
                batch_id="",
                accepted=0,
                quarantined=0,
                duplicates=len(item.frame),
                corrections=0,
                status="no_op",
            )

        rows = [
            row
            for row in item.frame.to_dict(orient="records")
            if row["staging_status"] != "duplicate"
        ]
        provisional_batch = hashlib.sha256(
            f"{item.preview_id}\0{item.checksum}".encode()
        ).hexdigest()
        batch_id = f"batch-{provisional_batch[:32]}"
        event_payloads: list[tuple[str, dict[str, Any]]] = []
        event_ids: list[str] = []
        for row in rows:
            clean = _json_row(row)
            content_hash = str(clean["content_hash"])
            event_id = hashlib.sha256(
                f"{batch_id}\0{clean['event_key']}\0{content_hash}".encode()
            ).hexdigest()
            clean.update(
                {
                    "contract": PORTFOLIO_IMPORT_CONTRACT,
                    "batch_id": batch_id,
                    "event_id": event_id,
                    "execution_allowed": False,
                }
            )
            clean["event_hash"] = _payload_hash(clean)
            event_ids.append(event_id)
            event_payloads.append((event_id, clean))
        membership_hash = _membership_hash(event_payloads)
        batch = {
            "contract": PORTFOLIO_IMPORT_CONTRACT,
            "batch_id": batch_id,
            "stage_id": item.preview_id,
            "source_name": item.path.name,
            "source_sha256": expected_source,
            "preview_checksum": item.checksum,
            "event_ids": sorted(event_ids),
            "membership_hash": membership_hash,
            "mapping_version": int(stage["mapping_version"]),
            "decision_time": str(stage["decision_time"]),
            "committed_at": datetime.now(timezone.utc).isoformat(),
            "execution_allowed": False,
        }
        batch["batch_hash"] = _payload_hash(batch)
        try:
            with TransactionalStore(self.root) as store:
                with store.transaction() as connection:
                    existing_batches = _connection_payloads(connection, _BATCH_TYPE)
                    if any(
                        payload.get("batch_id") == batch_id
                        for _, payload in existing_batches
                    ):
                        return PortfolioCommitResult(
                            batch_id, 0, 0, 0, 0, status="idempotent"
                        )
                    existing_events = _verified_active_payloads(
                        _connection_payloads(connection, _BATCH_TYPE),
                        _connection_payloads(connection, _EVENT_TYPE),
                        _connection_payloads(connection, _ROLLBACK_TYPE),
                        _connection_payloads(connection, _STAGE_TYPE),
                    )
                    current = {
                        str(payload["event_key"]): (
                            str(payload["content_hash"]),
                            int(float(payload["source_revision"])),
                        )
                        for payload in existing_events
                        if payload.get("staging_status") in {"accepted", "correction"}
                    }
                    for _, payload in event_payloads:
                        if payload.get("staging_status") != "correction":
                            continue
                        expected = str(payload.get("predecessor_content_hash") or "")
                        expected_revision = int(
                            float(payload.get("predecessor_revision") or 0)
                        )
                        actual = current.get(str(payload["event_key"]), ("", 0))
                        if not expected or (expected, expected_revision) != actual:
                            raise PortfolioImportError(
                                f"stale correction predecessor for {payload['event_key']}"
                            )
                    _insert_immutable(connection, _BATCH_TYPE, batch_id, batch)
                    for event_id, payload in event_payloads:
                        _insert_immutable(connection, _EVENT_TYPE, event_id, payload)
        except PortfolioImportError:
            raise
        except (StorageSchemaError, sqlite3.DatabaseError, OSError, ValueError) as exc:
            raise PortfolioImportError(
                f"portfolio commit rejected atomically: {exc}"
            ) from exc
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
            rollback_payload = {
                "contract": PORTFOLIO_IMPORT_CONTRACT,
                "rollback_id": rollback_id,
                "batch_id": batch_key,
                "reason": explanation,
                "execution_allowed": False,
            }
            rollback_payload["rollback_hash"] = _payload_hash(rollback_payload)
            store.put_many(
                (
                    (
                        _ROLLBACK_TYPE,
                        rollback_id,
                        rollback_payload,
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
        reconciliation_errors: list[str] = []
        for row in active.sort_values(
            ["occurred_at", "event_key", "content_hash"], kind="stable"
        ).to_dict(orient="records"):
            record_type = str(row["record_type"])
            account_id = str(row.get("account_id") or "default")
            instrument_id = str(row.get("instrument_id") or "")
            currency = str(row.get("currency") or "").upper()
            invariant_error = _row_error(row)
            if invariant_error:
                reconciliation_errors.append(f"{row['event_key']}:{invariant_error}")
                continue
            if record_type == "transaction" and instrument_id:
                direction = (
                    Decimal(1) if str(row.get("side")).lower() == "buy" else Decimal(-1)
                )
                holdings[(account_id, instrument_id)] += direction * _decimal(
                    row.get("quantity")
                )
            if (
                record_type == "lot"
                and instrument_id
                and row.get("lot_role") == "opening_position"
            ):
                holdings[(account_id, instrument_id)] += _decimal(row.get("quantity"))
            if record_type == "corporate_action" and instrument_id:
                key = (account_id, instrument_id)
                if key not in holdings:
                    reconciliation_errors.append(
                        f"{row['event_key']}:corporate_action_without_position"
                    )
                    continue
                ratio = _decimal(row.get("ratio_numerator")) / _decimal(
                    row.get("ratio_denominator")
                )
                holdings[key] *= ratio
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
            holdings=holdings_frame,
            cash=cash_frame,
            active_events=active,
            quarantined=quarantined,
            balanced=not reconciliation_errors,
            reconciliation_errors=tuple(reconciliation_errors),
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

    def apply_mapping(
        self,
        preview_id: str,
        *,
        source_identity: str,
        canonical_instrument_id: str,
        reviewer: str,
        reason: str,
    ) -> ImportPreview:
        """Create an immutable mapped staging revision after human review."""

        previous = self._load_stage_preview(preview_id)
        if previous is None:
            raise KeyError(f"portfolio staging preview unavailable: {preview_id}")
        raw_identity = str(source_identity).strip()
        canonical_id = str(canonical_instrument_id).strip()
        if (
            not raw_identity
            or not canonical_id
            or not str(reviewer).strip()
            or not str(reason).strip()
        ):
            raise ValueError(
                "source identity, canonical identity, reviewer and reason are required"
            )
        frame = previous.frame.copy(deep=True)
        matches = (
            frame["raw_instrument_id"]
            .astype("string")
            .str.casefold()
            .eq(raw_identity.casefold())
        )
        if not matches.any():
            raise KeyError(f"source identity is absent from staging: {raw_identity}")
        decision_time = datetime.now(timezone.utc).isoformat()
        with IdentityMasterStore(self.root) as identity_store:
            for effective_at in frame.loc[matches, "occurred_at"].astype(str).unique():
                resolution = identity_store.resolve(
                    canonical_id,
                    effective_at=effective_at,
                    decision_time=decision_time,
                )
                if (
                    resolution.requires_manual_review
                    or resolution.resolution_state != "resolved"
                ):
                    raise PortfolioImportError(
                        "manual mapping target is not resolved in the identity master"
                    )
        frame["decision_time"] = decision_time
        frame.loc[matches, "instrument_id"] = canonical_id
        frame.loc[matches, "identity_candidates"] = canonical_id
        frame.loc[matches, "identity_mapping_method"] = "manual_reviewed"
        frame.loc[matches, "identity_review_decisions"] = json.dumps(
            {
                "reviewer": str(reviewer).strip(),
                "reason": str(reason).strip(),
                "canonical_instrument_id": canonical_id,
            },
            sort_keys=True,
        )
        frame = self._classify(frame, preserve_mappings=True)
        stage = self._verified_stage(previous.preview_id)
        mapping_version = int(stage["mapping_version"]) + 1
        new_id = f"portfolio_{uuid.uuid4().hex}"
        checksum = _frame_checksum(frame)
        warnings = tuple(
            warning
            for warning in previous.warnings
            if not warning.startswith(("mapping_version:", "decision_time:"))
        ) + (
            f"mapping_version:{mapping_version}",
            f"decision_time:{decision_time}",
        )
        mapped = ImportPreview(
            new_id,
            "portfolio_history",
            previous.path,
            True,
            len(frame),
            tuple(map(str, frame.columns)),
            (),
            frame,
            warnings,
            checksum,
        )
        decision = {
            "source_identity": raw_identity,
            "canonical_instrument_id": canonical_id,
            "reviewer": str(reviewer).strip(),
            "reason": str(reason).strip(),
            "decision_time": decision_time,
        }
        self._persist_stage(
            mapped,
            raw_bytes=base64.b64decode(str(stage["raw_source_base64"]), validate=True),
            source_format=str(stage["source_format"]),
            numeric_locale=str(stage["numeric_locale"]),
            mapping_version=mapping_version,
            mapping_decisions=(*tuple(stage.get("mapping_decisions", ())), decision),
            parent_preview_id=previous.preview_id,
            decision_time=decision_time,
        )
        _PREVIEWS[new_id] = mapped
        ImportService(self.root).register(mapped)
        return mapped

    def stages(self) -> tuple[dict[str, Any], ...]:
        with TransactionalStore(self.root) as store:
            return tuple(dict(record.payload) for record in store.list(_STAGE_TYPE))

    def batches(self) -> tuple[dict[str, Any], ...]:
        with TransactionalStore(self.root) as store:
            batches = [
                (record.entity_id, dict(record.payload))
                for record in store.list(_BATCH_TYPE)
            ]
            events = [
                (record.entity_id, dict(record.payload))
                for record in store.list(_EVENT_TYPE)
            ]
            rollbacks = [
                (record.entity_id, dict(record.payload))
                for record in store.list(_ROLLBACK_TYPE)
            ]
            stages = [
                (record.entity_id, dict(record.payload))
                for record in store.list(_STAGE_TYPE)
            ]
            _verified_active_payloads(batches, events, rollbacks, stages)
            rolled_back = {str(payload["batch_id"]) for _, payload in rollbacks}
            return tuple(
                dict(payload) | {"rolled_back": record_id in rolled_back}
                for record_id, payload in batches
            )

    def _persist_stage(
        self,
        preview: ImportPreview,
        *,
        raw_bytes: bytes,
        source_format: str,
        numeric_locale: str,
        mapping_version: int,
        mapping_decisions: Iterable[Mapping[str, Any]],
        parent_preview_id: str,
        decision_time: str,
    ) -> None:
        payload: dict[str, Any] = {
            "contract": PORTFOLIO_IMPORT_CONTRACT,
            "stage_id": preview.preview_id,
            "parent_stage_id": parent_preview_id,
            "source_path": str(preview.path),
            "source_name": preview.path.name,
            "source_sha256": _file_bytes_checksum(raw_bytes),
            "raw_source_base64": base64.b64encode(raw_bytes).decode("ascii"),
            "source_format": source_format,
            "numeric_locale": numeric_locale,
            "mapping_version": mapping_version,
            "mapping_decisions": [dict(item) for item in mapping_decisions],
            "decision_time": decision_time,
            "currency_registry": _CURRENCY_REGISTRY_VERSION,
            "preview_checksum": preview.checksum,
            "warnings": list(preview.warnings),
            "columns": list(preview.frame.columns),
            "rows": [_json_row(row) for row in preview.frame.to_dict(orient="records")],
            "valid": preview.valid,
            "errors": list(preview.errors),
            "execution_allowed": False,
        }
        payload["stage_hash"] = _payload_hash(payload)
        with TransactionalStore(self.root) as store:
            store.put_many(
                ((_STAGE_TYPE, preview.preview_id, payload),), immutable=True
            )

    def _verified_stage(self, preview_id: str) -> dict[str, Any]:
        with TransactionalStore(self.root) as store:
            record = store.get(_STAGE_TYPE, preview_id)
        if record is None:
            raise PortfolioImportError(
                f"durable portfolio stage unavailable: {preview_id}"
            )
        payload = dict(record.payload)
        stage_hash = str(payload.pop("stage_hash", ""))
        if not stage_hash or stage_hash != _payload_hash(payload):
            raise PortfolioImportError("staging integrity failure: stage hash mismatch")
        try:
            raw_bytes = base64.b64decode(
                str(payload["raw_source_base64"]), validate=True
            )
            frame = pd.DataFrame(payload["rows"], columns=payload["columns"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PortfolioImportError(
                "staging integrity failure: invalid durable stage"
            ) from exc
        if (
            _file_bytes_checksum(raw_bytes) != payload.get("source_sha256")
            or _frame_checksum(frame) != payload.get("preview_checksum")
            or (
                not frame.empty
                and payload.get("decision_time") != _single_decision_time(frame)
            )
            or payload.get("currency_registry") != _CURRENCY_REGISTRY_VERSION
            or _warning_value(payload.get("warnings", ()), "source_sha256")
            != payload.get("source_sha256")
            or _warning_value(payload.get("warnings", ()), "source_format")
            != payload.get("source_format")
            or _warning_value(payload.get("warnings", ()), "numeric_locale")
            != payload.get("numeric_locale")
            or _warning_value(payload.get("warnings", ()), "mapping_version")
            != str(payload.get("mapping_version"))
            or _warning_value(payload.get("warnings", ()), "decision_time")
            != payload.get("decision_time")
        ):
            raise PortfolioImportError(
                "staging integrity failure: durable stage metadata mismatch"
            )
        payload["stage_hash"] = stage_hash
        return payload

    def _load_stage_preview(self, preview_id: str) -> ImportPreview | None:
        stage = self._verified_stage(preview_id)
        frame = pd.DataFrame(stage["rows"], columns=stage["columns"])
        preview = ImportPreview(
            preview_id,
            "portfolio_history",
            Path(str(stage["source_path"])),
            bool(stage["valid"]),
            len(frame),
            tuple(str(item) for item in stage["columns"]),
            tuple(str(item) for item in stage["errors"]),
            frame,
            tuple(str(item) for item in stage["warnings"]),
            str(stage["preview_checksum"]),
        )
        _PREVIEWS[preview_id] = preview
        return preview

    def _active_events(self) -> pd.DataFrame:
        try:
            with TransactionalStore(self.root) as store:
                integrity = store.integrity()
                if not integrity.ok:
                    raise PortfolioImportError(
                        "portfolio storage integrity check failed"
                    )
                batches = [
                    (record.entity_id, dict(record.payload))
                    for record in store.list(_BATCH_TYPE)
                ]
                events = [
                    (record.entity_id, dict(record.payload))
                    for record in store.list(_EVENT_TYPE)
                ]
                rollbacks = [
                    (record.entity_id, dict(record.payload))
                    for record in store.list(_ROLLBACK_TYPE)
                ]
                stages = [
                    (record.entity_id, dict(record.payload))
                    for record in store.list(_STAGE_TYPE)
                ]
                rows = _verified_active_payloads(batches, events, rollbacks, stages)
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
        latest: dict[str, dict[str, Any]] = {}
        quarantined: dict[str, dict[str, Any]] = {}
        for row in rows:
            status = str(row.get("staging_status"))
            if status in {"accepted", "correction"}:
                latest[str(row["event_key"])] = row
            elif status == "quarantined":
                quarantined[str(row["event_id"])] = row
        return pd.DataFrame([*latest.values(), *quarantined.values()])

    def _classify(
        self, frame: pd.DataFrame, *, preserve_mappings: bool = False
    ) -> pd.DataFrame:
        if frame.empty:
            return frame.assign(
                staging_status=pd.Series(dtype=str),
                quarantine_reason=pd.Series(dtype=str),
                content_hash=pd.Series(dtype=str),
            )
        existing = self._existing_by_source()
        seen: dict[str, tuple[str, int]] = {}
        statuses: list[str] = []
        reasons: list[str] = []
        hashes: list[str] = []
        mapped_rows: list[dict[str, Any]] = []
        for original in frame.to_dict(orient="records"):
            row = dict(original)
            if str(row["record_type"]) in _INSTRUMENT_RECORDS:
                row = _map_identity(self.root, row, preserve_mapping=preserve_mappings)
            mapped_rows.append(row)
        mapped = pd.DataFrame(
            mapped_rows,
            columns=tuple(frame.columns)
            + tuple(
                column
                for column in (
                    "identity_candidates",
                    "identity_mapping_method",
                    "identity_review_decisions",
                )
                if column not in frame.columns
            ),
        )
        for row in mapped.to_dict(orient="records"):
            content_hash = _content_hash(row)
            hashes.append(content_hash)
            event_key = str(row["event_key"])
            source_revision = int(float(row["source_revision"]))
            reason = _row_error(row) or (
                ""
                if str(row["record_type"]) not in _INSTRUMENT_RECORDS
                else _mapped_identity_error(row)
            )
            if reason:
                statuses.append("quarantined")
                reasons.append(reason)
            elif event_key in seen:
                statuses.append(
                    "duplicate"
                    if seen[event_key] == (content_hash, source_revision)
                    else "quarantined"
                )
                reasons.append(
                    "duplicate_in_file"
                    if seen[event_key] == (content_hash, source_revision)
                    else "conflicting_source_id_in_file"
                )
            elif event_key in existing:
                prior, prior_revision = existing[event_key]
                predecessor = str(row.get("predecessor_content_hash") or "")
                predecessor_revision = row.get("predecessor_revision")
                if prior == content_hash and source_revision == prior_revision:
                    statuses.append("duplicate")
                    reasons.append("same_namespaced_source_and_content")
                elif not predecessor or _missing(predecessor_revision):
                    statuses.append("quarantined")
                    reasons.append("missing_correction_predecessor")
                elif (
                    predecessor != prior
                    or int(float(predecessor_revision)) != prior_revision
                ):
                    statuses.append("quarantined")
                    reasons.append("stale_correction_predecessor")
                elif source_revision != prior_revision + 1:
                    statuses.append("quarantined")
                    reasons.append("invalid_correction_revision")
                else:
                    statuses.append("correction")
                    reasons.append("supersedes_explicit_predecessor")
            else:
                statuses.append("accepted")
                reasons.append("")
            seen[event_key] = (content_hash, source_revision)
        result = mapped.copy()
        result["staging_status"] = statuses
        result["quarantine_reason"] = reasons
        result["content_hash"] = hashes
        result["execution_allowed"] = False
        _quarantine_unpaired_transfers(result)
        return result

    def _existing_by_source(self) -> dict[str, tuple[str, int]]:
        frame = self._active_events()
        if frame.empty:
            return {}
        return {
            str(row["event_key"]): (
                str(row["content_hash"]),
                int(float(row["source_revision"])),
            )
            for row in frame.to_dict(orient="records")
        }


def _connection_payloads(
    connection: sqlite3.Connection, entity_type: str
) -> list[tuple[str, dict[str, Any]]]:
    rows = connection.execute(
        "SELECT entity_id, payload_json FROM transactional_records WHERE entity_type = ? AND deleted_at IS NULL ORDER BY created_at, entity_id",
        (entity_type,),
    ).fetchall()
    result: list[tuple[str, dict[str, Any]]] = []
    for entity_id, encoded in rows:
        payload = json.loads(str(encoded))
        if not isinstance(payload, dict):
            raise PortfolioImportError(
                f"portfolio integrity failure: {entity_type} payload is not an object"
            )
        result.append((str(entity_id), payload))
    return result


def _insert_immutable(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    payload: Mapping[str, Any],
) -> None:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    existing = connection.execute(
        "SELECT payload_json FROM transactional_records WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchone()
    if existing:
        if str(existing[0]) != encoded:
            raise PortfolioImportError(
                f"portfolio integrity failure: immutable record collision {entity_id}"
            )
        return
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        "INSERT INTO transactional_records (entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at) VALUES (?, ?, ?, 1, ?, ?, NULL)",
        (entity_type, entity_id, encoded, now, now),
    )


def _verified_active_payloads(
    batches: Iterable[tuple[str, Mapping[str, Any]]],
    events: Iterable[tuple[str, Mapping[str, Any]]],
    rollbacks: Iterable[tuple[str, Mapping[str, Any]]],
    stages: Iterable[tuple[str, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    stage_map: dict[str, dict[str, Any]] = {}
    for record_id, raw in stages:
        payload = dict(raw)
        stored_hash = str(payload.pop("stage_hash", ""))
        if (
            record_id != payload.get("stage_id")
            or not stored_hash
            or stored_hash != _payload_hash(payload)
        ):
            raise PortfolioImportError(
                f"portfolio integrity failure: invalid stage {record_id}"
            )
        try:
            raw_bytes = base64.b64decode(
                str(payload["raw_source_base64"]), validate=True
            )
        except (KeyError, ValueError) as exc:
            raise PortfolioImportError(
                f"portfolio integrity failure: invalid raw stage {record_id}"
            ) from exc
        if _file_bytes_checksum(raw_bytes) != payload.get("source_sha256"):
            raise PortfolioImportError(
                f"portfolio integrity failure: raw checksum {record_id}"
            )
        frame = pd.DataFrame(
            payload.get("rows", ()), columns=payload.get("columns", ())
        )
        if (
            _frame_checksum(frame) != payload.get("preview_checksum")
            or (
                not frame.empty
                and payload.get("decision_time") != _single_decision_time(frame)
            )
            or payload.get("currency_registry") != _CURRENCY_REGISTRY_VERSION
        ):
            raise PortfolioImportError(
                f"portfolio integrity failure: staged frame {record_id}"
            )
        payload["stage_hash"] = stored_hash
        stage_map[record_id] = payload

    batch_map: dict[str, dict[str, Any]] = {}
    for record_id, raw in batches:
        payload = dict(raw)
        stored_hash = str(payload.pop("batch_hash", ""))
        expected_batch_id = (
            "batch-"
            + hashlib.sha256(
                f"{payload.get('stage_id')}\0{payload.get('preview_checksum')}".encode()
            ).hexdigest()[:32]
        )
        if (
            record_id != payload.get("batch_id")
            or record_id != expected_batch_id
            or payload.get("contract") != PORTFOLIO_IMPORT_CONTRACT
            or not stored_hash
            or stored_hash != _payload_hash(payload)
        ):
            raise PortfolioImportError(
                f"portfolio integrity failure: invalid batch {record_id}"
            )
        stage = stage_map.get(str(payload.get("stage_id")))
        if stage is None:
            raise PortfolioImportError(
                f"portfolio integrity failure: missing stage for {record_id}"
            )
        if (
            stage.get("preview_checksum") != payload.get("preview_checksum")
            or stage.get("source_sha256") != payload.get("source_sha256")
            or stage.get("mapping_version") != payload.get("mapping_version")
            or stage.get("decision_time") != payload.get("decision_time")
        ):
            raise PortfolioImportError(
                f"portfolio integrity failure: batch-stage linkage {record_id}"
            )
        payload["batch_hash"] = stored_hash
        batch_map[record_id] = payload

    event_map: dict[str, dict[str, Any]] = {}
    by_batch: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for record_id, raw in events:
        payload = dict(raw)
        stored_hash = str(payload.pop("event_hash", ""))
        batch_id = str(payload.get("batch_id") or "")
        expected_id = hashlib.sha256(
            f"{batch_id}\0{payload.get('event_key')}\0{payload.get('content_hash')}".encode()
        ).hexdigest()
        if (
            record_id != payload.get("event_id")
            or record_id != expected_id
            or batch_id not in batch_map
            or payload.get("contract") != PORTFOLIO_IMPORT_CONTRACT
            or not stored_hash
            or stored_hash != _payload_hash(payload)
            or payload.get("content_hash") != _content_hash(payload)
            or payload.get("decision_time") != batch_map[batch_id].get("decision_time")
        ):
            raise PortfolioImportError(
                f"portfolio integrity failure: invalid event {record_id}"
            )
        payload["event_hash"] = stored_hash
        event_map[record_id] = payload
        by_batch[batch_id].append((record_id, payload))

    for batch_id, batch in batch_map.items():
        members = by_batch.get(batch_id, [])
        if list(batch.get("event_ids", ())) != sorted(
            record_id for record_id, _ in members
        ) or batch.get("membership_hash") != _membership_hash(members):
            raise PortfolioImportError(
                f"portfolio integrity failure: batch membership {batch_id}"
            )

    rolled_back: set[str] = set()
    for record_id, raw in rollbacks:
        payload = dict(raw)
        stored_hash = str(payload.pop("rollback_hash", ""))
        expected_rollback_id = hashlib.sha256(
            f"{payload.get('batch_id')}\0{payload.get('reason')}".encode()
        ).hexdigest()
        if (
            record_id != payload.get("rollback_id")
            or record_id != expected_rollback_id
            or payload.get("batch_id") not in batch_map
            or not stored_hash
            or stored_hash != _payload_hash(payload)
        ):
            raise PortfolioImportError(
                f"portfolio integrity failure: invalid rollback {record_id}"
            )
        rolled_back.add(str(payload["batch_id"]))

    ordered_batches = sorted(
        batch_map.values(),
        key=lambda payload: (
            str(payload.get("committed_at", "")),
            str(payload["batch_id"]),
        ),
    )
    result: list[dict[str, Any]] = []
    for batch in ordered_batches:
        batch_id = str(batch["batch_id"])
        if batch_id in rolled_back:
            continue
        result.extend(payload for _, payload in by_batch.get(batch_id, []))
    current_versions: dict[str, tuple[str, int]] = {}
    for payload in result:
        status = str(payload.get("staging_status"))
        if status not in {"accepted", "correction"}:
            continue
        event_key = str(payload["event_key"])
        source_revision = int(float(payload.get("source_revision") or 0))
        if status == "correction":
            predecessor = (
                str(payload.get("predecessor_content_hash") or ""),
                int(float(payload.get("predecessor_revision") or 0)),
            )
            if predecessor != current_versions.get(event_key, ("", 0)):
                raise PortfolioImportError(
                    f"portfolio integrity failure: correction chain {event_key}"
                )
            if source_revision != predecessor[1] + 1:
                raise PortfolioImportError(
                    f"portfolio integrity failure: correction revision {event_key}"
                )
        elif event_key in current_versions or source_revision != 1:
            raise PortfolioImportError(
                f"portfolio integrity failure: accepted source revision {event_key}"
            )
        current_versions[event_key] = (str(payload["content_hash"]), source_revision)
    return result


def _map_identity(
    root: Path, row: dict[str, Any], *, preserve_mapping: bool
) -> dict[str, Any]:
    row.setdefault("identity_candidates", "")
    row.setdefault("identity_mapping_method", "unresolved")
    row.setdefault("identity_review_decisions", "[]")
    effective_at = str(row.get("occurred_at") or "")
    decision_time = str(row.get("decision_time") or "")
    existing_id = str(row.get("instrument_id") or "").strip()
    candidates: tuple[str, ...]
    if (
        preserve_mapping
        and row.get("identity_mapping_method") == "manual_reviewed"
        and existing_id
    ):
        candidates = (existing_id,)
        method = "manual_reviewed"
    else:
        candidates, method = _identity_candidates(
            root, row, effective_at, decision_time
        )
    row["identity_candidates"] = "|".join(candidates)
    row["identity_mapping_method"] = method
    if len(candidates) != 1:
        row["instrument_id"] = ""
        return row
    canonical_id = candidates[0]
    try:
        with IdentityMasterStore(root) as store:
            resolution = store.resolve(
                canonical_id, effective_at=effective_at, decision_time=decision_time
            )
            projection = store.projection(
                canonical_id, effective_at=effective_at, decision_time=decision_time
            )
    except (KeyError, ValueError, IdentityMasterSchemaError):
        row["instrument_id"] = ""
        row["identity_mapping_method"] = "unresolved"
        return row
    row["identity_review_decisions"] = json.dumps(
        projection.get("identity_reviews", []), sort_keys=True
    )
    if resolution.requires_manual_review or resolution.resolution_state != "resolved":
        row["instrument_id"] = ""
        row["identity_mapping_method"] = "ambiguous"
        return row
    expected_currency = str(resolution.identity.currency or "").upper()
    supplied_currency = str(row.get("currency") or "").upper()
    if (
        expected_currency
        and supplied_currency
        and expected_currency != supplied_currency
    ):
        row["instrument_id"] = ""
        row["identity_mapping_method"] = f"currency_conflict:{expected_currency}"
        return row
    row["instrument_id"] = canonical_id
    return row


def _identity_candidates(
    root: Path,
    row: Mapping[str, Any],
    effective_at: str,
    decision_time: str,
) -> tuple[tuple[str, ...], str]:
    explicit = str(row.get("instrument_id") or "").strip()
    if explicit:
        try:
            with IdentityMasterStore(root) as store:
                store.resolve(
                    explicit,
                    effective_at=effective_at,
                    decision_time=decision_time,
                )
            return (explicit,), "canonical_id"
        except (KeyError, ValueError, IdentityMasterSchemaError):
            pass
    try:
        with TransactionalStore(root) as store:
            claims = [
                dict(record.payload.get("claim", {}))
                for record in store.list(_IDENTITY_CLAIM_TYPE)
            ]
    except (StorageSchemaError, sqlite3.DatabaseError, OSError):
        return (), "identity_master_unavailable"
    claims = [
        claim
        for claim in claims
        if _claim_effective(claim, effective_at, decision_time)
    ]

    def matches(field_names: set[str], value: object) -> set[str]:
        text = str(value or "").strip().casefold()
        if not text:
            return set()
        return {
            str(claim.get("instrument_id"))
            for claim in claims
            if str(claim.get("field", "")).casefold() in field_names
            and str(claim.get("value", "")).strip().casefold() == text
        }

    isin = matches({"isin"}, row.get("isin"))
    if isin:
        return tuple(sorted(isin)), "isin"
    listing = matches({"listing"}, row.get("listing_id"))
    if listing:
        return tuple(sorted(listing)), "listing"
    ticker = matches({"ticker"}, row.get("ticker") or row.get("raw_instrument_id"))
    mic_value = row.get("mic")
    if ticker and not _missing(mic_value):
        venue = matches({"mic", "exchange"}, mic_value)
        ticker &= venue
        return tuple(sorted(ticker)), "ticker+mic"
    if ticker:
        return tuple(sorted(ticker)), "ticker"
    return (), "unresolved"


def _claim_effective(
    claim: Mapping[str, Any], effective_at: str, decision_time: str
) -> bool:
    try:
        effective = pd.Timestamp(effective_at)
        valid_from = (
            pd.Timestamp(claim["valid_from"]) if claim.get("valid_from") else None
        )
        valid_to = pd.Timestamp(claim["valid_to"]) if claim.get("valid_to") else None
        available = (
            pd.Timestamp(claim["available_at"]) if claim.get("available_at") else None
        )
    except (TypeError, ValueError):
        return False
    try:
        decision = pd.Timestamp(decision_time)
    except (TypeError, ValueError):
        return False
    return not (
        (valid_from is not None and effective < valid_from)
        or (valid_to is not None and effective >= valid_to)
        or available is None
        or available > decision
    )


def _mapped_identity_error(row: Mapping[str, Any]) -> str:
    method = str(row.get("identity_mapping_method") or "")
    candidates = tuple(
        item for item in str(row.get("identity_candidates") or "").split("|") if item
    )
    if method.startswith("currency_conflict:"):
        return "identity_currency_conflict"
    if len(candidates) > 1 or method == "ambiguous":
        return "identity_ambiguous"
    if not str(row.get("instrument_id") or ""):
        return "identity_unresolved"
    return ""


def _quarantine_unpaired_transfers(frame: pd.DataFrame) -> None:
    transfers = frame.loc[frame["record_type"].eq("transfer")]
    for namespace, group in transfers.groupby(
        ["provider_id", "source_system", "transfer_id"], dropna=False
    ):
        transfer_id = namespace[2]
        indexes = group.index
        reasons = set(group["quarantine_reason"].astype(str)) - {""}
        legs = set(group["transfer_leg"].astype(str).str.lower())
        currencies = set(group["currency"].astype(str).str.upper())
        total = sum(
            (_decimal(value, default=Decimal(0)) for value in group["cash_amount"]),
            Decimal(0),
        )
        if (
            _missing(transfer_id)
            or len(group) != 2
            or legs != {"credit", "debit"}
            or len(currencies) != 1
            or total != 0
        ):
            frame.loc[indexes, "staging_status"] = "quarantined"
            frame.loc[indexes, "quarantine_reason"] = "unpaired_transfer"
        elif reasons:
            frame.loc[indexes, "staging_status"] = "quarantined"


def _payload_hash(payload: Mapping[str, Any]) -> str:
    clean = {
        key: _json_value(value)
        for key, value in payload.items()
        if key not in {"stage_hash", "batch_hash", "event_hash", "rollback_hash"}
    }
    return hashlib.sha256(
        json.dumps(
            clean,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _membership_hash(events: Iterable[tuple[str, Mapping[str, Any]]]) -> str:
    members = sorted(
        (event_id, str(payload.get("event_hash") or "")) for event_id, payload in events
    )
    return hashlib.sha256(
        json.dumps(members, separators=(",", ":")).encode()
    ).hexdigest()


def _file_bytes_checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _normalise_frame(
    frame: pd.DataFrame,
    *,
    source_format: str,
    numeric_locale: str,
    decision_time: str,
    source_system: str | None = None,
    provider_id: str | None = None,
) -> pd.DataFrame:
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
    locale_name = str(numeric_locale).strip()
    if locale_name not in {"en_US", "de_DE"}:
        raise ValueError("numeric_locale must be explicitly en_US or de_DE")
    for column in CANONICAL_COLUMNS:
        if column not in result:
            result[column] = None
    result = result.loc[:, list(CANONICAL_COLUMNS)]
    for column in result.columns:
        result[column] = result[column].map(_clean_value)
    result["decision_time"] = decision_time
    inferred_sides = result["record_type"].map(
        lambda value: (
            str(value).strip().lower()
            if str(value).strip().lower() in {"buy", "sell"}
            else ""
        )
    )
    result["side"] = result["side"].where(
        result["side"].notna() & result["side"].astype(str).str.strip().ne(""),
        inferred_sides,
    )
    result["record_type"] = result["record_type"].map(_normalise_record_type)
    result["source_id"] = result["source_id"].map(lambda value: str(value).strip())
    default_system = str(source_system or source_format).strip().lower()
    default_provider = str(provider_id or "user_local").strip().lower()
    result["source_system"] = result["source_system"].map(
        lambda value: str(value or default_system).strip().lower()
    )
    result["provider_id"] = result["provider_id"].map(
        lambda value: str(value or default_provider).strip().lower()
    )
    result["raw_instrument_id"] = result.apply(_raw_identity, axis=1)
    timestamps = pd.to_datetime(result["occurred_at"], errors="coerce", utc=True)
    result["occurred_at"] = timestamps.map(
        lambda value: value.isoformat() if not pd.isna(value) else ""
    )
    currency_errors: list[str] = [""] * len(result)
    for currency_column in ("currency", "from_currency", "to_currency"):
        identity_column = f"{currency_column}_identity"
        codes: list[str | None] = []
        identities: list[str] = []
        for position, (value, effective_at) in enumerate(
            zip(result[currency_column], result["occurred_at"], strict=True)
        ):
            code, identity, error = _resolve_currency(
                value, effective_at=str(effective_at), field=currency_column
            )
            codes.append(code)
            identities.append(identity)
            if error and not currency_errors[position]:
                currency_errors[position] = error
        result[currency_column] = codes
        result[identity_column] = identities
    result["currency_error"] = currency_errors
    numeric_columns = (
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
        "fee_amount",
        "tax_amount",
        "ratio_numerator",
        "ratio_denominator",
        "predecessor_revision",
        "source_revision",
    )
    numeric_errors: list[str] = [""] * len(result)
    for column in numeric_columns:
        parsed: list[float | None] = []
        for position, value in enumerate(result[column].tolist()):
            number, error = _parse_number(value, locale_name)
            parsed.append(number)
            if error and not numeric_errors[position]:
                numeric_errors[position] = f"{error}:{column}"
        result[column] = parsed
    result["source_revision"] = result["source_revision"].map(
        lambda value: 1 if _missing(value) else value
    )
    result["numeric_error"] = numeric_errors
    result["event_key"] = result.apply(
        lambda row: "|".join(
            (
                str(row["provider_id"]),
                str(row["source_system"]),
                str(row.get("account_id") or "_market"),
                str(row["source_id"]),
            )
        ),
        axis=1,
    )
    return result


def _resolve_currency(
    value: object, *, effective_at: str, field: str
) -> tuple[str | None, str, str]:
    if _missing(value):
        return None, "", ""
    raw = str(value).strip().upper()
    candidates = _CURRENCY_ALIASES.get(raw, (raw,))
    if len(candidates) != 1:
        return raw, "", f"ambiguous_currency:{field}"
    code = candidates[0]
    if code in _WITHDRAWN_CURRENCIES:
        try:
            effective = pd.Timestamp(effective_at)
            withdrawn_at = pd.Timestamp(_WITHDRAWN_CURRENCIES[code])
        except (TypeError, ValueError):
            return code, "", f"withdrawn_currency:{field}"
        if effective >= withdrawn_at:
            return code, "", f"withdrawn_currency:{field}"
        return code, f"ISO4217:{code}", ""
    if code not in _ACTIVE_CURRENCIES:
        return code, "", f"unknown_currency:{field}"
    return code, f"ISO4217:{code}", ""


def _row_error(row: Mapping[str, Any]) -> str:
    record_type = str(row.get("record_type") or "")
    if str(row.get("numeric_error") or ""):
        return str(row["numeric_error"])
    if str(row.get("currency_error") or ""):
        return str(row["currency_error"])
    if record_type not in RECORD_TYPES:
        return "unsupported_record_type"
    if not str(row.get("provider_id") or "") or not str(row.get("source_system") or ""):
        return "missing_source_namespace"
    if not str(row.get("source_id") or ""):
        return "missing_source_id"
    if not _positive_integer(row.get("source_revision")):
        return "invalid_source_revision"
    if not str(row.get("occurred_at") or ""):
        return "invalid_occurred_at"
    if not str(row.get("decision_time") or ""):
        return "missing_decision_time"
    if record_type != "price" and not str(row.get("account_id") or ""):
        return "missing_account_id"
    if record_type in _CASH_RECORDS and not str(row.get("currency") or ""):
        return "missing_currency"
    for name in ("currency", "from_currency", "to_currency"):
        value = row.get(name)
        if not _missing(value) and not re.fullmatch(r"[A-Z]{3}", str(value)):
            return f"invalid_currency:{name}"
        if not _missing(value) and row.get(f"{name}_identity") != f"ISO4217:{value}":
            return f"invalid_currency_identity:{name}"
    if record_type == "price":
        if not _positive_finite(row.get("adjusted_close")):
            return "invalid_adjusted_price"
    if record_type == "transaction":
        if not _positive_finite(row.get("quantity")):
            return "invalid_quantity"
        side = str(row.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            return "missing_trade_side"
        if _missing(row.get("settlement_cash")):
            return "unbalanced_transaction"
        if not _missing(row.get("fee_amount")) and _decimal(row.get("fee_amount")) > 0:
            return "invalid_fee_sign"
        if not _missing(row.get("tax_amount")) and _decimal(row.get("tax_amount")) > 0:
            return "invalid_tax_sign"
    if record_type in {"cash", "transfer", "fee", "tax", "income"} and _missing(
        row.get("cash_amount")
    ):
        return "unbalanced_cash_event"
    if (
        record_type in {"fee", "tax"}
        and _decimal(row.get("cash_amount"), default=Decimal(0)) > 0
    ):
        return f"invalid_{record_type}_sign"
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
        if not _positive_finite(row.get("fx_rate")):
            return "invalid_fx_rate"
        expected_to = -_decimal(row.get("from_amount")) * _decimal(row.get("fx_rate"))
        if not _close(expected_to, _decimal(row.get("to_amount"))):
            return "fx_rate_mismatch"
    if record_type == "lot":
        if not _positive_finite(row.get("quantity")):
            return "invalid_lot_quantity"
        if str(row.get("lot_role") or "") not in {
            "opening_position",
            "trade_detail",
        }:
            return "unsupported_lot_semantics"
    if record_type == "corporate_action":
        if str(row.get("corporate_action_type") or "") not in {
            "split",
            "reverse_split",
        }:
            return "unsupported_corporate_action"
        if not _positive_finite(row.get("ratio_numerator")) or not _positive_finite(
            row.get("ratio_denominator")
        ):
            return "invalid_corporate_action_ratio"
        if not _missing(row.get("quantity")):
            return "arbitrary_corporate_action_quantity"
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
        if not _positive_finite(notional):
            return "invalid_bond_notional"
        if not _positive_finite(row.get("clean_price")) or _decimal(
            row.get("clean_price")
        ) > Decimal(1000):
            return "invalid_clean_price"
        if not _finite(row.get("accrued_interest")):
            return "invalid_accrued_interest"
        direction = (
            Decimal(-1) if str(row.get("side") or "").lower() == "buy" else Decimal(1)
        )
        expected = direction * (
            _decimal(notional) * _decimal(row.get("clean_price")) / Decimal(100)
            + _decimal(row.get("accrued_interest"))
        )
        expected -= abs(_decimal(row.get("fee_amount"), default=Decimal(0))) + abs(
            _decimal(row.get("tax_amount"), default=Decimal(0))
        )
        actual = _decimal(row.get("settlement_cash"))
        if abs(expected - actual) > max(
            Decimal("0.01"), abs(expected) * Decimal("0.000001")
        ):
            return "unbalanced_bond_settlement"
    elif record_type == "transaction":
        if not _positive_finite(row.get("price")):
            return "invalid_price"
        gross = _decimal(row.get("quantity")) * _decimal(row.get("price"))
        costs = abs(_decimal(row.get("fee_amount"), default=Decimal(0))) + abs(
            _decimal(row.get("tax_amount"), default=Decimal(0))
        )
        expected = (
            -(gross + costs) if str(row.get("side")).lower() == "buy" else gross - costs
        )
        actual = _decimal(row.get("settlement_cash"))
        if str(row.get("side")).lower() == "buy" and actual >= 0:
            return "trade_settlement_sign"
        if not _close(expected, actual):
            return "trade_settlement_mismatch"
    return ""


def _normalise_record_type(value: object) -> str:
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return _RECORD_TYPE_ALIASES.get(key, key)


def _content_hash(row: Mapping[str, Any]) -> str:
    payload = {
        column: _json_value(row.get(column))
        for column in CANONICAL_COLUMNS
        if column != "decision_time"
    }
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


def _single_decision_time(frame: pd.DataFrame) -> str:
    if "decision_time" not in frame.columns or frame.empty:
        return ""
    values = tuple(dict.fromkeys(frame["decision_time"].astype(str)))
    return values[0] if len(values) == 1 else ""


def _preview_matches_stage(supplied: ImportPreview, durable: ImportPreview) -> bool:
    return (
        supplied.preview_id == durable.preview_id
        and supplied.import_type == durable.import_type
        and supplied.path.resolve() == durable.path.resolve()
        and supplied.valid == durable.valid
        and supplied.rows == durable.rows
        and supplied.columns == durable.columns
        and len(supplied.frame) == durable.rows
        and tuple(map(str, supplied.frame.columns)) == durable.columns
        and supplied.errors == durable.errors
        and supplied.warnings == durable.warnings
        and supplied.checksum == durable.checksum
        and _frame_checksum(supplied.frame) == durable.checksum
    )


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


def _raw_identity(row: pd.Series) -> str:
    for name in ("instrument_id", "isin", "listing_id", "ticker"):
        value = row.get(name)
        if not _missing(value):
            return str(value).strip()
    return ""


def _missing(value: object) -> bool:
    return (
        value is None
        or value == ""
        or (not isinstance(value, str) and bool(pd.isna(value)))
    )


def _parse_number(value: object, locale_name: str) -> tuple[float | None, str]:
    if _missing(value):
        return None, ""
    text = str(value).strip()
    if locale_name == "en_US":
        if "," in text and not re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", text):
            return None, "ambiguous_number"
        normalised = text.replace(",", "")
    else:
        if (
            "." in text
            and "," not in text
            and not re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", text)
        ):
            return None, "ambiguous_number"
        if "," in text and not re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})*,\d+", text):
            return None, "ambiguous_number"
        normalised = text.replace(".", "").replace(",", ".")
    try:
        return float(Decimal(normalised)), ""
    except (InvalidOperation, ValueError):
        return None, "invalid_number"


def _finite(value: object) -> bool:
    if _missing(value):
        return False
    try:
        return math.isfinite(float(str(value)))
    except (TypeError, ValueError):
        return False


def _positive_finite(value: object) -> bool:
    return _finite(value) and float(str(value)) > 0


def _positive_integer(value: object) -> bool:
    if not _positive_finite(value):
        return False
    number = float(str(value))
    return number.is_integer()


def _close(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= max(Decimal("0.01"), abs(left) * Decimal("0.000001"))


def _decimal(value: object, *, default: Decimal | None = None) -> Decimal:
    if value is None or value == "" or (not isinstance(value, str) and pd.isna(value)):
        if default is not None:
            return default
        raise ValueError("numeric value is required")
    return Decimal(str(value))


def _json_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if pd.isna(value):
        return None
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
            if _missing(value):
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
