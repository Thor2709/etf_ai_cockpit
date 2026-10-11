from __future__ import annotations

from typing import Any

from etf_cockpit.models.timesfm_adapter import (
    TimesFMAdapter, _clean_positive_series, _torch_cuda_available,
    timesfm_level_forecast_to_results,
)


class TimesFM3Adapter(TimesFMAdapter):
    """Local TimesFM 3 inference; score authority remains in governance."""

    model_name = "timesfm3"
    model_version = "timesfm_3_0_optional"

    def _backend_available(self) -> str | None:
        try:
            module = __import__("timesfm")
            return "timesfm3" if hasattr(module, "TimesFM3Forecaster") else None
        except Exception:
            return None

    def _checkpoint_reference(self) -> str | None:
        path = self._local_model_path()
        if path is not None and path.is_dir() and (path / "config.json").is_file() and (path / "model.safetensors").is_file():
            return str(path)
        if self.config.allow_remote_download and not self.config.local_files_only:
            return self.config.hf_repo_id
        return None

    def load_model(self) -> None:
        if not self.is_available():
            raise RuntimeError("TimesFM 3 package or local checkpoint missing.")
        module = __import__("timesfm")
        device = self.config.device
        if device == "auto" or (device.startswith("cuda") and not _torch_cuda_available()):
            device = "cuda" if _torch_cuda_available() else "cpu"
        self._model = module.TimesFM3Forecaster.from_pretrained(
            self._checkpoint_reference(), device=device,
            local_files_only=self.config.local_files_only,
        )
        self._runtime_backend = "timesfm3"

    def _forecast_with_transformers(self, series: Any, horizons: list[int], *, etf_id: str, forecast_date: Any, run_id: str):
        cleaned = _clean_positive_series(series)
        values = cleaned.tail(self.config.context_length)
        output = self._model.predict(
            context=values.to_numpy(dtype=float), horizon=max(horizons),
            return_quantiles=self.config.use_quantiles,
        )
        return timesfm_level_forecast_to_results(
            mean_predictions=output.forecast, quantile_predictions=output.quantiles,
            last_value=float(values.iloc[-1]), horizons=horizons, etf_id=etf_id,
            forecast_date=forecast_date, run_id=run_id,
            model_version="timesfm_3_0_pytorch", model_name=self.model_name,
            observed_returns=len(cleaned) - 1,
        )
