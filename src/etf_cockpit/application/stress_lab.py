"""Application boundary for local Stress Lab scenarios."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Mapping

import pandas as pd

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    StoredRecord,
    TransactionalStore,
)
from etf_cockpit.portfolio.factor_risk import build_factor_exposures
from etf_cockpit.portfolio.stress_testing import (
    StressResult,
    StressScenario,
    StressScenarioError,
    reverse_stress,
    run_stress_scenario,
)


STRESS_SCENARIO_ENTITY = "stress_scenario"


class StressLabPersistenceError(RuntimeError):
    """Raised when local scenario state is unavailable or corrupted."""


@dataclass(frozen=True)
class SavedStressScenario:
    scenario: StressScenario
    revision: int
    updated_at: str


def build_stress_scenario(
    *,
    scenario_id: str,
    name: str,
    shocks: Mapping[str, object],
    horizon_days: object = 1,
    historical_date: str | None = None,
    version: object = 1,
) -> StressScenario:
    try:
        parsed_shocks = {str(key): float(value) for key, value in shocks.items()}
        return StressScenario(
            scenario_id=scenario_id,
            name=name,
            shocks=parsed_shocks,
            horizon_days=_integer(horizon_days, "horizon_days"),
            historical_date=historical_date or None,
            version=_integer(version, "version"),
        )
    except (TypeError, ValueError, StressScenarioError) as exc:
        raise StressScenarioError(f"scenario inputs are invalid: {exc}") from exc


class StressLabFacade:
    """Run and persist evidence-only scenarios using the current local snapshot."""

    def __init__(self, snapshot: object, *, root: Path = ROOT) -> None:
        self.snapshot = snapshot
        self.root = root

    def run(self, scenario: StressScenario, *, notional: float = 100_000.0) -> StressResult:
        allocation = _allocation(self.snapshot)
        exposures = _factor_exposures(self.snapshot, allocation)
        historical = _adjusted_returns(getattr(self.snapshot, "prices", None)) if scenario.historical_date else None
        return run_stress_scenario(
            scenario,
            allocation,
            factor_exposures=exposures,
            historical_returns=historical,
            notional=notional,
        )

    def reverse(
        self,
        *,
        shock_name: str,
        loss_limit: float,
        notional: float = 100_000.0,
        upper_bound: float = 5.0,
    ) -> dict[str, object]:
        allocation = _allocation(self.snapshot)
        return reverse_stress(
            allocation,
            shock_name=shock_name,
            loss_limit=loss_limit,
            factor_exposures=_factor_exposures(self.snapshot, allocation),
            notional=notional,
            upper_bound=upper_bound,
        )

    def save(self, scenario: StressScenario, *, expected_revision: int = 0) -> SavedStressScenario:
        payload = _scenario_payload(scenario)
        try:
            with TransactionalStore(self.root) as store:
                record = store.put(
                    STRESS_SCENARIO_ENTITY,
                    scenario.scenario_id,
                    payload,
                    expected_revision=expected_revision,
                )
        except StorageRevisionConflict:
            raise
        except (OSError, sqlite3.Error, StorageSchemaError) as exc:
            raise StressLabPersistenceError(f"local scenario storage is unavailable: {exc}") from exc
        return SavedStressScenario(scenario, record.revision, record.updated_at)

    def load(self, scenario_id: str) -> SavedStressScenario:
        try:
            with TransactionalStore(self.root) as store:
                record = store.get(STRESS_SCENARIO_ENTITY, scenario_id)
        except (OSError, sqlite3.Error, StorageSchemaError) as exc:
            raise StressLabPersistenceError(f"local scenario storage is unavailable: {exc}") from exc
        if record is None:
            raise StressLabPersistenceError("no saved scenario has this ID")
        return SavedStressScenario(_scenario_from_record(record), record.revision, record.updated_at)

    def list_saved(self) -> tuple[SavedStressScenario, ...]:
        try:
            with TransactionalStore(self.root) as store:
                records = store.list(STRESS_SCENARIO_ENTITY)
        except (OSError, sqlite3.Error, StorageSchemaError) as exc:
            raise StressLabPersistenceError(f"local scenario storage is unavailable: {exc}") from exc
        return tuple(SavedStressScenario(_scenario_from_record(record), record.revision, record.updated_at) for record in records)


def _allocation(snapshot: object) -> pd.DataFrame:
    holdings = getattr(snapshot, "holdings", None)
    if holdings is None or not isinstance(holdings, pd.DataFrame):
        return pd.DataFrame()
    return holdings.copy()


def _factor_exposures(snapshot: object, allocation: pd.DataFrame) -> pd.DataFrame:
    if allocation.empty:
        return pd.DataFrame()
    factor_allocation = allocation.copy()
    if "etf_id" not in factor_allocation.columns and "instrument_id" in factor_allocation.columns:
        factor_allocation = factor_allocation.rename(columns={"instrument_id": "etf_id"})
    return build_factor_exposures(
        factor_allocation,
        getattr(snapshot, "latest_features", None),
        getattr(snapshot, "holdings", None),
    )


def _adjusted_returns(prices: object) -> pd.DataFrame | None:
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return None
    identifier = "instrument_id" if "instrument_id" in prices.columns else "etf_id" if "etf_id" in prices.columns else None
    date_column = "date" if "date" in prices.columns else "as_of" if "as_of" in prices.columns else None
    price_column = next((column for column in ("adjusted_close", "adj_close", "close_adjusted", "total_return_price") if column in prices.columns), None)
    if identifier is None or date_column is None or price_column is None:
        return None
    frame = prices[[identifier, date_column, price_column]].copy().rename(columns={identifier: "instrument_id", date_column: "date", price_column: "adjusted_close"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna(subset=["date", "adjusted_close"]).sort_values(["instrument_id", "date"])
    frame["adjusted_return"] = frame.groupby("instrument_id", sort=False)["adjusted_close"].pct_change()
    return frame[["instrument_id", "date", "adjusted_return"]]


def _scenario_payload(scenario: StressScenario) -> dict[str, object]:
    body = scenario.to_payload()
    body["assumption_fingerprint"] = _payload_checksum(body)
    return {**body, "payload_checksum": _payload_checksum(body)}


def _scenario_from_record(record: StoredRecord) -> StressScenario:
    payload = dict(record.payload)
    required = {
        "schema_version",
        "scenario_id",
        "name",
        "shocks",
        "horizon_days",
        "historical_date",
        "version",
        "execution_allowed",
        "assumption_fingerprint",
        "payload_checksum",
    }
    if set(payload) != required or payload.get("execution_allowed") is not False:
        raise StressLabPersistenceError("saved scenario has an invalid field set or authority flag")
    checksum = str(payload.pop("payload_checksum", ""))
    if checksum != _payload_checksum(payload):
        raise StressLabPersistenceError("saved scenario checksum does not match")
    assumption = str(payload.get("assumption_fingerprint", ""))
    body = {key: value for key, value in payload.items() if key != "assumption_fingerprint"}
    if assumption != _payload_checksum(body):
        raise StressLabPersistenceError("saved scenario assumptions do not match")
    scenario = StressScenario(
        scenario_id=str(payload["scenario_id"]),
        name=str(payload["name"]),
        shocks=payload["shocks"],
        horizon_days=payload["horizon_days"],
        historical_date=payload["historical_date"],
        version=payload["version"],
    )
    if scenario.scenario_id != record.entity_id:
        raise StressLabPersistenceError("saved scenario identity does not match its record")
    return scenario


def _payload_checksum(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{label} must be an integer")
    return int(number)


__all__ = [
    "SavedStressScenario",
    "STRESS_SCENARIO_ENTITY",
    "StressLabFacade",
    "StressLabPersistenceError",
    "build_stress_scenario",
]
