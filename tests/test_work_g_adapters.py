from datetime import date
from types import SimpleNamespace
import builtins

import numpy as np
import pandas as pd

from etf_cockpit.core.config import ModelRuntimeConfig
from etf_cockpit.models.timesfm_adapter import TimesFMAdapter
from etf_cockpit.models.timesfm3_adapter import TimesFM3Adapter
from etf_cockpit.models.toto_adapter import TotoAdapter


def test_timesfm_transformers_auto_cpu_without_cuda_or_accelerate(monkeypatch):
    monkeypatch.setattr("etf_cockpit.models.timesfm_adapter._torch_cuda_available", lambda: False)
    calls = {}
    class Model:
        def to(self, device):
            calls["device"] = device
            return self
        def eval(self):
            return self
    class Loader:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["kwargs"] = kwargs
            return Model()
    original = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **kw: SimpleNamespace(TimesFm2_5ModelForPrediction=Loader) if name == "transformers" else original(name, *a, **kw))
    adapter = TimesFMAdapter(ModelRuntimeConfig(device="auto"))
    adapter._load_transformers_model("local")
    assert calls == {"device": "cpu", "kwargs": {"local_files_only": True}}


def test_timesfm3_local_cpu_and_point_in_time(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text('{"patch_size": 32}')
    (tmp_path / "model.safetensors").write_bytes(b"fake")
    calls = {}
    class Forecaster:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls.update(kwargs)
            return Forecaster()
        def predict(self, context, horizon, **kwargs):
            calls["context"] = context
            return SimpleNamespace(forecast=np.repeat(context[-1] * 1.01, horizon), quantiles=None)
    original = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda name, *a, **kw: SimpleNamespace(TimesFM3Forecaster=Forecaster) if name == "timesfm" else original(name, *a, **kw))
    adapter = TimesFM3Adapter(ModelRuntimeConfig(enabled=True, mode="live", model_path=str(tmp_path), device="cpu"))
    series = pd.Series(np.arange(1, 81), index=pd.date_range("2025-01-01", periods=80))
    rows = adapter.forecast_series(series, [5], forecast_date=date(2025, 2, 9))
    assert rows[0].status == "ok" and rows[0].model_name == "timesfm3"
    assert calls["context"][-1] == 40 and calls["device"] == "cpu"
    short = adapter.forecast_series(series, [5], forecast_date=date(2025, 1, 5))
    assert short[0].status == "unavailable" and "context patch" in short[0].reason_unavailable


def test_timesfm3_missing_checkpoint_is_disabled_safe(monkeypatch, tmp_path):
    adapter = TimesFM3Adapter(ModelRuntimeConfig(enabled=True, mode="live", model_path=str(tmp_path)))
    rows = adapter.forecast_series(pd.Series([1, 2], index=pd.date_range("2025-01-01", periods=2)), [5])
    assert rows[0].status == "unavailable" and not rows[0].model_allowed_in_score
    from etf_cockpit.core.config import load_config
    from etf_cockpit.models.local_weights import model_weight_inventory
    (tmp_path / "config.json").write_text('{}')
    (tmp_path / "model.safetensors").write_bytes(b"fake")
    config = load_config().model_copy(deep=True)
    config.models.models["timesfm3"] = {"enabled": True, "mode": "live", "model_path": str(tmp_path)}
    monkeypatch.setattr("etf_cockpit.models.local_weights._package_available", lambda name: True)
    monkeypatch.setattr(TimesFM3Adapter, "_backend_available", lambda self: None)
    status = next(row for row in model_weight_inventory(config) if row.model_name == "timesfm3")
    assert not status.live_ready and status.status != "live_ready"
    assert "TimesFM3Forecaster" in status.message and "ready for live" not in status.message


def test_toto_incompatible_installed_runtime_is_precise(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text('{"d_model": 256}')
    (tmp_path / "model.safetensors").write_bytes(b"fake")
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == "toto2":
            raise ImportError("absent")
        if name == "toto.model.toto":
            return SimpleNamespace(Toto=object)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    adapter = TotoAdapter(ModelRuntimeConfig(enabled=True, mode="live", model_path=str(tmp_path)))
    row = adapter.forecast_etf("ETF", date(2025, 1, 1), [5])[0]
    assert row.status == "unavailable" and "incompatible" in row.reason_unavailable
