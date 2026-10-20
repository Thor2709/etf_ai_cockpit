"""Issue #972: native guards for forecast origins, sessions and training evidence."""
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import etf_cockpit.application.forecast_service as service_module
from etf_cockpit.application.forecast_service import ForecastService, _postprocess_forecast_benchmark_fields
from etf_cockpit.core.config import ModelRuntimeConfig, load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.features.forecast_lab import _pooled_mase
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.model_zoo import run_model_zoo
from etf_cockpit.models.toto_adapter import TotoAdapter


def _identity():
    return {"status": "available", "instrument_id": "AAA", "identity_decision_id": "fixture-972",
            "identity_decision_time": "2024-01-01T00:00:00+00:00", "identity_effective_at": "2024-01-01",
            "identity_history": [{"source_id": "fixture-972"}],
            "identity_objects": [{"object_type": "listing", "object_id": "fixture-AAA-XNYS",
                                  "fields": {"mic": "XNYS", "calendar_id": "XNYS", "timezone": "America/New_York"}}]}


def _series(count=181):
    return pd.Series(100 * np.exp(np.arange(count) * .001), index=pd.bdate_range(end="2026-03-06", periods=count))


def _frame(series):
    return pd.DataFrame({"date": series.index.strftime("%Y-%m-%d"), "etf_id": "AAA",
                         "adjusted_close": series.to_numpy(), "calendar_identity": [_identity()] * len(series)})


@pytest.fixture
def service(monkeypatch):
    config = load_config()
    config.models.promotion.enabled = False
    context = SimpleNamespace(resolution=None, benchmark_data_id=None, identity={})
    instance = ForecastService(config, reference_context=context)
    monkeypatch.setattr(service_module, "ensure_run_manifest", lambda *a, **k: None)
    monkeypatch.setattr(instance, "_run_timesfm_forecasts", lambda *a, **k: [])
    monkeypatch.setattr(instance, "_run_toto_forecasts", lambda *a, **k: [])
    monkeypatch.setattr(instance, "_evidence_gated_forecasts", lambda rows, *a: rows)
    monkeypatch.setattr(instance, "_probability_statuses", lambda *a: {})
    monkeypatch.setattr(instance, "_write_forecasts", lambda *a, **k: None)
    return instance


def test_c011_n001_sparse_sessions_never_become_daily_returns(service):
    rows = service.run_forecasts(date(2026, 3, 6), ["AAA"], _frame(_series().iloc[::5]), horizons=[60])
    assert rows[0].status == "unavailable"
    assert rows[0].expected_return is None
    assert rows[0].reason_unavailable == "sparse_adjusted_price_session_history"


def test_c011_n001_direct_baseline_rejects_sparse_history():
    prices = _series()
    last = prices.index[-1].date()
    assert baseline_forecast("AAA", prices.iloc[::5], [60], last, "r") == []
    assert baseline_forecast("AAA", prices, [60], last, "r")[0].status == "ok"
    # Session-grid NaN holes (non-NaN density still above 90%) are not sparse.
    holed = prices.copy()
    holed.iloc[100] = np.nan
    assert baseline_forecast("AAA", holed, [60], last, "r")[0].status == "ok"


def test_plain_price_frame_without_calendar_evidence_keeps_ok_baselines(service):
    plain = _frame(_series()).drop(columns="calendar_identity")
    rows = service.run_forecasts(date(2026, 3, 6), ["AAA"], plain, horizons=[5])
    assert rows[0].status == "ok" and rows[0].forecast_date == date(2026, 3, 6)
    sparse = service.run_forecasts(date(2026, 3, 6), ["AAA"], plain.iloc[::5], horizons=[5])
    assert sparse[0].status == "unavailable" and sparse[0].reason_unavailable == "sparse_adjusted_price_session_history"
    stale = service.run_forecasts(date(2026, 4, 6), ["AAA"], plain, horizons=[5])
    assert stale[0].status == "unavailable"
    # One missing certified session is a gap in the series, not a reason to blank the instrument.
    holed = service.run_forecasts(date(2026, 3, 6), ["AAA"], _frame(_series()).drop(index=100), horizons=[5])
    assert holed[0].status == "ok"


