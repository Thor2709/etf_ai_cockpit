"""Edge tests for group G fixes (S4-01 ex-coupon entitlement, S4-03 default basis)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal as D

from etf_cockpit.analysis.fixed_income_analytics import (
    ContractualCashFlow as CF,
    CurveNode,
    DiscountCurveEvidence,
    FixedIncomeValuationInput,
    calculate_fixed_income_analytics,
)
from etf_cockpit.analysis.fixed_income_returns import (
    FixedIncomeReturnInput,
    calculate_fixed_income_return_decomposition,
)
from etf_cockpit.data.market_calendar import DayCountConvention as DC


def _flows():
    return (
        CF(date(2026, 7, 1), D("2.5"), "coupon", "v", date(2026, 1, 1), date(2026, 7, 1), date(2026, 6, 24)),
        CF(date(2027, 1, 1), D("2.5"), "coupon", "v", date(2026, 7, 1), date(2027, 1, 1), date(2026, 12, 24)),
        CF(date(2027, 1, 1), D(100), "redemption", "v"),
    )


def _bond(settlement: date, **kwargs) -> FixedIncomeValuationInput:
    return FixedIncomeValuationInput(
        "B", "v", "EUR", D(100), settlement, date(2027, 1, 1), D(".05"), 2,
        DC.ACT_365F, _flows(), datetime(2026, 6, 1, tzinfo=timezone.utc), **kwargs,
    )


def test_coupon_still_entitled_before_ex_date():
    result = calculate_fixed_income_analytics(_bond(date(2026, 6, 23), yield_to_maturity=D(0)))
    assert result.dirty_price == D("105")


def test_curve_value_excludes_detached_coupon():
    t = datetime(2026, 6, 1, tzinfo=timezone.utc)
    curve = DiscountCurveEvidence(
        "c", "zero", "EUR", "decimal", "annual", "linear_zero", DC.ACT_365F,
        (CurveNode(D(".1"), D(0)), CurveNode(D(2), D(0))),
        "issuer", "1", "a" * 64, t, t, t,
    )
    from dataclasses import replace

    result = calculate_fixed_income_analytics(
        replace(_bond(date(2026, 6, 25), yield_to_maturity=D(0)), curve=curve)
    )
    assert result.curve_dirty_value == D("102.5")


def test_coupon_gone_ex_inside_horizon_counts_as_received_carry():
    # Yield 0: holding through the ex-date must not lose value; the 2.5 coupon
    # detaches (ex 06-24, paid 07-01) before the 06-26 horizon.
    item = FixedIncomeReturnInput(_bond(date(2026, 6, 1), yield_to_maturity=D(0)), 25)
    result = calculate_fixed_income_return_decomposition(item)
    assert abs(result.coupon_carry + result.pull_to_par_roll_down) < D("0.000001")


def test_default_return_scales_with_dirty_value_without_curve():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bond = FixedIncomeValuationInput(
        "B", "v", "EUR", D(100), date(2026, 1, 1), date(2028, 1, 1), D(0), 0,
        DC.ACT_365F, (CF(date(2028, 1, 1), D(100), "redemption", "v"),), t,
        clean_price=D(80),
    )
    item = FixedIncomeReturnInput(
        bond, 90, default_probability=D(".1"), recovery_rate=D(".4"),
        fx_return=D(0), cost_bps=D(0),
    )
    # PD x LGD = 0.06 of face = 6 per 100 face over a dirty value of 80.
    assert calculate_fixed_income_return_decomposition(item).default_recovery == D("-6") / D(80)
