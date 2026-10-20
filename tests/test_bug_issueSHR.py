"""#SHR: short-history fundamentals are shrunk toward the cohort median (n / (n + k)); score uncertainty bands."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis.peer_cohorts import bootstrap_percentile_interval, weighted_empirical_cdf
from etf_cockpit.analysis.stock_evidence import (
    MarketInputs,
    band_is_label_stable,
    build_stock_evidence,
)
from etf_cockpit.data.stock_fundamentals import load_stock_config
from etf_cockpit.signals import simple_scores as ss

UTC = timezone.utc
DECISION = datetime(2026, 10, 9, tzinfo=UTC)
CONFIG = load_stock_config()


def _period(year: int, *, roic_scale: float = 1.0, **overrides: float) -> sm.Period:
    values = {
        "revenue": 1000.0,
        "gross_profit": 400.0,
        "ebit": 200.0 * roic_scale,
        "da": 60.0,
        "pretax_income": 180.0,
        "income_tax": 45.0,
        "net_income_parent": 100.0,
        "cfo": 220.0,
        "capex": 70.0,
        "dividends_paid": 30.0,
        "equity_parent": 900.0,
        "minority_interest": 0.0,
        "ib_debt": 300.0,
        "lease_liabilities": 50.0,
        "cash_sti": 150.0,
        "shares_outstanding": 10.0,
    }
    values.update(overrides)
    known_at = datetime.fromisoformat(f"{year + 1}-02-15").replace(tzinfo=UTC)
    return sm.Period(date(year, 12, 31), "FY", known_at, "EUR", "sec_edgar", values)


def _evidence(years: tuple[int, ...], cohorts, config=CONFIG, **overrides: float):
    periods = [_period(y, **overrides) for y in years]
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8))
    return build_stock_evidence("T", periods, DECISION, market, None, config, cohort_values=cohorts)


def _sub(ev, key: str):
    return next(s for s in ev.components["stock_quality"].inputs if s.key == key)


def _cohort(metric: str, median: float, peers: int = 7, spread: float = 0.01):
    return {"sector": {metric: {f"P{i}": median + spread * (i - peers // 2) for i in range(peers)}}}


def test_one_observation_roic_is_pulled_toward_the_sector_median() -> None:
    ev = _evidence((2025,), _cohort("roic", 0.12), ebit=900.0, pretax_income=900.0, income_tax=0.0)
    roic = _sub(ev, "roic")
    assert roic.raw_value is not None and roic.raw_value > 0.30
    k = float(CONFIG["scoring"]["shrinkage"]["k"])
    assert k == 4 and roic.observations == 1
    weight = 1 / (1 + k)
    assert roic.shrink_weight == pytest.approx(weight)
    assert roic.shrunk_value == pytest.approx(weight * roic.raw_value + (1 - weight) * 0.12)
    assert 0.12 < roic.shrunk_value < roic.raw_value
    assert roic.value == roic.raw_value  # the stored estimate stays raw; the score used the shrunk value
    peers = list(_cohort("roic", 0.12)["sector"]["roic"].values())
    assert roic.score == pytest.approx(10.0 * weighted_empirical_cdf(peers, [1.0] * len(peers), roic.shrunk_value))


def test_many_observations_leave_the_shrunk_value_close_to_raw() -> None:
    config = {**CONFIG, "scoring": {**CONFIG["scoring"], "shrinkage": {**CONFIG["scoring"]["shrinkage"], "k": 4}}}
    periods = [_period(y) for y in range(2005, 2026)]  # 21 annual observations
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 10, 8))
    ev = build_stock_evidence("T", periods, DECISION, market, None, config, cohort_values=_cohort("roe", 0.05))
    roe = _sub(ev, "roe")
    assert roe.observations == 21
    assert roe.shrink_weight == pytest.approx(21 / 25)
    assert abs(roe.shrunk_value - roe.raw_value) < 0.2 * abs(roe.raw_value - 0.05)
    n = 4000
    assert n / (n + 4) > 0.999


def test_missing_cohort_median_makes_the_input_unavailable_not_invented() -> None:
    ev = _evidence((2022, 2023, 2024, 2025), {"sector": {"roic": {}}, "universe": {}})
    roic = _sub(ev, "roic")
    assert roic.score is None and roic.shrunk_value is None
    assert "needs 3 peers" in (roic.reason or "")
    assert roic.value is not None  # the raw estimate stays visible

    without_cohort = _sub(_evidence((2022, 2023, 2024, 2025), None), "roic")
    assert without_cohort.score is None and without_cohort.shrunk_value is None
    assert "cohort median" in (without_cohort.reason or "")


def test_band_crossing_a_label_boundary_sets_label_stable_false() -> None:
    boundaries = CONFIG["scoring"]["uncertainty"]["label_boundaries"]
    assert boundaries == [4.0, 5.0, 6.5, 8.0]
    assert band_is_label_stable(5.2, 6.0, boundaries) is True
    assert band_is_label_stable(4.6, 5.4, boundaries) is False
    assert band_is_label_stable(5.0, 6.4, boundaries) is True  # score 5.0 already carries the 5.0 label
    assert band_is_label_stable(6.4, 6.5, boundaries) is False


def test_headline_band_is_informational_and_flags_unstable_labels() -> None:
    def component(key: str, score: float, low: float | None, high: float | None):
        raw = (score - 5.0) / 5.0
        return ss.SimpleScoreComponent(
            key=key, label=key, score_10=score, raw_score=raw, status="OK", explanation="", good_score="", why="",
            source_id="sec_edgar:fundamentals", as_of_date="2026-09-30", freshness_status="ok",
            band_low=low, band_high=high,
        )

    weights = {"stock_value": 0.5, "stock_quality": 0.5}
    boundaries = (4.0, 5.0, 6.5, 8.0)
    wide = [component("stock_value", 6.0, 3.0, 8.0), component("stock_quality", 6.0, 4.0, 8.0)]
    low, high, stable, basis = ss.headline_score_band(wide, weights, 6.0, boundaries)
    assert (low, high) == (3.5, 8.0) and stable is False and "2 of 2" in basis
    narrow = [component("stock_value", 6.0, 5.6, 6.2), component("stock_quality", 6.0, 5.8, 6.3)]
    low, high, stable, _ = ss.headline_score_band(narrow, weights, 6.0, boundaries)
    assert low <= 6.0 <= high and stable is True
    # no component carries a band: no band is invented
    assert ss.headline_score_band([component("stock_value", 6.0, None, None)], weights, 6.0, boundaries) is None
    # partial or unverifiable component bands make the headline band unavailable instead of silently holding that component at its point
    assert ss.headline_score_band([component("stock_value", 6.0, 5.6, None)], weights, 6.0, boundaries) is None
    assert ss.headline_score_band([component("stock_value", 6.0, -1.0, 8.0)], weights, 6.0, boundaries) is None


def test_bands_never_change_the_score_and_contain_it() -> None:
    cohorts = {"sector": {m: {f"P{i}": 0.05 + 0.02 * i for i in range(7)} for m in ("roe", "roic", "ebit_margin", "fcf_conversion", "revenue_cagr")}}
    base = _evidence((2022, 2023, 2024, 2025), cohorts)
    no_unc = {**CONFIG, "scoring": {**CONFIG["scoring"], "uncertainty": {"bootstrap_samples": 5, "lower_quantile": 0.0, "upper_quantile": 1.0}}}
    other = _evidence((2022, 2023, 2024, 2025), cohorts, config=no_unc)
    quality, quality_other = base.components["stock_quality"], other.components["stock_quality"]
    assert quality.score_10 == quality_other.score_10  # band settings never move the score
    for item in quality.used:
        if item.band_low is not None:
            assert item.band_low <= item.score <= item.band_high
    assert quality.band_low is not None and quality.band_low <= quality.score_10 <= quality.band_high
    assert quality.label_stable in (True, False)


def test_stock_component_and_headline_bands_reach_the_scoreboard() -> None:
    cohorts = {
        "sector": {
            metric: {f"P{i}": 0.05 + 0.02 * i for i in range(7)}
            for metric in ("roe", "roic", "ebit_margin", "fcf_conversion", "revenue_cagr", "earnings_yield", "fcf_yield", "ebit_ev_yield", "pe")
        }
    }
    evidence = _evidence((2022, 2023, 2024, 2025), cohorts)
    components = ss._stock_fundamental_components(evidence)
    quality = next(component for component in components if component.key == "stock_quality")
    assert quality.band_low is not None and quality.band_high is not None
    assert quality.band_low <= quality.score_10 <= quality.band_high
    assert quality.label_stable in (True, False)
    _, headline = ss.combine_component_scores(components, ss.headline_evidence_weights("STOCK"))
    assert headline is not None
    score = ss.SimpleInstrumentScore(
        instrument_key="configured:T",
        display_id="T",
        source_group="primary",
        asset_type="STOCK",
        name="T",
        yahoo_symbol="T",
        latest_date="2026-10-08",
        latest_price=50.0,
        final_score_10=headline,
        decision="Manual Review",
        one_line_reason="local test evidence",
        components=components,
        warnings=[],
        evidence_score_10=headline,
    )
    published = ss._with_score_band(score)
    assert published.final_score_10 == score.final_score_10
    assert published.score_band_low is not None and published.score_band_high is not None
    assert published.label_stable in (True, False)
    assert published.execution_allowed is False
    row = ss.simple_scoreboard_frame([published]).iloc[0]
    assert row["score_band_low"] == published.score_band_low
    assert row["score_band_high"] == published.score_band_high
    assert row["stock_quality_band_low"] == quality.band_low
    assert row["stock_quality_band_high"] == quality.band_high
    assert row["stock_quality_label_stable"] == quality.label_stable
    capped = ss._with_score_band(replace(score, final_score_10=3.2))
    assert capped.score_band_low <= 3.2 <= capped.score_band_high
    assert capped.score_band_basis == published.score_band_basis


def test_legacy_callers_without_cohorts_fail_closed_for_shrinkable_inputs() -> None:
    ev = _evidence((2022, 2023, 2024, 2025), None)
    roe = _sub(ev, "roe")
    assert roe.score is None and roe.shrunk_value is None and roe.band_low is None
    assert "cohort median" in (roe.reason or "")
    assert ev.components["stock_quality"].label_stable is None


def test_bootstrap_quantiles_default_to_the_95_percent_interval() -> None:
    values, weights = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [1.0] * 6
    kwargs = dict(parent_percentile=0.5, shrinkage_strength=0.0, seed=7, samples=200)
    wide = bootstrap_percentile_interval(values, weights, 3.5, **kwargs)
    p1090 = bootstrap_percentile_interval(values, weights, 3.5, lower_quantile=0.1, upper_quantile=0.9, **kwargs)
    assert wide[0] <= p1090[0] <= p1090[1] <= wide[1]
    with pytest.raises(ValueError):
        bootstrap_percentile_interval(values, weights, 3.5, lower_quantile=0.9, upper_quantile=0.1, **kwargs)


def test_label_boundaries_match_final_label_from_scores() -> None:
    labels = [ss.final_label_from_scores(score, 9.0, 9.0, warnings=[])[0] for score in (3.9, 4.0, 4.9, 5.0, 6.4, 6.5, 7.9, 8.0)]
    flips = [i for i in range(1, len(labels)) if labels[i] != labels[i - 1]]
    assert [(3.9, 4.0, 4.9, 5.0, 6.4, 6.5, 7.9, 8.0)[i] for i in flips] == [4.0, 5.0, 6.5, 8.0]
