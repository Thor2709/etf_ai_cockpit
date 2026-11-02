"""Application boundary for local Stress Lab scenarios.

Portfolio selection defaults to the current holdings. A paper account is usable
only when its ledger has complete marked positions; a candidate must have a
published construction result. Missing portfolio evidence remains unavailable.
"""

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
    transactional_store_initialized,
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


class StressPortfolioNotFoundError(LookupError):
    """Raised when a requested local paper account does not exist."""


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

    def run(
        self,
        scenario: StressScenario,
        *,
        notional: float = 100_000.0,
        allocation: pd.DataFrame | None = None,
    ) -> StressResult:
        allocation = _allocation(self.snapshot) if allocation is None else allocation.copy()
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
        allocation: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        allocation = _allocation(self.snapshot) if allocation is None else allocation.copy()
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
            if not transactional_store_initialized(self.root):
                raise StressLabPersistenceError("no saved scenario has this ID")
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


def resolve_stress_portfolio(
    snapshot: object,
    portfolio: str,
    *,
    root: Path = ROOT,
) -> tuple[pd.DataFrame, str | None]:
    """Resolve current, latest published candidate, or one paper account allocation."""

    selected = str(portfolio or "").strip()
    if selected == "current":
        allocation = _allocation(snapshot)
        return (allocation, None) if not allocation.empty else (allocation, "current_portfolio_unavailable")

    if selected == "candidate":
        from etf_cockpit.application.portfolio_sandbox import (
            PORTFOLIO_SANDBOX_ENTITY,
            PORTFOLIO_SANDBOX_RESULT_ENTITY,
            PortfolioSandboxPersistenceError,
            load_portfolio_candidate,
        )

        try:
            if not transactional_store_initialized(root):
                return pd.DataFrame(), "published_candidate_unavailable"
            with TransactionalStore(root) as store:
                with store.read_transaction():
                    candidates = store.list(PORTFOLIO_SANDBOX_ENTITY)
                    published_ids = {record.entity_id for record in store.list(PORTFOLIO_SANDBOX_RESULT_ENTITY)}
        except (OSError, sqlite3.Error, StorageSchemaError) as exc:
            raise StressLabPersistenceError(f"local portfolio storage is unavailable: {exc}") from exc
        published = [record for record in candidates if record.entity_id in published_ids]
        if not published:
            return pd.DataFrame(), "published_candidate_unavailable"
        record = max(published, key=lambda item: (item.updated_at, item.entity_id))
        name = str(record.payload.get("name", "")).strip()
        if not name:
            return pd.DataFrame(), "published_candidate_identity_unavailable"
        try:
            saved = load_portfolio_candidate(snapshot, name, root=root)
        except (PortfolioSandboxPersistenceError, OSError, sqlite3.Error, StorageSchemaError, TypeError, ValueError) as exc:
            raise StressLabPersistenceError(f"published candidate could not be read: {type(exc).__name__}") from exc
        if saved.result_payload is None:
            return pd.DataFrame(), "published_candidate_output_unavailable"
        target_weights = dict(saved.candidate.target_weights)
        holdings = getattr(snapshot, "holdings", None)
        rows: list[dict[str, object]] = []
        metadata: dict[str, dict[str, object]] = {}
        if isinstance(holdings, pd.DataFrame) and not holdings.empty:
            identifier = "instrument_id" if "instrument_id" in holdings.columns else "etf_id" if "etf_id" in holdings.columns else None
            if identifier is not None:
                for raw in holdings.to_dict("records"):
                    instrument_id = str(raw.get(identifier, "")).strip()
                    if instrument_id:
                        metadata.setdefault(instrument_id, raw)
        for instrument_id, weight in target_weights.items():
            row = dict(metadata.get(str(instrument_id), {}))
            row["instrument_id"] = str(instrument_id)
            row["current_weight"] = weight
            row["asset_class"] = str(row.get("asset_class") or row.get("asset_type") or "unavailable").strip().casefold()
            rows.append(row)
        allocation = pd.DataFrame.from_records(rows)
        return (allocation, None) if not allocation.empty else (allocation, "published_candidate_holdings_unavailable")

    if selected.startswith("paper:"):
        account_id = selected.removeprefix("paper:").strip()
        if not account_id:
            raise ValueError("portfolio must be current, candidate, or paper:<account_id>")
        from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError

        ledger = PaperLedger(root, account_id=account_id)
        if not ledger.path.is_file():
            raise StressPortfolioNotFoundError(account_id)
        try:
            account = ledger.snapshot()
        except (PaperLedgerError, OSError, sqlite3.Error) as exc:
            return pd.DataFrame(), f"paper_account_unavailable:{type(exc).__name__}"
        if int(getattr(account, "event_count", 0) or 0) == 0:
            raise StressPortfolioNotFoundError(account_id)
        if getattr(account, "status", "unavailable") != "ready":
            return pd.DataFrame(), "paper_account_unavailable"
        equity = _finite_number(getattr(account, "equity", None))
        if equity is None or equity <= 0:
            return pd.DataFrame(), "paper_equity_unavailable"
        rows = []
        asset_classes = _asset_class_map(snapshot)
        for position in tuple(getattr(account, "positions", ()) or ()):
            instrument_id = str(getattr(position, "instrument_id", "") or "").strip()
            quantity = _finite_number(getattr(position, "quantity", None))
            mark_price = _finite_number(getattr(position, "mark_price", None))
            mark_fx_rate = _finite_number(getattr(position, "mark_fx_rate", None))
            currency = str(getattr(position, "currency", "") or "").strip()
            if not instrument_id or quantity is None or mark_price is None or mark_price <= 0 or mark_fx_rate is None or mark_fx_rate <= 0:
                return pd.DataFrame(), "paper_position_valuation_unavailable"
            weight = quantity * mark_price * mark_fx_rate / equity
            if not math.isfinite(weight):
                return pd.DataFrame(), "paper_position_valuation_unavailable"
            rows.append({
                "instrument_id": instrument_id,
                "current_weight": weight,
                "currency": currency or None,
                "asset_class": asset_classes.get(instrument_id, "unavailable"),
            })
        allocation = pd.DataFrame.from_records(rows)
        return (allocation, None) if not allocation.empty else (allocation, "paper_positions_unavailable")

    raise ValueError("portfolio must be current, candidate, or paper:<account_id>")