def test_c011_n002_weekend_origin_is_last_price(service):
    rows = service.run_forecasts(date(2026, 3, 8), ["AAA"], _frame(_series()), horizons=[1])
    assert rows[0].forecast_date == date(2026, 3, 6)


def test_c011_n003_run_identity_binds_horizon_prices_settings(service, monkeypatch):
    prices = _frame(_series())
    def run(h=5, frame=prices):
        return service.run_forecasts(date(2026, 3, 6), ["AAA"], frame, horizons=[h])[0].run_id
    first = run()
    assert first == run()
    assert first != run(20)
    revised = prices.copy()
    revised.loc[0, "adjusted_close"] *= 1.1
    assert first != run(frame=revised)
    identity = {**service_module.current_settings_identity(), "settings_revision": "b" * 64}
    monkeypatch.setattr(service_module, "current_settings_identity", lambda: identity)
    assert first != run()


def test_c107_n001_research_forecasts_exclude_post_origin_prices():
    prices = _series()
    origin = prices.index[-20].date()
    before = run_model_zoo(prices.iloc[:-19], [5], forecast_date=origin)
    after = run_model_zoo(prices, [5], forecast_date=origin)
    pd.testing.assert_frame_equal(before, after)


def test_model_zoo_forecast_origin_requires_dated_prices():
    undated = pd.Series(_series().to_numpy())
    with pytest.raises(ValueError, match="dated adjusted_close"):
        run_model_zoo(undated, [5], forecast_date=date(2026, 3, 6))
    assert not run_model_zoo(undated, [5]).empty  # origin-less callers keep the ordinal contract


def test_c107_n002_ar1_recurses_each_future_step():
    returns = np.array([.03, -.02, .015, -.01, .007, -.005])
    prices = pd.Series(100 * np.exp(np.r_[0., returns.cumsum()]))
    coefficient = np.dot(returns[:-1], returns[1:]) / (np.dot(returns[:-1], returns[:-1]) + 1e-6)
    expected = sum(returns[-1] * coefficient ** step for step in range(1, 11))
    row = run_model_zoo(prices, [10], model_ids=["econometric_ar"]).iloc[0]
    assert row.expected_return == pytest.approx(expected)


def test_c107_n003_fractional_horizon_is_rejected():
    with pytest.raises(ValueError, match="horizon"):
        run_model_zoo(_series(), [1.5])


def test_c111_n001_date_only_close_not_available_before_exchange_close(service, monkeypatch):
    prices = _frame(_series())
    monkeypatch.setattr(service_module, "_calculation_window", lambda *a: {
        "start_date": "2025-01-01", "end_date": "2026-03-06", "decision_time": "2026-03-06T17:00:00+00:00"})
    row = service.run_forecasts(date(2026, 3, 6), ["AAA"], prices, horizons=[1])[0]
    assert row.forecast_date == date(2026, 3, 5)


def test_c111_n002_direct_baseline_benchmark_is_bounded_at_origin():
    prices = _series()
    benchmark = pd.Series(.001, index=prices.index)
    before = baseline_forecast("AAA", prices, [5], prices.index[-1].date(), "r", benchmark)[0]
    future = pd.Series([100.], index=[pd.Timestamp("2027-01-01")])
    after = baseline_forecast("AAA", prices, [5], prices.index[-1].date(), "r", pd.concat([benchmark, future]))[0]
    assert before.expected_excess_return == pytest.approx(after.expected_excess_return)


def test_c111_n003_toto_keeps_target_return_across_union_holiday():
    prices = pd.DataFrame({"date": ["2026-03-02", "2026-03-04", "2026-03-03"],
                           "etf_id": ["AAA", "AAA", "BBB"], "adjusted_close": [100., 110., 200.]})
    returns = TotoAdapter(ModelRuntimeConfig(enabled=True, mode="mock"))._return_history(date(2026, 3, 4), prices)
    assert returns.loc[date(2026, 3, 4), "AAA"] == pytest.approx(np.log(1.1))


