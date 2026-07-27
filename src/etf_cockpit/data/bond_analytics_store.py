"""Transactional publication and verified replay of bond analytics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping

import pandas as pd

from etf_cockpit.analysis.fixed_income_analytics import (
    CallRedemption,
    ContractualCashFlow,
    CurveNode,
    DiscountCurveEvidence,
    FIXED_INCOME_ANALYTICS_CONTRACT,
    FIXED_INCOME_ANALYTICS_SCHEMA_VERSION,
    FixedIncomeAnalyticsError,
    FixedIncomeValuationInput,
    FixedIncomeValuationResult,
    ObservedBondPrice,
    _hash,
    _jsonable,
    calculate_fixed_income_analytics,
)
from etf_cockpit.core.atomic_io import (
    atomic_write_bytes,
    parquet_payload,
    validate_parquet_file,
)
from etf_cockpit.data.local_storage import TransactionalStore, storage_layout
from etf_cockpit.data.market_calendar import DayCountConvention


@dataclass(frozen=True)
class BondAnalyticsRecord:
    record_id: str
    calculated_at: datetime
    input: FixedIncomeValuationInput
    result: FixedIncomeValuationResult
    schema_version: int = FIXED_INCOME_ANALYTICS_SCHEMA_VERSION
    execution_allowed: bool = False


def write_bond_analytics(path: Path, records: Iterable[BondAnalyticsRecord]) -> Path:
    items = tuple(records)
    if not items:
        raise FixedIncomeAnalyticsError("empty analytics stores are invalid")
    unique: dict[str, BondAnalyticsRecord] = {}
    for item in items:
        _validate_record(item)
        previous = unique.get(item.record_id)
        if previous is not None and previous != item:
            raise FixedIncomeAnalyticsError("duplicate analytics record_id has different content")
        unique[item.record_id] = item
    rows = [_record_row(item) for item in unique.values()]
    target = Path(path).resolve()
    root = _root_for(target)
    with TransactionalStore(root) as store:
        with store.transaction() as connection:
            for row in rows:
                encoded = json.dumps(row, sort_keys=True, separators=(",", ":"))
                previous = connection.execute(
                    "SELECT payload_json FROM transactional_records WHERE entity_type=? AND entity_id=? AND deleted_at IS NULL",
                    ("bond_analytics_v1", row["record_id"]),
                ).fetchone()
                if previous:
                    if json.loads(str(previous[0])) != row:
                        raise FixedIncomeAnalyticsError(
                            "analytics record identity already exists with different content"
                        )
                    continue
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """INSERT INTO transactional_records
                    (entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at)
                    VALUES (?, ?, ?, 1, ?, ?, NULL)""",
                    ("bond_analytics_v1", row["record_id"], encoded, now, now),
                )
            stored = connection.execute(
                "SELECT payload_json FROM transactional_records WHERE entity_type=? AND deleted_at IS NULL ORDER BY entity_id",
                ("bond_analytics_v1",),
            ).fetchall()
            atomic_write_bytes(
                target,
                parquet_payload(pd.DataFrame([json.loads(str(row[0])) for row in stored])),
                validate_parquet_file,
            )
    return target


def read_bond_analytics(path: Path) -> tuple[dict[str, object], ...]:
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError, ImportError) as exc:
        raise FixedIncomeAnalyticsError(f"bond analytics unavailable: {exc}") from exc
    required = {
        "schema_version", "record_id", "calculated_at", "instrument_id",
        "input_hash", "input_json", "result_json", "result_checksum",
        "execution_allowed",
    }
    if set(frame.columns) != required or frame.empty:
        raise FixedIncomeAnalyticsError("bond analytics schema is invalid")
    if set(frame["schema_version"]) != {FIXED_INCOME_ANALYTICS_SCHEMA_VERSION}:
        raise FixedIncomeAnalyticsError("bond analytics schema version is unsupported")
    if frame["execution_allowed"].astype(bool).any():
        raise FixedIncomeAnalyticsError("bond analytics execution authority is invalid")
    target = Path(path).resolve()
    database = storage_layout(_root_for(target)).transactional_path
    if not database.is_file():
        raise FixedIncomeAnalyticsError("committed analytics store is unavailable")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        committed = [
            json.loads(str(row[0]))
            for row in connection.execute(
                "SELECT payload_json FROM transactional_records WHERE entity_type=? AND deleted_at IS NULL ORDER BY entity_id",
                ("bond_analytics_v1",),
            )
        ]
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        raise FixedIncomeAnalyticsError("committed analytics store is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()
    projected = frame.to_dict("records")
    if _normalise_rows(projected) != _normalise_rows(committed):
        raise FixedIncomeAnalyticsError("bond analytics projection diverges from committed records")
    return tuple(_validate_row(row) for row in projected)


def _record_row(item: BondAnalyticsRecord) -> dict[str, object]:
    return {
        "schema_version": item.schema_version,
        "record_id": item.record_id,
        "calculated_at": item.calculated_at.isoformat(),
        "instrument_id": item.input.instrument_id,
        "input_hash": item.result.input_hash,
        "input_json": json.dumps(_jsonable(asdict(item.input)), sort_keys=True),
        "result_json": json.dumps(_jsonable(asdict(item.result)), sort_keys=True),
        "result_checksum": _hash(_jsonable(asdict(item.result))),
        "execution_allowed": False,
    }


def _validate_record(item: BondAnalyticsRecord) -> None:
    if (
        item.schema_version != FIXED_INCOME_ANALYTICS_SCHEMA_VERSION
        or item.execution_allowed or item.result.execution_allowed or not item.record_id
        or item.calculated_at.tzinfo is None
        or item.calculated_at.utcoffset() != timezone.utc.utcoffset(item.calculated_at)
        or item.calculated_at < item.input.decision_time.astimezone(timezone.utc)
    ):
        raise FixedIncomeAnalyticsError("analytics record schema/authority/time is invalid")
    canonical = calculate_fixed_income_analytics(item.input)
    if (
        item.result.instrument_id != item.input.instrument_id
        or item.result.terms_version_id != item.input.terms_version_id
        or item.result.input_hash != item.input.input_hash
        or _jsonable(asdict(canonical)) != _jsonable(asdict(item.result))
    ):
        raise FixedIncomeAnalyticsError("analytics record result is not canonical")


def _validate_row(row: Mapping[str, object]) -> dict[str, object]:
    try:
        calculated = _parse_datetime(row["calculated_at"])
        if calculated.utcoffset() != timezone.utc.utcoffset(calculated):
            raise FixedIncomeAnalyticsError("calculated_at must be UTC")
        source_input = json.loads(str(row["input_json"]))
        result = json.loads(str(row["result_json"]))
        if not isinstance(source_input, dict) or not isinstance(result, dict):
            raise FixedIncomeAnalyticsError("bond analytics JSON is invalid")
        stored_hash = str(row["input_hash"])
        if (
            bool(row["execution_allowed"])
            or result.get("execution_allowed") is not False
            or result.get("instrument_id") != str(row["instrument_id"])
            or result.get("input_hash") != stored_hash
            or _input_payload_hash(source_input) != stored_hash
            or _hash(result) != str(row["result_checksum"])
        ):
            raise FixedIncomeAnalyticsError("bond analytics identity/hash is corrupt")
        rebuilt = _input_from_payload(source_input)
        if calculated < rebuilt.decision_time.astimezone(timezone.utc):
            raise FixedIncomeAnalyticsError("analytics record chronology is invalid")
        if _jsonable(asdict(calculate_fixed_income_analytics(rebuilt))) != result:
            raise FixedIncomeAnalyticsError("bond analytics result is not canonical")
        return {
            "schema_version": int(row["schema_version"]),
            "record_id": str(row["record_id"]),
            "calculated_at": str(row["calculated_at"]),
            "decision_time": rebuilt.decision_time.astimezone(timezone.utc).isoformat(),
            "instrument_id": str(row["instrument_id"]),
            "input_hash": stored_hash,
            "result": result,
            "execution_allowed": False,
        }
    except FixedIncomeAnalyticsError:
        raise
    except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        raise FixedIncomeAnalyticsError("bond analytics record is corrupt") from exc


def _input_from_payload(payload: Mapping[str, object]) -> FixedIncomeValuationInput:
    flows = tuple(
        ContractualCashFlow(
            date.fromisoformat(str(flow["payment_date"])), Decimal(str(flow["amount"])),
            str(flow["kind"]), str(flow["source_version_id"]),
            date.fromisoformat(str(flow["accrual_start"])) if flow.get("accrual_start") else None,
            date.fromisoformat(str(flow["accrual_end"])) if flow.get("accrual_end") else None,
            date.fromisoformat(str(flow["ex_coupon_date"])) if flow.get("ex_coupon_date") else None,
        )
        for flow in payload["cashflows"]  # type: ignore[union-attr]
    )
    calls = tuple(
        CallRedemption(date.fromisoformat(str(call["call_date"])), Decimal(str(call["amount"])), str(call["source_id"]))
        for call in payload.get("calls", ())  # type: ignore[union-attr]
    )
    curve_data = payload.get("curve")
    curve = None
    if isinstance(curve_data, Mapping):
        curve = DiscountCurveEvidence(
            str(curve_data["curve_id"]), str(curve_data["curve_kind"]), str(curve_data["currency"]),
            str(curve_data["rate_unit"]), str(curve_data["compounding"]), str(curve_data["interpolation"]),
            DayCountConvention(str(curve_data["day_count"])),
            tuple(CurveNode(Decimal(str(node["tenor_years"])), Decimal(str(node["rate"]))) for node in curve_data["nodes"]),  # type: ignore[union-attr]
            str(curve_data["source_id"]), str(curve_data["source_version"]), str(curve_data["source_checksum"]),
            _parse_datetime(curve_data["as_of"]), _parse_datetime(curve_data["retrieved_at"]),
            _parse_datetime(curve_data["decision_time"]), int(str(curve_data["schema_version"])),
        )
    observed_data = payload.get("observed_price")
    observed = None
    if isinstance(observed_data, Mapping):
        observed = ObservedBondPrice(
            Decimal(str(observed_data["clean_price"])), str(observed_data["currency"]),
            str(observed_data["price_unit"]), str(observed_data["source_id"]),
            str(observed_data["source_checksum"]), _parse_datetime(observed_data["as_of"]),
            _parse_datetime(observed_data["retrieved_at"]),
        )
    return FixedIncomeValuationInput(
        instrument_id=str(payload["instrument_id"]), terms_version_id=str(payload["terms_version_id"]),
        currency=str(payload["currency"]), face_value=Decimal(str(payload["face_value"])),
        settlement_date=date.fromisoformat(str(payload["settlement_date"])),
        maturity_date=date.fromisoformat(str(payload["maturity_date"])),
        coupon_rate=Decimal(str(payload["coupon_rate"])), coupon_frequency=int(str(payload["coupon_frequency"])),
        day_count=DayCountConvention(str(payload["day_count"])), cashflows=flows,
        decision_time=_parse_datetime(payload["decision_time"]),
        clean_price=Decimal(str(payload["clean_price"])) if payload.get("clean_price") is not None else None,
        yield_to_maturity=Decimal(str(payload["yield_to_maturity"])) if payload.get("yield_to_maturity") is not None else None,
        calls=calls, curve=curve, observed_price=observed,
        scenario_shifts_bps=tuple(Decimal(str(value)) for value in payload.get("scenario_shifts_bps", ())),  # type: ignore[union-attr]
        yield_compounding=str(payload["yield_compounding"]), explicit_stub=bool(payload["explicit_stub"]),
        tolerance=Decimal(str(payload["tolerance"])), schema_version=int(str(payload["schema_version"])),
    )


def _input_payload_hash(payload: Mapping[str, object]) -> str:
    return _hash({"schema_version": payload.get("schema_version"), "contract": FIXED_INCOME_ANALYTICS_CONTRACT, "input": payload, "execution_allowed": False})


def _normalise_rows(rows: Iterable[Mapping[str, object]]) -> tuple[str, ...]:
    return tuple(sorted(json.dumps(_jsonable(dict(row)), sort_keys=True, separators=(",", ":"), allow_nan=False) for row in rows))


def _parse_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed


def _root_for(target: Path) -> Path:
    return target.parents[2] if target.parent.name == "analytics" and target.parent.parent.name == "data" else target.parent
