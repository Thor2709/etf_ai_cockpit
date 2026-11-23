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
# The shipped config has no metric set (Round 3 ruling); the mechanism is tested with these fixture sets (D 2.4 weights).
SETS = {
    "utilities": {"sectors": ["Utilities"], "industries": ["Telecom Services"],
                  "value": {"earnings_yield": 0.5, "dividend_yield": 0.25}, "quality": {"net_debt_to_ebitda": 0.4, "roe": 0.3}},
    "technology": {"sectors": ["Information Technology"], "industries": ["Internet Content & Information"],
                   "value": {"sbc_fcf_yield": 0.4, "earnings_yield": 0.3}, "quality": {"gross_profitability": 0.3, "revenue_cagr": 0.2}},
    "real_estate": {"sectors": ["Real Estate"], "value": {"ffo_yield": 0.5, "dividend_yield": 0.2}},
    "cyclical": {"sectors": ["Energy"], "industries": ["Copper"], "value": {"ebit_ev_yield_5y": 0.4, "fcf_yield_3y": 0.3}},
}
SET_CONFIG = {**CONFIG, "scoring": {**CONFIG["scoring"], "metric_sets": SETS}}


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


def _build(sector: str | None = None, industry: str | None = None, periods=None, config=SET_CONFIG, **kwargs):
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8), dividends_per_share_12m=2.0)
    periods = periods or [_period(y) for y in (2021, 2022, 2023, 2024, 2025)]
    return build_stock_evidence("T", periods, DECISION, market, None, config, sector=sector, industry=industry, **kwargs)


def _cohorts(**values: float) -> dict[str, dict[str, dict[str, float]]]:
    """One industry cohort: three peers at 0.5x, 1x and 2x of each given value."""

    return {"industry": {key: {"P1": value * 0.5, "P2": value, "P3": value * 2.0} for key, value in values.items()}}


def test_the_shipped_config_has_no_metric_set() -> None:
    assert not CONFIG["scoring"].get("metric_sets")
    assert _build("Utilities", "Utilities - Regulated Electric", config=CONFIG).components == _build(config=CONFIG).components


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
    with_revenue = _build(sector, industry)
    assert with_revenue.components["stock_quality"] == _build().components["stock_quality"]  # with revenue: its sector's set
    assert with_revenue.components["stock_value"].score_10 is not None


# --- item 3 (F6): new metrics from SEC companyfacts fields -----------------------------------------------------------

from etf_cockpit.data import stock_fundamentals as store  # noqa: E402
from etf_cockpit.data import stock_sources as src  # noqa: E402

F6_FIELDS = {
    "gain_on_property_sales": 10.0, "real_estate_impairment": 5.0, "goodwill": 100.0, "intangibles_ex_goodwill": 50.0,
    "credit_loss_provision": 8.0, "loans_net": 1000.0, "net_interest_income": 40.0, "premiums_earned": 100.0,
    "claims_incurred": 60.0, "acquisition_cost_amortization": 25.0, "stock_based_compensation": 20.0,
}


def _f6(**overrides: float):
    return _build(periods=[_period(y, **{**F6_FIELDS, **overrides}) for y in (2021, 2022, 2023, 2024, 2025)]).metrics


@pytest.mark.parametrize(("key", "expected"), [
    ("ffo", 100.0 + 60.0 - 10.0 + 5.0),  # net income + D&A - gains on property sales + real-estate impairments
    ("ffo_yield", 155.0 / 500.0),
    ("ptbv", 500.0 / (900.0 - 100.0 - 50.0)),  # market cap / (equity - goodwill - other intangibles)
    ("rote", 100.0 / 750.0),  # net income / average tangible equity
    ("credit_cost", 8.0 / 1000.0),  # provisions / average net loans
    ("nii_to_assets", 40.0 / 2000.0),  # net interest income / average total assets
    ("combined_ratio", (60.0 + 25.0) / 100.0),  # (claims + acquisition-cost amortisation) / earned premiums
    ("gross_profitability", 400.0 / 2000.0),
    ("sbc_fcf_yield", (220.0 - 70.0 - 20.0) / 500.0),
])
def test_each_new_metric_from_its_fixture(key: str, expected: float) -> None:
    metric = _f6()[key]
    assert metric.available and metric.value == pytest.approx(expected) and metric.as_of == "2025-12-31"


def test_multi_year_averages_use_consecutive_fiscal_years() -> None:
    ebit = {2021: 100.0, 2022: 150.0, 2023: 200.0, 2024: 250.0, 2025: 300.0}
    cfo = {2021: 0.0, 2022: 0.0, 2023: 200.0, 2024: 220.0, 2025: 240.0}
    metrics = _build(periods=[_period(y, ebit=ebit[y], cfo=cfo[y]) for y in ebit]).metrics
    assert metrics["ebit_ev_yield_5y"].value == pytest.approx(200.0 / 700.0)  # mean EBIT / EV (500 + net debt 200)
    assert metrics["fcf_yield_3y"].value == pytest.approx(150.0 / 500.0)  # mean FCF of the last 3 years / market cap
    gap = _build(periods=[_period(y) for y in (2021, 2022, 2024, 2025)]).metrics
    assert not gap["ebit_ev_yield_5y"].available and not gap["fcf_yield_3y"].available  # never bridged over a missing year


