"""PSF: one price-strength family capped at 30% (audit #927 NEW-2, B-01..B-05, B-08)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import numpy as np
import pytest
import yaml

from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityReport, DatasetMetadata
from etf_cockpit.core.versioning import build_version_registry
from etf_cockpit.models.ensemble import BASELINE_SOURCE_FORECAST, BASELINE_SOURCE_HEURISTIC, effective_ensemble_weights
from etf_cockpit.signals import signal_pipeline
from etf_cockpit.signals.canonical_scoring import canonical_score_from_signal_row, load_score_policy
from etf_cockpit.signals.scoring import component_scores
from etf_cockpit.signals import simple_scores as ss
from etf_cockpit.signals.simple_scores import combine_component_scores, raw_to_score_10

V3 = Path(__file__).resolve().parents[1] / "configs" / "score_engine_v3.yaml"
PRICE_FAMILY = ("momentum", "trend", "relative_strength")
CAP = 0.30


def _document() -> dict:
    return yaml.safe_load(V3.read_text(encoding="utf-8"))


def _tables() -> list[tuple[str, dict[str, float]]]:
    document = _document()
    tables = [("action_composite", document["action_composite"]["weights"])]
    for asset, policy in document["asset_policies"].items():
        tables.append((f"{asset}.attractiveness", policy["attractiveness"]))
        tables.append((f"{asset}.headline_evidence", policy["headline_evidence"]))
    return tables


@pytest.mark.parametrize(("name", "table"), _tables(), ids=[name for name, _ in _tables()])
def test_price_family_weight_share_is_capped_for_stock_and_etf(name: str, table: dict[str, float]) -> None:
    total = sum(table.values())
    share = sum(table.get(key, 0.0) for key in PRICE_FAMILY) / total
    assert share <= CAP + 1e-9, (name, share)
    assert table["relative_strength"] == 0.0  # RS is not a separate weighted component (one global anchor, B-01)
    # the family is the cap, not an arbitrary lower number: freed weight went to the non-price families
    assert share == pytest.approx(CAP, abs=1e-3)


def test_policy_loader_exposes_the_capped_family_and_bumped_lineage() -> None:
    for asset in ("ETF", "STOCK"):
        policy = load_score_policy(asset)
        assert "relative_strength" not in policy.groups["attractiveness"]  # zero weights are not positive weights
        assert policy.headline_weights["relative_strength"] == 0.0
        assert sum(policy.headline_weights[k] for k in ("momentum", "trend")) / sum(policy.headline_weights.values()) <= CAP + 1e-9
        assert policy.formula_version == "score-engine-v3.2.0"
        assert policy.formula_checksum == hashlib.sha256(V3.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    record = next(item for item in build_version_registry()["records"] if item["artifact_id"] == "formula:score-engine-v3")
    assert record["version"] == "3.2.0" and record["available"]


def _features(scale_anchor: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame([
        {"etf_id": key, "momentum_20d": .01, "momentum_60d": .02 * scale, "momentum_120d": .03 * scale, "momentum_180d": .04,
         "trend_slope": .01 * scale, "trend_100": 1., "trend_200": 1., "vol_60d_ann": .2, "ewma_vol_ann": .2,
         "drawdown_60d_max": -.05, "relative_strength_60d": .02 * scale - scale_anchor}
        for key, scale in (("AAA", 1), ("BBB", 2), ("CCC", 3))
    ])


def _allocation() -> pd.DataFrame:
    return pd.DataFrame([
        {"etf_id": key, "current_weight": 0.0, "target_weight": 0.0, "hard_band": .05, "soft_band": .03, "max_weight": .25}
        for key in ("AAA", "BBB", "CCC")
    ])


def test_relative_strength_is_not_a_scored_component_and_a_constant_anchor_changes_no_rank() -> None:
    config = load_config()
    base = component_scores(_features(), _allocation(), config)
    shifted = component_scores(_features(scale_anchor=0.07), _allocation(), config)  # a different single global anchor
    assert base["score_relative_strength"].rank().tolist() == shifted["score_relative_strength"].rank().tolist()
    assert base["score_relative_strength"].tolist() == pytest.approx(shifted["score_relative_strength"].tolist())
    assert base["total_score"].tolist() == pytest.approx(shifted["total_score"].tolist())
    # RS carries no weight: wrecking it leaves the composite unchanged
    broken = _features()
    broken["relative_strength_60d"] = [0.5, -0.5, 0.0]
    assert component_scores(broken, _allocation(), config)["total_score"].tolist() == pytest.approx(base["total_score"].tolist())
    # headline: an RS component with any raw score does not move the headline value
    def comp(key: str, raw: float) -> ss.SimpleScoreComponent:
        return replace(ss._component(key, raw, "fixture"), as_of_date="2026-01-06", freshness_status="ok")

    others = [("momentum", 0.4), ("trend", 0.2), ("risk", 0.3), ("liquidity_cost", 0.5)]
    values = {
        rs: combine_component_scores([comp(key, raw) for key, raw in [*others, ("relative_strength", rs)]], ss.headline_weights("ETF"))
        for rs in (-0.9, 0.0, 0.9)
    }
    assert len(set(values.values())) == 1 and values[0.0][0] is not None
    assert ss.headline_weights("ETF")["relative_strength"] == ss.headline_weights("STOCK")["relative_strength"] == 0.0


def test_unavailable_models_move_no_weight_to_momentum_or_trend_and_coverage_drops() -> None:
    config = load_config()
    configured = config.models.ensemble["weights"]
    total = sum(configured.values())
    for toto, timesfm in ((True, True), (False, True), (True, False), (False, False)):
        effective = effective_ensemble_weights(configured, toto_available=toto, timesfm_available=timesfm)
        for key in ("momentum", "trend", "baseline_ml", "risk"):
            assert effective[key] == pytest.approx(configured[key] / total), (key, toto, timesfm)
        assert sum(effective.values()) == pytest.approx(1.0)
    scored = component_scores(_features(), _allocation(), config)  # no model available, no forecasts
    assert (scored["composite_coverage"] < 1.0).all()
    model_weight = sum(configured[key] for key in ("toto", "timesfm", "baseline_ml", "chatgpt_thesis"))
    price_risk = sum(configured[key] for key in ("momentum", "trend", "risk"))
    assert scored["composite_coverage"].iloc[0] == pytest.approx(price_risk / (price_risk + model_weight))
    # with every model unavailable the score is exactly the momentum/trend/risk blend at their configured weights
    row = scored.iloc[0]
    expected = sum(configured[k] * row["score_" + k] for k in ("momentum", "trend", "risk")) / price_risk
    assert row["total_score"] == pytest.approx(expected - row["cost_penalty"])


def test_baseline_price_fallback_is_a_labelled_heuristic_without_weight() -> None:
    config = load_config()
    heuristic = component_scores(_features(), _allocation(), config)
    assert (heuristic["score_baseline_source"] == BASELINE_SOURCE_HEURISTIC).all()
    assert heuristic["score_baseline_ml"].notna().all()  # still displayed
    forecasts = {"baseline": {"AAA": 0.2, "BBB": 0.2, "CCC": 0.2}}
    backed = component_scores(_features(), _allocation(), config, forecast_scores=forecasts)
    assert (backed["score_baseline_source"] == "forecast").all()
    weights = effective_ensemble_weights(config.models.ensemble["weights"], toto_available=False, timesfm_available=False)
    assert (backed["composite_coverage"] > heuristic["composite_coverage"]).all()
    assert backed["composite_coverage"].iloc[0] - heuristic["composite_coverage"].iloc[0] == pytest.approx(weights["baseline_ml"])
    # canonical action composite: the heuristic baseline stays visible but labelled, and carries no legacy-composite weight
    def canonical(frame: pd.DataFrame):
        signal = frame.set_index("etf_id").loc["AAA"].copy()
        signal["etf_id"], signal["price_freshness"] = "AAA", "ok"
        signal["score_etf_exposure"] = 0.2
        return canonical_score_from_signal_row(signal, config, "2026-01-06"), signal

    baseline_of = lambda score: next(item for item in score.components if item["key"] == "baseline")  # noqa: E731
    heuristic_score, heuristic_row = canonical(heuristic)
    heuristic_baseline = baseline_of(heuristic_score)
    assert "price heuristic" in heuristic_baseline["explanation"]
    assert heuristic_baseline["raw_metric"] is not None  # displayed
    assert heuristic_baseline["status"] == "unavailable" and heuristic_baseline["source_id"] == "heuristic:momentum_trend"
    assert heuristic_baseline["score_eligible"] is False and not heuristic_baseline["contribution_raw"]  # no expected_return weight
    assert heuristic_score.legacy_composite_raw == pytest.approx(heuristic_row["total_score"], abs=1e-3)
    backed_score, _ = canonical(backed)
    assert "price heuristic" not in baseline_of(backed_score)["explanation"]
    backed_baseline = baseline_of(backed_score)
    assert backed_baseline["score_eligible"] is True and backed_baseline["source_id"] == "model:baseline"
    # the heuristic baseline holds no canonical coverage: the model-backed one adds exactly its configured v3 weight
    assert backed_score.coverage > heuristic_score.coverage
    assert baseline_of(backed_score)["raw_metric"] == pytest.approx(0.2)


def test_risk_is_centred_so_a_neutral_input_scores_five() -> None:
    config = load_config()
    neutral = component_scores(_features(), _allocation(), config)  # equal volatility everywhere: z = 0
    assert neutral["score_risk"].tolist() == [0.0, 0.0, 0.0]
    assert [raw_to_score_10(value) for value in neutral["score_risk"]] == [5.0, 5.0, 5.0]
    # one volatility measure only: drawdown (rho ~ -0.79 with volatility in the audit, above 0.7) does not enter risk
    deeper = _features()
    deeper["drawdown_60d_max"] = [-0.30, -0.02, -0.15]
    assert component_scores(deeper, _allocation(), config)["score_risk"].tolist() == [0.0, 0.0, 0.0]
    # symmetric around neutral and full range: lower volatility than peers scores above 5, higher below 5
    spread = _features()
    spread["vol_60d_ann"] = [0.10, 0.20, 0.40]
    risk = component_scores(spread, _allocation(), config)["score_risk"]
    assert risk.iloc[0] > 0 > risk.iloc[2]
    # missing volatility stays unavailable, never zero-filled to neutral
    missing = _features()
    missing["vol_60d_ann"], missing["ewma_vol_ann"] = float("nan"), float("nan")
    assert component_scores(missing, _allocation(), config)["score_risk"].isna().all()


def test_baseline_requires_explicit_forecast_provenance_for_weight_and_coverage() -> None:
    config = load_config()
    row = {
        "etf_id": "AAA", "price_freshness": "ok", "score_momentum": 0.2, "score_trend": 0.3,
        "score_risk": 0.0, "score_etf_exposure": 0.2, "cost_penalty": 0.0, "score_baseline_ml": 1.0,
    }
    def score(values):
        return canonical_score_from_signal_row(values, config, "2026-01-06")

    absent = score({**row, "score_baseline_ml": None})
    backed = score({**row, "score_baseline_source": BASELINE_SOURCE_FORECAST})
    for fields in ({}, {"score_baseline_source": "unknown"}, {"score_baseline_source": None}, {"score_baseline_source": pd.NA}):
        unverified = score({**row, **fields})
        component = next(item for item in unverified.components if item["key"] == "baseline")
        assert component["status"] == "unavailable" and not component["score_eligible"]
        assert "provenance" in component["explanation"] and component["source_id"] != "model:baseline"
        assert component["raw_metric"] == 1.0 and not component["contribution_raw"]
        assert unverified.expected_return_10 is None
        assert unverified.coverage == absent.coverage < backed.coverage
        assert unverified.evidence_confidence_10 == absent.evidence_confidence_10
        assert unverified.legacy_composite_raw == absent.legacy_composite_raw


def _signal_with_edge(monkeypatch: pytest.MonkeyPatch, distributions: dict | None):
    config = load_config()
    scores = pd.DataFrame([{
        "etf_id": "AAA", "total_score": 0.4, "confidence": 0.8, "current_weight": 0.0, "target_weight": 0.2, "hard_band": 0.05,
        "momentum_20d": 0.1, "relative_strength_60d": 0.1, "momentum_60d": 0.1, "momentum_120d": 0.1, "trend_200": 1.0, "ewma_vol_ann": 0.1,
        "score_baseline_source": BASELINE_SOURCE_HEURISTIC,
    }])
    canonical = SimpleNamespace(
        legacy_composite_raw=0.4, decision_distribution={}, attractiveness_10=8.0, expected_return_10=8.0,
        risk_implementation_10=8.0, evidence_confidence_10=8.0, coverage=1.0, formula_version="t", formula_checksum="a" * 64,
        source_vintage_hash="v",
    )
    patches = {
        "component_scores": lambda *a, **k: scores.copy(),
        "allocation_frame": lambda *a, **k: pd.DataFrame([{"etf_id": "AAA", "drift": 0.1, "role": "core", "name": "AAA"}]),
        "canonical_score_from_signal_row": lambda *a, **k: canonical,
        "portfolio_value": lambda _h: 1000.0,
        "calibrate_forecast_distribution": lambda *a, **k: {**(distributions or {}).get("AAA", {}), "conformal_calibration": {"status": "calibrated"}},
        "preliminary_action": lambda *a, **k: "hold",
        "proposed_new_weight": lambda *a, **k: 0.2,
        "evaluate_risk_gates": lambda *a, **k: ([], []),
        "suggested_trade_value": lambda *a, **k: 100.0,
        "estimate_execution_cost": lambda *a, **k: SimpleNamespace(total_cost_bps=1.0, model_id="t", data_quality="t", capacity_eur=1000.0),
        "_cost_stress_metrics": lambda *a, **k: {},
        "row_components": lambda _r: {},
        "explain_signal": lambda *a, **k: ("Review", "Detail"),
        "decompose_forecast_uncertainty": lambda *a, **k: {"status": "available", "adjusted_confidence": 0.8},
        "generate_scenarios": lambda *a, **k: {"status": "available"},
        "classification_score_state": lambda *a, **k: {"status": "current", "version_id": "t", "invalidation_token": "t"},
        "_structure_cap_for_row": lambda *a, **k: 1.0,
    }
    for name, value in patches.items():
        monkeypatch.setattr(signal_pipeline, name, value)
    meta = DatasetMetadata(
        source_name="prices", source_type="prices", as_of_date=date(2026, 3, 2), ingested_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        currency="EUR", timezone="UTC", provider_or_manual_source="fixture", checksum="a" * 64, staleness_status="ok", age_days=0,
    )
    return signal_pipeline.generate_signals(
        config, pd.DataFrame([{"etf_id": "AAA"}]), pd.DataFrame([{"etf_id": "AAA", "current_weight": 0.0}]),
        DataQualityReport(as_of_date=date(2026, 3, 2), issues=[], dataset_metadata=[meta]),
        as_of_date=date(2026, 3, 2), run_id="psf", publish=False, forecast_distributions=distributions,
        decision_time=pd.Timestamp("2026-03-02"), structure_confidence_caps={"AAA": 1.0},
    )[0]


def test_expected_edge_and_baseline_fallbacks_are_labelled_heuristics(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = _signal_with_edge(monkeypatch, None)
    assert fallback.supporting_metrics["expected_edge_source"] == signal_pipeline.EDGE_SOURCE_HEURISTIC
    assert fallback.supporting_metrics["baseline_score_source"] == BASELINE_SOURCE_HEURISTIC
    forecast = _signal_with_edge(monkeypatch, {"AAA": {"horizon_days": 60, "q50_return": 0.02}})
    assert forecast.supporting_metrics["expected_edge_source"] == signal_pipeline.EDGE_SOURCE_FORECAST
    assert forecast.supporting_metrics["expected_edge_bps"] == pytest.approx(200.0)


def test_candidate_screening_risk_is_centred_and_volatility_only() -> None:
    peers = pd.DataFrame({"volatility_60d_ann": [0.10, 0.20, 0.40], "current_drawdown": [-0.30, -0.02, -0.15]})
    reference = ss._candidate_volatility_reference(peers)
    assert reference == pytest.approx(0.20)
    neutral = pd.Series({"volatility_60d_ann": 0.20, "current_drawdown": -0.10})
    assert ss._candidate_risk_raw(neutral, reference) == 0.0
    assert raw_to_score_10(ss._candidate_risk_raw(neutral, reference)) == 5.0
    # drawdown is not a second term: any drawdown gives the same risk at equal volatility
    deep = neutral.copy()
    deep["current_drawdown"] = -0.60
    assert ss._candidate_risk_raw(deep, reference) == 0.0
    # lower volatility than peers scores above neutral, higher below; the range is clamped to -1..1
    assert ss._candidate_risk_raw(pd.Series({"volatility_60d_ann": 0.10}), reference) == pytest.approx(0.5)
    assert ss._candidate_risk_raw(pd.Series({"volatility_60d_ann": 0.90}), reference) == -1.0
    # no volatility or no peer reference -> unavailable, never zero-filled to neutral
    assert ss._candidate_risk_raw(pd.Series({"current_drawdown": -0.10}), reference) is None
    assert ss._candidate_risk_raw(neutral, None) is None
    assert ss._candidate_volatility_reference(pd.DataFrame({"current_drawdown": [-0.1]})) is None


def test_b05_horizon_map_is_published_with_the_tactical_and_underwriting_split() -> None:
    lineage = (Path(__file__).resolve().parents[1] / "docs" / "architecture" / "score-lineage.md").read_text(encoding="utf-8")
    section = lineage.split("## Horizon map (B-05)", 1)[1]
    for component in ("momentum", "trend", "risk", "liquidity_cost", "stock_value", "stock_quality", "analyst_revision", "forecasts", "Sparebank EC"):
        assert f"| {component} |" in section, component
    assert "separate output" in section
    assert _document()["horizons"]["primary"] == "1-3 months"


def test_candidate_nonpositive_volatility_is_unavailable_instead_of_favourable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ss, "_etf_exposure_lookup", dict)
    rows = [
        {"instrument_id": str(index), "asset_type": "ETF", "latest_date": "2026-01-06", "latest_price": 100.0,
         "rows": 504, "volatility_60d_ann": vol}
        for index, vol in enumerate((-0.10, 0.0, 0.20))
    ]
    scores = ss.build_candidate_simple_scores(pd.DataFrame(rows), pd.DataFrame(), decision_date=date(2026, 1, 6))
    for result in scores:
        risk = next(item for item in result.components if item.key == "risk")
        if result.display_id in {"0", "1"}:
            assert risk.status == "N/A" and risk.raw_score is None and risk.score_10 is None
            assert not risk.score_eligible and "positive and finite" in risk.why
        else:
            assert risk.raw_score == 0.0 and risk.score_10 == 5.0
    assert len(scores) == 3
    for vol in (-0.1, 0.0):
        assert ss._candidate_risk_raw(pd.Series({"volatility_60d_ann": vol}), 0.2) is None


def test_b04_probe_momentum_construction_has_no_skip_window_or_volatility_scaling() -> None:
    from etf_cockpit.features.momentum import weighted_momentum

    frame = pd.DataFrame({"momentum_20d": [1.0], "momentum_60d": [0.0], "momentum_120d": [0.0], "momentum_180d": [0.0]})
    assert weighted_momentum(frame).iloc[0] == pytest.approx(0.15)  # the 20-day window enters unskipped, weight 0.15
    scaled = frame.assign(vol_60d_ann=[0.5])
    assert weighted_momentum(scaled).iloc[0] == pytest.approx(0.15)  # unscaled by volatility
    assert not hasattr(__import__("etf_cockpit.features.momentum", fromlist=["x"]), "skip_momentum")  # skip uses the existing momentum path


def test_b04_research_challengers_skip_recent_prices_scale_valid_volatility_and_preserve_live_blend() -> None:
    from etf_cockpit.features.feature_pipeline import compute_features
    from etf_cockpit.features.momentum import weighted_momentum

    prices = pd.DataFrame({
        "etf_id": "AAA", "date": pd.bdate_range("2025-01-01", periods=280),
        "adjusted_close": np.exp(np.arange(280) * 0.001 + np.sin(np.arange(280)) * 0.01), "volume": 1000.0,
    })
    features = compute_features(prices)
    skip = "momentum_252d_skip_20d"
    scaled = "weighted_momentum_vol_scaled"
    assert features[skip].iloc[:252].isna().all()
    assert features[skip].iloc[252] == pytest.approx(np.log(prices.adjusted_close.iloc[232] / prices.adjusted_close.iloc[0]))
    changed = prices.copy()
    changed.loc[260:, "adjusted_close"] *= 1.5
    assert compute_features(changed)[skip].iloc[-1] == features[skip].iloc[-1]
    assert features[scaled].iloc[-1] == pytest.approx(weighted_momentum(features).iloc[-1] / features.vol_60d_ann.iloc[-1])
    prefix = compute_features(prices.iloc[:270])
    pd.testing.assert_frame_equal(prefix[[skip, scaled]], features.loc[:269, [skip, scaled]])
    for vol in (None, 0.0, -0.1, float("inf"), float("nan")):
        invalid = features.assign(vol_60d_ann=vol)
        assert weighted_momentum(invalid, volatility=invalid.vol_60d_ann).isna().all()
    live = features.tail(1).copy()
    corrupted = live.assign(**{skip: 1e6, scaled: -1e6})
    config = load_config()
    base = component_scores(live, _allocation(), config)
    assert base.weighted_momentum.iloc[0] == weighted_momentum(live).iloc[0]
    pd.testing.assert_series_equal(base.total_score, component_scores(corrupted, _allocation(), config).total_score)
