"""Deterministic local stress scenarios for ISSUE-0115.

Scenarios are evidence calculations, never probability forecasts or trading
instructions.  Inputs are explicit adjusted-price returns, allocations and
factor look-through exposures; missing coverage remains visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Mapping

import pandas as pd


STRESS_SCHEMA_VERSION = "stress_scenario.v1"
EXECUTION_ALLOWED = False
SHOCK_NAMES = frozenset({"equity", "rates", "fx", "credit", "commodity", "liquidity"})


class StressScenarioError(ValueError):
    """Raised when a scenario is unsafe, ambiguous or not reproducible."""


@dataclass(frozen=True)
class StressScenario:
    scenario_id: str
    name: str
    shocks: Mapping[str, float]
    horizon_days: int = 1
    historical_date: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        scenario_id = _identifier(self.scenario_id, "scenario_id")
        name = _bounded(self.name, "name", 160)
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise StressScenarioError("version must be a positive integer.")
        if self.horizon_days < 1 or self.horizon_days > 3_650:
            raise StressScenarioError("horizon_days must be between 1 and 3650.")
        shocks = _shocks(self.shocks)
        if self.historical_date is not None:
            try:
                date.fromisoformat(str(self.historical_date))
            except ValueError as exc:
                raise StressScenarioError("historical_date must be ISO YYYY-MM-DD.") from exc
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "shocks", shocks)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": STRESS_SCHEMA_VERSION,
            "scenario_id": self.scenario_id,
            "name": self.name,
            "shocks": dict(sorted(self.shocks.items())),
            "horizon_days": self.horizon_days,
            "historical_date": self.historical_date,
            "version": self.version,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class StressResult:
    scenario: StressScenario
    status: str
    total_pnl: float | None
    instrument_contributions: tuple[dict[str, object], ...]
    factor_contributions: tuple[dict[str, object], ...]
    coverage: dict[str, object]
    limitations: tuple[str, ...]
    reverse_stress: dict[str, object] | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": STRESS_SCHEMA_VERSION,
            "scenario": self.scenario.to_payload(),
            "status": self.status,
            "total_pnl": self.total_pnl,
            "instrument_contributions": list(self.instrument_contributions),
            "factor_contributions": list(self.factor_contributions),
            "coverage": self.coverage,
            "limitations": list(self.limitations),
            "reverse_stress": self.reverse_stress,
            "execution_allowed": False,
        }


def run_stress_scenario(
    scenario: StressScenario,
    allocation: pd.DataFrame,
    *,
    factor_exposures: pd.DataFrame | None = None,
    historical_returns: pd.DataFrame | None = None,
    notional: float = 100_000.0,
) -> StressResult:
    """Run a hypothetical or dated historical scenario with reconciliation."""

    if notional <= 0 or not math.isfinite(float(notional)):
        raise StressScenarioError("notional must be finite and greater than zero.")
    frame = _allocation(allocation)
    if scenario.historical_date:
        frame = _apply_historical_shock(frame, historical_returns, scenario.historical_date)
    if frame.empty:
        return StressResult(scenario, "unavailable", None, (), (), {"status": "unavailable", "instrument_count": 0}, ("No validated allocation rows are available.",))
    exposures = _exposure_map(factor_exposures)
    instrument_rows: list[dict[str, object]] = []
    factor_totals: dict[str, float] = {}
    missing: list[str] = []
    for row in frame.to_dict("records"):
        instrument_id = str(row["instrument_id"])
        weight = float(row["weight"])
        base_return = row.get("historical_return")
        if base_return is not None:
            shock = float(base_return)
            source = "historical_adjusted_return"
            components: dict[str, float] = {"historical_adjusted_return": shock}
        elif scenario.historical_date:
            shock = 0.0
            components = {}
            source = "historical_adjusted_return_unavailable"
        else:
            common_components = _common_shock_components(scenario.shocks, row)
            shock = math.fsum(common_components.values())
            components = dict(common_components)
            source = "hypothetical_explicit_shock"
        for component, value in components.items():
            factor_totals[component] = factor_totals.get(component, 0.0) + weight * notional * value
        for factor, exposure in exposures.get(instrument_id, {}).items():
            shock_name = _scenario_factor_name(factor, scenario.shocks)
            if shock_name is not None:
                value = exposure * scenario.shocks[shock_name]
                shock += value
                components[shock_name] = value
                factor_totals[shock_name] = factor_totals.get(shock_name, 0.0) + weight * notional * value
        if not components and (scenario.historical_date or not any(name in scenario.shocks for name in SHOCK_NAMES)):
            missing.append(instrument_id)
        pnl = weight * notional * shock
        liquidity_cost = abs(weight * notional) * max(0.0, scenario.shocks.get("liquidity", 0.0))
        pnl -= liquidity_cost
        factor_totals["liquidity"] = factor_totals.get("liquidity", 0.0) - liquidity_cost
        instrument_rows.append({"instrument_id": instrument_id, "weight": weight, "shock": shock, "pnl": pnl, "factor_components": components, "source": source, "cost": liquidity_cost})
    total = None if len(missing) == len(instrument_rows) else math.fsum(float(row["pnl"]) for row in instrument_rows)
    factor_rows = tuple({"factor": factor, "pnl": value, "share": value / total if total else 0.0} for factor, value in sorted(factor_totals.items()))
    limitations = ["Scenario PnL is not a probability forecast.", "Nonlinear derivatives, taxes and transaction impact beyond the explicit liquidity cost are not modelled."]
    if missing:
        limitations.append("Some instruments have no applicable shock or factor coverage.")
    coverage = {"status": "partial" if missing else "available", "instrument_count": len(instrument_rows), "covered_instruments": len(instrument_rows) - len(missing), "missing_instruments": sorted(missing), "factor_coverage": len(exposures)}
    status = "unavailable" if len(missing) == len(instrument_rows) else "partial" if missing else "available"
    return StressResult(scenario, status, total, tuple(instrument_rows), factor_rows, coverage, tuple(limitations))


def reverse_stress(
    allocation: pd.DataFrame,
    *,
    shock_name: str,
    loss_limit: float,
    factor_exposures: pd.DataFrame | None = None,
    notional: float = 100_000.0,
    upper_bound: float = 5.0,
    iterations: int = 48,
) -> dict[str, object]:
    """Find the smallest shock magnitude that breaches a loss limit."""

    if shock_name not in SHOCK_NAMES:
        raise StressScenarioError("reverse stress shock_name is unsupported.")
    if loss_limit <= 0 or not math.isfinite(float(loss_limit)):
        raise StressScenarioError("loss_limit must be finite and greater than zero.")
    if upper_bound <= 0 or iterations < 8:
        raise StressScenarioError("reverse stress bounds are invalid.")
    baseline = StressScenario("reverse-stress", "Reverse stress", {shock_name: 0.0})

    def breached(magnitude: float) -> bool:
        result = run_stress_scenario(
            StressScenario(baseline.scenario_id, baseline.name, {shock_name: -magnitude}, baseline.horizon_days),
            allocation,
            factor_exposures=factor_exposures,
            notional=notional,
        )
        return result.total_pnl is not None and result.total_pnl <= -loss_limit

    if not breached(upper_bound):
        return {"status": "not_reached", "shock_name": shock_name, "threshold": None, "loss_limit": loss_limit, "binding_exposure": None, "execution_allowed": False}
    low, high = 0.0, upper_bound
    for _ in range(iterations):
        midpoint = (low + high) / 2.0
        if breached(midpoint):
            high = midpoint
        else:
            low = midpoint
    exposure = _binding_exposure(allocation, shock_name, factor_exposures)
    return {"status": "available", "shock_name": shock_name, "threshold": high, "loss_limit": loss_limit, "binding_exposure": exposure, "execution_allowed": False}


def _allocation(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["instrument_id", "weight"])
    result = frame.copy()
    identifier = "instrument_id" if "instrument_id" in result.columns else "etf_id" if "etf_id" in result.columns else None
    weight = "current_weight" if "current_weight" in result.columns else "target_weight" if "target_weight" in result.columns else "weight" if "weight" in result.columns else None
    if identifier is None or weight is None:
        return pd.DataFrame(columns=["instrument_id", "weight"])
    selected = ["instrument_id", "weight"]
    for optional in ("asset_class", "currency"):
        if optional in result.columns:
            selected.append(optional)
    result = result.rename(columns={identifier: "instrument_id", weight: "weight"})[selected].copy()
    result["instrument_id"] = result["instrument_id"].astype(str).str.strip()
    result["weight"] = pd.to_numeric(result["weight"], errors="coerce")
    return result[result["instrument_id"].ne("") & result["weight"].notna() & result["weight"].map(math.isfinite)].reset_index(drop=True)


def _exposure_map(frame: pd.DataFrame | None) -> dict[str, dict[str, float]]:
    if frame is None or frame.empty:
        return {}
    result: dict[str, dict[str, float]] = {}
    if {"instrument_id", "factor", "exposure"}.issubset(frame.columns):
        rows = frame.to_dict("records")
        for row in rows:
            value = _finite(row.get("exposure"))
            if value is not None:
                result.setdefault(str(row["instrument_id"]), {})[str(row["factor"])] = value
        return result
    wide = frame.copy()
    if "instrument_id" not in wide.columns:
        wide = wide.reset_index().rename(columns={wide.index.name or "index": "instrument_id"})
    if "instrument_id" not in wide.columns:
        return {}
    metadata = {"instrument_id", "portfolio_weight", "weight", "specific_risk"}
    for row in wide.to_dict("records"):
        instrument_id = str(row.get("instrument_id", "")).strip()
        if not instrument_id:
            continue
        for factor, raw in row.items():
            if factor in metadata:
                continue
            value = _finite(raw)
            if value is not None:
                result.setdefault(instrument_id, {})[str(factor)] = value
    return result


def _apply_historical_shock(frame: pd.DataFrame, returns: pd.DataFrame | None, as_of: str) -> pd.DataFrame:
    if returns is None or returns.empty:
        return frame.assign(historical_return=None)
    data = returns.copy()
    date_column = "date" if "date" in data.columns else "as_of" if "as_of" in data.columns else None
    adjusted_column = next((column for column in ("adjusted_return", "adjusted_close_return", "total_return") if column in data.columns), None)
    if date_column is None or (adjusted_column is None and "instrument_id" in data.columns):
        return frame.assign(historical_return=None)
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce").dt.date
    selected = data[data[date_column] == date.fromisoformat(as_of)]
    if selected.empty:
        return frame.assign(historical_return=None)
    result = frame.copy()
    if "instrument_id" in selected.columns and adjusted_column is not None:
        values = {
            str(row["instrument_id"]): _finite(row[adjusted_column])
            for row in selected.to_dict("records")
        }
        result["historical_return"] = result["instrument_id"].map(values)
    else:
        row = selected.iloc[-1]
        result["historical_return"] = result["instrument_id"].map(lambda item: _finite(row.get(item)))
    return result


def _common_shock(shocks: Mapping[str, float], row: Mapping[str, object]) -> float:
    return math.fsum(_common_shock_components(shocks, row).values())


def _common_shock_components(shocks: Mapping[str, float], row: Mapping[str, object]) -> dict[str, float]:
    asset_class = str(row.get("asset_class", "equity")).casefold()
    components: dict[str, float] = {}
    if asset_class in {"equity", "stock", "etf"}:
        components["equity"] = shocks.get("equity", 0.0)
    if asset_class in {"credit", "bond", "fixed_income"}:
        components["rates"] = shocks.get("rates", 0.0)
        components["credit"] = shocks.get("credit", 0.0)
    if asset_class in {"fx", "currency"}:
        components["fx"] = shocks.get("fx", 0.0)
    if asset_class in {"commodity", "commodities"}:
        components["commodity"] = shocks.get("commodity", 0.0)
    return {name: value for name, value in components.items() if value}


def _scenario_factor_name(factor: object, shocks: Mapping[str, float]) -> str | None:
    name = str(factor).strip()
    candidates = (name, f"factor:{name}") if not name.startswith("factor:") else (name, name.removeprefix("factor:"))
    return next((candidate for candidate in candidates if candidate in shocks), None)


def _binding_exposure(allocation: pd.DataFrame, shock_name: str, exposures: pd.DataFrame | None) -> dict[str, object] | None:
    frame = _allocation(allocation)
    if frame.empty:
        return None
    exposure_map = _exposure_map(exposures)
    candidates: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        instrument_id = str(row["instrument_id"])
        if shock_name.startswith("factor:"):
            factor = shock_name.removeprefix("factor:")
            value = exposure_map.get(instrument_id, {}).get(factor)
            if value is None:
                value = exposure_map.get(instrument_id, {}).get(shock_name)
            if value is None:
                continue
            exposure = float(row["weight"]) * float(value)
        else:
            exposure = float(row["weight"]) if _common_shock_components({shock_name: 1.0}, row) else 0.0
        if exposure:
            candidates.append({"instrument_id": instrument_id, "exposure": exposure, "absolute_exposure": abs(exposure)})
    if not candidates:
        return None
    binding = max(candidates, key=lambda item: (float(item["absolute_exposure"]), str(item["instrument_id"])))
    return {"shock_name": shock_name, **binding, "instrument_count": len(candidates)}


def _shocks(values: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(values, Mapping) or not values:
        raise StressScenarioError("At least one explicit scenario shock is required.")
    result: dict[str, float] = {}
    for key, raw in values.items():
        name = _bounded(key, "shock name", 80)
        if name not in SHOCK_NAMES and not name.startswith("factor:"):
            raise StressScenarioError(f"Unsupported scenario shock: {name}")
        value = _finite(raw)
        if value is None or abs(value) > 5:
            raise StressScenarioError("Scenario shocks must be finite and within +/-500%.")
        result[name] = value
    return result


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _identifier(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128 or text in {".", ".."} or "/" in text or "\\" in text:
        raise StressScenarioError(f"{label} is unsafe.")
    return text


def _bounded(value: object, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise StressScenarioError(f"{label} is invalid.")
    return text


__all__ = ["EXECUTION_ALLOWED", "SHOCK_NAMES", "STRESS_SCHEMA_VERSION", "StressResult", "StressScenario", "StressScenarioError", "reverse_stress", "run_stress_scenario"]