def _asset_class_map(snapshot: object) -> dict[str, str]:
    holdings = getattr(snapshot, "holdings", None)
    if not isinstance(holdings, pd.DataFrame) or holdings.empty:
        return {}
    identifier = "instrument_id" if "instrument_id" in holdings.columns else "etf_id" if "etf_id" in holdings.columns else None
    if identifier is None:
        return {}
    result: dict[str, str] = {}
    for raw in holdings.to_dict("records"):
        instrument_id = str(raw.get(identifier, "")).strip()
        asset_class = str(raw.get("asset_class") or raw.get("asset_type") or "").strip().casefold()
        if instrument_id and asset_class:
            result.setdefault(instrument_id, asset_class)
    return result


def _finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


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
    frame = frame.dropna(subset=["date"]).sort_values(["instrument_id", "date"])
    # Returns are computed BEFORE unusable prices are dropped: a missing price makes the
    # next return unavailable (NaN) instead of bridging the gap into a multi-day return.
    frame.loc[~frame["adjusted_close"].gt(0), "adjusted_close"] = float("nan")
    frame["adjusted_return"] = frame.groupby("instrument_id", sort=False)["adjusted_close"].pct_change(fill_method=None)
    frame.loc[frame["adjusted_close"].isna(), "adjusted_return"] = float("nan")
    return frame[["instrument_id", "date", "adjusted_return"]]


def adjusted_price_returns(prices: object) -> pd.DataFrame | None:
    """Per-instrument simple adjusted-price returns without bridging missing prices."""

    return _adjusted_returns(prices)


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
    "StressPortfolioNotFoundError",
    "StressScenarioError",
    "adjusted_price_returns",
    "build_stress_scenario",
    "resolve_stress_portfolio",
]