def test_c022_n003_mase_uses_only_training_prices():
    series = _series(40)
    rows = pd.DataFrame({"etf_id": ["AAA"], "forecast_date": [series.index[25]], "horizon_days": [5], "absolute_error": [.1]})
    prices = series.rename("adjusted_close").to_frame()
    before = _pooled_mase(rows, {"AAA": prices.iloc[:26]})
    revised = prices.copy()
    revised.iloc[31:, 0] *= np.arange(1, 10)
    assert before is not None
    assert _pooled_mase(rows, {"AAA": revised}) == pytest.approx(before)
    # Rows without a usable scale are left out of the pool, not allowed to blank it.
    mixed = pd.concat([rows, rows.assign(etf_id="ZZZ")], ignore_index=True)
    assert _pooled_mase(mixed, {"AAA": prices.iloc[:26]}) == pytest.approx(before)
    assert _pooled_mase(rows.assign(etf_id="ZZZ"), {"AAA": prices}) is None


def test_c07_c2_n001_tiny_volatility_probability_saturates_safely():
    row = ForecastResult(run_id="r", model_name="baseline", model_version="v", etf_id="AAA",
                         forecast_date=date(2026, 3, 6), horizon_days=5, expected_return=-1.,
                         expected_excess_return=None, forecast_vol=1e-300)
    actual = _postprocess_forecast_benchmark_fields([row], pd.Series([1.]))[0]
    assert actual.heuristic_probability_beat_benchmark == 0.


def test_c07_c2_n002_asset_and_benchmark_share_training_window():
    prices = _series(21)
    benchmark = pd.Series(1., index=pd.bdate_range(end=prices.index[-1], periods=181))
    benchmark.loc[prices.index] = .001
    row = baseline_forecast("AAA", prices, [5], prices.index[-1].date(), "r", benchmark)[0]
    assert row.expected_excess_return == pytest.approx(0., abs=1e-12)


def test_c07_c2_n003_stale_baseline_history_is_unavailable():
    rows = baseline_forecast("AAA", _series(), [5], date(2026, 6, 1), "r")
    assert not rows or all(row.status == "unavailable" and row.expected_return is None for row in rows)


def test_c07_c2_n004_model_zoo_sorts_dates_before_drift():
    prices = _series()
    pd.testing.assert_frame_equal(run_model_zoo(prices, [5]), run_model_zoo(prices.iloc[::-1], [5]))


def test_c07_c2_n005_flat_prices_never_emit_saturated_benchmark_score():
    prices = pd.Series(100., index=_series().index)
    benchmark = pd.Series(.001, index=prices.index)
    row = baseline_forecast("AAA", prices, [5], prices.index[-1].date(), "r", benchmark)[0]
    assert row.forecast_vol == 0.
    assert row.expected_excess_return is not None and row.expected_excess_return != 0.
    assert row.heuristic_probability_beat_benchmark is None
    actual = _postprocess_forecast_benchmark_fields([row], benchmark)[0]
    assert actual.heuristic_probability_beat_benchmark is None
    assert actual.expected_excess_return == row.expected_excess_return


@pytest.mark.parametrize("bad_vol", [0., float("nan"), -1.])
def test_c07_c2_n005_service_guard_still_applies_to_baseline_rows(bad_vol):
    benchmark = pd.Series(.001, index=_series().index)
    row = ForecastResult(run_id="r", model_name="baseline", model_version="v", etf_id="AAA",
                         forecast_date=date(2026, 3, 6), horizon_days=5, expected_return=.01,
                         expected_excess_return=.005, forecast_vol=bad_vol,
                         heuristic_probability_beat_benchmark=1.)
    actual = _postprocess_forecast_benchmark_fields([row], benchmark)[0]
    assert actual.heuristic_probability_beat_benchmark is None
    assert actual.prob_beat_benchmark is None
    assert actual.expected_excess_return == .005
    assert "forecast_vol_unavailable_for_benchmark_probability" in (actual.reason_unavailable or "")
