"""Owner regression: fund structure evidence must not cap non-funds."""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import derived_cache, signal_service, structural_evidence
from etf_cockpit.backtest import engine
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.data.etf_structure import (
    LocalStructuralEvidence,
    STRUCTURE_CONFIDENCE_VERSION,
    STRUCTURE_PROJECTION_VERSION,
    STRUCTURE_SCHEMA_VERSION,
    structure_cap_scope,
    structure_confidence_caps,
)
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.signals import signal_pipeline


DECISION_DATE = date(2026, 9, 30)


def _config():
    config = load_config().model_copy(deep=True)
    config.universe.etfs = [
        item.model_copy(update={"instrument_type": kind, "enabled": True})
        for item, kind in zip(config.universe.etfs, ("stock", "equity_certificate", "etf", "certificate"))
    ]
    assert len(config.universe.etfs) == 4
    return config


def _empty_evidence():
    return LocalStructuralEvidence(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())


@pytest.mark.parametrize("evidence", ({}, {"report_records": "malformed"}))
def test_non_funds_are_not_applicable_and_funds_remain_fail_closed(evidence):
    config = _config()
    caps = structure_confidence_caps(
        config.universe.enabled_ids,
        not_applicable_types=structure_cap_scope(config),
        **evidence,
    )
    for item in config.universe.etfs[:2]:
        assert caps[item.id] == 1.0
        assert caps.provenance[item.id] == {
            "status": "not_applicable",
            "reason_code": "structure_not_applicable_instrument_type",
            "instrument_type": item.instrument_type,
            "structure_confidence_cap": 1.0,
            "structure_projection_version": STRUCTURE_PROJECTION_VERSION,
            "structure_schema_version": STRUCTURE_SCHEMA_VERSION,
            "structure_confidence_version": STRUCTURE_CONFIDENCE_VERSION,
            "structure_provenance_hash": "unavailable",
        }
    for item in config.universe.etfs[2:]:
        assert caps[item.id] == 0.0
        assert caps.provenance[item.id].get("status") != "not_applicable"


def test_unknown_missing_and_disabled_types_do_not_exempt():
    ids = _config().universe.enabled_ids
    config = SimpleNamespace(universe=SimpleNamespace(etfs=[
        SimpleNamespace(id=ids[0], enabled=True, instrument_type="bond"),
        SimpleNamespace(id=ids[1], enabled=True),
        SimpleNamespace(id=ids[2], enabled=True, instrument_type=None),
        SimpleNamespace(id=ids[3], enabled=False, instrument_type="stock"),
    ]))
    assert structure_cap_scope(config) == {}
    assert structure_confidence_caps(ids, not_applicable_types=structure_cap_scope(config)) == dict.fromkeys(ids, 0.0)


def test_load_failure_preserves_non_fund_provenance(monkeypatch):
    config = _config()

    def fail():
        raise ValueError("corrupt structural evidence")

    monkeypatch.setattr(structural_evidence, "_load_local_structural_evidence", fail)
    caps = structural_evidence._load_structure_caps(config.universe.enabled_ids, DECISION_DATE, config=config)
    assert caps == dict(zip(config.universe.enabled_ids, (1.0, 1.0, 0.0, 0.0)))
    assert caps.provenance[config.universe.etfs[0].id]["status"] == "not_applicable"
    assert caps.provenance[config.universe.etfs[2].id]["reason_code"] == "structural_evidence_load_failed"


