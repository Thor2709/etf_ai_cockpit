"""Native regressions for issue 964, using only synthetic local evidence."""

from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.pages import stock_research as page
from etf_cockpit.data.capital_allocation import capital_allocation_analysis
from etf_cockpit.data.market_calendar import ListingCalendarEvidence
from test_capital_allocation import DECISION, _analyse, _coverage, _fact, _split, _statements


def _market(**changes):
    return {
        "market_cap": 1000.0,
        "market_cap_at": "2025-12-31",
        "market_cap_effective_at": "2025-12-31T21:00:00Z",
        "market_cap_known_at": "2026-01-01T00:00:00Z",
        "market_cap_source_id": "fixture-close",
        "source_id": "fixture-close",
        "currency": "USD",
        "listing_calendar_evidence": _calendar(),
    } | changes


def _calendar():
    return ListingCalendarEvidence(
        listing_id="fixture-acme-listing", instrument_id="ACME", mic="XNYS",
        calendar_id="XNYS", timezone="America/New_York", source_id="fixture-calendar",
        source_checksum="0" * 64, valid_from=date(2020, 1, 1),
        known_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("known", ["2027-01-01T00:00:00Z", None, "bad", "2026-01-01"])
def test_b007_n001_market_cap_requires_verifiable_eligible_knowledge_time(known):
    result = _analyse(market_inputs=_market(market_cap_known_at=known))
    for name in ("dividend_yield", "buyback_yield", "issuance_dilution_yield", "shareholder_yield"):
        metric = result["metrics"][name]
        assert metric["value"] is None
        assert metric["status"] == "unavailable"
        assert metric["limitation"]
    assert result["metrics"]["shareholder_yield"]["source_timing_status"] == "unavailable"
    assert result["execution_allowed"] is False


def test_b007_n002_stock_dividend_quantity_factor_is_normalised():
    frame = _statements()
    frame.loc[frame["fiscal_year"].eq(2025) & frame["canonical_metric"].eq("shares_outstanding"), "value"] = 110.0
    action = replace(_split(), action_type="stock_dividend", ratio=1.1)
    result = _analyse(frame, corporate_actions=(action,), corporate_action_coverage=_coverage())
    metric = result["metrics"]["basic_share_count_change"]
    assert metric["value"] == pytest.approx(0.0)
    assert metric["denominator_value"] == pytest.approx(110.0)
    assert "corporate_action:stock_dividend" in {item["canonical_metric"] for item in metric["source_provenance"]}


def test_b007_n003_diluted_eps_shares_do_not_enter_issuance_identity():
    frame = _statements()
    frame.loc[frame["fiscal_year"].eq(2025) & frame["canonical_metric"].eq("diluted_shares"), "value"] = 120.0
    result = _analyse(frame, corporate_action_coverage=_coverage())
    check = next(item for item in result["reconciliations"] if item["name"] == "share_count_roll_forward")
    assert check["status"] == "passed"
    assert check["value"] == 0.0
    assert not any(source.startswith("diluted_shares") for source in check["source_ids"])
    assert result["metrics"]["diluted_share_count_change"]["value"] == pytest.approx(120 / 110 - 1)


def test_b107_n001_stock_research_forwards_existing_market_and_action_inputs(monkeypatch):
    market = _market()
    actions, coverage = (_split(),), _coverage()
    statements = _statements()
    context = {"statements": statements, "decision_time": DECISION, "valuation_market_inputs": market,
               "corporate_actions": actions, "corporate_action_coverage": coverage}
    captured = {}
    monkeypatch.setattr(page, "load_stock_research_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(page, "load_optional_research_import", lambda *args, **kwargs: {})
    monkeypatch.setattr(page, "build_stock_research_report", lambda *args, **kwargs: {"valuation": {}})
    monkeypatch.setattr(page, "_valuation_panel", lambda *args, **kwargs: ft.Container())

    def capture(frame, **kwargs):
        assert frame is statements
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(page, "load_capital_allocation_analysis", capture)
    page._fundamentals(SimpleNamespace(), SimpleNamespace(snapshot=None), "ACME", "Valuation")
    assert captured["market_inputs"]["market_cap"] == 1000.0
    assert captured["corporate_actions"] is actions
    assert captured["corporate_action_coverage"] is coverage
    assert captured["decision_time"] == DECISION


def test_b107_n002_annual_is_headline_when_q4_has_same_end():
    quarter = _fact(2025, "cash_from_operations", 7.0)
    quarter.update(period_type="quarterly", period_key="2025-Q4", fiscal_period="Q4", start="2025-10-01")
    result = _analyse(pd.concat([_statements(), pd.DataFrame([quarter])], ignore_index=True))
    assert result["coverage"]["latest_period"] == "FY2025"
    assert result["metrics"]["free_cash_flow"]["value"] == 95.0
    assert any(row["period"] == "2025-Q4" for row in result["history"])


def test_b107_n003_sunday_year_end_uses_friday_close():
    frame = _statements()
    frame = frame.loc[frame["fiscal_year"].eq(2023)].copy()
    frame = pd.concat([frame, pd.DataFrame([_fact(2023, metric, value) for metric, value in
                                          (("dividends", 15), ("gross_buybacks", 15), ("equity_issuance", 10))])])
    market = _market(market_cap_at="2023-12-29", market_cap_effective_at="2023-12-29T21:00:00Z",
                     market_cap_known_at="2023-12-30T00:00:00Z", listing_calendar_evidence=_calendar())
    metric = _analyse(frame, market_inputs=market)["metrics"]["shareholder_yield"]
    assert metric["value"] == 0.02
    assert metric["market_input_date"] == "2023-12-29"


def test_b07_c2_n001_annual_flows_use_annual_opening_balance_not_q3():
    quarter = _fact(2025, "cash_from_operations", 30.0)
    quarter.update(period_type="quarterly", period_key="2025-Q3", fiscal_period="Q3",
                   start="2025-07-01", end="2025-09-30", period_end="2025-09-30")
    point = _fact(2025, "shares_outstanding", 118.0, instant=True)
    point.update(period_key="instant:2025-09-30", end="2025-09-30", instant="2025-09-30", period_end="2025-09-30")
    frame = _statements()
    frame.loc[frame["fiscal_year"].eq(2025) & frame["canonical_metric"].eq("shares_outstanding"), "value"] = 120.0
    result = _analyse(pd.concat([frame, pd.DataFrame([quarter, point])], ignore_index=True), corporate_action_coverage=_coverage())
    assert result["metrics"]["basic_share_count_change"]["value"] == pytest.approx(0.20)
    assert result["metrics"]["basic_share_count_change"]["denominator_value"] == 100.0
    cash = next(item for item in result["reconciliations"] if item["name"] == "cash_balance_change")
    assert cash["status"] == "passed"


def test_b07_c2_n002_unscoped_instrument_cannot_apply_another_instruments_split():
    result = capital_allocation_analysis(_statements(), as_known_at=DECISION,
                                        corporate_actions=(_split(),), corporate_action_coverage=_coverage())
    metric = result["metrics"]["basic_share_count_change"]
    assert metric["value"] is None
    assert metric["limitation"]


@pytest.mark.parametrize("changes", [
    {"market_cap_effective_at": "invalid"},
    {"market_cap_effective_at": "2027-01-01T21:00:00Z"},
    {"market_cap_effective_at": "2025-12-30T21:00:00Z"},
    {"market_cap_known_at": "2025-12-31T20:00:00Z"},
    {"market_cap_source_id": None, "source_id": None},
    {"market_cap_source_provenance": [
        {"source_id": "fixture-close", "effective_at": "2025-12-31T21:00:00Z", "known_at": "2027-01-01T00:00:00Z"}]},
    {"market_cap_source_provenance": [
        {"source_id": "fixture-close", "effective_at": "bad", "known_at": "2026-01-01T00:00:00Z"}]},
    {"market_cap_source_provenance": []},
    {"market_cap_source_provenance": "invalid"},
    {"market_cap_source_provenance": [
        {"source_id": "fixture-close", "effective_at": "2025-12-31T21:00:00Z", "known_at": "2026-01-01T00:00:00Z"}, None]},
    {"instrument_id": "OTHER"},
])
def test_market_timing_is_invalid_or_conflicted_then_yields_fail_closed(changes):
    result = _analyse(market_inputs=_market(**changes))
    assert result["metrics"]["shareholder_yield"]["value"] is None
    assert result["metrics"]["shareholder_yield"]["source_timing_status"] == "unavailable"
    assert result["metrics"]["shareholder_yield"]["limitation"]


def test_market_knowledge_at_decision_is_eligible():
    result = _analyse(market_inputs=_market(market_cap_known_at=DECISION))
    assert result["metrics"]["shareholder_yield"]["value"] == 0.02
    assert result["metrics"]["shareholder_yield"]["source_timing_status"] == "available"


@pytest.mark.parametrize("known", ["2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z", None])
def test_share_price_fallback_has_same_knowledge_gate(known):
    market = {"share_price": 10.0, "share_price_at": "2025-12-31", "currency": "USD",
              "share_price_effective_at": "2025-12-31T21:00:00Z", "share_price_known_at": known,
              "source_id": "fixture-price", "listing_calendar_evidence": _calendar()}
    metric = _analyse(market_inputs=market)["metrics"]["shareholder_yield"]
    if known == "2026-01-01T00:00:00Z":
        assert metric["value"] == 0.02
    else:
        assert metric["value"] is None
        assert metric["source_timing_status"] == "unavailable"


@pytest.mark.parametrize("date_text", ["2023-12-28", "2023-12-31", "2024-01-01"])
def test_verified_calendar_rejects_stale_nontrading_or_future_close(date_text):
    frame = pd.DataFrame([_fact(2023, metric, value) for metric, value in
                          (("dividends", 15), ("gross_buybacks", 15), ("equity_issuance", 10))])
    market = _market(market_cap_at=date_text, market_cap_effective_at=f"{date_text}T21:00:00Z",
                     market_cap_known_at="2024-01-02T00:00:00Z", listing_calendar_evidence=_calendar())
    assert _analyse(frame, market_inputs=market)["metrics"]["shareholder_yield"]["value"] is None


@pytest.mark.parametrize("calendar", [None, "XNYS", replace(_calendar(), instrument_id="OTHER"),
                                      replace(_calendar(), known_at=datetime(2027, 1, 1, tzinfo=timezone.utc))])
def test_prior_close_requires_verifiable_scoped_calendar(calendar):
    frame = pd.DataFrame([_fact(2023, metric, value) for metric, value in
                          (("dividends", 15), ("gross_buybacks", 15), ("equity_issuance", 10))])
    market = _market(market_cap_at="2023-12-29", market_cap_effective_at="2023-12-29T21:00:00Z",
                     market_cap_known_at="2024-01-02T00:00:00Z", listing_calendar_evidence=calendar)
    assert _analyse(frame, market_inputs=market)["metrics"]["shareholder_yield"]["value"] is None


def test_existing_calendar_handles_holiday_before_weekend_fiscal_end():
    rows = [_fact(2021, metric, value) for metric, value in
            (("dividends", 15), ("gross_buybacks", 15), ("equity_issuance", 10))]
    for row in rows:
        row.update(end="2021-12-25", period_end="2021-12-25")
    market = _market(market_cap_at="2021-12-23", market_cap_effective_at="2021-12-23T21:00:00Z",
                     market_cap_known_at="2021-12-24T00:00:00Z", listing_calendar_evidence=_calendar())
    assert _analyse(pd.DataFrame(rows), market_inputs=market)["metrics"]["shareholder_yield"]["value"] == 0.02


@pytest.mark.parametrize("ratio", [None, 0.0, -1.0, float("nan")])
def test_stock_dividend_missing_or_invalid_factor_is_unavailable(ratio):
    action = replace(_split(), action_type="stock_dividend", ratio=ratio)
    metric = _analyse(corporate_actions=(action,), corporate_action_coverage=_coverage())["metrics"]["basic_share_count_change"]
    assert metric["value"] is None
    assert metric["limitation"]


def test_other_instrument_actions_are_excluded_when_scope_is_known():
    foreign = replace(_split(), instrument_id="OTHER")
    metric = _analyse(corporate_actions=(foreign,), corporate_action_coverage=_coverage())["metrics"]["basic_share_count_change"]
    assert metric["value"] == 0.0
    assert "split-filing" not in metric["source_ids"]


def test_share_identity_does_not_require_diluted_eps_share_evidence():
    frame = _statements().loc[lambda rows: ~rows["canonical_metric"].eq("diluted_shares")]
    result = _analyse(frame, corporate_action_coverage=_coverage())
    check = next(item for item in result["reconciliations"] if item["name"] == "share_count_roll_forward")
    assert check["status"] == "passed"


def test_annual_opening_balance_can_be_standalone_instant_without_prior_flow():
    frame = _statements().loc[lambda rows: rows["fiscal_year"].eq(2025) | rows["period_type"].eq("instant")]
    metric = _analyse(frame, corporate_action_coverage=_coverage())["metrics"]["basic_share_count_change"]
    assert metric["value"] == 0.0
    assert metric["denominator_value"] == 100.0


@pytest.mark.parametrize("start", [None, "bad", "2025-01-02"])
def test_missing_or_unmatched_opening_date_never_substitutes_another_balance(start):
    frame = _statements()
    frame.loc[frame["fiscal_year"].eq(2025) & frame["period_type"].eq("annual"), "start"] = start
    metric = _analyse(frame, corporate_action_coverage=_coverage())["metrics"]["basic_share_count_change"]
    assert metric["value"] is None
    assert metric["limitation"]


def test_ttm_beats_same_end_q4_when_fy_is_absent():
    frame = _statements()
    latest = frame["fiscal_year"].eq(2025) & frame["period_type"].eq("annual")
    frame.loc[latest, ["period_type", "period_key", "fiscal_period"]] = ["ttm", "TTM2025", "TTM"]
    quarter = _fact(2025, "cash_from_operations", 7.0)
    quarter.update(period_type="quarterly", period_key="2025-Q4", fiscal_period="Q4", start="2025-10-01")
    result = _analyse(pd.concat([frame, pd.DataFrame([quarter])], ignore_index=True))
    assert result["coverage"]["latest_period"] == "2025-TTM"
    assert result["metrics"]["free_cash_flow"]["value"] == 95.0


def test_weekday_holiday_is_not_a_verified_close_without_calendar():
    rows = [_fact(2021, metric, value) for metric, value in
            (("dividends", 15), ("gross_buybacks", 15), ("equity_issuance", 10))]
    for row in rows:
        row.update(end="2021-12-24", period_end="2021-12-24")
    market = _market(market_cap_at="2021-12-24", market_cap_effective_at="2021-12-24T21:00:00Z",
                     market_cap_known_at="2021-12-25T00:00:00Z", listing_calendar_evidence=None)
    metric = _analyse(pd.DataFrame(rows), market_inputs=market)["metrics"]["shareholder_yield"]
    assert metric["value"] is None
    assert metric["status"] == "unavailable"


@pytest.mark.parametrize("name", ["source_provenance", "price_source_ids"])
def test_market_provenance_containers_and_source_aliases_cannot_hide_conflicts(name):
    market = {"share_price": 10.0, "share_price_at": "2025-12-31", "currency": "USD",
              "share_price_effective_at": "2025-12-31T21:00:00Z",
              "share_price_known_at": "2026-01-01T00:00:00Z", "source_id": "fixture-price",
              "listing_calendar_evidence": _calendar(),
              "share_price_source_provenance": [{"source_id": "fixture-price", "effective_at": "2025-12-31T21:00:00Z", "known_at": "2026-01-01T00:00:00Z"}]}
    market[name] = "malformed" if name == "source_provenance" else ("conflicting-price-source",)
    metric = _analyse(market_inputs=market)["metrics"]["shareholder_yield"]
    assert metric["value"] is None
    assert metric["status"] == "unavailable"


@pytest.mark.parametrize("retraction_known", ["2025-07-01T00:00:00Z", "2027-01-01T00:00:00Z"])
def test_stock_dividend_retraction_is_resolved_at_decision_time(retraction_known):
    original = replace(_split(), action_type="stock_dividend", ratio=1.1)
    retracted = replace(original, revision=2, status="retracted", known_at=retraction_known)
    metric = _analyse(corporate_actions=(original, retracted), corporate_action_coverage=_coverage())["metrics"]["basic_share_count_change"]
    if retraction_known.startswith("2027"):
        assert metric["value"] == pytest.approx(100 / 110 - 1)
    else:
        # Known retraction must never leave the old factor active: zero change or
        # explicit unavailability are both valid canonical resolution outcomes.
        assert metric["value"] is None or metric["value"] == 0.0
