"""Verified A03 regressions and owner decisions D2, D3, D11 and D12."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace as N

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.core.research_states import (
    AuthorityDecision, GateResult, GateSeverity, InternalSignalIntent,
    ResearchState, ScoreComponent, resolve_research_state,
)
from etf_cockpit.core.types import ComponentScores, SignalResult
from etf_cockpit.signals.actions import preliminary_action
from etf_cockpit.signals.canonical_scoring import (
    CanonicalComponent, CanonicalScoreError, build_canonical_score,
    canonical_score_from_signal_row, load_score_policy,
)
from etf_cockpit.signals.feature_drivers import build_feature_drivers
from etf_cockpit.signals.scoring import component_scores


def test_resolver_allows_passed_blocker_and_ignores_zero_headline_weights():
    decision = AuthorityDecision(
        analysis_status="complete", research_state=ResearchState.RESEARCH_CANDIDATE,
        research_promotion_allowed=True,
        gates=(GateResult(gate_id="dq", severity=GateSeverity.BLOCKER, passed=True),),
    )
    evidence = ScoreComponent("momentum", score=0.8, source_id="yfinance:prices")
    optional = [ScoreComponent(key, status="unavailable") for key in (
        "toto", "timesfm", "baseline", "etf_exposure", "etf_product_quality", "relative_strength",
    )]
    assert resolve_research_state([evidence, *optional], decision) is ResearchState.RESEARCH_CANDIDATE
    stock_optional = [ScoreComponent("analyst_revision", status="unavailable")]
    assert resolve_research_state([evidence, *stock_optional], decision, asset_type="STOCK") is ResearchState.RESEARCH_CANDIDATE
    for severity in GateSeverity:
        failed = decision.model_copy(update={"gates": (GateResult(gate_id="dq", severity=severity, passed=False),)})
        assert resolve_research_state([evidence], failed) is ResearchState.NOT_SCOREABLE
    for status, value in (("unavailable", None), ("failed", None), ("ok", float("nan"))):
        required = ScoreComponent("risk", status=status, score=value)
        assert resolve_research_state([evidence, required], decision) is ResearchState.NOT_SCOREABLE
    non_positive = decision.model_copy(update={"research_state": ResearchState.AVOID})
    assert resolve_research_state([ScoreComponent("risk", status="unavailable")], non_positive) is ResearchState.AVOID
    assert decision.execution_allowed is False


def _signal_row():
    return {
        "etf_id": "X", "price_freshness": "ok", "score_momentum": 0.4,
        "score_trend": 0.2, "score_risk": 0.3, "score_etf_exposure": 0.2,
        "cost_penalty": 0.01,
    }


def test_certificate_and_universe_ec_routing():
    config = N(models=N(ensemble={"weights": {"momentum": 0.5, "risk": 0.5}}))
    for kind in ("equity_certificate", "equity certificate", "egenkapitalbevis", "ec"):
        for field in ("asset_type", "instrument_type", "instrument_subtype", "capital_class"):
            with pytest.raises(CanonicalScoreError, match="native Sparebank"):
                canonical_score_from_signal_row({**_signal_row(), field: kind}, config, "2026-10-20")
        configured = N(models=config.models, universe=N(by_id=lambda: {"X": N(instrument_type=kind)}))
        # Even a generic row declaration cannot hide a configured EC identity.
        with pytest.raises(CanonicalScoreError, match="native Sparebank"):
            canonical_score_from_signal_row({**_signal_row(), "asset_type": "stock"}, configured, "2026-10-20")
    for row_declared in (True, False):
        certificate_config = N(models=config.models, universe=N(by_id=lambda: {"X": N(instrument_type="certificate")}))
        row = {**_signal_row(), **({"asset_type": "certificate"} if row_declared else {})}
        score = canonical_score_from_signal_row(row, certificate_config, "2026-10-20")
        assert score.asset_type == "CERTIFICATE"
        fundamentals = [item for item in score.components if item["key"] in {"stock_value", "stock_quality"}]
        # Zero-weight fundamentals are omitted from the canonical group rows.
        assert fundamentals == []
        supplied = canonical_score_from_signal_row({**row, "score_stock_value": 0.5, "score_stock_quality": 0.6}, certificate_config, "2026-10-20")
        assert all(item["weight"] > 0 for item in supplied.components if item["key"] in {"stock_value", "stock_quality"})


def test_signal_row_stock_quality_completeness():
    config = load_config()
    row = {**_signal_row(), "asset_type": "stock", "score_stock_value": 0.4, "score_stock_quality": 0.6}
    complete = canonical_score_from_signal_row(row, config, "2026-10-20")
    partial = canonical_score_from_signal_row({**row, "quality_status": "partial"}, config, "2026-10-20")
    missing = canonical_score_from_signal_row({**row, "score_stock_quality": float("nan")}, config, "2026-10-20")
    quality = next(item for item in complete.components if item["key"] == "stock_quality")
    assert quality["status"] == "ok" and quality["score_eligible"] is True
    assert quality["raw_metric"] == 0.6
    # Other critical evidence is deliberately absent, so the group is still
    # withheld. Quality now counts toward pre-gate coverage and remains eligible.
    assert complete.unavailable_reason is None
    assert partial.unavailable_reason == "insufficient_coverage"
    for score in (partial, missing):
        quality = next(item for item in score.components if item["key"] == "stock_quality")
        assert quality["score_eligible"] is False
    assert next(item for item in missing.components if item["key"] == "stock_quality")["raw_metric"] is None


def test_analyst_revision_disabled_and_stock_weights_rescaled_pro_rata():
    weights = load_score_policy("STOCK").headline_weights
    assert weights["analyst_revision"] == 0.0
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["momentum"] == 0.1742 and weights["trend"] == 0.1258
    for key, previous in {"risk": 0.1615, "liquidity_cost": 0.1346, "stock_value": 0.1615, "stock_quality": 0.175}.items():
        assert weights[key] == pytest.approx(previous * 0.70 / 0.6326, abs=0.0000000001)


def test_composites_use_one_available_weight_rule_and_require_two_families():
    config = load_config()
    weights = {"momentum": 0.2, "trend": 0.1, "risk": 0.3, "baseline_ml": 0.4, "relative_strength": 0.0}
    config.models.ensemble["weights"] = weights
    features = pd.DataFrame([
        {"etf_id": key, "momentum_20d": 0.01 * scale, "momentum_60d": 0.02 * scale,
         "momentum_120d": 0.03 * scale, "momentum_180d": 0.04 * scale,
         "trend_slope": 0.01 * scale, "trend_100": 1.0, "trend_200": 1.0,
         "vol_60d_ann": 0.2 * scale, "ewma_vol_ann": 0.2 * scale, "relative_strength_60d": 0.02 * scale}
        for key, scale in (("AAA", 1), ("BBB", 2), ("CCC", 3))
    ])
    allocation = pd.DataFrame([
        {"etf_id": key, "current_weight": 0.0, "target_weight": 0.0,
         "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}
        for key in features.etf_id
    ])
    for forecasts, active in (({"baseline": {key: 0.8 for key in features.etf_id}}, tuple(weights)[:4]), ({}, tuple(weights)[:3])):
        scored = component_scores(features, allocation, config, forecast_scores=forecasts)
        for _, row in scored.iterrows():
            expected = sum(weights[key] * row["score_" + key] for key in active) / sum(weights[key] for key in active)
            assert row.total_score == pytest.approx(expected - row.cost_penalty)
            assert row.composite_coverage == pytest.approx(sum(weights[key] for key in active))
            signal = {**row.to_dict(), "price_freshness": "ok", "score_etf_exposure": 0.2}
            canonical = canonical_score_from_signal_row(signal, config, "2026-10-20")
            assert canonical.legacy_composite_raw == pytest.approx(row.total_score, abs=0.0001)
    component = CanonicalComponent("momentum", 0.8, "attractiveness", "peers", "yfinance:prices", "vendor_verified", "ok", "low", "ok", "momentum")
    one = build_canonical_score(instrument_id="X", asset_type="ETF", decision_time="2026-10-20", components=[component], legacy_component_weights={"momentum": 0.5, "trend": 0.5})
    assert one.legacy_composite_raw is None
    config.models.ensemble["weights"] = {"momentum": 0.5, "toto": 0.5, "relative_strength": 0.0}
    assert component_scores(features, allocation, config).total_score.isna().all()


def test_distribution_action_normalization_and_disabled_forecast():
    config = load_config()
    distribution = {"attractiveness": 0.8, "expected_return": None, "risk_implementation": 0.8, "evidence_confidence": 0.8, "coverage": 0.8}
    def action(**changes):
        return preliminary_action(config, score_distribution={**distribution, **changes}, confidence=0.9, current_weight=0.0, drift=0.0, hard_band=0.05, trend_200=1.0)
    assert action() == "buy"
    assert action(forecast_weight=0.0) == "buy"
    assert action(forecast_weight=0.2) == "hold"
    assert action(forecast_weight=0.2, expected_return=0.8) == "buy"
    assert action(attractiveness=0.5) == "no_trade"
    assert action(attractiveness=0.05) == "hold"
    for field in ("attractiveness", "risk_implementation", "evidence_confidence", "coverage"):
        assert action(**{field: None}) == "hold"
        assert action(**{field: float("nan")}) == "hold"


def test_signal_result_preserves_blocked_intent_and_unavailable_status():
    signal = SignalResult(
        run_id="run", signal_date=date(2026, 10, 20), etf_id="X", action="buy",
        confidence=0.8, total_score=0.8, components=ComponentScores(*(0.0 for _ in range(12))),
        blocked_by=[], warnings=[], reason_short="test", reason_long="test", horizon_primary="1-3 months",
    )
    decision = AuthorityDecision(analysis_status="unavailable", research_state=ResearchState.NOT_SCOREABLE)
    for blocked in (
        replace(signal, authority_decision=decision, internal_intent=InternalSignalIntent.NONE),
        replace(signal, blocked_by=["stale_data"], internal_intent=InternalSignalIntent.NONE, analysis_status="unavailable"),
        replace(signal, status="failed", internal_intent=InternalSignalIntent.NONE, analysis_status="unavailable"),
    ):
        assert blocked.internal_intent is InternalSignalIntent.NONE
        assert blocked.analysis_status == "unavailable"
        assert blocked.execution_allowed is False
    assert signal.internal_intent is InternalSignalIntent.INCREASE
    assert signal.analysis_status == "complete"


def test_feature_driver_date_and_vintage_fallbacks_respect_cutoff():
    component = N(key="stock_quality", raw_score=0.6, score_10=8.0, authority="high",
                  as_of_date=None, source_vintage_hash=None, source_id="yfinance:fundamentals",
                  source_authority="official_filing", freshness_status="ok", why="quality")
    canonical_row = {"key": "stock_quality", "source_vintage_hash": "b" * 64}
    canonical = N(source_vintage_hash="a" * 64, components=[canonical_row], decision_time="2026-10-20")
    score = N(display_id="X", latest_date="2026-10-20", components=[component], canonical_score=canonical)
    row = build_feature_drivers([score]).iloc[0]
    assert row.as_of_date == "2026-10-20" and row.source_vintage_hash == "b" * 64
    canonical_row["source_vintage_hash"] = None
    assert build_feature_drivers([score]).iloc[0].source_vintage_hash == "unavailable"
    component.source_vintage_hash = "c" * 64
    assert build_feature_drivers([score]).iloc[0].source_vintage_hash == "c" * 64
    component.source_vintage_hash = None
    component.source_id = ""
    common = {"instrument_id": "X", "component": "stock_quality", "as_of_date": "2026-10-20",
              "source_authority": "official_filing", "source_span": "quality", "source_vintage_hash": "d" * 64}
    ledger = pd.DataFrame([
        {**common, "source_id": "official:filing", "known_at": "2026-10-20T16:00:00Z"},
        {**common, "source_id": "future", "known_at": "2026-10-21T00:00:00Z"},
    ])
    merged = build_feature_drivers([score], ledger).iloc[0]
    assert merged.source_id == "official:filing" and merged.source_vintage_hash == "d" * 64
    canonical.decision_time = "2026-10-20T15:00:00Z"
    assert build_feature_drivers([score], ledger).iloc[0].source_id == ""
