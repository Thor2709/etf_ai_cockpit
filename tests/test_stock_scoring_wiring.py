"""The stock score uses the canonical fundamentals components and never zero-fills a missing one."""

from __future__ import annotations

from datetime import date, datetime, timezone

from etf_cockpit.analysis.stock_evidence import AnalystInputs, MarketInputs, build_stock_evidence
from etf_cockpit.analysis.stock_universe import live_decision_time
from etf_cockpit.data.stock_fundamentals import load_stock_config
from etf_cockpit.signals import simple_scores as ss
from tests.test_stock_evidence import _period

UTC = timezone.utc
DECISION = datetime(2026, 10, 9, 12, tzinfo=UTC)


def _evidence(analyst: AnalystInputs | None = None):
    periods = [_period(year) for year in (2022, 2023, 2024, 2025)]
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8))
    return build_stock_evidence("T", periods, DECISION, market, analyst, load_stock_config())


def test_stock_components_are_score_eligible_with_filing_provenance() -> None:
    components = {c.key: c for c in ss._stock_fundamental_components(_evidence())}
    value, quality = components["stock_value"], components["stock_quality"]
    assert value.score_10 is not None and quality.score_10 is not None
    assert value.score_eligible and quality.score_eligible
    assert quality.source_id == "sec_edgar:fundamentals" and quality.source_authority == "official_regulator"
    assert "ROE" in quality.why and "inputs" in quality.why


def test_missing_fundamentals_stay_out_of_the_score_and_name_the_reason() -> None:
    components = ss._stock_fundamental_components(None, "stock fundamentals could not be evaluated (OSError: disk)")
    assert all(c.score_10 is None and not c.score_eligible for c in components)
    assert all("could not be evaluated" in c.why for c in components)
    analyst = {c.key: c for c in ss._stock_fundamental_components(_evidence())}["analyst_revision"]
    assert analyst.score_10 is None and "no analyst estimate snapshot" in analyst.why  # not zero, not neutral


def test_composite_uses_available_components_and_reports_coverage() -> None:
    base = [ss._component("momentum", 0.4, "m", authority="high"), ss._component("trend", 0.2, "t", authority="high")]
    base = [ss.replace(c, as_of_date="2026-10-08", freshness_status="ok") for c in base]
    with_fundamentals = [*base, *ss._stock_fundamental_components(_evidence())]
    without = [*base, *ss._stock_fundamental_components(None)]
    score_with = ss.combine_component_scores(with_fundamentals, ss.STOCK_EVIDENCE_WEIGHTS)[1]
    score_without = ss.combine_component_scores(without, ss.STOCK_EVIDENCE_WEIGHTS)[1]
    assert score_without is not None and score_with is not None and score_with != score_without
    eligible = [c for c in with_fundamentals if c.score_eligible]
    assert {"stock_value", "stock_quality"} <= {c.key for c in eligible}


def test_live_decision_time_is_now_for_current_data_and_end_of_day_for_a_replay() -> None:
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    assert live_decision_time(date(2026, 10, 8), now) == now
    replay = live_decision_time(date(2026, 3, 2), now)
    assert replay == datetime(2026, 3, 2, 23, 59, 59, tzinfo=UTC)
