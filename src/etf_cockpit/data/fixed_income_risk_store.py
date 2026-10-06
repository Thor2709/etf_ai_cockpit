"""Atomic immutable storage and verified replay for fixed-income risk."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping, Sequence, cast

import pandas as pd

from etf_cockpit.analysis.fixed_income_analytics import _hash, _jsonable
from etf_cockpit.analysis.fixed_income_risk import (
    CurveShock,
    FIXED_INCOME_RISK_CONTRACT,
    FixedIncomeRiskError,
    FixedIncomeRiskInput,
    FixedIncomeRiskRecord,
    calculate_fixed_income_risk,
)
from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.data.bond_analytics_store import _input_from_payload
from etf_cockpit.data.local_storage import TransactionalStore, storage_layout


@dataclass(frozen=True)
class StoredFixedIncomeRisk:
    record_id: str
    calculated_at: datetime
    input: FixedIncomeRiskInput
    result: FixedIncomeRiskRecord
    execution_allowed: bool = False


def write_fixed_income_risk(
    path: Path, records: Iterable[StoredFixedIncomeRisk]
) -> Path:
    items = tuple(records)
    if not items:
        raise FixedIncomeRiskError("empty risk publication is invalid")
    rows = []
    for item in items:
        canonical = calculate_fixed_income_risk(item.input)
        if (
            not item.record_id
            or item.record_id != item.input.input_hash
            or item.execution_allowed
            or item.calculated_at.tzinfo is None
            or item.calculated_at.utcoffset() != timezone.utc.utcoffset(item.calculated_at)
            or item.calculated_at < item.input.valuation.decision_time
            or _jsonable(asdict(canonical)) != _jsonable(asdict(item.result))
        ):
            raise FixedIncomeRiskError("risk record is not canonical")
        payload = _jsonable(asdict(item.input))
        result = _jsonable(asdict(item.result))
        rows.append(
            {
                "schema_version": 1,
                "contract": FIXED_INCOME_RISK_CONTRACT,
                "record_id": item.record_id,
                "instrument_id": item.input.valuation.instrument_id,
                "decision_time": item.input.valuation.decision_time.isoformat(),
                "calculated_at": item.calculated_at.isoformat(),
                "input_hash": item.input.input_hash,
                "input_json": json.dumps(payload, sort_keys=True),
                "result_json": json.dumps(result, sort_keys=True),
                "result_checksum": _hash(result),
                "execution_allowed": False,
            }
        )
    target = Path(path).resolve()
    root = _root_for(target)
    with TransactionalStore(root) as store:
        with store.transaction() as connection:
            for row in rows:
                encoded = json.dumps(row, sort_keys=True, separators=(",", ":"))
                previous = connection.execute(
                    "SELECT payload_json FROM transactional_records WHERE entity_type=? AND entity_id=? AND deleted_at IS NULL",
                    ("fixed_income_risk_v1", row["record_id"]),
                ).fetchone()
                if previous:
                    if json.loads(str(previous[0])) != row:
                        raise FixedIncomeRiskError("risk record identity/content collision")
                    continue
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """INSERT INTO transactional_records
                    (entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at)
                    VALUES (?, ?, ?, 1, ?, ?, NULL)""",
                    ("fixed_income_risk_v1", row["record_id"], encoded, now, now),
                )
            stored = connection.execute(
                "SELECT payload_json FROM transactional_records WHERE entity_type=? AND deleted_at IS NULL ORDER BY entity_id",
                ("fixed_income_risk_v1",),
            ).fetchall()
            atomic_write_bytes(
                target,
                parquet_payload(pd.DataFrame([json.loads(str(row[0])) for row in stored])),
                validate_parquet_file,
            )
    return target


def read_fixed_income_risk(path: Path) -> tuple[Mapping[str, object], ...]:
    target = Path(path).resolve()
    try:
        frame = pd.read_parquet(target)
    except (OSError, ValueError, ImportError) as exc:
        raise FixedIncomeRiskError("fixed-income risk store is unavailable") from exc
    required = {
        "schema_version", "contract", "record_id", "instrument_id", "decision_time",
        "calculated_at", "input_hash", "input_json", "result_json", "result_checksum",
        "execution_allowed",
    }
    if set(frame.columns) != required or frame.empty:
        raise FixedIncomeRiskError("fixed-income risk schema is invalid")
    database = storage_layout(_root_for(target)).transactional_path
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        committed = [
            json.loads(str(row[0]))
            for row in connection.execute(
                "SELECT payload_json FROM transactional_records WHERE entity_type=? AND deleted_at IS NULL ORDER BY entity_id",
                ("fixed_income_risk_v1",),
            )
        ]
    except (sqlite3.DatabaseError, OSError) as exc:
        raise FixedIncomeRiskError("committed fixed-income risk store is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()
    projected = frame.to_dict("records")
    if _normalise(projected) != _normalise(committed):
        raise FixedIncomeRiskError("risk projection diverges from committed records")
    output = []
    for row in projected:
        try:
            if (
                int(row["schema_version"]) != 1
                or row["contract"] != FIXED_INCOME_RISK_CONTRACT
                or bool(row["execution_allowed"])
            ):
                raise FixedIncomeRiskError("risk schema or authority is invalid")
            payload = json.loads(str(row["input_json"]))
            result = json.loads(str(row["result_json"]))
            rebuilt = _risk_input(payload)
            canonical = _jsonable(asdict(calculate_fixed_income_risk(rebuilt)))
            decision_time = datetime.fromisoformat(str(row["decision_time"]))
            calculated_at = datetime.fromisoformat(str(row["calculated_at"]))
            if (
                rebuilt.input_hash != row["input_hash"]
                or row["record_id"] != rebuilt.input_hash
                or row["instrument_id"] != rebuilt.valuation.instrument_id
                or decision_time != rebuilt.valuation.decision_time
                or calculated_at.tzinfo is None
                or calculated_at.utcoffset() != timezone.utc.utcoffset(calculated_at)
                or calculated_at < decision_time.astimezone(timezone.utc)
                or _hash(result) != row["result_checksum"]
                or canonical != result
                or result.get("execution_allowed") is not False
            ):
                raise FixedIncomeRiskError("risk hash/result verification failed")
            output.append(dict(row) | {"result": result})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FixedIncomeRiskError("fixed-income risk record is corrupt") from exc
    return tuple(output)


def _risk_input(payload: Mapping[str, object]) -> FixedIncomeRiskInput:
    valuation = _input_from_payload(payload["valuation"])  # type: ignore[arg-type]
    scenario_rows = cast(Iterable[Mapping[str, object]], payload["scenarios"])
    scenarios = tuple(
        CurveShock(
            str(row["scenario_id"]),
            Decimal(str(row["parallel_bps"])),
            tuple(
                (Decimal(str(pair[0])), Decimal(str(pair[1])))
                for pair in cast(
                    Iterable[Sequence[object]], row["key_rate_bps"]
                )
            ),
        )
        for row in scenario_rows
    )
    decimal_fields = {
        name: Decimal(str(payload[name])) if payload.get(name) is not None else None
        for name in (
            "spread_shock_bps", "rating_change_loss", "default_probability",
            "recovery_rate", "quote_age_seconds", "minimum_size",
            "intended_liquidation_size", "liquidity_cost_bps",
        )
    }
    return FixedIncomeRiskInput(
        valuation=valuation,
        instrument_kind=str(payload["instrument_kind"]),
        position_face_value=Decimal(str(payload["position_face_value"])),
        scenarios=scenarios,
        issuer_id=str(payload["issuer_id"]) if payload.get("issuer_id") else None,
        callable=bool(payload.get("callable")),
        inflation_linked=bool(payload.get("inflation_linked")),
        fx_exposed=bool(payload.get("fx_exposed")),
        evidence_lineage=tuple(
            str(value)
            for value in cast(
                Iterable[object], payload.get("evidence_lineage", ())
            )
        ),
        schema_version=int(str(payload["schema_version"])),
        **decimal_fields,
    )


def _normalise(rows: Iterable[Mapping[str, object]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            json.dumps(_jsonable(dict(row)), sort_keys=True, separators=(",", ":"), allow_nan=False)
            for row in rows
        )
    )


def _root_for(target: Path) -> Path:
    return target.parents[2] if target.parent.name == "analytics" and target.parent.parent.name == "data" else target.parent
