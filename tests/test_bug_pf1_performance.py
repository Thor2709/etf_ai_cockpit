"""Issue #967 (Bughunt D): portfolio performance, valuation and attribution regressions."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.portfolio_valuation import build_portfolio_valuation_history
from etf_cockpit.portfolio.attribution import (
    _benchmark_attribution,
    _currency_attribution,
    build_performance_attribution,
)
from etf_cockpit.portfolio.holdings import portfolio_value, portfolio_value_with_coverage
from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series
from etf_cockpit.portfolio.valuation import (
    SNAPSHOT_COLUMNS,
    build_daily_portfolio_snapshots,
    calculate_money_weighted_return,
    link_time_weighted_return,
)


def _history(
    dates: pd.DatetimeIndex | list[pd.Timestamp],
    *,
    prices: list[float],
    cash: list[float],
    quantities: list[float] | None = None,
    events: list[tuple[int, str, float]] | None = None,
) -> pd.DataFrame:
    positions = [1.0] * len(dates) if quantities is None else quantities
    event_rows = [{"date": dates[index], "event_type": kind, "amount": amount} for index, kind, amount in (events or [])]
    report = build_portfolio_valuation_history(
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "quantity": positions}),
        pd.DataFrame({"date": dates, "instrument_id": ["AAA"] * len(dates), "price": prices}),
        pd.DataFrame({"date": dates, "cash_value": cash}),
        pd.DataFrame(event_rows, columns=["date", "event_type", "amount"]),
        decision_time=pd.Timestamp(dates[-1]).normalize() + pd.Timedelta(days=1),
    )
    return report["snapshots"]


def _frame(dates: list[str], values: list[float], flows: list[float] | None = None, capital: list[float] | None = None) -> pd.DataFrame:
    flows = flows or [0.0] * len(dates)
    rows = []
    for index, observed in enumerate(dates):
        previous = values[index - 1] if index else None
        rows.append(
            {
                "date": pd.Timestamp(observed),
                "cash_value": 0.0,
                "securities_value": values[index],
                "total_value": values[index],
                "external_flow": flows[index],
                "invested_capital": capital[index] if capital else values[0] + sum(flows[1 : index + 1]),
                "dividends": 0.0,
                "coupons": 0.0,
                "fees": 0.0,
                "taxes": 0.0,
                "investment_pnl": math.nan if previous is None else values[index] - previous - flows[index],
                "period_return": math.nan if previous is None else (values[index] - flows[index]) / previous - 1.0,
                "valuation_status": "available",
                "flow_status": "available",
                "availability_evidence": "timestamped",
                "missing_reasons": "",
                "execution_allowed": False,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SNAPSHOT_COLUMNS)


# --- holdings (D101-N001) -------------------------------------------------


@pytest.mark.parametrize(
    ("values", "status", "partial"),
    [([100.0, math.nan], "partial", 100.0), ([math.nan, math.nan], "unavailable", None), ([100.0, 50.0], "available", 150.0)],
)
def test_d101_n001_missing_market_value_is_never_summed_as_zero(values, status, partial) -> None:
    holdings = pd.DataFrame({"market_value_eur": values})
    coverage = portfolio_value_with_coverage(holdings)
    assert coverage["status"] == status
    assert coverage["partial_value"] == partial
    if status == "available":
        assert portfolio_value(holdings) == pytest.approx(150.0)
    else:
        assert coverage["value"] is None
        assert portfolio_value(holdings) is None


# --- valuation (D101-N003/N004, D105-N001/N002/N003, C2-N001/N004) --------


def test_d101_n003_civil_date_is_kept_before_utc_conversion() -> None:
    snapshots = build_daily_portfolio_snapshots(
        pd.DataFrame({"date": ["2026-01-06T00:00:00+11:00"], "instrument_id": ["AAA"], "quantity": [1.0]}),
        pd.DataFrame({"date": ["2026-01-06T00:00:00Z"], "instrument_id": ["AAA"], "price": [100.0]}),
        pd.DataFrame({"date": ["2026-01-06"], "cash_value": [0.0]}),
        pd.DataFrame({"date": pd.Series([], dtype=object), "event_type": [], "amount": []}),
        decision_time="2026-01-07",
    )
    assert snapshots["date"].tolist() == [pd.Timestamp("2026-01-06")]
    assert snapshots.iloc[0]["valuation_status"] == "available"
    assert snapshots.iloc[0]["total_value"] == pytest.approx(100.0)


def test_d101_n004_exchange_calendar_replaces_generic_weekdays() -> None:
    # NYSE is closed on 2026-01-01; 31 Dec and 2 Jan are consecutive sessions.
    snapshots = _frame(["2025-12-31", "2026-01-02"], [100.0, 110.0])
    result = link_time_weighted_return(snapshots)
    assert result["status"] == "available"
    assert result["value"] == pytest.approx(0.10)
    gap = link_time_weighted_return(_frame(["2025-12-30", "2026-01-02"], [100.0, 110.0]))
    assert gap["status"] == "unavailable"  # 2025-12-31 is a real missing session


def test_d105_n001_first_day_external_flow_is_invested_capital() -> None:
    dates = pd.bdate_range("2026-01-05", periods=2)
    snapshots = _history(dates, prices=[100.0, 100.0], cash=[100.0, 100.0], quantities=[0.0, 0.0], events=[(0, "contribution", 100.0)])
    assert snapshots["external_flow"].tolist() == [100.0, 0.0]
    assert snapshots["invested_capital"].tolist() == [100.0, 100.0]


def test_d105_n002_zero_prior_nav_restarts_invested_capital() -> None:
    dates = pd.bdate_range("2026-01-05", periods=3)
    snapshots = _history(
        dates,
        prices=[100.0, 100.0, 110.0],
        cash=[0.0, 0.0, 0.0],
        quantities=[0.0, 1.0, 1.0],
        events=[(1, "contribution", 100.0)],
    )
    assert snapshots["total_value"].tolist() == [0.0, 100.0, 110.0]
    assert snapshots["invested_capital"].notna().all()
    assert snapshots["invested_capital"].tolist() == [0.0, 100.0, 100.0]
    assert snapshots.iloc[1]["investment_pnl"] == pytest.approx(0.0)
    assert snapshots.iloc[2]["investment_pnl"] == pytest.approx(10.0)


def test_d105_n003_short_period_xirr_finds_the_wide_root() -> None:
    annual = 1.91796
    days = 31
    period_return = (1.0 + annual) ** (days / 365.0) - 1.0
    snapshots = _frame(["2026-01-05", "2026-02-05"], [100.0, 100.0 * (1.0 + period_return)])
    result = calculate_money_weighted_return(snapshots)
    assert result["method"] == "xirr_deannualized_period_return"
    assert result["annualized_xirr"] == pytest.approx(annual, abs=1e-6)
    assert result["value"] == pytest.approx(period_return, abs=1e-9)


def test_c2_n004_xirr_tolerance_is_scale_invariant() -> None:
    small = calculate_money_weighted_return(_frame(["2026-01-05", "2026-07-06"], [1e-9, 1.1e-9]))
    large = calculate_money_weighted_return(_frame(["2026-01-05", "2026-07-06"], [1e9, 1.1e9]))
    assert small["method"] == large["method"] == "xirr_deannualized_period_return"
    assert small["value"] == pytest.approx(0.1, abs=1e-8)
    assert small["value"] == pytest.approx(large["value"], abs=1e-8)


def test_c2_n001_daily_twr_below_minus_100_percent_is_never_shown() -> None:
    # Total value 5 with a 50 inflow is a -145% "return": invalid, not displayable.
    dates = pd.bdate_range("2026-01-05", periods=2)
    built = _history(dates, prices=[100.0, 5.0], cash=[0.0, 0.0], events=[(1, "contribution", 50.0)])
    assert math.isnan(built.iloc[1]["period_return"])
    stored = _frame(["2026-01-05", "2026-01-06"], [100.0, 5.0], flows=[0.0, 50.0])
    assert stored.iloc[1]["period_return"] < -1.0
    series = build_portfolio_performance_series(stored, metric="twr_return", aggregation="day")
    assert series.points[-1].value is None
    assert series.points[-1].status == "unavailable"


# --- performance series (D101-N002, C2-N002, C2-N003) ----------------------


def test_d101_n002_mwr_buckets_include_the_prior_close() -> None:
    snapshots = _frame(["2025-12-31", "2026-01-02", "2026-01-05"], [100.0, 110.0, 121.0])
    monthly = build_portfolio_performance_series(snapshots, metric="mwr_return", aggregation="month")
    january = next(point for point in monthly.points if point.period_start.month == 1)
    assert january.value == pytest.approx(0.21, abs=1e-8)  # 31 Dec close anchors January
    daily = build_portfolio_performance_series(snapshots, metric="mwr_return", aggregation="day")
    by_day = {point.period_end.isoformat(): point.value for point in daily.points}
    assert by_day["2026-01-02"] == pytest.approx(0.10, abs=1e-8)
    assert by_day["2026-01-05"] == pytest.approx(0.10, abs=1e-8)


def test_c2_n002_invested_capital_does_not_move_with_fx_without_a_contribution() -> None:
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    snapshots = _frame(dates, [100.0, 100.0, 100.0], capital=[100.0, 100.0, 100.0])
    fx = pd.DataFrame(
        [
            {"as_of_date": day, "base_currency": "EUR", "quote_currency": "USD", "rate": rate, "source": "ECB", "ingested_at": "2025-12-01T09:00:00Z"}
            for day, rate in zip(dates, [1.10, 1.20, 1.30], strict=True)
        ]
    )
    series = build_portfolio_performance_series(snapshots, metric="net_invested_capital", currency="USD", fx_rates=fx)
    values = [point.value for point in series.points]
    assert all(value is not None for value in values)
    assert values == pytest.approx([110.0, 110.0, 110.0])


def test_c2_n003_unavailable_nav_does_not_display_a_numeric_value() -> None:
    snapshots = _frame(["2026-01-05", "2026-01-06"], [100.0, 105.0])
    snapshots.loc[1, "valuation_status"] = "unavailable"
    series = build_portfolio_performance_series(snapshots, metric="portfolio_value", aggregation="day")
    last = series.points[-1]
    assert last.value is None
    assert last.status == "unavailable"


# --- attribution (D007, D107) ----------------------------------------------


def _prices(days: int = 3) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=days)
    return pd.DataFrame({"date": dates, "etf_id": ["AAA"] * days, "adjusted_close": [100.0 + 10.0 * index for index in range(days)]})


def _allocation() -> pd.DataFrame:
    return pd.DataFrame([{"etf_id": "AAA", "current_weight": 1.0, "currency": "EUR"}])


def test_d007_n001_eur_costs_are_converted_to_return_space() -> None:
    costs = pd.DataFrame({"category": ["commission"], "amount": [5.0]})
    report = build_performance_attribution(_prices(), _allocation(), costs=costs, nav_eur=1_000.0)
    gross = report["time_weighted_return"]
    assert report["net_return_after_explicit_costs"] == pytest.approx(gross - 0.005)
    assert report["diagnostics"]["explicit_cost_return"] == pytest.approx(0.005)
    # Without a NAV denominator the net return is unavailable, never gross minus EUR.
    unscaled = build_performance_attribution(_prices(), _allocation(), costs=costs)
    assert unscaled["net_return_after_explicit_costs"] is None
    assert "cost_nav_denominator_unavailable" in unscaled["warnings"]


def test_d107_n002_cost_signs_are_preserved() -> None:
    costs = pd.DataFrame({"category": ["commission", "rebate"], "amount": [10.0, -8.0]})
    report = build_performance_attribution(_prices(), _allocation(), costs=costs, nav_eur=1_000.0)
    amounts = dict(zip(report["cost_attribution"]["category"], report["cost_attribution"]["amount"], strict=True))
    assert amounts == {"commission": 10.0, "rebate": -8.0}
    assert report["diagnostics"]["explicit_cost_total"] == pytest.approx(2.0)
    assert report["net_return_after_explicit_costs"] == pytest.approx(report["time_weighted_return"] - 0.002)


def test_d007_n002_factor_attribution_keeps_the_first_return_day() -> None:
    prices = _prices(4)
    dates = list(prices["date"].iloc[1:])
    factors = pd.DataFrame({"date": dates, "factor": ["market"] * 3, "factor_return": [0.01, 0.02, 0.03]})
    exposures = pd.DataFrame({"market": [1.0]}, index=["AAA"])
    report = build_performance_attribution(prices, _allocation(), factor_returns=factors, factor_exposures=exposures)
    row = report["factor_attribution"].iloc[0]
    assert row["observations"] == 3
    wealth_before = [1.0, *report["daily"]["wealth"].iloc[:-1].tolist()]
    expected = sum(r * w for r, w in zip([0.01, 0.02, 0.03], wealth_before, strict=True))
    assert row["contribution"] == pytest.approx(expected)


def test_d007_n003_duplicate_currency_rows_do_not_multiply_contributions() -> None:
    summary = pd.DataFrame({"instrument_id": ["AAA"], "contribution": [0.05], "observations": [3], "mean_return": [0.0], "coverage": [1.0]})
    allocation = pd.DataFrame({"etf_id": ["AAA", "AAA"], "currency": ["EUR", "EUR"]})
    result = _currency_attribution(summary, allocation)
    assert result["contribution"].sum() == pytest.approx(0.05)
    conflicting = _currency_attribution(summary, pd.DataFrame({"etf_id": ["AAA", "AAA"], "currency": ["EUR", "USD"]}))
    assert conflicting["contribution"].sum() == pytest.approx(0.05)
    assert conflicting["currency"].tolist() == ["unavailable"]


def test_d107_n001_partial_benchmark_overlap_is_not_available() -> None:
    days = pd.date_range("2026-01-05", periods=4, tz="UTC")
    portfolio = pd.Series([0.1] * 4, index=days)
    benchmark = pd.DataFrame({"date": days[:2], "benchmark": "BM", "return": [0.0, 0.0]})
    partial = _benchmark_attribution(0.46, benchmark, days, portfolio_returns=portfolio)
    assert partial.iloc[0]["status"] == "partial"
    full = _benchmark_attribution(0.46, pd.DataFrame({"date": days, "benchmark": "BM", "return": [0.0] * 4}), days, portfolio_returns=portfolio)
    assert full.iloc[0]["status"] == "available"


def test_d107_n003_same_date_price_conflicts_are_flagged_and_order_independent() -> None:
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-06", "2026-01-07", "2026-01-05", "2026-01-06", "2026-01-07"]),
            "etf_id": ["AAA", "AAA", "AAA", "AAA", "BBB", "BBB", "BBB"],
            "adjusted_close": [100.0, 90.0, 110.0, 100.0, 100.0, 100.0, 100.0],
        }
    )
    allocation = pd.DataFrame({"etf_id": ["AAA", "BBB"], "current_weight": [0.5, 0.5]})
    forward = build_performance_attribution(base, allocation)
    reverse = build_performance_attribution(base.iloc[::-1].reset_index(drop=True), allocation)
    assert "same_date_price_conflict_excluded" in forward["warnings"]
    assert forward["diagnostics"]["price_conflicts"] == ["AAA@2026-01-06"]
    assert forward["time_weighted_return"] == pytest.approx(reverse["time_weighted_return"])
    assert np.isfinite(forward["time_weighted_return"])
