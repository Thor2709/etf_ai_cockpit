"""Owner regressions A/F/G/F11: fake torch keeps these runnable without torch."""

import sys
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import ForecastService
from etf_cockpit.core.config import ModelRuntimeConfig
from etf_cockpit.models.toto_adapter import TotoAdapter, toto_quantiles_to_log_return_results


class PeerModel:
    """Peers affect a target only through Toto2's group-id equality mask."""

    def __init__(self):
        self.calls = []

    def forecast(self, inputs, horizon, **kwargs):
        self.calls.append(({key: value.copy() for key, value in inputs.items()}, kwargs))
        values, mask = inputs["target"][0], inputs["target_mask"][0]
        ids = inputs["series_ids"][0]
        counts = mask.sum(axis=1)
        means = np.divide((values * mask).sum(axis=1), counts,
                          out=np.zeros(len(counts)), where=counts > 0)
        related = (ids[:, None] == ids[None, :]) & (counts[None, :] > 0)
        np.fill_diagonal(related, False)
        median = means + 0.35 * (related * means[None, :]).sum(axis=1)
        daily = median[None, :] + np.arange(-4, 5)[:, None] * 0.001
        return np.repeat(daily[:, None, :, None], horizon, axis=3)


@pytest.fixture
def runtime(monkeypatch):
    # Only the tensor operations the adapter uses; importing real torch is unnecessary.
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        tensor=lambda values, **kwargs: np.asarray(values),
        zeros=lambda shape, **kwargs: np.zeros(shape, dtype=np.int64),
        float32=np.float32, bool=np.bool_, long=np.int64, no_grad=nullcontext,
    ))
    monkeypatch.setattr(TotoAdapter, "_patch_size", lambda self: 2)
    monkeypatch.setattr(TotoAdapter, "is_available", lambda self: True)
    config = ModelRuntimeConfig(enabled=True, mode="live", context_length=8)
    model = PeerModel()

    def load(adapter):
        adapter._model = model

    monkeypatch.setattr(TotoAdapter, "load_model", load)
    return config, model


def prices():
    days = pd.date_range("2025-01-01", periods=9)
    return pd.concat([
        pd.DataFrame({"date": days, "etf_id": name,
                      "adjusted_close": 100 * np.exp(np.arange(len(days)) * daily)})
        for name, daily in [("A", 0.001), ("B", 0.002), ("C", 0.003)]
    ], ignore_index=True)


def run_service(config, frame, targets):
    service = ForecastService(SimpleNamespace(models=SimpleNamespace(runtime=lambda name: config)))
    return service._run_toto_forecasts(frame, targets, [1, 3], date(2025, 1, 9), "work-u")


def test_universe_group_ids_and_fully_unobserved_peer_mask(runtime):
    config, model = runtime
    frame = prices()
    frame.loc[frame.etf_id == "C", "adjusted_close"] = np.nan
    rows = run_service(config, frame, ["B", "A"])
    assert all(row.status == "ok" for row in rows)
    inputs, kwargs = model.calls[0]
    np.testing.assert_array_equal(inputs["series_ids"], np.zeros((1, 3), dtype=int))
    assert (inputs["series_ids"][0, :, None] == inputs["series_ids"][0, None, :]).all()
    assert not inputs["target_mask"][0, 2].any()
    assert inputs["target_mask"][0, :2].all()
    assert kwargs["has_missing_values"] is True


def test_peer_perturbation_changes_target_forecast(runtime):
    config, model = runtime
    original = run_service(config, prices(), ["A"])[0]
    changed = prices()
    changed.loc[changed.etf_id == "B", "adjusted_close"] *= np.exp(np.arange(9) * 0.02)
    perturbed = run_service(config, changed, ["A"])[0]
    assert original.status == perturbed.status == "ok"
    assert perturbed.expected_return - original.expected_return == pytest.approx(0.35 * 0.02)
    assert len(model.calls) == 2