def test_signal_pipeline_removes_only_the_non_fund_structure_block(monkeypatch):
    config = _config()
    ids = config.universe.enabled_ids
    scored = pd.DataFrame([
        {"etf_id": instrument_id, "total_score": 0.8, "confidence": 0.8,
         "current_weight": 0.0, "target_weight": 0.2, "hard_band": 0.05,
         "momentum_20d": 0.02, "momentum_60d": 0.05, "momentum_120d": 0.1,
         "relative_strength_60d": 0.05, "price_freshness": "ok",
         "score_momentum": 0.8, "score_trend": 0.8, "score_risk": 0.8,
         "score_baseline_ml": 0.8, "score_toto": None, "score_timesfm": None,
         "score_baseline_source": "forecast",
         "trend_200": 1.0, "drawdown_60d_max": -0.01, "ewma_vol_ann": 0.1}
        for instrument_id in ids
    ])
    monkeypatch.setattr(signal_pipeline, "component_scores", lambda *args, **kwargs: scored.copy())
    distribution = {
        "status": "available", "coverage_ratio": 1.0,
        "decision_time": f"{DECISION_DATE}T00:00:00+00:00",
        "q10_return": 0.01, "q50_return": 0.02, "q90_return": 0.03,
        "per_model_distributions": [{
            "model_name": "baseline", "model_id": "baseline",
            "q10_return": 0.01, "q50_return": 0.02, "q90_return": 0.03,
            "forecast_date": f"{DECISION_DATE}T00:00:00+00:00",
        }],
    }
    holdings = pd.DataFrame(columns=["etf_id", "current_weight", "market_value_eur"])
    kwargs = dict(
        as_of_date=DECISION_DATE, publish=False,
        forecast_distributions=dict.fromkeys(ids, distribution),
        decision_time=pd.Timestamp(DECISION_DATE, tz="UTC"),
    )
    report = DataQualityReport(as_of_date=DECISION_DATE, issues=[])
    caps = structure_confidence_caps(ids, not_applicable_types=structure_cap_scope(config))
    signals = signal_pipeline.generate_signals(config, scored, holdings, report, structure_confidence_caps=caps, **kwargs)
    uncapped = signal_pipeline.generate_signals(config, scored, holdings, report, structure_confidence_caps=dict.fromkeys(ids, 1.0), **kwargs)
    previous = signal_pipeline.generate_signals(config, scored, holdings, report, structure_confidence_caps=dict.fromkeys(ids, 0.0), **kwargs)
    by_id = {signal.etf_id: signal for signal in signals}
    for signal in uncapped:
        assert "forecast_confidence_below_threshold" not in signal.blocked_by
    for signal in previous:
        assert "forecast_confidence_below_threshold" in signal.blocked_by
    for item in config.universe.etfs[:2]:
        signal = by_id[item.id]
        baseline = next(value for value in uncapped if value.etf_id == item.id)
        assert signal.blocked_by == baseline.blocked_by
        assert signal.confidence == baseline.confidence > 0.0
        assert signal.supporting_metrics["structure_evidence_status"] == "not_applicable"
        assert signal.execution_allowed is False
    for item in config.universe.etfs[2:]:
        assert "forecast_confidence_below_threshold" in by_id[item.id].blocked_by
        assert by_id[item.id].confidence == 0.0


def test_backtest_and_signal_service_call_the_same_scope(monkeypatch):
    config = _config()
    prices = generate_sample_prices(config, periods=280, end_date=DECISION_DATE)
    evidence = _empty_evidence()
    scope_calls = []
    service_caps, backtest_caps = [], []

    assert structural_evidence.structure_cap_scope is engine.structure_cap_scope is structure_cap_scope

    def scope(value):
        assert value is config
        scope_calls.append(value)
        return structure_cap_scope(value)

    def capture(caps_list):
        def generate(*args, **kwargs):
            caps_list.append(kwargs["structure_confidence_caps"])
            return []
        return generate

    monkeypatch.setattr(structural_evidence, "structure_cap_scope", scope)
    monkeypatch.setattr(engine, "structure_cap_scope", scope)
    monkeypatch.setattr(structural_evidence, "_load_local_structural_evidence", lambda: evidence)
    monkeypatch.setattr(signal_service, "load_prices", lambda: prices.copy())
    monkeypatch.setattr(signal_service, "load_holdings", lambda: pd.DataFrame(columns=["etf_id", "current_weight", "market_value_eur"]))
    monkeypatch.setattr(signal_service, "load_features", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(signal_service, "load_latest_forecasts", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(signal_service, "load_forecast_history", pd.DataFrame)
    monkeypatch.setattr(signal_service.FeatureService, "compute_features", lambda *args, **kwargs: engine.compute_features(prices))
    monkeypatch.setattr(signal_service.DataService, "validate_prices", lambda *args, **kwargs: DataQualityReport(as_of_date=DECISION_DATE, issues=[]))
    monkeypatch.setattr(signal_service, "generate_signals", capture(service_caps))
    monkeypatch.setattr(signal_service, "_run_decision_shadow_guard", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "generate_signals", capture(backtest_caps))
    signal_service.SignalService(config).generate_signals(as_of_date=DECISION_DATE)
    engine.run_backtest(config, prices)
    assert service_caps and backtest_caps and len(scope_calls) == len(service_caps) + len(backtest_caps)
    expected = dict(zip(config.universe.enabled_ids, (1.0, 1.0, 0.0, 0.0)))
    assert all(caps == expected for caps in service_caps + backtest_caps)
    assert all(caps.provenance == service_caps[0].provenance for caps in backtest_caps)


@pytest.mark.parametrize("nonempty", [False, True])
def test_cache_matches_shared_scope_and_rejects_old_zero_caps(nonempty):
    config = _config()
    evidence = _empty_evidence()
    if nonempty:
        evidence.document_registry.loc[0, "source_id"] = "unavailable"
    ids = config.universe.enabled_ids
    signal_log = pd.DataFrame({"date": [DECISION_DATE] * len(ids), "etf_id": ids})
    caps = structure_confidence_caps(ids, document_registry=evidence.document_registry, not_applicable_types=structure_cap_scope(config))
    hashes = pd.Series([caps.provenance[instrument_id]["structure_provenance_hash"] for instrument_id in ids])
    assert derived_cache._cached_structure_columns_match(signal_log, pd.Series([caps[item] for item in ids]), hashes, evidence, ids, config=config)
    assert not derived_cache._cached_structure_columns_match(signal_log, pd.Series([0.0] * len(ids)), hashes, evidence, ids, config=config)