def test_new_metrics_use_only_facts_filed_by_the_decision_date() -> None:
    periods = [_period(y, **F6_FIELDS) for y in (2021, 2022, 2023, 2024)]
    periods.append(_period(2025, known="2026-11-01", **{**F6_FIELDS, "real_estate_impairment": 500.0, "ebit": 9000.0}))
    metrics = _build(periods=periods).metrics
    assert metrics["ffo"].value == pytest.approx(155.0) and metrics["ffo"].as_of == "2024-12-31"
    assert metrics["ebit_ev_yield_5y"].as_of == "2024-12-31" and metrics["ebit_ev_yield_5y"].value == pytest.approx(200.0 / 700.0)


def test_a_missing_component_is_never_zero_filled() -> None:
    periods = [_period(y, **{k: v for k, v in F6_FIELDS.items() if k != "gain_on_property_sales"}) for y in (2021, 2022, 2023, 2024, 2025)]
    metrics = _build(periods=periods).metrics
    assert not metrics["ffo"].available and not metrics["ffo_yield"].available


def test_companyfacts_concepts_reach_the_period_fields() -> None:
    concepts = {"gain_on_property_sales": "GainsLossesOnSalesOfInvestmentRealEstate", "real_estate_impairment": "ImpairmentOfRealEstate",
                "credit_loss_provision": "ProvisionForLoanLeaseAndOtherLosses", "net_interest_income": "InterestIncomeExpenseNet",
                "premiums_earned": "PremiumsEarnedNet", "claims_incurred": "PolicyholderBenefitsAndClaimsIncurredNet",
                "acquisition_cost_amortization": "DeferredPolicyAcquisitionCostAmortizationExpense"}
    balances = {"intangibles_ex_goodwill": "IntangibleAssetsNetExcludingGoodwill", "loans_net": "LoansAndLeasesReceivableNetReportedAmount"}
    flow = lambda value: {"units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": value, "filed": "2026-02-10", "form": "10-K"}]}}  # noqa: E731
    instant = lambda value: {"units": {"USD": [{"end": "2025-12-31", "val": value, "filed": "2026-02-10", "form": "10-K"}]}}  # noqa: E731
    gaap = {"Revenues": flow(1000.0), "NetIncomeLoss": flow(100.0), "StockholdersEquity": instant(900.0)}
    gaap.update({concept: flow(float(i + 1)) for i, concept in enumerate(concepts.values())})
    gaap.update({concept: instant(float(i + 50)) for i, concept in enumerate(balances.values())})
    rows = src.parse_edgar_companyfacts({"entityName": "T", "facts": {"us-gaap": gaap}}, CONFIG, source_ref="test")
    fy = store._row_period(next(row for row in rows if row["period_type"] == "FY"), {})
    assert {name: fy.values.get(name) for name in concepts} == {name: float(i + 1) for i, name in enumerate(concepts)}
    assert {name: fy.values.get(name) for name in balances} == {name: float(i + 50) for i, name in enumerate(balances)}


@pytest.mark.parametrize(("sector", "industry", "inputs"), [
    ("Real Estate", "REIT - Industrial", ["ffo_yield", "dividend_yield"]),
    ("Energy", "Oil & Gas E&P", ["ebit_ev_yield_5y", "fcf_yield_3y"]),
    ("Materials", "Copper", ["ebit_ev_yield_5y", "fcf_yield_3y"]),
    ("Information Technology", "Software - Infrastructure", ["sbc_fcf_yield", "earnings_yield"]),
])
def test_new_value_inputs_are_wired_where_d_p3_names_them(sector: str, industry: str, inputs: list[str]) -> None:
    value = _build(sector, industry, [_period(y, **F6_FIELDS) for y in (2021, 2022, 2023, 2024, 2025)]).components["stock_value"]
    assert [item.key for item in value.inputs] == inputs and value.score_10 is not None


# --- correction pass (review 2026-11-23): currency and balance-sheet guards on ptbv / rote / nii_to_assets ----------

from dataclasses import replace  # noqa: E402


def test_rote_never_mixes_currencies() -> None:
    periods = [_period(y, **F6_FIELDS) for y in (2021, 2022, 2023, 2025)]
    periods.insert(3, replace(_period(2024, **F6_FIELDS), currency="USD"))  # the opening balance is in another currency
    rote = _build(periods=periods).metrics["rote"]
    assert not rote.available and "currency_mismatch" in str(rote.reason)


def test_a_blocked_balance_sheet_blocks_the_new_balance_ratios() -> None:
    metrics = _f6(cash_sti=5000.0)  # cash above total assets (2000): the anomaly guard blocks the matched ratios
    for key in ("ptbv", "rote", "nii_to_assets"):
        assert not metrics[key].available and "accounting anomaly" in str(metrics[key].reason), key


def test_a_tiny_tangible_equity_is_blocked_not_divided() -> None:
    metrics = _f6(intangibles_ex_goodwill=799.999)  # tangible equity 0.001 against total assets 2000
    for key in ("ptbv", "rote"):
        assert not metrics[key].available and "tiny_denominator" in str(metrics[key].reason), key
