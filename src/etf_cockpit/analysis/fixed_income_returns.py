"""Point-in-time fixed-income return decomposition and forecast status.

The baseline uses the canonical bond analytics and risk repricer. Rate and
spread shocks default to an explicit unchanged-market scenario; no calibrated
return distribution is inferred from a deterministic scenario.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from typing import Mapping

from etf_cockpit.analysis.fixed_income_analytics import (
    FixedIncomeValuationInput,
    calculate_fixed_income_analytics,
    cashflow_entitled,
)
from etf_cockpit.analysis.fixed_income_risk import (
    CurveShock,
    FixedIncomeRiskInput,
    calculate_fixed_income_risk,
)


FIXED_INCOME_RETURN_CONTRACT = "fixed-income-return-decomposition.v1"
FIXED_INCOME_DISTRIBUTION_CONTRACT = "fixed-income-return-distribution.v1"


class FixedIncomeReturnError(ValueError):
    """Raised when a fixed-income return decomposition is not reproducible."""


@dataclass(frozen=True)
class FixedIncomeReturnInput:
    valuation: FixedIncomeValuationInput
    horizon_days: int = 90
    rate_shock_bps: Decimal = Decimal("0")
    spread_shock_bps: Decimal = Decimal("0")
    default_probability: Decimal | None = None
    recovery_rate: Decimal | None = None
    fx_return: Decimal | None = None
    cost_bps: Decimal | None = None

    @property
    def input_hash(self) -> str:
        return _hash(asdict(self))


@dataclass(frozen=True)
class FixedIncomeReturnDecomposition:
    instrument_id: str
    decision_time: datetime
    horizon_days: int
    input_hash: str
    currency: str
    status: str
    coupon_carry: Decimal | None
    pull_to_par_roll_down: Decimal | None
    rate_scenario: Decimal | None
    spread_scenario: Decimal | None
    baseline_total_return: Decimal | None
    default_recovery: Decimal | None
    fx: Decimal | None
    costs: Decimal | None
    net_total_return: Decimal | None
    modified_duration: Decimal | None
    yield_to_worst: Decimal | None
    reason_codes: tuple[str, ...]
    assumptions: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class FixedIncomeReturnDistribution:
    instrument_id: str
    horizon_days: int
    status: str
    q05: Decimal | None
    q50: Decimal | None
    q95: Decimal | None
    loss_probability: Decimal | None
    beat_cash_probability: Decimal | None
    beat_benchmark_probability: Decimal | None
    reason_codes: tuple[str, ...]
    calibration_id: str | None = None
    execution_allowed: bool = False


def calculate_fixed_income_return_decomposition(
    item: FixedIncomeReturnInput,
) -> FixedIncomeReturnDecomposition:
    """Calculate carry, roll, rate and spread effects from frozen inputs.

    The four baseline components are normalized by starting dirty value. A
    net return is available only when default/recovery, FX and costs are also
    explicitly known. A missing component never becomes zero.
    """

    _validate(item)
    valuation = item.valuation
    base = calculate_fixed_income_analytics(valuation)
    if (
        base.dirty_price is None
        or base.clean_price is None
        or base.accrued_interest is None
        or base.yield_to_maturity is None
    ):
        raise FixedIncomeReturnError("canonical starting valuation is incomplete")

    horizon = valuation.settlement_date + timedelta(days=item.horizon_days)
    if horizon >= valuation.maturity_date:
        return _unavailable(item, "horizon_reaches_maturity", base)

    future_valuation = replace(
        valuation,
        settlement_date=horizon,
        clean_price=None,
        yield_to_maturity=base.yield_to_maturity,
        calls=tuple(call for call in valuation.calls if call.call_date > horizon),
    )
    future = calculate_fixed_income_analytics(future_valuation)
    if future.clean_price is None or future.accrued_interest is None:
        raise FixedIncomeReturnError("canonical horizon valuation is incomplete")

    # Coupons the holder is entitled to at settlement and that have been paid or
    # gone ex-coupon by the horizon (a detached coupon is no longer in the
    # horizon price, so it must be counted here as received cash).
    coupon_cash = sum(
        (
            flow.amount / valuation.face_value * Decimal("100")
            for flow in valuation.cashflows
            if flow.kind == "coupon"
            and cashflow_entitled(flow, valuation.settlement_date)
            and (flow.ex_coupon_date or flow.payment_date) <= horizon
        ),
        Decimal("0"),
    )
    denominator = base.dirty_price
    carry = (
        coupon_cash + future.accrued_interest - base.accrued_interest
    ) / denominator
    roll = (future.clean_price - base.clean_price) / denominator

    rate: Decimal | None
    spread: Decimal | None
    default: Decimal | None
    costs: Decimal | None
    assumptions = [
        "canonical_dirty_value_denominator",
        "contractual_coupon_cashflows_only",
        "deterministic_horizon_reprice",
        "execution_allowed=false",
    ]
    risk = None
    if valuation.curve is not None:
        risk = calculate_fixed_income_risk(
            FixedIncomeRiskInput(
                valuation=future_valuation,
                instrument_kind="bond",
                position_face_value=valuation.face_value,
                scenarios=(
                    CurveShock(
                        "fixed_income_return_baseline",
                        parallel_bps=item.rate_shock_bps,
                    ),
                ),
                spread_shock_bps=item.spread_shock_bps,
                default_probability=item.default_probability,
                recovery_rate=item.recovery_rate,
                liquidity_cost_bps=item.cost_bps,
                evidence_lineage=(valuation.input_hash,),
            )
        )
        scenario = risk.scenarios[0]
        position_value = denominator * valuation.face_value / Decimal("100")
        rate = scenario.rate_full_reprice_pnl / position_value
        spread = (
            scenario.spread_pnl / position_value
            if scenario.spread_pnl is not None
            else None
        )
        default = (
            scenario.default_pnl / position_value
            if scenario.default_pnl is not None
            else None
        )
        costs = (
            scenario.liquidity_pnl / position_value
            if scenario.liquidity_pnl is not None
            else None
        )
    else:
        rate = Decimal("0") if item.rate_shock_bps == 0 else None
        spread = Decimal("0") if item.spread_shock_bps == 0 else None
        default = _default_return(item, denominator)
        costs = _cost_return(item)
        if rate is not None and spread is not None:
            assumptions.append("configured_neutral_rate_and_spread_scenario")

    fx = item.fx_return
    if rate is None:
        assumptions.append("rate_scenario_unavailable_without_typed_curve")
    if spread is None:
        assumptions.append("spread_scenario_unavailable_without_typed_curve")

    baseline_parts = (carry, roll, rate, spread)
    baseline = sum(baseline_parts, Decimal("0")) if all(x is not None for x in baseline_parts) else None
    net_parts = (*baseline_parts, default, fx, costs)
    net = sum((x for x in net_parts if x is not None), Decimal("0")) if all(x is not None for x in net_parts) else None
    reasons = tuple(
        f"{name}_unavailable"
        for name, value in (
            ("rate", rate),
            ("spread", spread),
            ("default_recovery", default),
            ("fx", fx),
            ("costs", costs),
        )
        if value is None
    )
    status = "available" if net is not None else "partial" if baseline is not None else "unavailable"
    return FixedIncomeReturnDecomposition(
        instrument_id=valuation.instrument_id,
        decision_time=valuation.decision_time,
        horizon_days=item.horizon_days,
        input_hash=item.input_hash,
        currency=valuation.currency,
        status=status,
        coupon_carry=carry,
        pull_to_par_roll_down=roll,
        rate_scenario=rate,
        spread_scenario=spread,
        baseline_total_return=baseline,
        default_recovery=default,
        fx=fx,
        costs=costs,
        net_total_return=net,
        modified_duration=base.modified_duration,
        yield_to_worst=base.yield_to_worst,
        reason_codes=reasons,
        assumptions=tuple(assumptions),
        execution_allowed=False,
    )


def uncalibrated_fixed_income_distribution(
    decomposition: FixedIncomeReturnDecomposition,
) -> FixedIncomeReturnDistribution:
    """Return explicit research-only distribution fields until outcomes calibrate."""

    supported = decomposition.baseline_total_return is not None
    return FixedIncomeReturnDistribution(
        instrument_id=decomposition.instrument_id,
        horizon_days=decomposition.horizon_days,
        status="research_only" if supported else "unavailable",
        q05=None,
        q50=None,
        q95=None,
        loss_probability=None,
        beat_cash_probability=None,
        beat_benchmark_probability=None,
        reason_codes=(
            "fixed_income_return_calibration_unavailable"
            if supported
            else "fixed_income_return_baseline_unavailable",
        ),
        execution_allowed=False,
    )


def _unavailable(
    item: FixedIncomeReturnInput,
    reason: str,
    base: object,
) -> FixedIncomeReturnDecomposition:
    return FixedIncomeReturnDecomposition(
        instrument_id=item.valuation.instrument_id,
        decision_time=item.valuation.decision_time,
        horizon_days=item.horizon_days,
        input_hash=item.input_hash,
        currency=item.valuation.currency,
        status="unavailable",
        coupon_carry=None,
        pull_to_par_roll_down=None,
        rate_scenario=None,
        spread_scenario=None,
        baseline_total_return=None,
        default_recovery=None,
        fx=None,
        costs=None,
        net_total_return=None,
        modified_duration=getattr(base, "modified_duration", None),
        yield_to_worst=getattr(base, "yield_to_worst", None),
        reason_codes=(reason,),
        assumptions=("horizon_reaches_or_exceeds_maturity", "execution_allowed=false"),
        execution_allowed=False,
    )


def _default_return(
    item: FixedIncomeReturnInput, dirty_price: Decimal
) -> Decimal | None:
    """Expected default loss (PD x LGD on face value) as a return on dirty value.

    This is the same basis the curve path derives from the canonical risk
    engine: loss on position face value divided by the starting dirty value.
    """

    if item.default_probability is None or item.recovery_rate is None:
        return None
    loss_per_100_face = (
        item.default_probability * (Decimal("1") - item.recovery_rate) * Decimal("100")
    )
    return -loss_per_100_face / dirty_price


def _cost_return(item: FixedIncomeReturnInput) -> Decimal | None:
    if item.cost_bps is None:
        return None
    return -item.cost_bps / Decimal("10000")


def _validate(item: FixedIncomeReturnInput) -> None:
    if not isinstance(item, FixedIncomeReturnInput):
        raise FixedIncomeReturnError("return input type is invalid")
    if item.horizon_days < 1 or isinstance(item.horizon_days, bool):
        raise FixedIncomeReturnError("horizon_days must be positive")
    if item.valuation.decision_time.tzinfo is None:
        raise FixedIncomeReturnError("decision_time must be timezone-aware")
    if any(
        not value.is_finite()
        for value in (item.rate_shock_bps, item.spread_shock_bps)
    ):
        raise FixedIncomeReturnError("scenario shocks must be finite")
    if (item.default_probability is None) != (item.recovery_rate is None):
        raise FixedIncomeReturnError("default probability and recovery must be paired")
    if item.default_probability is not None and not Decimal("0") <= item.default_probability <= Decimal("1"):
        raise FixedIncomeReturnError("default_probability must be in [0, 1]")
    if item.recovery_rate is not None and not Decimal("0") <= item.recovery_rate <= Decimal("1"):
        raise FixedIncomeReturnError("recovery_rate must be in [0, 1]")
    if item.fx_return is not None and not item.fx_return.is_finite():
        raise FixedIncomeReturnError("fx_return must be finite")
    if item.cost_bps is not None and (not item.cost_bps.is_finite() or item.cost_bps < 0):
        raise FixedIncomeReturnError("cost_bps must be finite and non-negative")


def _hash(value: object) -> str:
    encoded = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
        return getattr(value, "value")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "FIXED_INCOME_DISTRIBUTION_CONTRACT",
    "FIXED_INCOME_RETURN_CONTRACT",
    "FixedIncomeReturnDecomposition",
    "FixedIncomeReturnDistribution",
    "FixedIncomeReturnError",
    "FixedIncomeReturnInput",
    "calculate_fixed_income_return_decomposition",
    "uncalibrated_fixed_income_distribution",
]
