"""Chronos-2 forecast adapter (shadow only; score authority stays in governance).

Duck contract of ``TimesFMAdapter``: ``is_available``, ``load_model``, ``forecast_series``,
``unload_model``. The input is the adjusted log price level; the predicted log-level quantiles
become horizon log-return quantiles through ``timesfm_level_forecast_to_results`` (one canonical
conversion). Covariates are past values only (no future covariates). The weights load from a
local folder with no download: ``HF_HUB_OFFLINE`` and ``TRANSFORMERS_OFFLINE`` are set before any
Hugging Face library is imported.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from importlib.util import find_spec
from typing import Any

import numpy as np
import pandas as pd

from etf_cockpit.core.types import ForecastResult
from etf_cockpit.models.timesfm_adapter import (
    TimesFMAdapter, _clean_positive_series, _to_numpy, _torch_cuda_available,
    timesfm_level_forecast_to_results,
)

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Deciles are native Chronos-2 quantile levels; the shared conversion reads a 9-wide decile matrix.
_DECILES = [round(0.1 * step, 1) for step in range(1, 10)]
_MEDIAN_COLUMN = 4


class Chronos2Adapter(TimesFMAdapter):
    model_name = "chronos2"
    model_version = "chronos_2_optional"

    def is_available(self) -> bool:
        if not self.config.enabled or self.config.mode != "live":
            return False
        path = self._local_model_path()
        if path is None or not (path / "config.json").is_file() or not (path / "model.safetensors").is_file():
            return False
        return find_spec("torch") is not None and find_spec("chronos") is not None

    def load_model(self) -> None:
        if not self.is_available():
            raise RuntimeError("Chronos-2 unavailable - using baselines only.")
        from chronos import Chronos2Pipeline

        device = self.config.device
        if device == "auto" or (device.startswith("cuda") and not _torch_cuda_available()):
            device = "cuda" if _torch_cuda_available() else "cpu"
        path = self._local_model_path()
        self._model = Chronos2Pipeline.from_pretrained(str(path), device_map=device, local_files_only=True)

    def forecast_series(
        self,
        series: pd.Series,
        horizons: list[int],
        *,
        etf_id: str = "UNKNOWN",
        forecast_date: date | None = None,
        run_id: str = "manual",
        past_covariates: Mapping[str, pd.Series] | None = None,
    ) -> list[ForecastResult]:
        forecast_date = forecast_date or pd.to_datetime(series.index.max()).date()
        if not self.is_available():
            return self._status_results(
                horizons, etf_id=etf_id, forecast_date=forecast_date, run_id=run_id, status="unavailable",
                message="Chronos-2 disabled or compatible package/checkpoint missing.",
            )
        series = series.loc[pd.to_datetime(series.index).date <= forecast_date].sort_index()
        try:
            cleaned = _clean_positive_series(series)
            values = cleaned.tail(self.config.context_length)
            task: dict[str, Any] = {"target": np.log(values.to_numpy(dtype=float))}
            covariates = _past_covariates(values.index, past_covariates)
            if covariates:
                task["past_covariates"] = covariates
            if self._model is None:
                self.load_model()
            quantiles, _ = self._model.predict_quantiles(
                [task], prediction_length=max(horizons), quantile_levels=_DECILES,
            )
            levels = np.exp(np.asarray(_to_numpy(quantiles[0]), dtype=float)[0])
            return timesfm_level_forecast_to_results(
                mean_predictions=levels[:, _MEDIAN_COLUMN], quantile_predictions=levels,
                last_value=float(values.iloc[-1]), horizons=horizons, etf_id=etf_id,
                forecast_date=forecast_date, run_id=run_id, model_version="chronos_2_pytorch",
                model_name=self.model_name,
                observed_returns=int((cleaned.notna() & cleaned.shift().notna()).sum()),
            )
        except Exception as exc:
            return self._status_results(
                horizons, etf_id=etf_id, forecast_date=forecast_date, run_id=run_id,
                status="unavailable" if isinstance(exc, ValueError) else "failed",
                message=f"Chronos-2 live forecast failed: {type(exc).__name__}: {exc}",
            )


def _past_covariates(
    index: pd.Index, covariates: Mapping[str, pd.Series] | None,
) -> dict[str, np.ndarray]:
    """Covariate values on the target's own sessions, only from UTC dates before the origin session (that day's close may follow the target's)."""

    days = pd.to_datetime(index, utc=True).date
    aligned: dict[str, np.ndarray] = {}
    for name, covariate in (covariates or {}).items():
        covariate_days = pd.to_datetime(covariate.index, utc=True).date
        covariate = covariate.loc[covariate_days < days[-1]]
        covariate_days = covariate_days[covariate_days < days[-1]]
        known = pd.Series(covariate.to_numpy(dtype=float), index=covariate_days)
        known = known[~known.index.duplicated(keep="last")]
        values = known.reindex(days).to_numpy(dtype=float)
        if np.isfinite(values).any():
            aligned[name] = values
    return aligned
