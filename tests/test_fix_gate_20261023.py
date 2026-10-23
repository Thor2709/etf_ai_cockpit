"""FIX-GATE: signed costs, evidence admission and resolved gate provenance."""

from dataclasses import replace
from types import SimpleNamespace
import json

import pandas as pd

from etf_cockpit.application import score_backfill
from etf_cockpit.core.config import load_config
from etf_cockpit.core.research_states import ResearchState
from etf_cockpit.core.types import DataQualityIssue
from etf_cockpit.signals import signal_pipeline as pipeline
from etf_cockpit.signals import simple_scores
from etf_cockpit.signals.gates import evaluate_risk_gates
from tests._pit_listing import verified_listing_history  # noqa: F401
from tests.test_bug_fc3_gates_calibration import SIGNAL_DATE, _metadata, _report, _signal
from tests.test_score_backfill import AS_OF, _eur_ids, _prices, _run


def _canonical(**changes):
    values = dict(
        asset_type="ETF", components=(), legacy_composite_raw=0.8,
        decision_distribution=None, attractiveness_10=8.0, expected_return_10=8.0,
        risk_implementation_10=8.0, evidence_confidence_10=8.0, coverage=1.0,
        formula_version="test_v1", formula_checksum="a" * 64, source_vintage_hash="test-vintage",
    )
    return SimpleNamespace(**{**values, **changes})


def _generate(monkeypatch, *, caps=None, changes=None):
    row = {
        "etf_id": "AAA", "total_score": 0.8, "confidence": 0.8,
        "current_weight": 0.0, "target_weight": 0.2, "hard_band": 0.05,
        "momentum_20d": 0.1, "momentum_60d": 0.1, "momentum_120d": 0.1,
        "relative_strength_60d": 0.1, "trend_200": 1.0,
        "drawdown_60d_max": -0.05, "ewma_vol_ann": 0.1,
    }
    row.update(changes or {})
    monkeypatch.setattr(pipeline, "component_scores", lambda *a, **k: pd.DataFrame([row]))
    monkeypatch.setattr(pipeline, "allocation_frame", lambda *a: pd.DataFrame([
        {"etf_id": "AAA", "drift": -0.2, "role": "core", "name": "AAA"},
    ]))
    monkeypatch.setattr(pipeline, "canonical_score_from_signal_row", lambda *a, **k: _canonical())
    monkeypatch.setattr(pipeline, "portfolio_value", lambda *a: 100_000.0)
    monkeypatch.setattr(pipeline, "estimated_cost_bps", lambda *a: 20.0)
    monkeypatch.setattr(pipeline, "estimate_execution_cost", lambda *a, **k: SimpleNamespace(
        total_cost_bps=20.0, model_id="test", data_quality="test", capacity_eur=100_000.0,
    ))
    monkeypatch.setattr(pipeline, "row_components", lambda *a: None)
    monkeypatch.setattr(pipeline, "explain_signal", lambda *a: ("Review", "Detail"))
    monkeypatch.setattr(pipeline, "classification_score_state", lambda *a: {
        "status": "current", "version_id": "test", "invalidation_token": "test",
    })
    return pipeline.generate_signals(
        load_config(), pd.DataFrame([{"etf_id": "AAA"}]),
        pd.DataFrame([{"etf_id": "AAA", "current_weight": 0.0}]), _report(_metadata()),
        as_of_date=SIGNAL_DATE, run_id="fix-gate", publish=False, structure_confidence_caps=caps,
    )[0]


def test_valuation_uses_fresh_stock_value_and_is_not_applicable_to_etfs():
    component = dict(key="stock_value", raw_metric=0.5, score_eligible=True, status="ok", freshness_status="ok")
    for asset_type, components, expected in (
        ("ETF", (), True), ("STOCK", (component,), True), ("STOCK", (), False),
        ("STOCK", ({**component, "freshness_status": "fresh"},), True),
        ("STOCK", ({**component, "freshness_status": "stale"},), False),
        ("STOCK", ({**component, "score_eligible": False},), False),
        ("STOCK", ({**component, "raw_metric": float("nan")},), False),
    ):
        signal = _signal(action="buy", canonical_score=_canonical(asset_type=asset_type, components=components))
        decision = pipeline._attach_authority(signal, _report(_metadata())).authority_decision
        gate = next(gate for gate in decision.gates if gate.gate_id == "valuation")
        assert gate.passed is expected
        assert decision.research_promotion_allowed is expected
        assert decision.execution_allowed is False


