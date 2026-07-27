"""Provider-neutral, point-in-time fixed-income market evidence.

The core owns persistence and manual import.  Provider plugins can describe
capabilities, but never receive this store or execution authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence, cast

import pandas as pd

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.legal_terms import LegalTermsError, load_legal_terms
from etf_cockpit.data.fixed_income_terms import (
    FixedIncomeTermsSchemaError,
    FixedIncomeTermsStore,
    fixed_income_terms_exists,
)
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    TransactionalStore,
    atomic_write_bytes,
    parquet_payload,
    validate_parquet_file,
    storage_layout,
)


FIXED_INCOME_MARKET_DATA_CONTRACT = "fixed-income-market-data.v1"
FIXED_INCOME_COVERAGE_CONTRACT = "fixed-income-provider-coverage.v1"
FIXED_INCOME_PROVIDER_COVERAGE_PATH = Path(
    "data/market/fixed_income_provider_coverage.parquet"
)
_ENTITY_TYPE = "fixed_income_market_observation_v1"
_SHA256 = frozenset("0123456789abcdef")


class FixedIncomeMarketDataError(ValueError):
    """Raised when market evidence or its import authority is invalid."""


class FixedIncomeMarketDataSchemaError(RuntimeError):
    """Raised when immutable persisted evidence is corrupt."""


@dataclass(frozen=True)
class FixedIncomeMarketObservation:
    instrument_id: str
    provider_id: str
    observation_type: str
    market: str
    currency: str
    valid_at: datetime
    known_at: datetime
    retrieved_at: datetime
    source_checksum: str
    raw_checksum: str
    values: Mapping[str, object] = field(default_factory=dict)
    clean_price: Decimal | float | int | str | None = None
    dirty_price: Decimal | float | int | str | None = None
    yield_value: Decimal | float | int | str | None = None
    spread: Decimal | float | int | str | None = None
    bid: Decimal | float | int | str | None = None
    ask: Decimal | float | int | str | None = None
    quote_size: Decimal | float | int | str | None = None
    trade_price: Decimal | float | int | str | None = None
    trade_size: Decimal | float | int | str | None = None
    tape_available: bool = False
    evidence_label: str = "indicative"
    source_authority: str = SourceAuthority.MANUAL.value
    legal_terms_record: str = "manual_local"
    retention: str = "local_only"
    quality: str = "current"
    revision: int = 1
    source_reference: str = ""
    quality_label: str = "observed"

    @property
    def identity(self) -> str:
        payload = {
            "instrument_id": self.instrument_id,
            "provider_id": self.provider_id,
            "observation_type": self.observation_type,
            "market": self.market,
            "valid_at": _iso(self.valid_at),
            "known_at": _iso(self.known_at),
            "retrieved_at": _iso(self.retrieved_at),
            "revision": self.revision,
        }
        return _hash(payload)

    @property
    def content_checksum(self) -> str:
        return _hash(_payload(self))


@dataclass(frozen=True)
class CurveTenorPoint:
    tenor: str
    value: Decimal | float | int | str


@dataclass(frozen=True)
class YieldCurveSnapshot:
    curve_id: str
    provider_id: str
    market: str
    currency: str
    valid_at: datetime
    known_at: datetime
    retrieved_at: datetime
    source_checksum: str
    raw_checksum: str
    tenors: Mapping[str, Decimal | float | int | str]
    curve_type: str
    interpolation: str
    tenor_points: tuple[CurveTenorPoint, ...] = ()
    revision: int = 1
    source_reference: str = ""
    quality_label: str = "observed"
    source_authority: str = SourceAuthority.MANUAL.value
    legal_terms_record: str = "manual_local"
    retention: str = "local_only"
    quality: str = "current"

    def as_observation(self) -> FixedIncomeMarketObservation:
        points = (
            {point.tenor: point.value for point in self.tenor_points}
            if self.tenor_points
            else dict(self.tenors)
        )
        return FixedIncomeMarketObservation(
            instrument_id=self.curve_id,
            provider_id=self.provider_id,
            observation_type="yield_curve",
            market=self.market,
            currency=self.currency,
            valid_at=self.valid_at,
            known_at=self.known_at,
            retrieved_at=self.retrieved_at,
            source_checksum=self.source_checksum,
            raw_checksum=self.raw_checksum,
            values={
                "tenors": points,
                "curve_type": self.curve_type,
                "interpolation": self.interpolation,
            },
            evidence_label="evaluated",
            source_authority=self.source_authority,
            legal_terms_record=self.legal_terms_record,
            retention=self.retention,
            quality=self.quality,
            revision=self.revision,
            source_reference=self.source_reference,
            quality_label=self.quality_label,
        )


@dataclass(frozen=True)
class BondLiquidityObservation:
    instrument_id: str
    provider_id: str
    market: str
    currency: str
    valid_at: datetime
    known_at: datetime
    retrieved_at: datetime
    source_checksum: str
    raw_checksum: str
    bid: Decimal | float | int | str | None = None
    ask: Decimal | float | int | str | None = None
    trade_price: Decimal | float | int | str | None = None
    trade_size: Decimal | float | int | str | None = None
    tape_available: bool = False
    quote_type: str = "unavailable"
    revision: int = 1
    source_reference: str = ""
    quality_label: str = "observed"
    evidence_label: str = "indicative"
    source_authority: str = SourceAuthority.MANUAL.value
    legal_terms_record: str = "manual_local"
    retention: str = "local_only"
    quality: str = "current"

    def as_observation(self) -> FixedIncomeMarketObservation:
        return FixedIncomeMarketObservation(
            instrument_id=self.instrument_id,
            provider_id=self.provider_id,
            observation_type="bond_liquidity",
            market=self.market,
            currency=self.currency,
            valid_at=self.valid_at,
            known_at=self.known_at,
            retrieved_at=self.retrieved_at,
            source_checksum=self.source_checksum,
            raw_checksum=self.raw_checksum,
            values={
                "bid": self.bid,
                "ask": self.ask,
                "trade_price": self.trade_price,
                "trade_size": self.trade_size,
                "tape_available": self.tape_available,
                "quote_type": self.quote_type,
            },
            bid=self.bid,
            ask=self.ask,
            trade_price=self.trade_price,
            trade_size=self.trade_size,
            tape_available=self.tape_available,
            evidence_label=(
                "executable"
                if self.quote_type == "direct" and self.tape_available
                else (
                    "evaluated"
                    if self.quality_label == "evaluated"
                    else self.evidence_label
                )
            ),
            source_authority=self.source_authority,
            legal_terms_record=self.legal_terms_record,
            retention=self.retention,
            quality=(
                "stale"
                if self.quality_label == "stale"
                else self.quality
            ),
            revision=self.revision,
            source_reference=self.source_reference,
            quality_label=self.quality_label,
        )


@dataclass(frozen=True)
class ProviderCoverage:
    provider_id: str
    as_of: datetime
    source_checksum: str
    raw_checksum: str
    market_covered: int | None = None
    market_total: int | None = None
    rating_covered: int | None = None
    rating_total: int | None = None
    currency_covered: int | None = None
    currency_total: int | None = None
    duration_covered: int | None = None
    duration_total: int | None = None
    size_covered: int | None = None
    size_total: int | None = None
    history_covered: int | None = None
    history_total: int | None = None


class FixedIncomeMarketDataStore:
    """Append-only immutable evidence with deterministic point-in-time replay."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        try:
            self._store = TransactionalStore(self.root)
            self._load()
        except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise FixedIncomeMarketDataSchemaError(
                f"fixed-income market-data storage is unavailable: {exc}"
            ) from exc

    def __enter__(self) -> "FixedIncomeMarketDataStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._store.close()

    def append(
        self,
        observations: Sequence[
            FixedIncomeMarketObservation | YieldCurveSnapshot | BondLiquidityObservation
        ],
    ) -> tuple[str, ...]:
        items = tuple(_normalise(item) for item in observations)
        records = tuple((_ENTITY_TYPE, item.identity, _payload(item)) for item in items)
        try:
            self._store.put_many(records, immutable=True)
        except (StorageRevisionConflict, sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise FixedIncomeMarketDataSchemaError(
                f"fixed-income market-data append rejected: {exc}"
            ) from exc
        return tuple(item.identity for item in items)

    def import_manual_local(
        self,
        observations: Sequence[
            FixedIncomeMarketObservation | YieldCurveSnapshot | BondLiquidityObservation
        ],
        *,
        legal_terms_path: Path | None = None,
    ) -> tuple[str, ...]:
        """Validate legal/cache authority, then append user-owned local evidence."""

        try:
            registry = load_legal_terms(
                legal_terms_path or self.root / "configs" / "legal_terms_registry.yaml"
            )
        except LegalTermsError as exc:
            raise FixedIncomeMarketDataError("legal terms authority is unavailable") from exc
        entry = registry.entry("manual_local")
        if (
            entry is None
            or entry.unresolved
            or not entry.terms_reference
            or not entry.permitted_cache
            or entry.permitted_cache not in {"local_only", "local_user_only", "local_replay"}
        ):
            raise FixedIncomeMarketDataError(
                "manual_local licence and retention approval is required"
            )
        items = tuple(_normalise(item) for item in observations)
        if any(item.provider_id != "manual_local" for item in items):
            raise FixedIncomeMarketDataError(
                "the manual import path only accepts provider_id=manual_local"
            )
        if any(
            item.legal_terms_record != "manual_local"
            or item.retention != entry.permitted_cache
            or item.source_authority != SourceAuthority.MANUAL.value
            for item in items
        ):
            raise FixedIncomeMarketDataError(
                "observation legal terms and retention do not match manual_local authority"
            )
        security_ids = {
            item.instrument_id
            for item in items
            if item.observation_type != "yield_curve"
        }
        if security_ids:
            if not fixed_income_terms_exists(self.root):
                raise FixedIncomeMarketDataError(
                    "canonical fixed-income security terms are required for bond liquidity"
                )
            try:
                with FixedIncomeTermsStore(self.root) as terms:
                    for instrument_id in security_ids:
                        resolution = terms.resolve(instrument_id)
                        if resolution.status != "available":
                            raise FixedIncomeMarketDataError(
                                "bond liquidity requires available, conflict-free security terms"
                            )
            except (FixedIncomeTermsSchemaError, KeyError) as exc:
                raise FixedIncomeMarketDataError(
                    "canonical fixed-income security terms are unavailable"
                ) from exc
        return self.append(items)

    def history(
        self, instrument_id: str, *, decision_time: datetime | None = None
    ) -> tuple[FixedIncomeMarketObservation, ...]:
        cutoff = _utc(decision_time or datetime.max.replace(tzinfo=timezone.utc))
        return tuple(
            sorted(
                (
                    item
                    for item in self._load()
                    if item.instrument_id == str(instrument_id)
                    and item.known_at <= cutoff
                    and item.retrieved_at <= cutoff
                ),
                key=_sort_key,
            )
        )

    def resolve(
        self,
        instrument_id: str,
        *,
        effective_at: datetime | None = None,
        decision_time: datetime | None = None,
        observation_type: str | None = None,
    ) -> dict[str, object]:
        decision = _utc(decision_time or datetime.now(timezone.utc))
        effective = _utc(effective_at or decision)
        visible = tuple(
            item
            for item in self.history(instrument_id, decision_time=decision)
            if item.valid_at <= effective
            and (observation_type is None or item.observation_type == observation_type)
        )
        base = {
            "contract": FIXED_INCOME_MARKET_DATA_CONTRACT,
            "instrument_id": str(instrument_id),
            "execution_allowed": False,
        }
        if not visible:
            return base | {
                "status": "unavailable",
                "reason_codes": ["market_observation_not_known_at_decision_time"],
                "observations": [],
                "precise_liquidity_available": False,
                "provider_coverage": _coverage_projection(self.root),
            }
        by_type_provider: dict[tuple[str, str], FixedIncomeMarketObservation] = {}
        for item in visible:
            key = (item.observation_type, item.provider_id)
            current = by_type_provider.get(key)
            if current is None or _sort_key(item) > _sort_key(current):
                by_type_provider[key] = item
        selected = tuple(
            sorted(
                by_type_provider.values(),
                key=lambda item: (item.observation_type, item.provider_id),
            )
        )
        conflicted_types = {
            kind
            for kind in {item.observation_type for item in selected}
            if len(
                {
                    _market_fingerprint(item)
                    for item in selected
                    if item.observation_type == kind
                }
            )
            > 1
        }
        conflict = bool(conflicted_types)
        stale = any(
            item.quality != "current" or item.evidence_label == "evaluated"
            for item in selected
        )
        rows = tuple(_projection(item) for item in selected)
        liquidity_rows = tuple(
            row for row in rows if row["observation_type"] == "bond_liquidity"
        )
        executable = (
            bool(liquidity_rows)
            and "bond_liquidity" not in conflicted_types
            and all(
                bool(row["precise_liquidity_available"])
                for row in liquidity_rows
            )
        )
        reasons = ["provider_conflict"] if conflict else []
        if not executable:
            reasons.append("precise_liquidity_or_execution_evidence_unavailable")
        return base | {
            "status": "conflicted" if conflict else ("stale" if stale else "available"),
            "reason_codes": reasons,
            "observations": list(rows),
            "history": [_projection(item) for item in visible],
            "precise_liquidity_available": executable,
            "provider_coverage": _coverage_projection(self.root),
        }

    def _load(self) -> tuple[FixedIncomeMarketObservation, ...]:
        try:
            return tuple(_from_payload(record.payload) for record in self._store.list(_ENTITY_TYPE))
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            raise FixedIncomeMarketDataSchemaError(
                f"fixed-income market-data store is corrupt: {exc}"
            ) from exc


def write_provider_coverage(path: Path, rows: Sequence[ProviderCoverage]) -> Path:
    """Materialise explicit numerators/denominators without deriving estimates."""

    payload_rows: list[dict[str, object]] = []
    dimensions = ("market", "rating", "currency", "duration", "size", "history")
    for row in rows:
        if not row.provider_id.strip():
            raise FixedIncomeMarketDataError("coverage provider_id is required")
        _utc(row.as_of)
        _checksum(row.source_checksum, "source_checksum")
        _checksum(row.raw_checksum, "raw_checksum")
        payload = _jsonable(asdict(row))
        payload["contract"] = FIXED_INCOME_COVERAGE_CONTRACT
        for dimension in dimensions:
            covered = getattr(row, f"{dimension}_covered")
            total = getattr(row, f"{dimension}_total")
            if (covered is None) != (total is None):
                raise FixedIncomeMarketDataError(
                    f"{dimension} coverage requires both numerator and denominator"
                )
            if covered is not None and (
                covered < 0 or total is None or total <= 0 or covered > total
            ):
                raise FixedIncomeMarketDataError(f"{dimension} coverage is invalid")
            payload[f"{dimension}_status"] = (
                "available" if covered is not None else "unavailable"
            )
        payload_rows.append(payload)
    frame = pd.DataFrame(payload_rows)
    destination = Path(path)
    atomic_write_bytes(destination, parquet_payload(frame), validate_parquet_file)
    return destination


def read_provider_coverage(path: Path) -> tuple[dict[str, object], ...]:
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError, ImportError) as exc:
        raise FixedIncomeMarketDataSchemaError("provider coverage is unavailable") from exc
    rows = tuple(frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records"))
    if any(row.get("contract") != FIXED_INCOME_COVERAGE_CONTRACT for row in rows):
        raise FixedIncomeMarketDataSchemaError("provider coverage contract is invalid")
    for row in rows:
        try:
            if not str(row.get("provider_id", "")).strip():
                raise FixedIncomeMarketDataError("coverage provider_id is required")
            _utc(datetime.fromisoformat(str(row["as_of"])))
            _checksum(str(row["source_checksum"]), "source_checksum")
            _checksum(str(row["raw_checksum"]), "raw_checksum")
            for dimension in ("market", "rating", "currency", "duration", "size", "history"):
                covered, total = row.get(f"{dimension}_covered"), row.get(f"{dimension}_total")
                if (covered is None) != (total is None):
                    raise FixedIncomeMarketDataError("incomplete coverage pair")
                expected_status = "available" if covered is not None else "unavailable"
                if row.get(f"{dimension}_status") != expected_status:
                    raise FixedIncomeMarketDataError("coverage status does not match values")
                if covered is not None and (
                    int(covered) < 0 or int(total) <= 0 or int(covered) > int(total)
                ):
                    raise FixedIncomeMarketDataError("invalid coverage pair")
        except (KeyError, TypeError, ValueError, FixedIncomeMarketDataError) as exc:
            raise FixedIncomeMarketDataSchemaError("provider coverage row is invalid") from exc
    return rows


def fixed_income_market_data_exists(root: Path) -> bool:
    """Check for evidence without creating storage during a read projection."""

    path = storage_layout(root).transactional_path
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            return (
                connection.execute(
                    "SELECT 1 FROM transactional_records "
                    "WHERE entity_type=? AND deleted_at IS NULL LIMIT 1",
                    (_ENTITY_TYPE,),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise FixedIncomeMarketDataSchemaError(
            f"fixed-income market-data store is unreadable: {exc}"
        ) from exc


def _normalise(
    item: FixedIncomeMarketObservation | YieldCurveSnapshot | BondLiquidityObservation,
) -> FixedIncomeMarketObservation:
    if isinstance(item, YieldCurveSnapshot | BondLiquidityObservation):
        item = item.as_observation()
    if not isinstance(item, FixedIncomeMarketObservation):
        raise FixedIncomeMarketDataError("unsupported market observation")
    required = (
        item.instrument_id,
        item.provider_id,
        item.observation_type,
        item.market,
        item.currency,
    )
    if any(not str(value).strip() for value in required):
        raise FixedIncomeMarketDataError("market observation identity is incomplete")
    if item.revision < 1:
        raise FixedIncomeMarketDataError("revision must be positive")
    _checksum(item.source_checksum, "source_checksum")
    _checksum(item.raw_checksum, "raw_checksum")
    valid, known, retrieved = (
        _utc(item.valid_at),
        _utc(item.known_at),
        _utc(item.retrieved_at),
    )
    if known > retrieved:
        raise FixedIncomeMarketDataError("known_at cannot be after retrieved_at")
    if item.evidence_label not in {"indicative", "evaluated", "executable"}:
        raise FixedIncomeMarketDataError("invalid evidence_label")
    if item.quality not in {"current", "stale", "unavailable"}:
        raise FixedIncomeMarketDataError("invalid quality")
    try:
        source_authority = SourceAuthority(
            str(item.source_authority).strip().lower()
        ).value
    except ValueError as exc:
        raise FixedIncomeMarketDataError("invalid source authority") from exc
    if not item.legal_terms_record.strip():
        raise FixedIncomeMarketDataError("source authority and legal terms record are required")
    if item.retention not in {"local_only", "local_user_only", "local_replay"}:
        raise FixedIncomeMarketDataError("invalid retention authority")
    if len(item.currency.strip()) != 3 or not item.currency.strip().isalpha():
        raise FixedIncomeMarketDataError("currency must be a three-letter code")
    numeric_fields = (
        "clean_price", "dirty_price", "yield_value", "spread", "bid", "ask",
        "quote_size", "trade_price", "trade_size",
    )
    for name in numeric_fields:
        value = getattr(item, name)
        if value is not None:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise FixedIncomeMarketDataError(f"{name} must be numeric") from exc
            if not math.isfinite(number):
                raise FixedIncomeMarketDataError(f"{name} must be finite")
    if item.bid is not None and item.ask is not None and float(item.bid) > float(item.ask):
        raise FixedIncomeMarketDataError("bid cannot exceed ask")
    if item.evidence_label == "executable" and (
        item.observation_type != "bond_liquidity"
        or item.bid is None
        or item.ask is None
        or not item.tape_available
    ):
        raise FixedIncomeMarketDataError("executable evidence requires direct quote and tape")
    if item.observation_type == "yield_curve":
        curve_type = str(item.values.get("curve_type", "")).strip()
        interpolation = str(item.values.get("interpolation", "")).strip()
        tenors = item.values.get("tenors")
        if not curve_type or interpolation not in {
            "linear",
            "log_linear",
            "piecewise_constant",
            "none",
        }:
            raise FixedIncomeMarketDataError("yield curve type/interpolation is invalid")
        if not isinstance(tenors, Mapping) or not tenors:
            raise FixedIncomeMarketDataError("yield curve requires typed tenor points")
        for tenor, value in tenors.items():
            if not str(tenor).strip():
                raise FixedIncomeMarketDataError("yield curve tenor is required")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise FixedIncomeMarketDataError("yield curve point must be numeric") from exc
            if not math.isfinite(number):
                raise FixedIncomeMarketDataError("yield curve point must be finite")
    return FixedIncomeMarketObservation(
        **{
            **asdict(item),
            "instrument_id": item.instrument_id.strip(),
            "provider_id": item.provider_id.strip().lower(),
            "observation_type": item.observation_type.strip().lower(),
            "market": item.market.strip().upper(),
            "currency": item.currency.strip().upper(),
            "valid_at": valid,
            "known_at": known,
            "retrieved_at": retrieved,
            "source_checksum": item.source_checksum.lower(),
            "raw_checksum": item.raw_checksum.lower(),
            "values": _jsonable(dict(item.values)),
            "quality_label": item.quality_label.strip().lower(),
            "source_authority": source_authority,
        }
    )


def _projection(item: FixedIncomeMarketObservation) -> dict[str, object]:
    precise = True
    if item.observation_type == "bond_liquidity":
        precise = (
            item.bid is not None
            and item.ask is not None
            and item.tape_available
            and item.evidence_label == "executable"
            and item.quality == "current"
        )
    return _payload(item) | {
        "observation_id": item.identity,
        "content_checksum": item.content_checksum,
        "precise_liquidity_available": precise,
        "executable_claim_allowed": False,
        "execution_allowed": False,
    }


def _payload(item: FixedIncomeMarketObservation) -> dict[str, object]:
    return {
        "contract": FIXED_INCOME_MARKET_DATA_CONTRACT,
        **_jsonable(asdict(item)),
    }


def _from_payload(payload: Mapping[str, object]) -> FixedIncomeMarketObservation:
    if payload.get("contract") != FIXED_INCOME_MARKET_DATA_CONTRACT:
        raise ValueError("unknown fixed-income market-data contract")
    numeric = Decimal | float | int | str | None
    return _normalise(
        FixedIncomeMarketObservation(
            instrument_id=str(payload["instrument_id"]),
            provider_id=str(payload["provider_id"]),
            observation_type=str(payload["observation_type"]),
            market=str(payload["market"]),
            currency=str(payload["currency"]),
            valid_at=datetime.fromisoformat(str(payload["valid_at"])),
            known_at=datetime.fromisoformat(str(payload["known_at"])),
            retrieved_at=datetime.fromisoformat(str(payload["retrieved_at"])),
            source_checksum=str(payload["source_checksum"]),
            raw_checksum=str(payload["raw_checksum"]),
            values=dict(cast(Mapping[str, object], payload.get("values", {}))),
            clean_price=cast(numeric, payload.get("clean_price")),
            dirty_price=cast(numeric, payload.get("dirty_price")),
            yield_value=cast(numeric, payload.get("yield_value")),
            spread=cast(numeric, payload.get("spread")),
            bid=cast(numeric, payload.get("bid")),
            ask=cast(numeric, payload.get("ask")),
            quote_size=cast(numeric, payload.get("quote_size")),
            trade_price=cast(numeric, payload.get("trade_price")),
            trade_size=cast(numeric, payload.get("trade_size")),
            tape_available=bool(payload.get("tape_available", False)),
            evidence_label=str(payload.get("evidence_label", "indicative")),
            source_authority=str(payload.get("source_authority", "user_owned")),
            legal_terms_record=str(payload.get("legal_terms_record", "")),
            retention=str(payload.get("retention", "")),
            quality=str(payload.get("quality", "current")),
            revision=int(cast(int | str, payload.get("revision", 1))),
            source_reference=str(payload.get("source_reference", "")),
            quality_label=str(payload.get("quality_label", "observed")),
        )
    )


def _market_fingerprint(item: FixedIncomeMarketObservation) -> str:
    return _hash(
        {
            "observation_type": item.observation_type,
            "values": item.values,
            "clean_price": item.clean_price,
            "dirty_price": item.dirty_price,
            "yield_value": item.yield_value,
            "spread": item.spread,
            "bid": item.bid,
            "ask": item.ask,
            "quote_size": item.quote_size,
            "trade_price": item.trade_price,
            "trade_size": item.trade_size,
            "tape_available": item.tape_available,
            "evidence_label": item.evidence_label,
            "quality": item.quality,
        }
    )


def _sort_key(item: FixedIncomeMarketObservation) -> tuple[datetime, int, datetime, str]:
    return (item.valid_at, item.revision, item.retrieved_at, item.content_checksum)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FixedIncomeMarketDataError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _checksum(value: str, name: str) -> None:
    text = str(value).strip().lower()
    if len(text) != 64 or any(char not in _SHA256 for char in text):
        raise FixedIncomeMarketDataError(f"{name} must be a SHA-256 checksum")


def _hash(value: object) -> str:
    encoded = json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _jsonable(value: object) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _coverage_projection(root: Path) -> dict[str, object]:
    path = root / FIXED_INCOME_PROVIDER_COVERAGE_PATH
    if not path.is_file():
        return {"status": "unavailable", "rows": []}
    try:
        return {"status": "available", "rows": list(read_provider_coverage(path))}
    except FixedIncomeMarketDataSchemaError:
        return {"status": "unavailable", "rows": [], "reason_code": "coverage_invalid"}


__all__ = [
    "BondLiquidityObservation",
    "CurveTenorPoint",
    "FIXED_INCOME_COVERAGE_CONTRACT",
    "FIXED_INCOME_MARKET_DATA_CONTRACT",
    "FIXED_INCOME_PROVIDER_COVERAGE_PATH",
    "FixedIncomeMarketDataError",
    "FixedIncomeMarketDataSchemaError",
    "FixedIncomeMarketDataStore",
    "FixedIncomeMarketObservation",
    "ProviderCoverage",
    "YieldCurveSnapshot",
    "fixed_income_market_data_exists",
    "read_provider_coverage",
    "write_provider_coverage",
]
