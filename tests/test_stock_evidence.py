"""Stock evidence: hand-computed metrics, point-in-time rules, currency, peers and score components."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.stock_evidence import AnalystInputs, MarketInputs, build_stock_evidence
from etf_cockpit.data.stock_fundamentals import load_stock_config

UTC = timezone.utc
DECISION = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
CONFIG = load_stock_config()


def _period(year: int, *, known: str | None = None, currency: str = "EUR", **overrides: float) -> sm.Period:
    values = {
        "revenue": 1000.0 * (1.1 ** (year - 2022)),
        "gross_profit": 400.0,
        "ebit": 200.0,
        "da": 60.0,
        "pretax_income": 180.0,
        "income_tax": 45.0,
        "net_income_parent": 100.0 * (1.1 ** (year - 2022)),
        "cfo": 220.0,
        "capex": 70.0,
        "dividends_paid": 30.0,
        "equity_parent": 900.0 + 100.0 * (year - 2022),
        "minority_interest": 30.0,
        "ib_debt": 300.0,
        "lease_liabilities": 50.0,
        "cash_sti": 150.0,
        "shares_outstanding": 10.0,
    }
    values.update(overrides)
    known_at = datetime.fromisoformat(known or f"{year + 1}-02-15").replace(tzinfo=UTC)
    return sm.Period(date(year, 12, 31), "FY", known_at, currency, "sec_edgar", values)


def _market(price: float = 50.0, currency: str = "EUR", **extra: object) -> MarketInputs:
    return MarketInputs(price=price, price_currency=currency, price_date=date(2026, 10, 8), **extra)  # type: ignore[arg-type]


def _evidence(periods=None, market=None, **kwargs):
    periods = periods or [_period(y) for y in (2022, 2023, 2024, 2025)]
    return build_stock_evidence("T", periods, DECISION, market or _market(), None, CONFIG, **kwargs)


def test_golden_metrics_for_a_fiscal_year_company() -> None:
    ev = _evidence()
    m = ev.metrics
    ni, rev = 100.0 * 1.1**3, 1000.0 * 1.1**3
    assert m["revenue"].value == pytest.approx(rev) and m["revenue"].basis == "FY"
    assert m["ebit_margin"].value == pytest.approx(200.0 / rev)
    assert m["roe"].value == pytest.approx(ni / ((1100.0 + 1200.0) / 2))  # average of opening FY2024 and closing FY2025
    nopat = 200.0 * (1 - 45.0 / 180.0)
    assert m["roic"].value == pytest.approx(nopat / (((1100 + 300 + 50 - 150) + (1200 + 300 + 50 - 150)) / 2))
    assert m["fcf"].value == pytest.approx(150.0) and m["net_debt"].value == pytest.approx(200.0)
    assert m["market_cap"].value == pytest.approx(500.0)  # 50 x 10
    assert m["ev"].value == pytest.approx(730.0)  # 500 + 200 net debt + 30 minority
    assert m["pe"].value == pytest.approx(500.0 / ni) and m["pb"].value == pytest.approx(500.0 / 1200.0)
    assert m["ev_ebit"].value == pytest.approx(730.0 / 200.0) and m["fcf_yield"].value == pytest.approx(150.0 / 500.0)
    assert m["net_debt_to_ebitda"].value == pytest.approx(200.0 / 260.0)
    assert m["revenue_cagr"].value == pytest.approx(0.10, abs=1e-9) and m["revenue_cagr"].source.startswith("FY2022->FY2025")


def test_only_facts_known_at_the_decision_time_are_used() -> None:
    periods = [_period(y) for y in (2022, 2023, 2024)] + [_period(2025, known="2026-11-01")]
    ev = _evidence(periods)
    assert ev.metrics["revenue"].as_of == "2024-12-31"  # FY2025 is only known in November
    only_future = _evidence([_period(2025, known="2026-11-01")], no_data_reason="x")
    assert only_future.metrics["revenue"].status == sm.UNAVAILABLE and only_future.metrics["revenue"].reason == "x"
    assert only_future.components["stock_value"].score_10 is None


def test_loss_is_not_meaningful_and_scores_zero_on_yield_inputs() -> None:
    ev = _evidence([_period(y, net_income_parent=-50.0, ebit=-20.0) for y in (2022, 2023, 2024, 2025)])
    assert ev.metrics["pe"].status == sm.NOT_MEANINGFUL and "loss" in ev.metrics["pe"].reason
    assert ev.metrics["pe"].value is None  # never a negative multiple
    ey = next(s for s in ev.components["stock_value"].inputs if s.key == "earnings_yield")
    assert ey.score == 0.0 and ey.value < 0  # a known loss scores the minimum, it is not treated as missing


def test_price_in_another_currency_needs_an_fx_rate() -> None:
    usd = _market(price=60.0, currency="USD")
    blocked = _evidence(market=usd)
    assert blocked.metrics["market_cap"].status == sm.UNAVAILABLE and "currency_mismatch" in blocked.metrics["pe"].reason
    converted = _evidence(market=_market(price=60.0, currency="USD", fx_to_reporting=0.9))
    assert converted.metrics["market_cap"].value == pytest.approx(60.0 * 0.9 * 10.0)
    pence = _evidence(market=_market(price=5000.0, currency="GBp", fx_to_reporting=1.2))  # 50 GBP x 1.2
    assert pence.metrics["market_cap"].value == pytest.approx(50.0 * 1.2 * 10.0)


def test_inconsistent_filing_share_count_falls_back_to_the_provider_count() -> None:
    periods = [_period(y, shares_outstanding=0.01) for y in (2022, 2023, 2024, 2025)]  # e.g. class A count against a class B price
    market = _market(shares_fallback=10.0, shares_fallback_known_at=datetime(2026, 10, 8, tzinfo=UTC))
    ev = _evidence(periods, market)
    assert ev.metrics["market_cap"].value == pytest.approx(500.0)
    assert any("differs from the provider count" in note for note in ev.notes)


def test_peer_median_excludes_the_instrument_and_shows_the_count() -> None:
    peers = {"pe": {"T": 99.0, "A": 10.0, "B": 20.0, "C": 30.0, "D": 40.0}}
    ev = _evidence(peer_values=peers)
    stat = ev.peer_stats["pe"]
    assert stat.count == 4 and stat.median == 25.0  # T itself is excluded
    own = ev.metrics["pe"].value
    assert stat.premium == pytest.approx(own / 25.0 - 1.0)
    assert ev.metrics["pe_vs_peers"].status == sm.OK
    few = _evidence(peer_values={"pe": {"A": 10.0, "B": 20.0}})
    assert few.metrics["pe_vs_peers"].status == sm.UNAVAILABLE and "3 needed" in few.metrics["pe_vs_peers"].reason


def test_valuation_history_percentile_uses_only_filings_known_at_each_date() -> None:
    periods = [_period(y) for y in (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025)]
    series = []
    day = date(2021, 11, 30)
    while day < date(2026, 10, 1):
        series.append((day, 50.0 + (day.year - 2021) * 2.0))
        year, month = (day.year + (day.month // 12), day.month % 12 + 1)
        day = (date(year, month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    ev = _evidence(periods, _market(price_series=tuple(series)))
    assert ev.history_points >= 12
    assert 0.0 <= ev.metrics["pe_percentile"].value <= 1.0 and ev.metrics["pe_percentile"].status == sm.OK
    short = _evidence(market=_market(price_series=tuple(series[:3])))
    assert short.metrics["pe_percentile"].status == sm.UNAVAILABLE and "month-end" in short.metrics["pe_percentile"].reason


def test_reverse_valuation_is_unavailable_until_cost_of_equity_is_configured() -> None:
    ev = _evidence()
    assert ev.metrics["implied_growth_pe"].status == sm.UNAVAILABLE and "cost of equity" in ev.metrics["implied_growth_pe"].reason
    configured = {**CONFIG, "valuation": {**CONFIG["valuation"], "cost_of_equity": 0.09, "terminal_growth": 0.02}}
    ev = build_stock_evidence("T", [_period(y) for y in (2022, 2023, 2024, 2025)], DECISION, _market(), None, configured)
    pe, payout = ev.metrics["pe"].value, 30.0 / (100.0 * 1.1**3)
    assert ev.metrics["implied_growth_pe"].value == pytest.approx(0.09 - payout / pe)
    assert ev.metrics["implied_growth_dcf"].status == sm.OK


def test_components_score_from_available_inputs_and_state_what_is_missing() -> None:
    ev = _evidence()
    quality = ev.components["stock_quality"]
    roe = next(s for s in quality.inputs if s.key == "roe")
    assert roe.score == pytest.approx(10 * ev.metrics["roe"].value / 0.20, abs=1e-3)  # 0 at 0 %, 10 at 20 %
    assert quality.score_10 == pytest.approx(sum(s.score for s in quality.used) / len(quality.used), abs=1e-2)
    value = ev.components["stock_value"]
    assert value.score_10 is not None and "Not used" in value.why and "P/E vs own history" in value.why
    assert ev.components["analyst_revision"].score_10 is None and "no analyst estimate snapshot" in ev.components["analyst_revision"].why
    analyst = AnalystInputs(eps_current=4.4, eps_90d_ago=4.0, revisions_up_30d=4.0, revisions_down_30d=1.0, known_at=DECISION - timedelta(days=1))
    scored = build_stock_evidence("T", [_period(2025)], DECISION, _market(), analyst, CONFIG).components["analyst_revision"]
    assert scored.score_10 == pytest.approx((10.0 * (0.10 + 0.10) / 0.20 + 10.0 * 0.8) / 2, abs=1e-2)
    future = AnalystInputs(eps_current=4.4, eps_90d_ago=4.0, known_at=DECISION + timedelta(days=1))
    assert build_stock_evidence("T", [_period(2025)], DECISION, _market(), future, CONFIG).components["analyst_revision"].score_10 is None
