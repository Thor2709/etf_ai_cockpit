"""Issue #994 (B13): fixed-income precision, entitlement, peers and FX compounding."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.fixed_income_analytics import (
    ContractualCashFlow,
    FixedIncomeAnalyticsError,
    FixedIncomeValuationInput,
    accrued_interest,
    calculate_fixed_income_analytics,
)
from etf_cockpit.analysis.fixed_income_returns import (
    FixedIncomeReturnInput,
    calculate_fixed_income_return_decomposition,
)
from etf_cockpit.analysis.fixed_income_screener import (
    build_fixed_income_screener,
    load_fixed_income_screener_config,
)
from etf_cockpit.data.bond_analytics_store import (
    BondAnalyticsRecord,
    read_bond_analytics,
    write_bond_analytics,
)
from etf_cockpit.data.market_calendar import DayCountConvention
from tests.test_fixed_income_analytics import NOW, _bond
from tests.test_fixed_income_screener import _security, _valuation


def _zero_year() -> FixedIncomeValuationInput:
    flows = (ContractualCashFlow(date(2027, 1, 1), Decimal("100"), "redemption", "terms-v1"),)
    return FixedIncomeValuationInput(
        instrument_id="ZERO-1",
        terms_version_id="terms-v1",
        currency="USD",
        face_value=Decimal("100"),
        settlement_date=date(2026, 1, 1),
        maturity_date=date(2027, 1, 1),
        coupon_rate=Decimal("0"),
        coupon_frequency=0,
        day_count=DayCountConvention.THIRTY_360_US,
        cashflows=flows,
        decision_time=NOW,
    )


def test_b13_n001_rounded_quote_accepted_but_real_mismatch_rejected() -> None:
    # 1y 5% annual-equivalent zero: 100/1.05 = 95.2380952381 quoted as 95.24.
    zero = replace(
        _zero_year(), yield_to_maturity=Decimal("0.05"), clean_price=Decimal("95.24"), coupon_frequency=0
    )
    result = calculate_fixed_income_analytics(zero)
    assert result.clean_price == Decimal("95.24")
    with pytest.raises(FixedIncomeAnalyticsError, match="contradictory"):
        calculate_fixed_income_analytics(replace(zero, clean_price=Decimal("95.25")))


def test_b13_n002_unpaid_coupon_after_accrual_end_is_accrued() -> None:
    bond = _bond()
    first = replace(bond.cashflows[0], payment_date=date(2026, 7, 2))
    shifted = replace(
        bond,
        settlement_date=date(2026, 7, 1),
        cashflows=(first, *bond.cashflows[1:]),
    )
    assert accrued_interest(shifted) == Decimal("2.5")
    # Once the payment date is reached only one day of the next coupon accrues.
    paid = replace(shifted, settlement_date=date(2026, 7, 2))
    assert accrued_interest(paid) == pytest.approx(Decimal("25") / 180 / 1000 * 100)
    # Ex-coupon: the detached coupon is not added on top.
    ex = replace(first, ex_coupon_date=date(2026, 7, 1))
    detached = replace(shifted, cashflows=(ex, *bond.cashflows[1:]))
    assert accrued_interest(detached) == 0


def test_b13_n003_unscorable_bond_does_not_support_peer_cohort() -> None:
    config = replace(
        load_fixed_income_screener_config(
            Path(__file__).parents[1] / "configs" / "fixed_income_returns_v1.yaml"
        ),
        minimum_peer_support=2,
        bootstrap_samples=20,
    )
    scorable_a = _security("A", years=3, coupon="0.04", ytm="0.04")
    scorable_b = _security("B", years=3, coupon="0.05", ytm="0.05")
    unscorable = replace(_security("C", years=3, coupon="0.06", ytm="0.06"), return_input=None)
    snapshot = build_fixed_income_screener(
        (scorable_a, scorable_b, unscorable), decision_time=NOW, config=config
    )
    rows = {row.instrument_id: row for row in snapshot.rows}
    for key in ("A", "B"):
        cohort = rows[key].peer_cohort
        assert cohort is not None
        assert "C" not in cohort.peer_instrument_ids
        assert cohort.status == "unavailable"
        assert rows[key].rank is None
    # With a third scorable bond support is met and the unscorable one stays out.
    d = _security("D", years=3, coupon="0.045", ytm="0.045")
    full = build_fixed_income_screener(
        (scorable_a, scorable_b, d, unscorable), decision_time=NOW, config=config
    )
    cohort = {row.instrument_id: row for row in full.rows}["A"].peer_cohort
    assert cohort is not None and cohort.status == "supported"
    assert cohort.peer_instrument_ids == ("B", "D")


def test_b13_n004_local_and_fx_returns_compound() -> None:
    valuation = _valuation("FX-1", years=5, coupon="0.05", ytm="0.05")

    def decompose(fx: str):
        return calculate_fixed_income_return_decomposition(
            FixedIncomeReturnInput(
                valuation,
                default_probability=Decimal("0"),
                recovery_rate=Decimal("0.4"),
                fx_return=Decimal(fx),
                cost_bps=Decimal("0"),
            )
        )

    local = decompose("0")
    fx = decompose("0.10")
    assert local.net_total_return is not None and fx.net_total_return is not None
    expected = (Decimal("1") + local.net_total_return) * Decimal("1.10") - Decimal("1")
    assert fx.net_total_return == expected
    assert fx.net_total_return != local.net_total_return + Decimal("0.10")
    assert fx.fx == Decimal("0.10")


def test_b13_n004_ten_percent_local_and_ten_percent_fx_is_twenty_one_percent() -> None:
    # Pure compounding identity used by the decomposition: 1.10 x 1.10 - 1 = 0.21.
    assert (Decimal("1") + Decimal("0.10")) * (Decimal("1") + Decimal("0.10")) - 1 == Decimal("0.21")


def test_e01_c2_bond_store_rejects_future_evidence_and_backdated_calculation(tmp_path) -> None:
    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"
    bond = _bond()
    result = calculate_fixed_income_analytics(bond)
    early = datetime(2025, 12, 31, tzinfo=timezone.utc)
    with pytest.raises(FixedIncomeAnalyticsError):
        write_bond_analytics(path, (BondAnalyticsRecord("early", early, bond, result),))
    from tests.test_fixed_income_analytics import _curve

    future_curve = replace(_curve(), retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    with pytest.raises(FixedIncomeAnalyticsError, match="future-known"):
        calculate_fixed_income_analytics(replace(bond, curve=future_curve))


def test_e01_c2_n003_read_repair_never_changes_committed_history(tmp_path) -> None:
    path = tmp_path / "data" / "analytics" / "bond_analytics.parquet"
    bond = _bond()
    write_bond_analytics(
        path,
        (BondAnalyticsRecord("first", NOW, bond, calculate_fixed_income_analytics(bond)),),
    )
    before = read_bond_analytics(path)
    frame = pd.read_parquet(path)
    phantom = frame.iloc[0].copy()
    phantom["record_id"] = "phantom"
    pd.concat([frame, phantom.to_frame().T], ignore_index=True).to_parquet(path, index=False)
    after = read_bond_analytics(path)
    assert after == before
    assert list(pd.read_parquet(path)["record_id"]) == ["first"]
