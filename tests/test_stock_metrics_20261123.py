"""Train R2-F: financials routing by industry, sector metric sets and new SEC metrics (2026-11-23)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from etf_cockpit.analysis.stock_universe import FINANCIAL_INDUSTRY_MISSING, FINANCIAL_SET_NOT_BUILT, financial_route_reason
from etf_cockpit.signals import simple_scores as ss


def _evidence() -> SimpleNamespace:
    part = SimpleNamespace(score_10=8.0, why="generic", source_id="sec_edgar:fundamentals", as_of="2025-01-09", freshness="ok",
                           band_low=None, band_high=None, used=(), inputs=())
    return SimpleNamespace(components={"stock_value": part, "stock_quality": part, "analyst_revision": part}, metrics={})


def _scores(industry: str | None) -> dict[str, float | None]:
    parts = ss._stock_fundamental_components(_evidence(), None, sector="Financial Services", industry=industry)
    return {part.key: part.score_10 for part in parts}


# --- item 1 (F4): fee-based financials are scored, banks and insurers stay out --------------------------------------


@pytest.mark.parametrize("industry", ["Asset Management", "Financial Data & Stock Exchanges", "Insurance Brokers"])
def test_fee_based_financials_use_the_existing_metric_set(industry: str) -> None:
    assert financial_route_reason("Financial Services", industry) is None
    assert _scores(industry)["stock_value"] == 8.0 and _scores(industry)["stock_quality"] == 8.0


@pytest.mark.parametrize("industry", ["Banks - Regional", "Banks - Diversified", "Capital Markets", "Credit Services"])
def test_banks_and_lenders_stay_out_until_their_set_exists(industry: str) -> None:
    assert financial_route_reason("Financial Services", industry) == FINANCIAL_SET_NOT_BUILT
    parts = {p.key: p for p in ss._stock_fundamental_components(_evidence(), None, sector="Financial Services", industry=industry)}
    assert parts["stock_value"].score_10 is None and FINANCIAL_SET_NOT_BUILT in parts["stock_value"].why


@pytest.mark.parametrize("industry", ["Insurance - Life", "Insurance - Property & Casualty", "Insurance - Reinsurance"])
def test_insurers_stay_out_until_their_set_exists(industry: str) -> None:
    assert financial_route_reason("Financials", industry) == FINANCIAL_SET_NOT_BUILT
    assert _scores(industry)["stock_quality"] is None


@pytest.mark.parametrize("industry", [None, "", "  "])
def test_financial_without_industry_fails_closed(industry: str | None) -> None:
    assert financial_route_reason("Financial Services", industry) == FINANCIAL_INDUSTRY_MISSING
    parts = {p.key: p for p in ss._stock_fundamental_components(_evidence(), None, sector="Financial Services", industry=industry)}
    assert parts["stock_value"].score_10 is None and FINANCIAL_INDUSTRY_MISSING in parts["stock_value"].why
    assert parts["analyst_revision"].score_10 == 8.0


def test_non_financial_sector_ignores_industry() -> None:
    assert financial_route_reason("Industrials", None) is None
    assert financial_route_reason("Industrials", "Banks - Regional") is None


# --- item 2 (F5): sector metric sets ------------------------------------------------------------------------------

from datetime import date, datetime, timezone  # noqa: E402

from etf_cockpit.analysis import stock_metrics as sm  # noqa: E402
from etf_cockpit.analysis.stock_evidence import MarketInputs, build_stock_evidence  # noqa: E402
from etf_cockpit.data.stock_fundamentals import load_stock_config  # noqa: E402

UTC = timezone.utc
DECISION = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
CONFIG = load_stock_config()


def _period(year: int, *, known: str | None = None, **overrides: float) -> sm.Period:
    values = {
        "revenue": 1000.0, "gross_profit": 400.0, "ebit": 200.0, "da": 60.0, "pretax_income": 180.0, "income_tax": 45.0,
        "net_income_parent": 100.0, "cfo": 220.0, "capex": 70.0, "dividends_paid": 30.0, "equity_parent": 900.0,
        "minority_interest": 0.0, "ib_debt": 300.0, "lease_liabilities": 50.0, "cash_sti": 150.0, "total_assets": 2000.0,
        "shares_outstanding": 10.0,
    }
    values.update(overrides)
    known_at = datetime.fromisoformat(known or f"{year + 1}-02-15").replace(tzinfo=UTC)
    return sm.Period(date(year, 12, 31), "FY", known_at, "EUR", "sec_edgar", values, field_sources={"shares_outstanding": "sec_dei"})


def _build(sector: str | None = None, industry: str | None = None, periods=None, **kwargs):
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8), dividends_per_share_12m=2.0)
    periods = periods or [_period(y) for y in (2021, 2022, 2023, 2024, 2025)]
    return build_stock_evidence("T", periods, DECISION, market, None, CONFIG, sector=sector, industry=industry, **kwargs)


def _cohorts(**values: float) -> dict[str, dict[str, dict[str, float]]]:
    """One industry cohort: three peers at 0.5x, 1x and 2x of each given value."""

    return {"industry": {key: {"P1": value * 0.5, "P2": value, "P3": value * 2.0} for key, value in values.items()}}


def test_a_sector_without_its_own_set_scores_as_today() -> None:
    today = _build()
    for sector, industry in (("Industrials", "Specialty Industrial Machinery"), ("Consumer Staples", None), ("Health Care", "Medical Devices")):
        assert _build(sector, industry).components == today.components


def test_utilities_value_uses_earnings_and_dividend_yield_only() -> None:
    value = _build("Utilities", "Utilities - Regulated Electric").components["stock_value"]
    assert [item.key for item in value.inputs] == ["earnings_yield", "dividend_yield"]
    # earnings yield 100/500 = 0.20 -> 10 on its 0..0.10 ladder; dividend yield 2/50 = 0.04 -> 6.667 on 0..0.06
    assert value.score_10 == pytest.approx(round((10.0 * 0.5 + 0.04 / 0.06 * 10.0 * 0.25) / 0.75, 2))
    assert "Not applicable" in value.why and "FCF yield" in value.why


def test_telecoms_take_the_utilities_set_by_industry() -> None:
    value = _build("Communication Services", "Telecom Services").components["stock_value"]
    assert [item.key for item in value.inputs] == ["earnings_yield", "dividend_yield"]


def test_technology_quality_uses_gross_profitability_and_growth() -> None:
    evidence = _build("Information Technology", "Software - Application", cohort_values=_cohorts(gross_profitability=0.2, revenue_cagr=0.0001))
    quality = evidence.components["stock_quality"]
    assert [item.key for item in quality.inputs] == ["gross_profitability", "revenue_cagr"]
    scores = {item.key: item.score for item in quality.inputs}
    assert scores["gross_profitability"] is not None and scores["revenue_cagr"] is not None
    assert quality.score_10 == pytest.approx(round((scores["gross_profitability"] * 0.3 + scores["revenue_cagr"] * 0.2) / 0.5, 2))
    assert "Not applicable" in quality.why and "ROE" in quality.why


@pytest.mark.parametrize(("sector", "industry"), [("Health Care", "Biotechnology"), ("Materials", "Gold")])
def test_pre_revenue_biotech_and_junior_miners_are_not_scorable(sector: str, industry: str) -> None:
    pre_revenue = _build(sector, industry, [_period(y, revenue=0.0) for y in (2021, 2022, 2023, 2024, 2025)])
    for key in ("stock_value", "stock_quality"):
        assert pre_revenue.components[key].score_10 is None and "not scorable" in pre_revenue.components[key].why
    assert pre_revenue.components["analyst_revision"] == _build().components["analyst_revision"]
    assert _build(sector, industry).components == _build().components  # with revenue: the default set
