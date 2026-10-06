from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from collections.abc import Mapping

from etf_cockpit.core.config import AppConfig


COST_MODEL_ID = "execution-cost-v1"


def _finite(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _non_negative(value: object, default: float = 0.0) -> float:
    return max(0.0, _finite(value, default))


def fixed_cost_eur(commission_eur: float, order_value_eur: float) -> float:
    """Return the fixed commission component for a non-executable estimate."""

    if abs(_finite(order_value_eur)) <= 0:
        return 0.0
    return _non_negative(commission_eur)


def spread_cost_bps(spread_bps: float, *, order_type: str = "market") -> float:
    """Return the conservative spread crossing assumption in basis points."""

    value = _non_negative(spread_bps)
    if order_type == "limit":
        return value * 0.5
    return value


def square_root_impact_bps(order_value_eur: float, adv_eur: float, coefficient_bps: float) -> float:
    """Estimate market impact with a monotonic square-root participation curve."""

    order = _non_negative(order_value_eur)
    adv = _non_negative(adv_eur)
    if order <= 0 or adv <= 0:
        return 0.0
    return _non_negative(coefficient_bps) * math.sqrt(order / adv)


def volatility_volume_impact_bps(order_value_eur: float, adv_eur: float, daily_volatility: float) -> float:
    """Estimate volatility/volume impact from daily volatility and participation."""

    order = _non_negative(order_value_eur)
    adv = _non_negative(adv_eur)
    volatility = _non_negative(daily_volatility)
    if order <= 0 or adv <= 0 or volatility <= 0:
        return 0.0
    return volatility * math.sqrt(order / adv) * 10_000.0 * 0.5


@dataclass(frozen=True)
class CostEstimate:
    """Immutable research estimate; realised fills are recorded separately."""

    estimate_id: str
    model_id: str
    instrument_id: str
    order_value_eur: float
    commission_eur: float
    spread_bps: float
    slippage_bps: float
    volatility_volume_impact_bps: float
    square_root_impact_bps: float
    market_impact_bps: float
    fx_bps: float
    gap_bps: float
    uncertainty_multiplier: float
    total_cost_bps: float
    total_cost_eur: float
    capacity_eur: float | None
    capacity_status: str
    data_quality: str
    estimate_kind: str = "research_estimate"
    execution_allowed: bool = False
    assumptions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioCostEstimate:
    """Aggregate immutable estimate used by rebalance and backtest consumers."""

    model_id: str
    total_order_value_eur: float
    total_cost_eur: float
    weighted_cost_bps: float
    capacity_eur: float | None
    estimates: tuple[CostEstimate, ...]
    execution_allowed: bool = False


def _calibration_value(calibration: Mapping[str, object] | None, name: str, fallback: float) -> tuple[float, bool]:
    if not calibration or name not in calibration:
        return fallback, False
    value = _finite(calibration.get(name), fallback)
    return (value if value >= 0 else fallback), value >= 0


def estimate_execution_cost(
    config: AppConfig,
    instrument_id: str,
    order_value_eur: float,
    *,
    adv_eur: float | None = None,
    daily_volatility: float | None = None,
    quoted_spread_bps: float | None = None,
    realised_slippage_bps: float | None = None,
    fx_bps: float | None = None,
    gap_bps: float | None = None,
    order_type: str = "market",
    session: str = "continuous",
    listing: str | None = None,
    stress_multiplier: float = 1.0,
    calibration: Mapping[str, object] | None = None,
) -> CostEstimate:
    """Build a deterministic, conservative local execution-cost estimate.

    Inputs may come from a local quote/fill import, but this function never
    fetches data, writes a fill or grants broker authority. Missing
    microstructure inputs widen the estimate and are explicitly labelled.
    """

    instrument = str(instrument_id or "").strip() or "unknown"
    order_value = _non_negative(order_value_eur)
    per_instrument = getattr(config.costs, "per_etf", {}).get(instrument, {})
    model = config.costs.cost_model
    model_id = str(getattr(model, "model_version", COST_MODEL_ID) or COST_MODEL_ID)
    stress = max(0.0, _finite(stress_multiplier, 1.0))
    if order_type not in {"market", "limit"}:
        order_type = "market"
    session_name = str(session or "continuous").strip().lower() or "continuous"
    session_multiplier = 1.25 if session_name in {"open", "close", "auction", "overnight"} else 1.0
    configured_listing = next(
        (
            str(getattr(item, "exchange", "") or "").strip()
            for item in getattr(getattr(config, "universe", None), "etfs", [])
            if str(getattr(item, "id", "")) == instrument and str(getattr(item, "exchange", "") or "").strip()
        ),
        "unknown",
    )
    listing_name = str(listing or configured_listing or "unknown").strip() or "unknown"

    configured_spread = _finite(per_instrument.get("spread_bps"), getattr(model, "default_spread_bps", 0.0))
    configured_slippage = _finite(per_instrument.get("slippage_bps"), getattr(model, "default_slippage_bps", 0.0))
    spread, spread_calibrated = _calibration_value(calibration, "spread_bps", quoted_spread_bps if quoted_spread_bps is not None else configured_spread)
    slippage, slippage_calibrated = _calibration_value(calibration, "slippage_bps", realised_slippage_bps if realised_slippage_bps is not None else configured_slippage)
    adv, adv_calibrated = _calibration_value(calibration, "adv_eur", adv_eur if adv_eur is not None else per_instrument.get("adv_eur", 0.0))
    volatility, volatility_calibrated = _calibration_value(calibration, "daily_volatility", daily_volatility if daily_volatility is not None else per_instrument.get("daily_volatility", 0.0))
    configured_fx = getattr(model, "fx_conversion_bps", 0.0)
    configured_gap = getattr(model, "gap_stress_bps", 0.0)
    fx = _non_negative(configured_fx if fx_bps is None else fx_bps)
    gap = _non_negative(configured_gap if gap_bps is None else gap_bps)
    commission = _non_negative(getattr(model, "default_commission_eur", 0.0))
    commission *= max(1.0, _finite(getattr(model, "commission_stress_multiplier", 1.0), 1.0))
    coefficient = _non_negative(per_instrument.get("impact_coefficient_bps", getattr(model, "impact_coefficient_bps", 25.0)))
    participation_limit = min(1.0, max(0.0, _finite(getattr(model, "max_participation_rate", 0.1), 0.1)))

    has_adv = adv > 0
    has_volatility = volatility > 0
    missing_microstructure = order_value > 0 and (not has_adv or not has_volatility)
    uncertainty = 1.0
    if missing_microstructure:
        uncertainty = max(1.0, _finite(getattr(model, "uncertainty_multiplier", 1.25), 1.25))
    participation = order_value / adv if has_adv else 0.10
    volatility_impact = volatility_volume_impact_bps(order_value, adv, volatility)
    square_root_impact = square_root_impact_bps(order_value, adv, coefficient)
    if missing_microstructure:
        # A missing ADV/volatility pair still receives a conservative impact
        # floor so a larger order cannot look cheaper merely because data is
        # absent.
        square_root_impact = max(square_root_impact, coefficient * (1.0 + math.sqrt(participation))) if order_value > 0 else 0.0
    market_impact = max(volatility_impact, square_root_impact)
    fixed_eur = fixed_cost_eur(commission, order_value)
    fixed_bps = fixed_eur / order_value * 10_000.0 if order_value > 0 else 0.0
    variable_bps = (
        spread_cost_bps(spread, order_type=order_type)
        + _non_negative(slippage)
        + fx
        + gap
        + market_impact
    ) * stress * uncertainty * session_multiplier
    total_bps = max(0.0, fixed_bps + variable_bps)
    total_eur = fixed_eur + order_value * variable_bps / 10_000.0
    capacity = adv * participation_limit if has_adv else None
    if capacity is None:
        capacity_status = "unavailable_missing_adv"
    elif order_value > capacity:
        capacity_status = "exceeds_configured_participation"
    else:
        capacity_status = "within_configured_participation"
    if missing_microstructure:
        quality = "degraded_missing_microstructure"
    elif spread_calibrated or slippage_calibrated or adv_calibrated or volatility_calibrated:
        quality = "calibrated_local_inputs"
    else:
        quality = "configured_assumptions"
    assumptions = [
        f"order_type={order_type}",
        f"session={session_name}",
        f"listing={listing_name}",
        "research_estimate_only",
    ]
    if missing_microstructure:
        assumptions.append("missing_microstructure_widens_estimate")
    if calibration:
        assumptions.append("completed_local_calibration_inputs_only")
    payload = {
        "model_id": model_id,
        "instrument_id": instrument,
        "order_value_eur": round(order_value, 8),
        "spread_bps": round(spread, 8),
        "slippage_bps": round(slippage, 8),
        "market_impact_bps": round(market_impact, 8),
        "fx_bps": round(fx, 8),
        "gap_bps": round(gap, 8),
        "session": session_name,
        "listing": listing_name,
        "session_multiplier": round(session_multiplier, 8),
        "uncertainty_multiplier": round(uncertainty, 8),
        "stress_multiplier": round(stress, 8),
    }
    estimate_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return CostEstimate(
        estimate_id=estimate_id,
        model_id=model_id,
        instrument_id=instrument,
        order_value_eur=round(order_value, 8),
        commission_eur=round(fixed_eur, 8),
        spread_bps=round(spread_cost_bps(spread, order_type=order_type), 8),
        slippage_bps=round(_non_negative(slippage), 8),
        volatility_volume_impact_bps=round(volatility_impact, 8),
        square_root_impact_bps=round(square_root_impact, 8),
        market_impact_bps=round(market_impact, 8),
        fx_bps=round(fx, 8),
        gap_bps=round(gap, 8),
        uncertainty_multiplier=round(uncertainty, 8),
        total_cost_bps=round(total_bps, 8),
        total_cost_eur=round(total_eur, 8),
        capacity_eur=None if capacity is None else round(capacity, 8),
        capacity_status=capacity_status,
        data_quality=quality,
        assumptions=tuple(assumptions),
    )


def estimate_rebalance_cost(config: AppConfig, portfolio_value_eur: float, weight_changes: Mapping[str, float]) -> PortfolioCostEstimate:
    """Estimate a portfolio rebalance using the same instrument model."""

    portfolio_value = _non_negative(portfolio_value_eur)
    estimates = tuple(
        estimate_execution_cost(config, str(instrument_id), portfolio_value * abs(_finite(weight_change)))
        for instrument_id, weight_change in sorted(weight_changes.items())
        if abs(_finite(weight_change)) > 0
    )
    total_order_value = sum(item.order_value_eur for item in estimates)
    total_cost = sum(item.total_cost_eur for item in estimates)
    capacity_values = [item.capacity_eur for item in estimates if item.capacity_eur is not None]
    return PortfolioCostEstimate(
        model_id=estimates[0].model_id if estimates else str(getattr(config.costs.cost_model, "model_version", COST_MODEL_ID) or COST_MODEL_ID),
        total_order_value_eur=round(total_order_value, 8),
        total_cost_eur=round(total_cost, 8),
        weighted_cost_bps=round(total_cost / total_order_value * 10_000.0, 8) if total_order_value else 0.0,
        capacity_eur=round(sum(capacity_values), 8) if capacity_values else None,
        estimates=estimates,
    )


def compare_realised_fill(estimate: CostEstimate, *, reference_price: float, fill_price: float, filled_value_eur: float | None = None) -> dict[str, object]:
    """Return TCA-style evidence without changing the prior estimate."""

    reference = _finite(reference_price)
    fill = _finite(fill_price)
    realised_bps = None if reference <= 0 else abs(fill - reference) / reference * 10_000.0
    return {
        "estimate_id": estimate.estimate_id,
        "model_id": estimate.model_id,
        "estimated_cost_bps": estimate.total_cost_bps,
        "estimated_cost_eur": estimate.total_cost_eur,
        "realised_price_impact_bps": None if realised_bps is None else round(realised_bps, 8),
        "filled_value_eur": None if filled_value_eur is None else round(_non_negative(filled_value_eur), 8),
        "estimate_kind": estimate.estimate_kind,
        "execution_allowed": False,
    }


def estimated_cost_bps(config: AppConfig, etf_id: str) -> float:
    """Return the configured-size-neutral cost used by score/net-return views."""

    return estimate_execution_cost(config, etf_id, 0.0).total_cost_bps


def estimated_trade_cost_eur(config: AppConfig, etf_id: str, trade_value_eur: float) -> float:
    return estimate_execution_cost(config, etf_id, trade_value_eur).total_cost_eur


def cost_capacity_status(config: AppConfig, instrument_id: str, order_value_eur: float = 10_000.0) -> dict[str, object]:
    """Presentation-safe summary for the read-only Cost/Capacity panel."""

    estimate = estimate_execution_cost(config, instrument_id, order_value_eur)
    return {
        "instrument_id": estimate.instrument_id,
        "order_preview_eur": estimate.order_value_eur,
        "estimated_cost_bps": estimate.total_cost_bps,
        "estimated_cost_eur": estimate.total_cost_eur,
        "capacity_eur": estimate.capacity_eur,
        "capacity_status": estimate.capacity_status,
        "data_quality": estimate.data_quality,
        "model_id": estimate.model_id,
        "execution_allowed": False,
        "assumptions": estimate.assumptions,
    }


__all__ = [
    "COST_MODEL_ID",
    "CostEstimate",
    "PortfolioCostEstimate",
    "compare_realised_fill",
    "cost_capacity_status",
    "estimate_execution_cost",
    "estimate_rebalance_cost",
    "estimated_cost_bps",
    "estimated_trade_cost_eur",
    "fixed_cost_eur",
    "spread_cost_bps",
    "square_root_impact_bps",
    "volatility_volume_impact_bps",
]
