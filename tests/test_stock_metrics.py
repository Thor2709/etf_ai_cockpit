"""Golden tests: every stock ratio against a hand-computed value (definitions in stock_metrics)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from etf_cockpit.analysis import stock_metrics as sm

UTC = timezone.utc


def _q(end: str, known: str, **values: float) -> sm.Period:
    return sm.Period(date.fromisoformat(end), "Q", datetime.fromisoformat(known).replace(tzinfo=UTC), "EUR", "yfinance", values)


def _fy(end: str, known: str, **values: float) -> sm.Period:
    return sm.Period(date.fromisoformat(end), "FY", datetime.fromisoformat(known).replace(tzinfo=UTC), "EUR", "yfinance", values)


def test_roe_uses_average_parent_equity_and_rejects_non_positive_equity() -> None:
    assert sm.roe(120.0, 900.0, 1100.0).value == pytest.approx(0.12)  # 120 / ((900 + 1100) / 2)
    negative = sm.roe(120.0, -50.0, 1100.0)
    assert negative.status == sm.NOT_MEANINGFUL and negative.value is None
    assert sm.roe(120.0, None, 1100.0).status == sm.UNAVAILABLE


def test_tax_rate_is_clamped_and_roic_uses_average_invested_capital() -> None:
    assert sm.effective_tax_rate(30.0, 100.0) == pytest.approx(0.30)
    assert sm.effective_tax_rate(60.0, 100.0) == pytest.approx(0.40)  # clamped to 40 %
    assert sm.effective_tax_rate(-5.0, 100.0) == 0.0  # clamped to 0 %
    assert sm.effective_tax_rate(10.0, -20.0) == 0.0  # loss: no tax shield assumed
    nopat = sm.nopat(200.0, 0.25)
    assert nopat == pytest.approx(150.0)
    opening = sm.invested_capital(800.0, 300.0, 50.0, 150.0)  # 800 + 300 + 50 - 150
    closing = sm.invested_capital(900.0, 350.0, 50.0, 100.0)  # 900 + 350 + 50 - 100
    assert (opening, closing) == (1000.0, 1200.0)
    assert sm.roic(nopat, opening, closing).value == pytest.approx(150.0 / 1100.0)


def test_margins_fcf_net_debt_and_leverage() -> None:
    assert sm.margin("ebit_margin", "EBIT margin", 200.0, 1000.0).value == pytest.approx(0.20)
    assert sm.margin("ebit_margin", "EBIT margin", 200.0, 0.0).status == sm.NOT_MEANINGFUL
    assert sm.free_cash_flow(500.0, 120.0) == 380.0
    assert sm.free_cash_flow(500.0, -120.0) == 380.0  # capex sign does not matter
    debt = sm.net_debt(300.0, 50.0, 150.0)
    assert debt == 200.0  # 300 + 50 leases - 150 cash
    assert sm.net_debt(300.0, None, 150.0) == 150.0  # leases not reported
    assert sm.ebitda(200.0, 60.0) == 260.0
    assert sm.net_debt_to_ebitda(debt, 260.0).value == pytest.approx(200.0 / 260.0)
    assert sm.net_debt_to_ebitda(debt, -5.0).status == sm.NOT_MEANINGFUL
    assert sm.debt_to_equity(300.0, 1200.0).value == pytest.approx(0.25)


def test_market_cap_ev_and_multiples_never_negative() -> None:
    cap = sm.market_cap(50.0, 10.0)
    assert cap == 500.0
    ev = sm.enterprise_value(cap, 200.0, 30.0)
    assert ev == 730.0  # market cap + net debt + minority interest
    pe = sm.multiple("pe", "P/E", cap, 40.0, formula="", denominator_name="net income")
    assert pe.value == pytest.approx(12.5)
    loss = sm.multiple("pe", "P/E", cap, -10.0, formula="", denominator_name="net income")
    assert loss.value is None and loss.status == sm.NOT_MEANINGFUL and "loss" in loss.reason
    assert sm.multiple("ev_ebit", "EV/EBIT", ev, 73.0, formula="", denominator_name="EBIT").value == pytest.approx(10.0)
    assert sm.multiple("ev_ebit", "EV/EBIT", -5.0, 73.0, formula="", denominator_name="EBIT").status == sm.NOT_MEANINGFUL
    assert sm.dividend_yield(1.2, 48.0).value == pytest.approx(0.025)


def test_cagr_percentile_median_and_currency() -> None:
    assert sm.cagr(100.0, 133.1, 3.0, key="g", label="g").value == pytest.approx(0.10)
    assert sm.cagr(-5.0, 20.0, 3.0, key="g", label="g").status == sm.NOT_MEANINGFUL
    assert sm.percentile_rank([10, 12, 14, 16, 18], 14.0) == pytest.approx(0.6)
    assert sm.median([4.0, None, 8.0, 6.0]) == 6.0 and sm.median([1.0, 3.0]) == 2.0 and sm.median([]) is None
    minor = {"GBp": ["GBP", 0.01]}
    assert sm.to_currency(227.0, "GBp", "GBP", fx_rate=None, minor_units=minor) == (pytest.approx(2.27), None)
    value, reason = sm.to_currency(227.0, "GBp", "EUR", fx_rate=1.18, minor_units=minor)
    assert value == pytest.approx(2.27 * 1.18) and reason is None
    assert sm.to_currency(100.0, "USD", "EUR", fx_rate=None, minor_units=minor) == (None, "currency_mismatch")


def test_reverse_valuation_needs_a_configured_cost_of_equity() -> None:
    assert sm.implied_growth_from_pe(20.0, 0.4, 0.08).value == pytest.approx(0.06)  # 0.08 - 0.4 / 20
    missing = sm.implied_growth_from_pe(20.0, 0.4, None)
    assert missing.status == sm.UNAVAILABLE and "cost of equity" in missing.reason
    assert sm.implied_growth_from_pe(20.0, 0.0, 0.08).status == sm.UNAVAILABLE
    # price a 2-stage DCF at g = 5 % and recover g from the market cap
    r, terminal, years, fcf = 0.09, 0.03, 5, 100.0
    cap = sm._dcf_value(fcf, 0.05, r, years, terminal)
    assert sm.implied_growth_from_dcf(cap, fcf, r, terminal, years).value == pytest.approx(0.05, abs=1e-6)
    assert sm.implied_growth_from_dcf(cap, fcf, None, terminal, years).status == sm.UNAVAILABLE
    assert sm.implied_growth_from_dcf(cap, -10.0, r, terminal, years).status == sm.NOT_MEANINGFUL


def test_ttm_is_four_known_quarters_else_fiscal_year() -> None:
    quarters = [
        _q("2025-03-31", "2025-05-01", revenue=100.0),
        _q("2025-06-30", "2025-08-01", revenue=110.0),
        _q("2025-09-30", "2025-11-01", revenue=120.0),
        _q("2025-12-31", "2026-02-01", revenue=130.0),
    ]
    year = _fy("2025-12-31", "2026-02-01", revenue=460.0)
    decision = datetime(2026, 3, 1, tzinfo=UTC)
    window = sm.flow_window(sm.known_periods([*quarters, year], decision), ["revenue"])
    assert window.basis == "TTM" and sm.window_sum(window, "revenue") == 460.0
    # the last quarter is not known yet at this decision time: only 3 quarters, so the fiscal year is used
    early = sm.flow_window(sm.known_periods([*quarters, _fy("2024-12-31", "2025-02-01", revenue=400.0)], datetime(2026, 1, 1, tzinfo=UTC)), ["revenue"])
    assert early.basis == "FY" and sm.window_sum(early, "revenue") == 400.0
    # a restatement known later is ignored at an earlier decision time
    restated = _q("2025-12-31", "2026-06-01", revenue=999.0)
    later = sm.known_periods([*quarters, restated], datetime(2026, 3, 1, tzinfo=UTC))
    assert [p.values["revenue"] for p in later if p.period_end == date(2025, 12, 31)] == [130.0]
