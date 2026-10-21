"""NS1: one score definition. ``configs/score_engine_v3.yaml`` is the only weight source (audit #927 A-01..A-03, A-06)."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from etf_cockpit.application import scoreboard_publication as publication
from etf_cockpit.core.config import load_config
from etf_cockpit.core.exceptions import ConfigError
from etf_cockpit.signals import simple_scores as ss
from etf_cockpit.signals.canonical_scoring import (
    CanonicalScoreError,
    canonical_score_from_signal_row,
    canonical_score_from_simple_components,
    headline_evidence_weights,
    load_score_policy,
)
from etf_cockpit.signals.scoring import component_scores
from etf_cockpit.validation.tuning_registry import load_tuning_registry

REPO = Path(__file__).resolve().parents[1]
CONFIGS = REPO / "configs"
V3 = CONFIGS / "score_engine_v3.yaml"

# The tables NS1 moved into the yaml. NS1 kept the original values (ETF 0.22/0.18/0.14/0.14/0.10/0.10; STOCK
# 0.18/0.13/0.12/0.12/0.10/0.12/0.13/0.05); PSF (score-engine-v3.2.0) capped momentum+trend at 30% and zeroed relative_strength,
# the freed weight going proportionally to the non-price families. The names are kept: they pin "yaml == every consumer".
ORIGINAL_ETF_TABLE = {
    "momentum": 0.165, "trend": 0.135, "relative_strength": 0.0, "risk": 0.4083, "liquidity_cost": 0.2917,
    "etf_exposure": 0.0,  # FPQ: etf_exposure moved to risk role, non-price ETF families rescaled pro rata
    "baseline": 0.0, "timesfm": 0.0, "toto": 0.0,
}
ORIGINAL_STOCK_TABLE = {
    "momentum": 0.1742, "trend": 0.1258, "relative_strength": 0.0, "risk": 0.1615, "liquidity_cost": 0.1346,
    "stock_value": 0.1615, "stock_quality": 0.175, "analyst_revision": 0.0674, "baseline": 0.0, "timesfm": 0.0, "toto": 0.0,
}


def _yaml() -> dict:
    return yaml.safe_load(V3.read_text(encoding="utf-8"))


def _leaf(document: object, path: list[str]) -> float:
    for part in path:
        document = document[part]  # type: ignore[index]
    return float(document)  # type: ignore[arg-type]


def test_headline_actions_and_tuner_read_the_same_v3_yaml_weights(tmp_path: Path) -> None:
    document = _yaml()
    # headline: identical values to the tables that used to be hard-coded
    assert headline_evidence_weights("ETF") == ORIGINAL_ETF_TABLE == ss.headline_weights("ETF")
    assert headline_evidence_weights("STOCK") == ORIGINAL_STOCK_TABLE == ss.headline_weights("Certificate")
    assert ss.headline_weights("ETF") == document["asset_policies"]["ETF"]["headline_evidence"]
    # actions: the composite weights come from the same file (the old ensemble values, minus the portfolio-drift term)
    config = load_config()
    assert config.models.ensemble["weights"] == document["action_composite"]["weights"]
    assert config.models.ensemble["weights"] == {
        "momentum": 0.155, "trend": 0.115, "risk": 0.14, "relative_strength": 0.0, "toto": 0.21, "timesfm": 0.14,
        "baseline_ml": 0.07, "chatgpt_thesis": 0.07,
    }
    # tuner: every knob reads this file and its current value is the yaml leaf
    registry = load_tuning_registry()
    assert {item.file for item in registry.parameters} == {"score_engine_v3.yaml"}
    for item in registry.parameters:
        assert item.current == _leaf(document, list(item.path)), item.key
    keys = {item.key for item in registry.parameters}
    assert "ensemble.rebalance" not in keys and "score.etf.headline.momentum" in keys
    # no hard-coded table remains anywhere in the code base, and model_settings.yaml carries no weights
    assert not hasattr(ss, "ETF_EVIDENCE_WEIGHTS") and not hasattr(ss, "STOCK_EVIDENCE_WEIGHTS")
    offenders = [
        str(path.relative_to(REPO)) for path in (REPO / "src").rglob("*.py")
        if re.search(r"\b(ETF|STOCK)_EVIDENCE_WEIGHTS\b", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert "weights" not in (yaml.safe_load((CONFIGS / "model_settings.yaml").read_text(encoding="utf-8")) or {}).get("ensemble", {})
    # editing the yaml moves all consumers: they read the file, not a copy
    copy = tmp_path / "configs"
    shutil.copytree(CONFIGS, copy)
    edited = yaml.safe_load((copy / "score_engine_v3.yaml").read_text(encoding="utf-8"))
    edited["asset_policies"]["ETF"]["headline_evidence"]["momentum"] = 0.15
    edited["action_composite"]["weights"]["momentum"] = 0.15
    (copy / "score_engine_v3.yaml").write_text(yaml.safe_dump(edited, sort_keys=False), encoding="utf-8")
    assert headline_evidence_weights("ETF", path=copy / "score_engine_v3.yaml")["momentum"] == 0.15
    assert load_config(copy).models.ensemble["weights"]["momentum"] == 0.15
    assert load_tuning_registry(copy / "tuning_v1.yaml").current_values()["ensemble.momentum"] == 0.15


def test_weights_fail_closed_when_the_yaml_does_not_carry_them(tmp_path: Path) -> None:
    copy = tmp_path / "configs"
    shutil.copytree(CONFIGS, copy)
    document = yaml.safe_load((copy / "score_engine_v3.yaml").read_text(encoding="utf-8"))
    del document["asset_policies"]["ETF"]["headline_evidence"]
    (copy / "score_engine_v3.yaml").write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    with pytest.raises(CanonicalScoreError, match="headline_evidence"):
        headline_evidence_weights("ETF", path=copy / "score_engine_v3.yaml")
    # a second weight source in model_settings.yaml is refused instead of silently winning or losing
    settings = yaml.safe_load((copy / "model_settings.yaml").read_text(encoding="utf-8"))
    settings["ensemble"]["weights"] = {"momentum": 1.0}
    (copy / "model_settings.yaml").write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigError, match="action_composite"):
        load_config(copy)


def _features() -> pd.DataFrame:
    return pd.DataFrame([
        {"etf_id": key, "momentum_20d": .01, "momentum_60d": .02, "momentum_120d": .03 * scale, "momentum_180d": .04,
         "trend_slope": .01 * scale, "trend_100": 1., "trend_200": 1., "vol_60d_ann": .2, "ewma_vol_ann": .2,
         "drawdown_60d_max": -.05, "relative_strength_60d": .02 * scale}
        for key, scale in (("AAA", 1), ("BBB", 2), ("CCC", 3))
    ])


def _allocation(current: float, target: float) -> pd.DataFrame:
    return pd.DataFrame([
        {"etf_id": key, "current_weight": current if key == "AAA" else 0.0, "target_weight": target if key == "AAA" else 0.0,
         "hard_band": .05, "soft_band": .03, "max_weight": .25}
        for key in ("AAA", "BBB", "CCC")
    ])


def test_an_instrument_scores_the_same_under_two_different_portfolios() -> None:
    config = load_config()
    forecasts = {"baseline": {"AAA": .1, "BBB": .2, "CCC": .3}}
    row_by_portfolio = []
    for current, target in ((0.0, 0.0), (0.30, 0.05)):  # on target vs far over target: very different drift
        scored = component_scores(_features(), _allocation(current, target), config, forecast_scores=forecasts)
        row = scored.set_index("etf_id").loc["AAA"].copy()
        row["etf_id"] = "AAA"
        row["price_freshness"] = "ok"
        row["score_etf_exposure"] = 0.2
        canonical = canonical_score_from_signal_row(row, config, "2026-01-06")
        row_by_portfolio.append((row, canonical))
    (low, low_canonical), (high, high_canonical) = row_by_portfolio
    assert low["score_rebalance"] != high["score_rebalance"]  # the drift still exists as a portfolio-view input
    assert low["total_score"] == pytest.approx(high["total_score"])
    assert low_canonical.legacy_composite_raw == pytest.approx(high_canonical.legacy_composite_raw)
    for field in ("attractiveness_10", "risk_implementation_10", "expected_return_10", "coverage", "evidence_confidence_10"):
        assert getattr(low_canonical, field) == getattr(high_canonical, field), field
    assert all(item["key"] != "rebalance" for item in low_canonical.components)
    assert "rebalance" not in _yaml()["action_composite"]["weights"]
    assert all("rebalance" not in group for policy in _yaml()["asset_policies"].values() for group in policy.values())


def test_missing_chatgpt_thesis_lowers_coverage_and_never_contributes_zero() -> None:
    config = load_config()
    base = dict(allocation=_allocation(0.0, 0.0), config=config)
    without = component_scores(_features(), base["allocation"], config)
    supplied = component_scores(_features(), base["allocation"], config, chatgpt_scores={"AAA": 0.0, "BBB": 0.0, "CCC": 0.0})
    assert without["score_chatgpt_thesis"].isna().all()  # never fillna(0.0)
    assert (supplied["score_chatgpt_thesis"] == 0.0).all()  # an explicit 0.0 opinion is a real value
    weights = config.models.ensemble["weights"]
    # PSF: an unavailable model keeps its weight and lowers coverage, so full coverage needs every model forecast too
    every_model = {name: {"AAA": 0.1, "BBB": 0.2, "CCC": 0.3} for name in ("toto", "timesfm", "baseline")}
    full = dict(toto_available=True, timesfm_available=True, forecast_scores=every_model)
    supplied_full = component_scores(_features(), base["allocation"], config, chatgpt_scores={"AAA": 0.0, "BBB": 0.0, "CCC": 0.0}, **full)
    without_full = component_scores(_features(), base["allocation"], config, **full)
    assert (supplied_full["composite_coverage"] == 1.0).all()
    assert (without_full["composite_coverage"] < 1.0).all()
    assert (without["composite_coverage"] < without_full["composite_coverage"]).all()
    # missing != 0: the unscored thesis is excluded from the numerator AND the denominator, not averaged in as zero
    row = without.iloc[0]
    from etf_cockpit.models.ensemble import effective_ensemble_weights

    effective = effective_ensemble_weights(weights, toto_available=False, timesfm_available=False)
    # PSF: unavailable models and the heuristic baseline keep their weight in the table but contribute no score
    retained = {k: w for k, w in effective.items() if w > 0 and k not in {"chatgpt_thesis", "toto", "timesfm", "baseline_ml"}}
    numerator = sum(w * row["score_" + k] for k, w in retained.items())
    assert row["total_score"] == pytest.approx(numerator / sum(retained.values()) - row["cost_penalty"])
    assert row["composite_coverage"] == pytest.approx(sum(retained.values()) / sum(w for w in effective.values() if w > 0))
    zero_filled = numerator / sum(w for w in effective.values() if w > 0) - row["cost_penalty"]
    assert row["total_score"] != pytest.approx(zero_filled)
    # canonical action composite: the thesis component exists, is not eligible when missing, and is when supplied
    # PSF: with no forecast model the heuristic baseline carries no coverage, so the price-only row is unavailable
    price_only = without.set_index("etf_id").loc["AAA"].copy()
    price_only["etf_id"], price_only["price_freshness"] = "AAA", "ok"
    unscored = canonical_score_from_signal_row(price_only, config, "2026-01-06")
    assert unscored.legacy_composite_raw is None and "score_unavailable:insufficient_coverage" in unscored.warnings
    models = dict(toto_available=True, timesfm_available=True)
    signal = without_full.set_index("etf_id").loc["AAA"].copy()
    signal["etf_id"], signal["price_freshness"] = "AAA", "ok"
    absent = canonical_score_from_signal_row(signal, config, "2026-01-06", **models)
    assert absent.legacy_composite_raw == pytest.approx(without_full.iloc[0]["total_score"], abs=1e-3)  # same composite on both paths
    signal_with_thesis = signal.copy()
    signal_with_thesis["score_chatgpt_thesis"] = 0.9
    present = canonical_score_from_signal_row(signal_with_thesis, config, "2026-01-06", **models)
    assert present.legacy_composite_raw != absent.legacy_composite_raw


def _simple(key: str, raw: float, role: str, source_id: str) -> ss.SimpleScoreComponent:
    component = ss._component(key, raw, "fixture", role=role)
    return replace(component, source_id=source_id, as_of_date="2026-01-06", freshness_status="ok", evidence_quality=5.0)


def test_signal_row_and_simple_component_builders_agree_on_the_v3_value() -> None:
    config = load_config()
    values = {"momentum": 0.4, "trend": 0.2, "relative_strength": 0.1, "etf_exposure": 0.3, "risk": 0.25, "baseline": 0.15}
    cost_penalty = 0.02
    row = {
        "etf_id": "AAA", "asset_type": "ETF", "price_freshness": "ok", "score_momentum": values["momentum"],
        "score_trend": values["trend"], "score_relative_strength": values["relative_strength"],
        "score_etf_exposure": values["etf_exposure"], "score_risk": values["risk"], "score_baseline_ml": values["baseline"],
        "score_baseline_source": "forecast",
        "cost_penalty": cost_penalty,
        "score_rebalance": 0.9,  # portfolio drift is not an input of the instrument score
    }
    liquidity = 1.0 - cost_penalty / 0.08
    components = [
        _simple("momentum", values["momentum"], "evidence", "yfinance:prices"),
        _simple("trend", values["trend"], "evidence", "yfinance:prices"),
        _simple("relative_strength", values["relative_strength"], "evidence", "yfinance:prices"),
        _simple("etf_exposure", values["etf_exposure"], "evidence", "yfinance:holdings"),
        _simple("risk", values["risk"], "risk", "yfinance:prices"),
        _simple("liquidity_cost", liquidity, "risk", "yfinance:prices"),
        _simple("baseline", values["baseline"], "model_confirmation", "model:baseline"),
    ]
    from_row = canonical_score_from_signal_row(row, config, "2026-01-06")
    from_components = canonical_score_from_simple_components("AAA", "ETF", "2026-01-06", components, critical_evidence={"identity": None})
    assert from_row.unavailable_reason is None and from_row.attractiveness_10 is not None
    for field in ("attractiveness_10", "risk_implementation_10", "expected_return_10", "evidence_confidence_10", "coverage",
                  "formula_version", "formula_checksum", "unavailable_reason"):
        assert getattr(from_row, field) == getattr(from_components, field), field
    keyed = lambda score: {(item["key"], round(float(item["weight"]), 9), item["score_eligible"], item["raw_metric"]) for item in score.components}  # noqa: E731
    # the signal row also lists its unsupplied inputs (timesfm/toto/thesis) as ineligible; eligible rows are identical
    eligible = lambda score: {item for item in keyed(score) if item[2]}  # noqa: E731
    assert eligible(from_row) == eligible(from_components)


def test_lineage_records_the_v3_yaml_version_and_checksum_for_every_visible_score() -> None:
    policy = load_score_policy("ETF")
    expected_checksum = hashlib.sha256(V3.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert policy.formula_checksum == expected_checksum
    manifest = publication.score_lineage_manifest()
    assert manifest
    for row in manifest:
        assert row["score_engine_version"] == policy.formula_version, (row["field"], row["surface"])
        assert row["score_engine_checksum"] == expected_checksum, (row["field"], row["surface"])
    headline = [row for row in manifest if row["field"] == "final_combined_score_10"]
    assert headline and all(row["weights_source"].startswith("configs/score_engine_v3.yaml") for row in headline)
    assert all(row["config_hash"] == expected_checksum and row["formula_version"] == policy.formula_version for row in headline)
    assert headline[0]["active_weights"] == {"ETF": ORIGINAL_ETF_TABLE, "STOCK": ORIGINAL_STOCK_TABLE}


def test_headline_score_value_is_unchanged_by_moving_the_table_into_the_yaml() -> None:
    components = [
        replace(ss._component(key, raw, "fixture"), as_of_date="2026-01-06", freshness_status="ok")
        for key, raw in (("momentum", 0.4), ("trend", 0.2), ("relative_strength", -0.1), ("risk", 0.3), ("liquidity_cost", 0.5))
    ]
    raw, score = ss.combine_component_scores(components, ORIGINAL_ETF_TABLE)
    assert (raw, score) == ss.combine_component_scores(components, ss.headline_weights("ETF"))
    assert (raw, score) == ss.combine_component_scores(components)
    assert np.isfinite(float(raw))
