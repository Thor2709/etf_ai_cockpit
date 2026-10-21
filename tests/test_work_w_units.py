"""Work-W owner-audit regressions; deterministic arrays/stubs, no model weights."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import (
    ForecastService, _postprocess_forecast_benchmark_fields, _timesfm_price_series,
)
from etf_cockpit.core.config import ModelRuntimeConfig, load_config
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.ensemble import effective_ensemble_weights
from etf_cockpit.models.timesfm_adapter import (
    TimesFMAdapter, _clean_positive_series, _quantile_vol_proxy,
    probability_positive_return, timesfm_level_forecast_to_results,
)
from etf_cockpit.models.timesfm3_adapter import TimesFM3Adapter
from etf_cockpit.models.toto_adapter import toto_quantiles_to_log_return_results
from etf_cockpit.signals.scoring import component_scores


DAY = date(2026, 1, 30)


def _row(point=102.0, quantiles=None, horizon=1, model_name="timesfm"):
    return timesfm_level_forecast_to_results(
        mean_predictions=np.repeat(point, horizon), quantile_predictions=quantiles,
        last_value=100.0, horizons=[horizon], etf_id="AAA", forecast_date=DAY,
        run_id="work-w-test", model_version="test", model_name=model_name,
    )[0]


def test_probability_interpolates_own_cdf_and_clamps_tails():
    # Positive median does not imply certainty. Zero lies halfway between q10/q50.
    assert probability_positive_return(-0.02, 0.02, 0.06) == pytest.approx(0.7)
    assert probability_positive_return(None, 0.02, None) is None
    assert probability_positive_return(0.01, 0.02, 0.03) == pytest.approx(0.9)
    assert probability_positive_return(-0.03, -0.02, -0.01) == pytest.approx(0.1)
    assert probability_positive_return(0.02, -0.02, 0.06) is None
    assert probability_positive_return(-0.02, np.nan, 0.06) is None
    assert probability_positive_return(-0.02, 0.02, 0.06, {}) is None
    assert probability_positive_return(0.0, 0.0, 0.0) == pytest.approx(0.1)


@pytest.mark.parametrize("model_name", ["timesfm", "timesfm3"])
def test_timesfm_probability_uses_row_quantiles_and_labels_median(model_name):
    returns = np.array([-0.04, -0.03, -0.02, -0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
    row = _row(quantiles=100 * np.exp(returns)[None, :], model_name=model_name)
    assert row.status == "ok" and row.point_statistic == "median"
    assert row.distribution_status == "available"
    # q25 is -.025; q50 is .02, so interpolate their CDF at zero.
    expected = 1 - (0.25 + 0.025 / 0.045 * 0.25)
    # The CDF value is a heuristic score until calibration for this model, target and horizon is admitted.
    assert row.prob_positive_return is None
    assert 0 < row.heuristic_probability_positive < 1
    assert row.heuristic_probability_positive == pytest.approx(expected)
    no_quantiles = _row(model_name=model_name)
    assert no_quantiles.status == "ok" and no_quantiles.point_statistic == "median"
    assert no_quantiles.prob_positive_return is None and no_quantiles.heuristic_probability_positive is None
    assert no_quantiles.distribution_status == "unavailable"


def test_toto_probability_uses_same_cdf():
    quantiles = np.array([-0.04, -0.03, -0.02, -0.01, 0.02, 0.03, 0.04, 0.05, 0.06]).reshape(9, 1, 1, 1)
    row = toto_quantiles_to_log_return_results(
        quantiles=quantiles, horizons=[1], etf_id="AAA", forecast_date=DAY,
        run_id="work-w-test", model_version="test",
    )[0]
    assert row.prob_positive_return is None
    assert row.heuristic_probability_positive == pytest.approx(1 - (0.25 + 0.025 / 0.045 * 0.25))
    assert row.forecast_vol == pytest.approx((0.06 - -0.04) / 2 / 1.2816)


def test_sixty_day_baseline_and_timesfm_have_identical_units_and_benchmark_probability():
    index = pd.bdate_range(end=DAY, periods=100)
    series = pd.Series(100 * np.exp(np.cumsum(0.001 + 0.01 * np.sin(np.arange(100)))), index=index)
    baseline = baseline_forecast("AAA", series, [60], DAY, "work-w-test")[0]
    deciles = np.interp(np.arange(1, 10) / 10, [0.1, 0.5, 0.9],
                        [baseline.q10_return, baseline.q50_return, baseline.q90_return])
    levels = np.repeat((100 * np.exp(deciles))[None, :], 60, axis=0)
    timesfm = _row(100 * np.exp(baseline.expected_return), levels, horizon=60)
    assert timesfm.forecast_vol == pytest.approx(baseline.forecast_vol, abs=1e-14)
    assert baseline.forecast_vol == pytest.approx((baseline.q90_return - baseline.q10_return) / 2 / 1.2816)
    processed = _postprocess_forecast_benchmark_fields([timesfm, baseline], pd.Series([0.001] * 100))
    assert processed[0].heuristic_probability_beat_benchmark == pytest.approx(processed[1].heuristic_probability_beat_benchmark, abs=1e-14)
    assert _quantile_vol_proxy(np.nan, 0.1, 60) is None
    assert _quantile_vol_proxy(0.1, -0.1, 60) is None
    # A very adverse benchmark must saturate safely without exp overflow.
    assert _postprocess_forecast_benchmark_fields([timesfm], pd.Series([1e6]))[0].heuristic_probability_beat_benchmark == 0


@pytest.mark.parametrize("bad_level", [-1.0, 0.0, np.nan, np.inf])
@pytest.mark.parametrize("bad_quantile", [False, True])
def test_invalid_predicted_levels_are_unavailable(bad_level, bad_quantile):
    levels = np.linspace(95, 105, 9)[None, :]
    if bad_quantile:
        levels[0, 1] = bad_level
    row = _row(102.0 if bad_quantile else bad_level, levels)
    assert row.status == "unavailable" and row.expected_return is None
    assert row.reason_unavailable and "invalid predicted level" in row.reason_unavailable
    assert not row.model_allowed_in_score


@pytest.mark.parametrize("adapter_type", [TimesFMAdapter, TimesFM3Adapter])
def test_official_context_retains_internal_missing_session(adapter_type, monkeypatch):
    series = pd.Series(np.arange(100.0, 164.0), index=pd.bdate_range(end=DAY, periods=64))
    series.iloc[20] = np.nan
    adapter = adapter_type(ModelRuntimeConfig(enabled=True, mode="live", backend="official", context_length=64))
    monkeypatch.setattr(adapter, "is_available", lambda: True)
    seen = {}
    if adapter_type is TimesFMAdapter:
        adapter._runtime_backend = "timesfm"
        def forecast(horizon, inputs):
            seen["values"] = inputs[0]
            return np.repeat(164.0, horizon)[None, :], None
        adapter._model = SimpleNamespace(forecast=forecast)
    else:
        adapter._runtime_backend = "timesfm3"
        def predict(context, horizon, **kwargs):
            seen["values"] = context
            return SimpleNamespace(forecast=np.repeat(164.0, horizon), quantiles=None)
        adapter._model = SimpleNamespace(predict=predict)
    row = adapter.forecast_series(series, [5], forecast_date=DAY)[0]
    assert row.status == "ok" and len(seen["values"]) == 64
    assert np.isnan(seen["values"][20]) and seen["values"][21] == 121
    assert row.coverage_ratio == pytest.approx(61 / 252)
    pd.testing.assert_series_equal(_clean_positive_series(series), series)


def test_transformers_missing_session_is_unavailable_without_compression(monkeypatch):
    series = pd.Series(100.0, index=pd.bdate_range(end=DAY, periods=64))
    series.iloc[20] = np.nan
    adapter = TimesFMAdapter(ModelRuntimeConfig(enabled=True, mode="live", backend="transformers"))
    monkeypatch.setattr(adapter, "is_available", lambda: True)
    adapter._runtime_backend = "transformers"
    adapter._model = object()
    row = adapter.forecast_series(series, [5], forecast_date=DAY)[0]
    assert row.status == "unavailable" and "NaN-context" in row.reason_unavailable


def _pivot(rows):
    pivot = rows.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
    pivot.attrs["timesfm_price_rows"] = {key: group for key, group in rows.groupby("etf_id")}
    return pivot


def test_service_never_invents_or_interpolates_sessions_without_calendar(monkeypatch):
    rows = pd.DataFrame({"date": pd.bdate_range("2026-01-26", periods=5), "etf_id": "AAA",
                         "adjusted_close": [100, 101, np.nan, 103, 104]})
    pivot = _pivot(rows)
    series = _timesfm_price_series(pivot, "AAA", DAY)
    # No certified calendar: a NaN row may be a holiday row, so it is dropped, never interpolated.
    assert len(series) == 4 and not series.isna().any()
    seen = {}
    def forecast(self, series, horizons, **kwargs):
        seen["series"] = series
        return []
    monkeypatch.setattr(TimesFMAdapter, "forecast_series", forecast)
    ForecastService(load_config())._run_timesfm_forecasts(pivot, ["AAA"], [1], DAY, "work-w-test")
    pd.testing.assert_series_equal(seen["series"], series)
    # An absent date is a non-session: never invented as a gap, never disables the model.
    absent = _timesfm_price_series(_pivot(rows.drop(index=2)), "AAA", DAY)
    assert len(absent) == 4 and not absent.isna().any()
    assert pd.Timestamp("2026-01-28") not in absent.index


def test_certified_calendar_excludes_holiday_and_restores_missing_session():
    # XNYS Christmas is a closure; Dec 24 is a missing trading session.
    identity = {
        "status": "available", "instrument_id": "AAA", "identity_decision_id": "work-w-fixture",
        "identity_decision_time": "2025-01-01T00:00:00+00:00", "identity_effective_at": "2025-01-01",
        "identity_objects": [{"object_type": "listing", "object_id": "work-w-listing",
                              "fields": {"mic": "XNYS", "calendar_id": "XNYS", "timezone": "America/New_York"}}],
        "identity_history": [{"source_id": "work-w-test"}],
    }
    rows = pd.DataFrame({"date": pd.to_datetime(["2025-12-23", "2025-12-26"]),
                         "etf_id": "AAA", "adjusted_close": [100.0, 101.0],
                         "calendar_identity": [identity, identity]})
    series = _timesfm_price_series(_pivot(rows), "AAA", date(2025, 12, 26))
    assert list(series.index.day) == [23, 24, 26] and pd.isna(series.iloc[1])
    future = dict(identity, identity_decision_time="2026-01-01T00:00:00+00:00")
    rows["calendar_identity"] = [future, future]
    with pytest.raises(ValueError, match="calendar unavailable"):
        _timesfm_price_series(_pivot(rows), "AAA", date(2025, 12, 26))
    wrong_instrument = dict(identity, instrument_id="BBB")
    rows["calendar_identity"] = [wrong_instrument, wrong_instrument]
    with pytest.raises(ValueError, match="does not match"):
        _timesfm_price_series(_pivot(rows), "AAA", date(2025, 12, 26))
    later_listing = dict(identity, identity_effective_at="2025-12-26")
    rows["calendar_identity"] = [later_listing, later_listing]
    with pytest.raises(ValueError, match="historical context"):
        _timesfm_price_series(_pivot(rows), "AAA", date(2025, 12, 26))
    conflicting_observation = pd.DataFrame({"date": pd.to_datetime(["2025-12-23", "2025-12-25", "2025-12-26"]),
                                           "etf_id": "AAA", "adjusted_close": [100., 101., 102.],
                                           "calendar_identity": [identity] * 3})
    # An observed price on a certified closure is kept as evidence of a session;
    # the certified missing session (Dec 24) is still restored as a gap.
    kept = _timesfm_price_series(_pivot(conflicting_observation), "AAA", date(2025, 12, 26))
    assert list(kept.index.day) == [23, 24, 25, 26] and pd.isna(kept.iloc[1]) and kept.iloc[2] == 101.0
    # A NaN row on a certified closure is not a session and is dropped.
    nan_on_closure = conflicting_observation.assign(adjusted_close=[100., np.nan, 102.])
    dropped = _timesfm_price_series(_pivot(nan_on_closure), "AAA", date(2025, 12, 26))
    assert list(dropped.index.day) == [23, 24, 26]


@pytest.mark.parametrize("missing_value", [None, np.nan, np.inf, -np.inf])
def test_scoring_renormalises_per_instrument_and_preserves_complete_score(missing_value):
    features = pd.DataFrame([
        {"etf_id": key, "momentum_20d": .01, "momentum_60d": .02,
         "momentum_120d": .03 * scale, "momentum_180d": .04,
         "trend_slope": .01 * scale, "trend_100": 1., "trend_200": 1.,
         "vol_60d_ann": .2, "ewma_vol_ann": .2, "drawdown_60d_max": -.05,
         "relative_strength_60d": .02 * scale} for key, scale in [("AAA", 1), ("BBB", 2)]
    ])
    allocation = pd.DataFrame([
        {"etf_id": key, "current_weight": 0., "target_weight": 0., "hard_band": .05,
         "soft_band": .03, "max_weight": .25} for key in ["AAA", "BBB"]
    ])
    config = load_config()
    scores = {"toto": {"AAA": .5, "BBB": .4}, "baseline": {"AAA": .1, "BBB": .2}}
    complete = component_scores(features, allocation, config, toto_available=True, forecast_scores=scores)
    if missing_value is None:
        del scores["toto"]["BBB"]
    else:
        scores["toto"]["BBB"] = missing_value
    partial = component_scores(features, allocation, config, toto_available=True, forecast_scores=scores)
    assert np.isfinite(partial["total_score"]).all()
    assert partial["score_toto"].dtype.kind == "f" and np.isnan(partial.iloc[1].score_toto)
    assert partial.iloc[0].total_score == complete.iloc[0].total_score
    assert "model_missing:toto" in partial.iloc[1].score_unavailable_reason_codes
    assert "model_missing:toto" not in partial.iloc[0].score_unavailable_reason_codes
    weights = effective_ensemble_weights(config.models.ensemble["weights"], toto_available=True, timesfm_available=False)
    # NS1: the unsupplied manual thesis is NaN (not eligible), never 0.0, so it leaves the denominator as well.
    retained = {key: weight for key, weight in weights.items()
                if weight > 0 and key != "toto" and "score_" + key in partial and np.isfinite(partial.iloc[1]["score_" + key])}
    assert "chatgpt_thesis" not in retained
    expected = sum(weight * partial.iloc[1]["score_" + key] for key, weight in retained.items())
    assert partial.iloc[1].total_score == pytest.approx(expected / sum(retained.values()) - partial.iloc[1].cost_penalty)