def test_negative_edge_cannot_clear_buy_cost_threshold_or_publish_positive_ratio():
    config = load_config()
    for action in ("buy", "add"):
        for edge, fails in ((-0.12, True), (0.0001, True), (0.12, False)):
            blocked, _ = evaluate_risk_gates(
                config, pd.Series(dict(etf_id="AAA", trend_200=1.0, drawdown_60d_max=-0.05,
                                       expected_edge_60d=edge, cost_bps=20.0, current_weight=0.0)),
                _report(), candidate_action=action, projected_weight=0.05, cash_weight=1.0,
            )
            assert ("edge_below_cost_threshold" in blocked) is fails
    metrics = pipeline._cost_stress_metrics(config, etf_id="AAA", expected_edge_bps=-1200.0,
                                           base_cost_bps=20.0, trade_value_eur=None)
    assert pipeline._edge_to_cost(-1200.0, 20.0) == -60.0
    assert metrics["edge_to_cost_base"] == -60.0
    assert metrics["cost_stress_warning"] == "edge_fails_base_cost"


def test_withheld_caps_stay_none_and_supplied_cap_controls_action_confidence(monkeypatch):
    for caps in (None, {}, {"AAA": float("nan")}):
        signal = _generate(monkeypatch, caps=caps)
        assert signal.supporting_metrics["structure_confidence_cap"] is None
        assert signal.confidence == 0.8 and signal.action == "add_candidate"
    signal = _generate(monkeypatch, caps={"AAA": 0.25})
    assert signal.confidence == 0.2 and signal.action not in {"buy", "add_candidate"}
    signal = _generate(monkeypatch, caps={"AAA": 0.0})
    assert signal.confidence == 0.0 and signal.action not in {"buy", "add_candidate"}


def test_nan_signal_inputs_remain_unavailable_and_cannot_create_a_weight(monkeypatch):
    for missing in (None, float("nan"), float("inf")):
        signal = _generate(monkeypatch, changes={
            "current_weight": missing, "score_toto": None, "score_timesfm": missing,
            "trend_200": missing, "momentum_120d": missing, "total_score": missing,
        })
        assert signal.suggested_new_weight is None and signal.suggested_trade_value_eur is None
        assert "signal_inputs_unavailable" in signal.blocked_by
        assert signal.authority_decision.execution_allowed is False
        for key in ("current_weight", "toto_score", "timesfm_score", "trend_200", "medium_term_signal_score", "raw_signal_score"):
            assert signal.supporting_metrics[key] is None
        blocked, _ = evaluate_risk_gates(
            load_config(), pd.Series(dict(etf_id="AAA", current_weight=missing, trend_200=1.0,
                                         drawdown_60d_max=-0.05, expected_edge_60d=0.1, cost_bps=20.0)),
            _report(), candidate_action="buy", projected_weight=0.1, cash_weight=0.05,
        )
        assert "portfolio_inputs_unavailable" in blocked
        for key in ("momentum_60d", "momentum_120d", "relative_strength_60d"):
            signal = _generate(monkeypatch, changes={key: missing})
            assert signal.supporting_metrics["expected_edge_bps"] is None
            assert "edge_inputs_unavailable" in signal.blocked_by
            assert signal.suggested_new_weight is None
            assert signal.execution_allowed is False


