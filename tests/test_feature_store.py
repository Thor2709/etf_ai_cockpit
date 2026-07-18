from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from etf_cockpit.features.feature_store import (
    FeatureDefinition,
    FeatureStoreError,
    LocalFeatureStore,
    TargetDefinition,
)


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "etf_id": ["AAA", "AAA", "AAA", "BBB"],
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-02"]),
            "signal": [1.0, 2.0, 3.0, 10.0],
            "future_target": [99.0, 98.0, 97.0, 96.0],
        }
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "etf_id": ["AAA"] * 5,
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]),
            "adjusted_close": [100.0, 101.0, 99.0, 102.0, 104.0],
        }
    )


def test_materialise_uses_only_rows_available_at_decision_time_and_is_reproducible(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal", availability_delay_days=1, units="score"))

    first = store.materialise(_features(), [date(2026, 1, 2)], feature_ids=["signal"])
    second = store.materialise(_features(), [date(2026, 1, 2)], feature_ids=["signal"])

    assert first.loc[0, "signal"] == 1.0
    assert "future_target" not in first.columns
    assert first.equals(second)
    assert first.attrs["execution_allowed"] is False
    assert first.loc[0, "feature_time"] == "2026-01-01"


def test_availability_timestamp_prevents_late_revision_from_leaking(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    frame = _features().assign(available_at=pd.to_datetime(["2026-01-01", "2026-01-05", "2026-01-04", "2026-01-02"]))

    result = store.materialise(frame, ["2026-01-03"], feature_ids=["signal"])

    assert result.loc[0, "signal"] == 1.0


def test_materialise_preserves_non_default_source_indexes(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))

    result = store.materialise(_features().set_axis([10, 20, 30, 40]), ["2026-01-03"], feature_ids=["signal"])

    assert result.loc[0, "signal"] == 3.0


def test_missing_policy_is_explicit(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal", availability_delay_days=10, missing_policy="zero"))

    result = store.materialise(_features(), ["2026-01-03"], feature_ids=["signal"])

    assert result.loc[0, "signal"] == 0.0
    assert bool(result.loc[0, "missing_signal"])

    store.register_feature(FeatureDefinition("strict", "signal", availability_delay_days=10, missing_policy="reject"))
    with pytest.raises(FeatureStoreError, match="unavailable"):
        store.materialise(_features(), ["2026-01-03"], feature_ids=["strict"])


def test_targets_are_separate_and_use_adjusted_prices(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_target(TargetDefinition("return_2d", 2))

    targets = store.build_targets(_prices(), ["2026-01-01"], target_ids=["return_2d"])

    assert targets.loc[0, "return_2d"] == pytest.approx(-0.01)
    assert "signal" not in targets.columns
    assert targets.loc[0, "return_2d__embargo_until"] == "2026-01-03"

    unadjusted = _prices().assign(is_adjusted=False)
    with pytest.raises(FeatureStoreError, match="unadjusted"):
        store.build_targets(unadjusted, ["2026-01-01"], target_ids=["return_2d"])


def test_excess_drawdown_and_event_targets_are_supported(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_target(TargetDefinition("excess", 2, kind="excess_return"))
    store.register_target(TargetDefinition("drawdown", 3, kind="drawdown"))
    store.register_target(TargetDefinition("event", 2, kind="event", event_threshold=0.01))
    benchmark = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=5), "adjusted_close": [100, 100, 100, 100, 100]})

    targets = store.build_targets(_prices(), ["2026-01-01"], benchmark_prices=benchmark)

    assert targets.loc[0, "excess"] == pytest.approx(-0.01)
    assert targets.loc[0, "drawdown"] == pytest.approx(-0.01)
    assert targets.loc[0, "event"] is False or bool(targets.loc[0, "event"]) is False


def test_leakage_check_detects_target_overlap_and_coverage_drift(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    store.register_target(TargetDefinition("return_2d", 2, embargo_days=1))
    targets = store.build_targets(_prices(), ["2026-01-01", "2026-01-02"], target_ids=["return_2d"])

    check = store.leakage_check(targets, "return_2d", validation_start="2026-01-03")
    matrix = store.materialise(_features(), ["2026-01-02", "2026-01-03"], feature_ids=["signal"])
    coverage = store.coverage(matrix)
    drift = store.drift(matrix.iloc[:1], matrix.iloc[1:], ["signal"])

    assert not check.safe
    assert check.overlapping_rows == 2
    assert coverage["coverage"]["signal"] == 1.0
    assert drift["feature_count"] == 1


def test_registry_survives_restart_and_inference_modes_share_contract(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    definition = FeatureDefinition("signal", "signal")
    store.register_feature(definition)
    del store
    restarted = LocalFeatureStore(tmp_path)

    offline = restarted.materialise(_features(), ["2026-01-02"], feature_ids=["signal"], mode="offline")
    paper = restarted.materialise(_features(), ["2026-01-02"], feature_ids=["signal"], mode="paper")
    live = restarted.materialise(_features(), ["2026-01-02"], feature_ids=["signal"], mode="live")

    assert restarted.feature_catalogue(include_builtins=False) == (definition,)
    assert offline.drop(columns="inference_mode").equals(paper.drop(columns="inference_mode"))
    assert offline.drop(columns="inference_mode").equals(live.drop(columns="inference_mode"))
