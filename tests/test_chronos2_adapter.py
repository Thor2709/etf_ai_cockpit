from __future__ import annotations

import os
import socket
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application import forecast_service
from etf_cockpit.application.forecast_service import ForecastService, _apply_promotion, _forecast_to_row
from etf_cockpit.core.config import ModelPromotionSettings, ModelRuntimeConfig, load_config
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.models import chronos2_adapter, model_promotion
from etf_cockpit.models.chronos2_adapter import Chronos2Adapter
from etf_cockpit.models.local_weights import model_weight_inventory
from etf_cockpit.models.model_promotion import (
    COUNTING, OPTIONAL_MODELS, PRETRAINING_CUTOFFS, ModelPromotion, checkpoint_provenance, evaluate_model_promotions,
)

HORIZONS = [5, 20]
FORECAST_DATE = date(2026, 3, 31)


def _prices(periods: int = 300) -> pd.Series:
    index = pd.bdate_range(end=pd.Timestamp(FORECAST_DATE), periods=periods)
    return pd.Series(100 * np.exp(np.cumsum(np.full(periods, 0.0004))), index=index)


def _checkpoint(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text("{}")
    (path / "model.safetensors").write_bytes(b"fake")
    return path


def _config(path: Path, **kwargs: object) -> ModelRuntimeConfig:
    return ModelRuntimeConfig(enabled=True, mode="live", backend="chronos2", model_path=str(path), **kwargs)  # type: ignore[arg-type]


class _StubPipeline:
    """Returns log-level quantiles of a known drift so the return units can be checked exactly."""

    def __init__(self, last_log_level: float):
        self.last = last_log_level
        self.tasks: list[dict] = []

    def predict_quantiles(self, inputs, prediction_length, quantile_levels):
        self.tasks.extend(inputs)
        steps = np.arange(1, prediction_length + 1)[:, None]
        spread = (np.arange(9) - 4)[None, :] * 0.01 * np.sqrt(steps)
        return [np.asarray([self.last + 0.001 * steps + spread])], None


def test_missing_weights_package_or_disabled_gives_unavailable_and_the_run_continues(tmp_path, monkeypatch):
    series = _prices()
    absent = Chronos2Adapter(_config(tmp_path / "absent"))
    rows = absent.forecast_series(series, HORIZONS, etf_id="X", forecast_date=FORECAST_DATE)
    assert not absent.is_available()
    assert [row.status for row in rows] == ["unavailable"] * 2
    assert all(row.expected_return is None and not row.model_allowed_in_score for row in rows)

    checkpoint = _checkpoint(tmp_path / "chronos-2")
    monkeypatch.setattr(chronos2_adapter, "find_spec", lambda name: None)
    assert not Chronos2Adapter(_config(checkpoint)).is_available()
    monkeypatch.setattr(chronos2_adapter, "find_spec", lambda name: object())
    assert Chronos2Adapter(_config(checkpoint)).is_available()
    assert not Chronos2Adapter(_config(checkpoint).model_copy(update={"mode": "disabled"})).is_available()

    service_rows = ForecastService(load_config().model_copy(deep=True))._run_chronos2_forecasts(
        pd.DataFrame({"X": series}), ["X"], HORIZONS, FORECAST_DATE, "run",
    )
    assert [row.status for row in service_rows] == ["unavailable"] * 2

    # A run that disables optional models never starts Chronos-2, even when its config is enabled and live.
    monkeypatch.setattr(forecast_service, "current_settings_identity", lambda: {"settings_revision": "a" * 64})
    monkeypatch.setattr(forecast_service, "settings_bound_run_id", lambda run_id, *, settings_identity: run_id)
    monkeypatch.setattr(forecast_service, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    live = load_config().model_copy(deep=True)
    live.models.models["chronos2"] = {"enabled": True, "mode": "live", "model_path": str(checkpoint)}
    service = ForecastService(live, reference_context=SimpleNamespace(resolution=None, benchmark_data_id="BENCH", identity={}))
    started: list[int] = []
    for name in ("_run_timesfm_forecasts", "_run_toto_forecasts", "_write_forecasts"):
        monkeypatch.setattr(service, name, lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_run_chronos2_forecasts", lambda *_args, **_kwargs: started.append(1) or [])
    dates = pd.bdate_range("2026-08-01", periods=30)
    frame = pd.DataFrame({"date": dates, "etf_id": "BENCH", "adjusted_close": np.exp(np.arange(30) * 0.01)})
    for flag in (False, True):
        service.run_forecasts(dates[-1].date(), ["BENCH"], frame, horizons=[1], live_optional_models=flag)
        assert len(started) == int(flag)


def test_output_is_horizon_log_returns_from_past_only_inputs(tmp_path, monkeypatch):
    series = _prices()
    stub = _StubPipeline(float(np.log(series.iloc[-1])))
    monkeypatch.setattr(chronos2_adapter, "find_spec", lambda name: object())
    adapter = Chronos2Adapter(_config(_checkpoint(tmp_path / "chronos-2")))
    adapter._model = stub
    future = pd.Series([999.0] * 3, index=pd.bdate_range(FORECAST_DATE + pd.Timedelta(days=1), periods=3))
    benchmark = pd.concat([pd.Series(0.001, index=series.index), future])
    after = pd.concat([series, pd.Series([1.0] * 3, index=future.index)])
    # Date-only stamps (real data): the origin day's close may be published after the target's, so it is dropped.
    late = pd.Series(0.5, index=series.index)

    rows = adapter.forecast_series(
        after, HORIZONS, etf_id="X", forecast_date=FORECAST_DATE, past_covariates={"benchmark": benchmark, "late": late},
    )

    assert [row.horizon_days for row in rows] == HORIZONS and all(row.status == "ok" for row in rows)
    for row in rows:
        h = row.horizon_days
        assert row.model_name == "chronos2" and row.expected_return == pytest.approx(0.001 * h)
        assert row.q50_return == pytest.approx(0.001 * h)
        assert row.q10_return == pytest.approx(0.001 * h - 0.04 * np.sqrt(h))
        assert row.q90_return == pytest.approx(0.001 * h + 0.04 * np.sqrt(h))
    task = stub.tasks[0]
    assert len(task["target"]) == len(series) and task["target"][-1] == pytest.approx(np.log(series.iloc[-1]))
    assert len(task["past_covariates"]["benchmark"]) == len(task["target"])
    assert not (task["past_covariates"]["benchmark"] == 999.0).any()
    assert np.isnan(task["past_covariates"]["late"][-1]) and np.isfinite(task["past_covariates"]["late"][:-1]).all()


def test_real_package_runs_offline_with_every_socket_denied(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    pytest.importorskip("chronos")
    from chronos.chronos2 import Chronos2CoreConfig, Chronos2Model

    quantiles = [0.01, 0.05, *[round(0.05 * step, 2) for step in range(2, 20)], 0.95, 0.99]
    core = Chronos2CoreConfig(
        d_model=16, d_kv=4, d_ff=32, num_layers=1, num_heads=2, vocab_size=2, reg_token_id=1, pad_token_id=0,
        chronos_pipeline_class="Chronos2Pipeline",
        chronos_config={
            "context_length": 64, "input_patch_size": 8, "input_patch_stride": 8, "output_patch_size": 8,
            "max_output_patches": 4, "quantiles": quantiles, "use_arcsinh": True, "use_reg_token": True,
            "time_encoding_scale": 64,
        },
    )
    Chronos2Model(core).save_pretrained(tmp_path / "tiny")

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    adapter = Chronos2Adapter(_config(tmp_path / "tiny", device="cpu", context_length=64))
    series = _prices(120)
    rows = adapter.forecast_series(
        series, HORIZONS, etf_id="X", forecast_date=FORECAST_DATE,
        past_covariates={"benchmark": pd.Series(np.random.default_rng(1).normal(size=len(series)), index=series.index)},
    )
    adapter.unload_model()

    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert [row.status for row in rows] == ["ok", "ok"], [row.error_message for row in rows]
    assert all(np.isfinite(row.expected_return) and np.isfinite(row.q10_return) and np.isfinite(row.q90_return) for row in rows)


def test_chronos2_is_shadow_with_unknown_cutoff_and_apache_licence_and_a_weight_row(tmp_path, monkeypatch):
    provenance = checkpoint_provenance("chronos2")
    assert "chronos2" in OPTIONAL_MODELS and "chronos2" not in PRETRAINING_CUTOFFS
    assert provenance.licence == "apache-2.0" and provenance.pretraining_cutoff is None
    assert provenance.cutoff_scope == "unknown" and provenance.leakage_flag(date(2035, 1, 1)) == "possibly_leaked"

    config = load_config().model_copy(deep=True)
    config.models.models["chronos2"] = {"enabled": True, "mode": "live", "model_path": str(tmp_path / "absent")}
    row = next(item for item in model_weight_inventory(config) if item.model_name == "chronos2")
    assert not row.live_ready and row.status == "missing_weights"
    _checkpoint(tmp_path / "present")
    config.models.models["chronos2"]["model_path"] = str(tmp_path / "present")
    row = next(item for item in model_weight_inventory(config) if item.model_name == "chronos2")
    assert row.status in {"weights_present", "live_ready"} and len(row.weight_files) == 1

    # Never promotable, even when the evaluator would say counting: no counting decision, no score
    # eligibility, and every stored row carries the unknown-cutoff leakage flag.
    forced = ModelPromotion("chronos2", COUNTING, "forced", model_version="v", evidence_after="2020-01-01")
    monkeypatch.setattr(model_promotion, "_decide", lambda model, *_args, **_kwargs: ModelPromotion(model, COUNTING, "forced"))
    decisions = evaluate_model_promotions(pd.DataFrame(), pd.DataFrame(), FORECAST_DATE, ModelPromotionSettings())
    assert decisions["timesfm"].counting and not decisions["chronos2"].counting
    result = ForecastResult("r", "chronos2", "v", "X", date(2026, 3, 2), 60, 0.02, 0.02, target_id="adj_close_log_return_60d")
    for promotions in ({"chronos2": forced}, {}):
        applied = _apply_promotion(result, promotions, False)
        assert not applied.model_allowed_in_score and applied.promotion_status == "shadow_only"
        for stored in (_forecast_to_row(applied, promotions, {}), _forecast_to_row(result, promotions, {})):
            assert stored["contamination_status"] == "possibly_leaked" and stored["promotion_state"] == "shadow_only"


def test_default_settings_keep_chronos2_off():
    runtime = load_config().models.runtime("chronos2")
    assert not runtime.enabled and runtime.mode == "disabled" and runtime.local_files_only and not runtime.allow_remote_download