def test_own_valid_sessions_before_union_calendar_and_asof(runtime, monkeypatch):
    config, _ = runtime
    monkeypatch.setattr(TotoAdapter, "_patch_size", lambda self: 1)
    frame = pd.DataFrame([
        ("2025-01-01", "A", 100), ("2025-01-03", "A", 110),
        ("2025-01-01", "B", 100), ("2025-01-02", "B", 101),
        ("2025-01-03", "B", 102), ("2025-01-04", "A", 1000),
    ], columns=["date", "etf_id", "adjusted_close"])
    adapter = TotoAdapter(config)
    context = adapter.build_multivariate_input("A", date(2025, 1, 3), frame)
    assert context.series.loc[date(2025, 1, 3), "A"] == pytest.approx(np.log(1.1))
    assert pd.isna(context.series.loc[date(2025, 1, 2), "A"])
    assert context.observed_returns == 1
    assert max(context.series.index) == date(2025, 1, 3)
    known = adapter.build_multivariate_input("A", date(2025, 1, 3), frame.iloc[:-1])
    pd.testing.assert_frame_equal(context.series, known.series)


def test_one_forward_pass_maps_all_targets_and_is_order_independent(runtime):
    config, model = runtime
    frame = prices()
    rows = run_service(config, frame, ["C", "A", "B"])
    assert len(model.calls) == 1
    actual = {(row.etf_id, row.horizon_days): asdict(row) for row in rows}
    assert len(actual) == 6
    assert [row.etf_id for row in rows] == ["C", "C", "A", "A", "B", "B"]
    for row in rows:
        own = {"A": 0.001, "B": 0.002, "C": 0.003}[row.etf_id]
        assert row.expected_return == pytest.approx((own + 0.35 * (0.006 - own)) * row.horizon_days)
    permuted = run_service(config, frame.iloc[::-1], ["B", "C", "A"])
    assert len(model.calls) == 2
    assert actual == {(row.etf_id, row.horizon_days): asdict(row) for row in permuted}
    np.testing.assert_array_equal(model.calls[0][0]["target"], model.calls[1][0]["target"])
    # The single-target API must select its actual column too, not column zero.
    single = TotoAdapter(config).forecast_etf("C", date(2025, 1, 9), [1, 3], frame, "work-u")
    assert all(asdict(row) == actual[("C", row.horizon_days)] for row in single)


def test_every_ok_row_records_approximation_and_point_statistic(runtime):
    config, _ = runtime
    quantiles = np.repeat(np.linspace(-0.02, 0.02, 9)[:, None, None, None], 3, axis=3)
    converted = toto_quantiles_to_log_return_results(
        quantiles=quantiles, horizons=[1, 3, 4], etf_id="A", forecast_date=date(2025, 1, 9),
        run_id="work-u", model_version="fixture",
    )
    assert converted[1].q10_return == pytest.approx(-0.02 * np.sqrt(3))
    assert converted[2].status == "skipped"
    mock = TotoAdapter(ModelRuntimeConfig(enabled=True, mode="mock"))
    rows = (run_service(config, prices(), ["A", "B", "C"]) + converted
            + mock.forecast_etf("A", date(2025, 1, 9), [1, 3], prices())
            + mock.forecast_etf("A", date(2025, 1, 9), [1, 3]))
    for row in rows:
        if row.status == "ok":
            assert row.quantile_method == "toto_daily_quadrature_approx"
            assert row.point_statistic == "median_sum_of_daily_medians"
            assert row.distribution_status == "available"
            assert row.model_allowed_in_score is False


def test_unavailable_targets_do_not_block_eligible_targets(runtime):
    config, model = runtime
    frame = prices()
    frame.loc[frame.etf_id == "C", "adjusted_close"] = np.nan
    rows = run_service(config, frame, ["A", "B", "C", "MISSING"])
    assert len(model.calls) == 1
    for row in rows:
        assert row.status == ("ok" if row.etf_id in {"A", "B"} else "unavailable")
        if row.status != "ok":
            assert row.expected_return is None
            assert row.model_allowed_in_score is False


@pytest.mark.parametrize("fault", ["shape", "nonfinite", "duplicate"])
def test_ambiguous_or_invalid_numbers_fail_closed(runtime, monkeypatch, fault):
    config, model = runtime
    original = model.forecast

    def invalid(*args, **kwargs):
        output = original(*args, **kwargs)
        if fault == "shape":
            return output[:, :, :1, :]
        output[:, :, 1, :] = np.nan
        return output

    frame = prices()
    if fault == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    else:
        monkeypatch.setattr(model, "forecast", invalid)
    rows = run_service(config, frame, ["A", "B", "C"])
    for row in rows:
        unavailable = fault != "nonfinite" or row.etf_id == "B"
        assert row.status == ("unavailable" if unavailable else "ok")
        if unavailable:
            assert row.expected_return is None and row.reason_unavailable
    if fault == "duplicate":
        assert not model.calls
