from __future__ import annotations

import builtins
import json
import struct

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.core.config import ModelRuntimeConfig
from etf_cockpit.models.local_weights import read_safetensors_header
from etf_cockpit.models.timesfm_adapter import TimesFMAdapter, _trim_to_complete_patches, timesfm_level_forecast_to_results
from etf_cockpit.models.toto_adapter import TotoAdapter, toto_quantiles_to_log_return_results


def test_timesfm_unavailable_returns_structured_results() -> None:
    adapter = TimesFMAdapter(ModelRuntimeConfig(enabled=False, mode="disabled"))
    result = adapter.forecast_series(pd.Series([1.0, 1.1, 1.2]), [5], etf_id="WORLD_CORE")
    assert result[0].status == "unavailable"
    assert result[0].model_name == "timesfm"


def test_toto_unavailable_returns_structured_results() -> None:
    adapter = TotoAdapter(ModelRuntimeConfig(enabled=False, mode="disabled"))
    result = adapter.forecast_etf("WORLD_CORE", pd.Timestamp("2026-06-26").date(), [20])
    assert result[0].status == "unavailable"
    assert result[0].model_name == "toto"


def test_toto_live_availability_requires_runtime_and_weights(monkeypatch, tmp_path) -> None:
    imports: list[str] = []
    real_import = builtins.__import__
    checkpoint = tmp_path / "Toto-2.0-4m"
    checkpoint.mkdir()
    (checkpoint / "model.safetensors").write_bytes(b"fake-weight-marker")
    (checkpoint / "config.json").write_text(
        json.dumps(
            {
                "patch_size": 32,
                "d_model": 256,
                "num_heads": 4,
                "num_layers": 4,
                "layer_group_size": 4,
                "num_variate_layers_per_group": 1,
                "variate_layer_first": False,
                "residual_attn_ratio": 5.136215466577748,
            }
        ),
        encoding="utf-8",
    )

    class FakeTotoModule:
        class Toto2Model:
            pass

    def fake_import(name: str, *args, **kwargs):
        imports.append(name)
        if name == "toto2":
            return FakeTotoModule
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    adapter = TotoAdapter(ModelRuntimeConfig(enabled=True, mode="live", model_path=str(checkpoint)))

    assert adapter.is_available()
    assert "toto2" in imports


def test_toto_live_availability_rejects_empty_runtime_folder(monkeypatch, tmp_path) -> None:
    real_import = builtins.__import__

    class FakeTotoModule:
        class Toto2Model:
            pass

    def fake_import(name: str, *args, **kwargs):
        if name == "toto2":
            return FakeTotoModule
        return real_import(name, *args, **kwargs)

    checkpoint = tmp_path / "Toto-2.0-4m"
    checkpoint.mkdir()
    monkeypatch.setattr(builtins, "__import__", fake_import)

    adapter = TotoAdapter(ModelRuntimeConfig(enabled=True, mode="live", model_path=str(checkpoint)))

    assert not adapter.is_available()


def test_toto_live_availability_rejects_weight_without_config(monkeypatch, tmp_path) -> None:
    real_import = builtins.__import__

    class FakeTotoModule:
        class Toto2Model:
            pass

    def fake_import(name: str, *args, **kwargs):
        if name == "toto2":
            return FakeTotoModule
        return real_import(name, *args, **kwargs)

    checkpoint = tmp_path / "Toto-2.0-4m"
    checkpoint.mkdir()
    (checkpoint / "model.safetensors").write_bytes(b"fake-weight-marker")
    monkeypatch.setattr(builtins, "__import__", fake_import)

    adapter = TotoAdapter(ModelRuntimeConfig(enabled=True, mode="live", model_path=str(checkpoint)))

    assert not adapter.is_available()


def test_toto_input_context_is_trimmed_to_complete_patches(tmp_path) -> None:
    checkpoint = tmp_path / "Toto-2.0-4m"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text(json.dumps({"patch_size": 32}), encoding="utf-8")
    adapter = TotoAdapter(ModelRuntimeConfig(enabled=True, mode="live", model_path=str(checkpoint), context_length=128))
    dates = pd.date_range("2026-01-01", periods=36, freq="D")
    prices = pd.DataFrame(
        {
            "date": list(dates) * 2,
            "etf_id": ["A"] * len(dates) + ["B"] * len(dates),
            "adjusted_close": list(np.linspace(100, 120, len(dates))) + list(np.linspace(80, 90, len(dates))),
        }
    )

    model_input = adapter.build_multivariate_input("A", dates[-1].date(), prices)

    assert len(model_input.series) == 32
    assert len(model_input.series) % 32 == 0
    assert not model_input.series.isna().all(axis=1).any()


def test_timesfm_context_is_trimmed_to_complete_patches() -> None:
    series = pd.Series(np.arange(65, dtype=float) + 1.0)

    trimmed = _trim_to_complete_patches(series, 32)

    assert len(trimmed) == 64
    assert trimmed.iloc[0] == 2.0


def test_safetensors_header_reader_uses_standard_library(tmp_path) -> None:
    header = {
        "__metadata__": {"format": "pt"},
        "layer.weight": {"dtype": "F32", "shape": [2, 3], "data_offsets": [0, 24]},
    }
    raw_header = json.dumps(header).encode("utf-8")
    path = tmp_path / "model.safetensors"
    path.write_bytes(struct.pack("<Q", len(raw_header)) + raw_header + (b"\0" * 24))

    summary = read_safetensors_header(path)

    assert summary.error is None
    assert summary.metadata == {"format": "pt"}
    assert summary.tensor_count == 1
    assert summary.sample_shapes == {"layer.weight": [2, 3]}


def test_timesfm_level_forecast_converts_prices_to_log_returns() -> None:
    result = timesfm_level_forecast_to_results(
        mean_predictions=np.array([[101.0, 104.0]]),
        quantile_predictions=np.array([[[99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]] * 2]),
        last_value=100.0,
        horizons=[1, 2, 3],
        etf_id="WORLD_CORE",
        forecast_date=pd.Timestamp("2026-06-26").date(),
        run_id="test",
        model_version="timesfm_2_5_transformers",
    )

    assert result[0].status == "ok"
    assert result[0].expected_return == pytest.approx(np.log(101.0 / 100.0))
    assert result[0].q10_return == pytest.approx(np.log(99.0 / 100.0))
    assert result[1].q90_return == pytest.approx(np.log(107.0 / 100.0))
    assert result[2].status == "skipped"
    assert result[2].expected_return is None


def test_toto_quantiles_convert_daily_return_paths_to_horizon_returns() -> None:
    quantiles = np.zeros((9, 1, 1, 3))
    quantiles[0, 0, 0, :] = -0.01
    quantiles[4, 0, 0, :] = 0.02
    quantiles[8, 0, 0, :] = 0.04

    result = toto_quantiles_to_log_return_results(
        quantiles=quantiles,
        horizons=[1, 3, 4],
        etf_id="WORLD_CORE",
        forecast_date=pd.Timestamp("2026-06-26").date(),
        run_id="test",
        model_version="toto_2_0_4m",
    )

    assert result[0].status == "ok"
    assert result[0].expected_return == pytest.approx(0.02)
    assert result[1].q10_return == pytest.approx(-0.03)
    assert result[1].q50_return == pytest.approx(0.06)
    assert result[1].q90_return == pytest.approx(0.12)
    assert result[2].status == "skipped"