def test_authority_routes_scoped_issues_cost_warnings_and_all_active_risk_and_limit_codes():
    signal = _signal(action="buy", canonical_score=_canonical())
    config = load_config()
    for code in ("insufficient_history", "invalid_ohlc", "stale_data", "unknown_block"):
        for scope in ("AAA", "BBB", "ALL"):
            report = _report(_metadata(), issues=[DataQualityIssue(scope, "block", code, "test")])
            blocked, _ = evaluate_risk_gates(
                config, pd.Series({"etf_id": "AAA"}), report,
                candidate_action="hold", projected_weight=None, cash_weight=1.0,
            )
            assert ("portfolio_validation_block" in blocked) == (scope == "ALL")
            assert (code in blocked) == (scope in {"AAA", "ALL"})
            decision = pipeline._attach_authority(replace(signal, blocked_by=blocked), report).authority_decision
            gates = {gate.gate_id: gate for gate in decision.gates}
            assert gates["risk"].passed is (scope == "BBB")
            assert gates["data_quality"].passed is (scope == "BBB")
            assert decision.research_promotion_allowed is (scope == "BBB")
    codes = (
        "edge_below_cost_threshold", "edge_inputs_unavailable", "expected_drawdown_unavailable",
        "trend_evidence_unavailable", "below_sma_200", "projected_weight_above_cap:5.0%",
        "cash_minimum_breached", "portfolio_inputs_unavailable", "portfolio_validation_block",
        "minimum_trade_size", "forecast_uncertainty_config_missing", "forecast_uncertainty_unavailable",
        "forecast_uncertainty_config_invalid", "forecast_model_disagreement",
        "forecast_confidence_below_threshold", "forecast_stale", "unknown_block",
        "signal_inputs_unavailable", "expected_drawdown_gate", "model_disagreement",
    )
    for code in codes:
        decision = pipeline._attach_authority(replace(signal, blocked_by=[code]), _report(_metadata())).authority_decision
        gates = {gate.gate_id: gate for gate in decision.gates}
        cost_only = code.startswith("edge_")
        assert gates["cost"].passed is not cost_only
        assert gates["risk"].passed is cost_only
        assert decision.research_state is (ResearchState.MANUAL_REVIEW if cost_only else ResearchState.NOT_SCOREABLE)
        if code.startswith("projected_weight_") or code in {
            "cash_minimum_breached", "portfolio_inputs_unavailable", "portfolio_validation_block", "minimum_trade_size",
        }:
            assert gates["portfolio_fit"].passed is False
        assert decision.execution_allowed is False


def test_ineligible_rows_are_removed_before_features_and_peer_scoring(monkeypatch):
    config = load_config()
    young = _eur_ids(config, "etf", 4)[3]
    stale = _eur_ids(config, "etf", 2)[0]
    illiquid, no_fx = _eur_ids(config, "stock", 2)
    prices = _prices(config, young=young)
    config.universe.by_id()[no_fx].currency = "USD"
    prices.loc[prices["etf_id"].eq(illiquid), "volume"] = 1.0
    prices.loc[prices["etf_id"].eq(no_fx), "currency"] = "USD"
    stale_dates = prices.loc[prices["etf_id"].eq(stale) & prices["date"].le(AS_OF), "date"].tail(10)
    prices = prices.loc[~(prices["etf_id"].eq(stale) & prices["date"].isin(stale_dates))]
    rejected = {young, stale, illiquid, no_fx}
    feature_inputs, score_inputs = [], []
    compute = score_backfill.FeatureService.compute_features
    build = score_backfill.build_universe_simple_scores

    def features(self, as_of, known, **kwargs):
        assert not rejected.intersection(known["etf_id"])
        result = compute(self, as_of, known, **kwargs)
        feature_inputs.append(result.copy())
        return result

    def scores(config, signals, forecasts, known, **kwargs):
        assert not rejected.intersection(config.universe.enabled_ids)
        assert not rejected.intersection(known["etf_id"])
        score_inputs.append(set(known["etf_id"]))
        return build(config, signals, forecasts, known, **kwargs)

    monkeypatch.setattr(score_backfill.FeatureService, "compute_features", features)
    monkeypatch.setattr(score_backfill, "build_universe_simple_scores", scores)
    history, log = _run(config, prices)
    assert history is not None and feature_inputs and score_inputs
    for instrument, reason in ((young, "insufficient_history"), (stale, "stale_data"),
                               (illiquid, "liquidity_gate"), (no_fx, "fx_unavailable")):
        row = log.set_index("instrument_id").loc[instrument]
        assert not row["eligible"] and reason in row["reasons"]
    changed = prices.copy()
    columns = ["open", "high", "low", "close", "adjusted_close"]
    changed.loc[changed["etf_id"].eq(young), columns] *= 1000.0
    again, _ = _run(config, changed)
    pd.testing.assert_frame_equal(feature_inputs[0], feature_inputs[1])
    pd.testing.assert_frame_equal(history, again)


def test_score_history_persists_resolved_gate_results_with_reasons(monkeypatch, tmp_path):
    captured = []
    finalize = score_backfill.rank_and_finalize_scores

    def ranking(*args, **kwargs):
        result = finalize(*args, **kwargs)
        captured.extend(result)
        return result

    monkeypatch.setattr(score_backfill, "rank_and_finalize_scores", ranking)
    config = load_config()
    history, eligibility = _run(config, _prices(config))
    assert history is not None and captured
    decisions = {score.display_id: score.authority_decision for score in captured}
    for row in history.itertuples():
        expected = [dict(gate_id=gate.gate_id, passed=gate.passed, severity=gate.severity.value, reason=gate.message)
                    for gate in decisions[row.instrument_id].gates]
        assert json.loads(row.gate_results) == expected and len(expected) == 9
        assert row.execution_allowed is False
    score_backfill.write_backfill_store(tmp_path, history, eligibility, {"execution_allowed": False})
    restored = score_backfill.load_backfill_score_history(tmp_path)
    assert restored["gate_results"].tolist() == history["gate_results"].tolist()


