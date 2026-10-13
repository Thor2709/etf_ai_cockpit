"""Bughunt C (#952): feature pipeline, feature store, regime freshness. Fixtures only."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.derived_cache import _feature_cache_binding
from etf_cockpit.data.duckdb_store import load_features, write_features
from etf_cockpit.features.feature_pipeline import FEATURE_ALGORITHM_VERSION, compute_features, robust_zscore
from etf_cockpit.features.feature_store import (
    BUILTIN_FEATURES,
    FeatureDefinition,
    FeatureStoreError,
    LocalFeatureStore,
    TargetDefinition,
)
from etf_cockpit.features.regime import build_market_regime, build_portfolio_fit_lookup
from etf_cockpit.signals.strategy_templates import _row_at_decision


# --- C003-N001 -------------------------------------------------------------------------------
def test_mad_zero_keeps_outlier_sign_not_all_zero() -> None:
    result = robust_zscore(pd.Series([0.0, 0.0, 0.2]))
    assert result.iloc[2] > 0 and result.iloc[0] == result.iloc[1] == 0.0  # the outlier is not erased


def test_constant_series_is_unavailable_not_neutral() -> None:
    assert robust_zscore(pd.Series([1.0, 1.0, 1.0])).isna().all()


# --- C003-N002 -------------------------------------------------------------------------------
def test_relative_strength_on_mismatched_calendars_equals_aligned_computation() -> None:
    days = pd.bdate_range("2026-01-01", periods=140)
    own = pd.Series(100.0 * np.exp(np.linspace(0, 0.4, len(days))), index=days)
    bench_days = days[::2]  # sparse benchmark calendar
    bench = pd.Series(100.0 * np.exp(np.linspace(0, 0.2, len(bench_days))), index=bench_days)
    rows = [{"etf_id": "X", "date": d, "adjusted_close": v, "volume": 1.0} for d, v in own.items()]
    rows += [{"etf_id": "B", "date": d, "adjusted_close": v, "volume": 1.0} for d, v in bench.items()]
    features = compute_features(pd.DataFrame(rows), benchmark_etf_id="B")
    got = features[features["etf_id"] == "X"].set_index("date")["relative_strength_60d"]
    bench_asof = bench.reindex(days, method="ffill")
    t, s = days[100], days[40]
    expected = np.log(own[t] / own[s]) - np.log(bench_asof[t] / bench_asof[s])
    assert got[t.date()] == pytest.approx(expected)


# --- C002-N001 / C101-N004 -------------------------------------------------------------------
def _frame(**extra) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "etf_id": ["A", "A"],
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "signal": [1.0, 21.0],
            **extra,
        }
    )


def test_row_available_after_decision_is_excluded_although_observed_before(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    frame = _frame(available_at=pd.to_datetime(["2026-01-01", "2026-01-09"]))
    result = store.materialise(frame, ["2026-01-05"], feature_ids=["signal"])
    assert result.loc[0, "signal"] == 1.0
    assert result.loc[0, "feature_time"] == "2026-01-01"  # observation time only


def test_source_vintage_hash_covers_available_at(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    early = store.materialise(_frame(available_at=pd.to_datetime(["2026-01-01", "2026-01-02"])), ["2026-01-05"], feature_ids=["signal"])
    late = store.materialise(_frame(available_at=pd.to_datetime(["2026-01-01", "2026-01-04"])), ["2026-01-05"], feature_ids=["signal"])
    assert early.loc[0, "signal"] == late.loc[0, "signal"] == 21.0
    assert early.loc[0, "available_at"] != late.loc[0, "available_at"]
    assert early.loc[0, "source_vintage_hash"] != late.loc[0, "source_vintage_hash"]


# --- C101-N002 / N003 / C105-N002 / C01-C2 ---------------------------------------------------
def test_declared_dependency_must_be_materialised(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("derived", "signal", dependencies=("base",)))
    with pytest.raises(FeatureStoreError, match="dependencies"):
        store.materialise(_frame(), ["2026-01-05"], feature_ids=["derived"])


@pytest.mark.parametrize("policy", ["zero", "reject"])
def test_missing_policy_applies_to_present_nan(tmp_path, policy) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal", missing_policy=policy))
    frame = _frame().assign(signal=[1.0, float("nan")])
    if policy == "reject":
        with pytest.raises(FeatureStoreError):
            store.materialise(frame, ["2026-01-05"], feature_ids=["signal"])
        return
    result = store.materialise(frame, ["2026-01-05"], feature_ids=["signal"])
    assert result.loc[0, "signal"] == 0.0 and bool(result.loc[0, "missing_signal"])
    assert store.coverage(result)["coverage"]["signal"] == 0.0  # C01-C2-N002


def test_builtin_feature_ids_cannot_be_shadowed(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    builtin = BUILTIN_FEATURES[0]
    with pytest.raises(FeatureStoreError, match="shadowed"):
        store.register_feature(FeatureDefinition(builtin.feature_id, "other_column"))
    assert store.register_feature(builtin) == builtin


def test_future_target_column_cannot_be_registered_as_research_signal() -> None:
    with pytest.raises(FeatureStoreError):
        FeatureDefinition("research_signal", "future_target")


def test_duplicate_price_index_does_not_crash_targets(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_target(TargetDefinition("fwd1", 1))
    prices = pd.DataFrame(
        {"etf_id": ["A"] * 3, "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]), "adjusted_close": [100.0, 101.0, 102.0]},
        index=[0, 0, 0],
    )
    result = store.build_targets(prices, ["2026-01-01"])
    assert result.loc[0, "fwd1"] == pytest.approx(0.01)


def test_equal_timestamp_revisions_tie_break_deterministically(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    base = pd.DataFrame({"etf_id": ["A", "A"], "date": pd.to_datetime(["2026-01-01"] * 2), "signal": [1.0, 2.0]})
    forward = store.materialise(base, ["2026-01-05"], feature_ids=["signal"])
    backward = store.materialise(base.iloc[::-1].reset_index(drop=True), ["2026-01-05"], feature_ids=["signal"])
    assert forward.loc[0, "signal"] == backward.loc[0, "signal"]


# --- C105-N001 / C005 ------------------------------------------------------------------------
_WINDOW = {"start_date": "2025-12-01", "end_date": "2026-01-01", "decision_time": "2026-01-01T23:59:59+00:00"}


def test_feature_cache_invalidates_when_algorithm_version_changes(tmp_path) -> None:
    path = tmp_path / "features.parquet"
    features = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "etf_id": ["A"], "x": [1.0]})
    prices = pd.DataFrame({"date": ["2026-01-01"], "etf_id": ["A"], "adjusted_close": [1.0], "volume": [10.0]})
    binding = _feature_cache_binding(prices, calculation_window=_WINDOW)
    write_features(features, path, cache_metadata={"universe_revision": "u", "settings_revision": "s", **binding})
    assert not load_features(path, universe_revision="u", settings_revision="s", extra_binding=binding).empty
    stale = {**binding, "feature_algorithm_version": "features-0"}
    assert load_features(path, universe_revision="u", settings_revision="s", extra_binding=stale).empty
    assert binding["feature_algorithm_version"] == FEATURE_ALGORITHM_VERSION


def test_feature_cache_binding_changes_with_volume() -> None:
    base = pd.DataFrame({"date": ["2026-01-01"], "etf_id": ["A"], "adjusted_close": [1.0], "volume": [10.0]})
    revised = base.assign(volume=[99.0])
    assert _feature_cache_binding(base, calculation_window=_WINDOW) != _feature_cache_binding(revised, calculation_window=_WINDOW)


# --- C120-N004 -------------------------------------------------------------------------------
def test_future_price_history_is_dropped_at_the_decision() -> None:
    index = pd.bdate_range("2026-01-01", periods=10)
    history = pd.DataFrame({"A": range(10)}, index=index)
    row = _row_at_decision({"price_history": history}, index[5])
    assert row["price_history"].index.max() == index[5]
    assert _row_at_decision({"price_history": history}, None)["price_history"] is history


# --- C021-N001 / C004 ------------------------------------------------------------------------
def _panel(benchmark_stale_days: int = 0, constant: str | None = None) -> pd.DataFrame:
    days = pd.bdate_range("2025-01-01", periods=260)
    rng = np.random.default_rng(1)
    rows = []
    for etf in ("BENCH", "A", "B"):
        values = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(days))))
        if etf == constant:
            values = np.full(len(days), 100.0)
        for d, v in zip(days, values):
            if etf == "BENCH" and d > days[-1] - pd.Timedelta(days=benchmark_stale_days):
                continue
            rows.append({"etf_id": etf, "date": d, "adjusted_close": v})
    return pd.DataFrame(rows)


@pytest.fixture
def bound_benchmark(monkeypatch):
    import etf_cockpit.features.regime as regime

    monkeypatch.setattr(regime, "validate_benchmark_reference", lambda *a, **k: "BENCH")
    monkeypatch.setattr(regime, "_clip_to_reference_window", lambda prices, reference: prices.copy())


def test_stale_benchmark_makes_regime_unavailable(bound_benchmark) -> None:
    fresh = build_market_regime(_panel(0), benchmark_id="BENCH")
    stale = build_market_regime(_panel(30), benchmark_id="BENCH")
    assert fresh["regime_score_10"] is not None
    assert stale["regime_score_10"] is None and stale["regime_label"] == "Regime unavailable"


def test_undefined_correlation_is_unavailable_not_fit(bound_benchmark) -> None:
    lookup = build_portfolio_fit_lookup(_panel(0, constant="A"), benchmark_id="BENCH")
    assert lookup["A"]["score"] is None
    assert lookup["B"]["score"] is not None


# --- correction pass 1 -----------------------------------------------------------------------
def _breadth_panel() -> pd.DataFrame:
    days = pd.bdate_range("2025-01-01", periods=260)
    rows = []
    for i, d in enumerate(days):
        rows.append({"etf_id": "BENCH", "date": d, "adjusted_close": 100.0 + i * 0.3})
        rows.append({"etf_id": "A", "date": d, "adjusted_close": 100.0 + i * 0.2})
        if i < len(days) - 30:  # B stops 30 sessions before the end and was falling (below its SMA200)
            rows.append({"etf_id": "B", "date": d, "adjusted_close": 300.0 - i * 0.5})
    return pd.DataFrame(rows)


def test_sma_breadth_forward_fill_is_unbounded_by_default_and_capped_when_requested(bound_benchmark) -> None:
    default = build_market_regime(_breadth_panel(), benchmark_id="BENCH")
    capped = build_market_regime(_breadth_panel(), benchmark_id="BENCH", max_forward_fill=5)
    assert default["configured_pct_above_sma200"] == pytest.approx(2 / 3, abs=1e-3)  # stale B close still counted
    assert capped["configured_pct_above_sma200"] == pytest.approx(1.0)  # B is beyond the 5-session cap


def test_price_snapshot_with_conflicting_equal_timestamp_prices_has_no_binding() -> None:
    from etf_cockpit.portfolio.benchmark_reference import adjusted_price_snapshot_binding

    prices = pd.DataFrame({"date": ["2026-01-01"] * 2, "etf_id": ["A"] * 2, "adjusted_close": [1.0, 2.0]})
    assert adjusted_price_snapshot_binding(prices, calculation_window=_WINDOW) is None
    assert adjusted_price_snapshot_binding(prices.iloc[:1], calculation_window=_WINDOW) is not None


def test_equal_timestamp_price_revisions_give_input_order_independent_targets(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_target(TargetDefinition("fwd1", 1))
    base = pd.DataFrame(
        {"etf_id": ["A"] * 4, "date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02"]), "adjusted_close": [100.0, 101.0, 102.0, 103.0]}
    )
    forward = store.build_targets(base, ["2026-01-01"])
    backward = store.build_targets(base.iloc[::-1].reset_index(drop=True), ["2026-01-01"])
    assert forward.loc[0, "fwd1"] == pytest.approx(backward.loc[0, "fwd1"])


def test_volume_cache_binding_is_independent_of_equal_timestamp_row_order() -> None:
    base = pd.DataFrame({"date": ["2026-01-01"] * 2, "etf_id": ["A"] * 2, "adjusted_close": [1.0, 1.0], "volume": [10.0, 20.0]})
    assert _feature_cache_binding(base, calculation_window=_WINDOW) == _feature_cache_binding(base.iloc[::-1], calculation_window=_WINDOW)


def test_feature_catalogue_sample_shows_newest_rows_of_unordered_snapshot(tmp_path) -> None:
    from etf_cockpit.application.ui_views.feature_catalogue import SAMPLE_ROWS, build_feature_catalogue_view

    dates = pd.bdate_range("2026-01-01", periods=SAMPLE_ROWS + 5)
    features = pd.DataFrame({"date": dates[::-1], "etf_id": "A", "return_1d_log": 0.0})  # newest first
    view = build_feature_catalogue_view(tmp_path, features)
    assert [row["date"] for row in view.sample_rows] == list(dates[-SAMPLE_ROWS:])


def test_outcome_column_guard_rejects_outcomes_but_not_forward_looking_ratios() -> None:
    assert FeatureDefinition("fpe", "forward_pe").source_column == "forward_pe"
    for column in ("forward_return_5d", "future_target", "label", "fwd_ret"):
        with pytest.raises(FeatureStoreError):
            FeatureDefinition("x", column)


def test_price_history_series_is_dropped_at_the_decision() -> None:
    index = pd.bdate_range("2026-01-01", periods=10)
    series = pd.Series(range(10), index=index)
    assert _row_at_decision({"price_history": series}, index[5])["price_history"].index.max() == index[5]
