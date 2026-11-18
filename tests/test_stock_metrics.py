"""Golden tests: every stock ratio against a hand-computed value (definitions in stock_metrics)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from etf_cockpit.analysis import stock_metrics as sm
from tests.test_stock_evidence import _evidence, _market, _period

UTC = timezone.utc


def _q(end: str, known: str, **values: float) -> sm.Period:
    return sm.Period(date.fromisoformat(end), "Q", datetime.fromisoformat(known).replace(tzinfo=UTC), "EUR", "yfinance", values)


def _fy(end: str, known: str, **values: float) -> sm.Period:
    return sm.Period(date.fromisoformat(end), "FY", datetime.fromisoformat(known).replace(tzinfo=UTC), "EUR", "yfinance", values)


def test_roe_uses_closing_parent_equity_and_rejects_non_positive_equity() -> None:
    assert sm.roe(120.0, 900.0, 1100.0).value == pytest.approx(120.0 / 1100.0)
    negative = sm.roe(120.0, -50.0, 1100.0)
    assert negative.status == sm.OK and negative.value == pytest.approx(120.0 / 1100.0)
    assert sm.roe(120.0, 900.0, -50.0).status == sm.NOT_MEANINGFUL
    assert sm.roe(120.0, None, 1100.0).value == pytest.approx(120.0 / 1100.0)


def test_tax_rate_is_clamped_and_roic_uses_closing_invested_capital() -> None:
    assert sm.effective_tax_rate(30.0, 100.0) == pytest.approx(0.30)
    assert sm.effective_tax_rate(60.0, 100.0) == pytest.approx(0.40)  # clamped to 40 %
    assert sm.effective_tax_rate(-5.0, 100.0) == 0.0  # clamped to 0 %
    assert sm.effective_tax_rate(10.0, -20.0) == 0.0  # loss: no tax shield assumed
    nopat = sm.nopat(200.0, 0.25)
    assert nopat == pytest.approx(150.0)
    opening = sm.invested_capital(800.0, 300.0, 50.0, 150.0)  # 800 + 300 + 50 - 150
    closing = sm.invested_capital(900.0, 350.0, 50.0, 100.0)  # 900 + 350 + 50 - 100
    assert (opening, closing) == (1000.0, 1200.0)
    assert sm.roic(nopat, opening, closing).value == pytest.approx(150.0 / 1200.0)


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
    # trailing P/E contract (#940 B106-N003): P/E = payout * (1 + g) / (r - g)  =>  g = (r * P/E - payout) / (P/E + payout)
    # (previously pinned the forward form g = r - payout / (P/E) = 0.06; flagged for Opus review)
    implied = sm.implied_growth_from_pe(20.0, 0.4, 0.08).value
    assert implied == pytest.approx((0.08 * 20.0 - 0.4) / 20.4)
    assert 0.4 * (1.0 + implied) / (0.08 - implied) == pytest.approx(20.0)
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


# Quality, earnings-quality and distress scores (INT-04): two fiscal years, hand-computed from the published definitions.
PREV = dict(revenue=1000.0, gross_profit=400.0, ebit=100.0, da=50.0, net_income_parent=50.0, cfo=60.0, total_assets=1000.0,
            total_liabilities=600.0, equity_parent=400.0, minority_interest=0.0, ib_debt=300.0, current_assets=400.0,
            current_liabilities=300.0, receivables=100.0, ppe_net=300.0, retained_earnings=150.0, sga=150.0, shares_outstanding=96.0)
CUR = dict(PREV, revenue=1200.0, gross_profit=420.0, ebit=120.0, da=60.0, net_income_parent=90.0, cfo=100.0, total_assets=1100.0,
           total_liabilities=660.0, equity_parent=440.0, ib_debt=250.0, current_assets=450.0, receivables=150.0, ppe_net=330.0,
           retained_earnings=200.0, sga=200.0, shares_outstanding=100.0, stock_based_compensation=12.0, gross_buybacks=45.0, share_issuance=15.0)
MCAP = 900.0  # price 9 x 100 shares
BENEISH = (-4.84 + 0.920 * 1.25 + 0.528 * (0.4 / 0.35) + 0.404 * ((1 - 780 / 1100) / 0.3) + 0.892 * 1.2
           + 0.115 * ((50 / 350) / (60 / 390)) + -0.172 * ((200 / 1200) / (150 / 1000)) + 4.679 * ((90 - 100) / 1100) - 0.327 * 1.0)
ALTMAN = 1.2 * 150 / 1100 + 1.4 * 200 / 1100 + 3.3 * 120 / 1100 + 0.6 * 900 / 660 + 1200 / 1100


def _scores():
    evidence = _evidence([_period(2024, **PREV), _period(2025, **CUR)], _market(9.0)).metrics
    return {key: evidence[key] for key in ("piotroski_f", "altman_z", "beneish_m", "gross_profitability", "accruals", "dilution",
                                           "sbc_adjusted_fcf", "buyback_yield", "shareholder_yield")}


@pytest.mark.parametrize("key, expected", [
    ("piotroski_f", 7.0),  # ROA, CFO, dROA, CFO > ROA, leverage, current ratio, turnover pass; new shares and gross margin fail
    ("altman_z", ALTMAN),
    ("beneish_m", BENEISH),
    ("gross_profitability", 420.0 / 1100.0),
    ("accruals", (90.0 - 100.0) / 1050.0),  # Sloan, on average total assets (1000 + 1100) / 2
    ("dilution", 100.0 / 96.0 - 1.0),  # net share issuance
    ("sbc_adjusted_fcf", 100.0 - 70.0 - 12.0),
    ("buyback_yield", 45.0 / MCAP),
    ("shareholder_yield", (30.0 + 45.0 - 15.0) / MCAP),
])
def test_quality_scores_match_hand_values(key: str, expected: float) -> None:
    metric = _scores()[key]
    assert metric.status == sm.OK and metric.value == pytest.approx(expected)


@pytest.mark.parametrize("call, status", [
    (lambda: sm.piotroski_f(CUR, {k: v for k, v in PREV.items() if k != "current_liabilities"}), sm.UNAVAILABLE),
    (lambda: sm.altman_z({k: v for k, v in CUR.items() if k != "retained_earnings"}, MCAP), sm.UNAVAILABLE),
    (lambda: sm.altman_z(CUR, None), sm.UNAVAILABLE),
    (lambda: sm.beneish_m(CUR, {k: v for k, v in PREV.items() if k != "sga"}), sm.UNAVAILABLE),
    (lambda: sm.sbc_adjusted_fcf(30.0, None), sm.UNAVAILABLE),
    (lambda: sm.buyback_yield(None, MCAP), sm.UNAVAILABLE),
    (lambda: sm.piotroski_f(dict(CUR, total_assets=0.0), PREV), sm.NOT_MEANINGFUL),
    (lambda: sm.beneish_m(CUR, dict(PREV, revenue=0.0)), sm.NOT_MEANINGFUL),
    (lambda: sm.altman_z(dict(CUR, total_liabilities=0.0), MCAP), sm.NOT_MEANINGFUL),
    (lambda: sm.altman_z(CUR, 0.0), sm.NOT_MEANINGFUL),
    (lambda: sm.gross_profitability(420.0, 0.0), sm.NOT_MEANINGFUL),
    # negative book equity (liabilities above assets) still scores: Altman uses the market value of equity
    (lambda: sm.altman_z(dict(CUR, total_liabilities=1300.0, equity_parent=-200.0), MCAP), sm.OK),
    (lambda: _evidence([_period(2025, **CUR)], _market(9.0)).metrics["piotroski_f"], sm.UNAVAILABLE),  # one fiscal year only
    (lambda: _evidence([_period(2024), _period(2025)], _market(9.0)).metrics["buyback_yield"], sm.UNAVAILABLE),  # line item not reported
])
def test_quality_score_states_never_fill_in_missing_inputs(call, status: str) -> None:
    metric = call()
    assert metric.status == status
    assert (metric.value is not None) == (status == sm.OK)


@pytest.mark.parametrize("call", [
    lambda applicable: sm.piotroski_f(CUR, PREV, sector_applicable=applicable),
    lambda applicable: sm.altman_z(CUR, MCAP, sector_applicable=applicable),
    lambda applicable: sm.beneish_m(CUR, PREV, sector_applicable=applicable),
    lambda applicable: sm.gross_profitability(420.0, 1100.0, sector_applicable=applicable),
    lambda applicable: sm.sbc_adjusted_fcf(30.0, 12.0, sector_applicable=applicable),
    lambda applicable: sm.buyback_yield(45.0, MCAP, sector_applicable=applicable),
    lambda applicable: sm.shareholder_yield(30.0, 45.0, 15.0, MCAP, sector_applicable=applicable),
])
def test_bank_and_insurer_scores_are_not_meaningful(call) -> None:
    assert call(True).status == sm.OK
    bank = call(False)
    assert bank.status == sm.NOT_MEANINGFUL and bank.value is None