def test_configured_equity_certificate_rows_take_native_path_not_generic_scoring(monkeypatch):
    config = load_config()
    base = config.universe.etfs[0]
    ec = base.model_copy(update={"id": "ECX", "instrument_type": "equity_certificate"})
    config = config.model_copy(update={"universe": config.universe.model_copy(update={"etfs": [*config.universe.etfs, ec]})})
    seen: list[list[str]] = []
    row = {"etf_id": "AAA", "total_score": 0.8, "confidence": 0.8, "current_weight": 0.0, "target_weight": 0.2,
           "hard_band": 0.05, "momentum_20d": 0.1, "momentum_60d": 0.1, "momentum_120d": 0.1, "relative_strength_60d": 0.1,
           "trend_200": 1.0, "drawdown_60d_max": -0.05, "ewma_vol_ann": 0.1}

    def components(features, *a, **k):
        seen.append(list(features["etf_id"]))
        return pd.DataFrame([row])

    def canonical(row_, *a, **k):
        assert str(row_["etf_id"]) != "ECX"
        return _canonical()

    monkeypatch.setattr(pipeline, "component_scores", components)
    monkeypatch.setattr(pipeline, "allocation_frame", lambda *a: pd.DataFrame([{"etf_id": "AAA", "drift": 0.0, "role": "core", "name": "AAA"}]))
    monkeypatch.setattr(pipeline, "canonical_score_from_signal_row", canonical)
    monkeypatch.setattr(pipeline, "portfolio_value", lambda *a: 100_000.0)
    monkeypatch.setattr(pipeline, "estimated_cost_bps", lambda *a: 20.0)
    monkeypatch.setattr(pipeline, "estimate_execution_cost", lambda *a, **k: SimpleNamespace(
        total_cost_bps=20.0, model_id="test", data_quality="test", capacity_eur=100_000.0))
    monkeypatch.setattr(pipeline, "row_components", lambda *a: None)
    monkeypatch.setattr(pipeline, "explain_signal", lambda *a: ("Review", "Detail"))
    monkeypatch.setattr(pipeline, "classification_score_state", lambda *a: {"status": "current", "version_id": "t", "invalidation_token": "t"})
    holdings = pd.DataFrame([{"etf_id": "AAA", "current_weight": 0.0}])
    kwargs = dict(as_of_date=SIGNAL_DATE, run_id="fix-gate-ec", publish=False)
    signals = pipeline.generate_signals(config, pd.DataFrame([{"etf_id": "AAA"}, {"etf_id": "ECX"}]), holdings, _report(_metadata()), **kwargs)
    assert seen == [["AAA"]] and [signal.etf_id for signal in signals] == ["AAA"]
    # Only ECs configured: nothing is generically scored and nothing raises.
    assert pipeline.generate_signals(config, pd.DataFrame([{"etf_id": "ECX"}]), holdings, _report(_metadata()), **kwargs) == []
    # The downstream scoreboard routes the configured EC with no generic signal to its native scorecard.
    native_config = config.model_copy(update={"universe": config.universe.model_copy(update={"etfs": [ec]})})
    cutoffs = []

    def native_rows(*, decision_time=None):
        cutoffs.append(decision_time)
        return {"ECX": {"final_combined_score_10": 8.0, "coverage": 1.0, "data_as_of_date": SIGNAL_DATE.isoformat()}}

    monkeypatch.setattr(simple_scores, "latest_sparebank_scores", native_rows)
    prices = pd.DataFrame([{"etf_id": "ECX", "date": SIGNAL_DATE, "adjusted_close": 100.0}])
    native = simple_scores.build_universe_simple_scores(
        native_config, [], pd.DataFrame(), prices,
        as_of_sources=simple_scores.AsOfScoreSources(decision_time=SIGNAL_DATE),
    )
    assert len(native) == 1 and native[0].display_id == "ECX"
    assert native[0].final_score_10 == 8.0 and native[0].analysis_tier == "sparebanken"
    assert native[0].canonical_score is None and native[0].execution_allowed is False
    assert cutoffs == [SIGNAL_DATE.isoformat()]
