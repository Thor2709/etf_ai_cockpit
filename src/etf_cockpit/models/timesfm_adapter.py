from __future__ import annotations

import json
from datetime import date
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from etf_cockpit.core.config import ModelRuntimeConfig
from etf_cockpit.core.paths import ROOT
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.features.returns import daily_log_returns


WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".ckpt")


class TimesFMAdapter:
    model_name = "timesfm"
    model_version = "timesfm_2_5_optional"

    def __init__(self, config: ModelRuntimeConfig):
        self.config = config
        self._model: Any = None
        self._runtime_backend: str | None = None

    def is_available(self) -> bool:
        if not self.config.enabled or self.config.mode == "disabled":
            return False
        if self.config.mode == "mock":
            return True
        if self._checkpoint_reference() is None:
            return False
        return self._backend_available() is not None

    def load_model(self) -> None:
        if not self.is_available():
            raise RuntimeError("TimesFM unavailable - using baselines only.")
        if self.config.mode == "mock":
            self._model = "mock"
            self._runtime_backend = "mock"
            return
        backend = self._backend_available()
        checkpoint = self._checkpoint_reference()
        if backend is None or checkpoint is None:
            raise RuntimeError("TimesFM runtime package or checkpoint is missing.")
        if backend == "transformers":
            self._load_transformers_model(checkpoint)
        elif backend == "timesfm":
            self._load_timesfm_package_model(checkpoint)
        else:
            raise RuntimeError(f"Unsupported TimesFM backend: {backend}")

    def forecast_series(
        self,
        series: pd.Series,
        horizons: list[int],
        *,
        etf_id: str = "UNKNOWN",
        forecast_date: date | None = None,
        run_id: str = "manual",
    ) -> list[ForecastResult]:
        forecast_date = forecast_date or pd.to_datetime(series.index.max()).date()
        if not self.is_available():
            return self._status_results(
                horizons,
                etf_id=etf_id,
                forecast_date=forecast_date,
                run_id=run_id,
                status="unavailable",
                message="TimesFM disabled or compatible package/checkpoint missing.",
            )
        if self.config.mode == "mock":
            return self._mock_forecast(series, horizons, etf_id=etf_id, forecast_date=forecast_date, run_id=run_id)
        try:
            if self._model is None:
                self.load_model()
            if self._runtime_backend == "timesfm":
                return self._forecast_with_timesfm_package(series, horizons, etf_id=etf_id, forecast_date=forecast_date, run_id=run_id)
            return self._forecast_with_transformers(series, horizons, etf_id=etf_id, forecast_date=forecast_date, run_id=run_id)
        except Exception as exc:
            return self._status_results(
                horizons,
                etf_id=etf_id,
                forecast_date=forecast_date,
                run_id=run_id,
                status="failed",
                message=f"TimesFM live forecast failed: {type(exc).__name__}: {exc}",
            )

    def unload_model(self) -> None:
        self._model = None
        self._runtime_backend = None

    def _backend_available(self) -> str | None:
        backend = self.config.backend.lower()
        if backend in {"auto", "transformers"}:
            try:
                module = __import__("transformers", fromlist=["TimesFm2_5ModelForPrediction"])
                if hasattr(module, "TimesFm2_5ModelForPrediction"):
                    return "transformers"
            except Exception:
                if backend == "transformers":
                    return None
        if backend in {"auto", "timesfm", "official"}:
            try:
                module = __import__("timesfm")
                if hasattr(module, "TimesFM_2p5_200M_torch"):
                    return "timesfm"
            except Exception:
                return None
        return None

    def _checkpoint_reference(self) -> str | None:
        local_path = self._local_model_path()
        if local_path is not None and _is_compatible_local_checkpoint(local_path, self.config.backend):
            return str(local_path)
        if self.config.allow_remote_download and not self.config.local_files_only and self.config.hf_repo_id:
            return self.config.hf_repo_id
        return None

    def _local_model_path(self) -> Path | None:
        if not self.config.model_path:
            return None
        path = Path(self.config.model_path)
        return path if path.is_absolute() else ROOT / path

    def _load_transformers_model(self, checkpoint: str) -> None:
        module = __import__("transformers", fromlist=["TimesFm2_5ModelForPrediction"])
        cls = module.TimesFm2_5ModelForPrediction
        kwargs: dict[str, Any] = {"local_files_only": self.config.local_files_only}
        if self.config.device == "auto" and _torch_cuda_available() and _package_available("accelerate"):
            kwargs["device_map"] = "auto"
        elif self.config.device and self.config.device != "cpu" and _package_available("accelerate"):
            kwargs["device_map"] = self.config.device
        self._model = cls.from_pretrained(checkpoint, **kwargs).eval()
        self._runtime_backend = "transformers"

    def _load_timesfm_package_model(self, checkpoint: str) -> None:
        timesfm = __import__("timesfm")
        checkpoint_path = Path(checkpoint)
        if checkpoint_path.is_file():
            model = timesfm.TimesFM_2p5_200M_torch(torch_compile=self.config.torch_compile)
            model.load_checkpoint(str(checkpoint_path), torch_compile=self.config.torch_compile)
        else:
            model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(checkpoint, torch_compile=self.config.torch_compile)
        model.compile(
            timesfm.ForecastConfig(
                max_context=self.config.context_length,
                max_horizon=256,
                normalize_inputs=True,
                use_continuous_quantile_head=self.config.use_quantiles,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
            )
        )
        self._model = model
        self._runtime_backend = "timesfm"

    def _forecast_with_transformers(
        self,
        series: pd.Series,
        horizons: list[int],
        *,
        etf_id: str,
        forecast_date: date,
        run_id: str,
    ) -> list[ForecastResult]:
        values = _trim_to_complete_patches(
            _clean_positive_series(series).tail(self.config.context_length),
            self._patch_length(),
        )
        torch = __import__("torch")
        device = getattr(self._model, "device", None)
        try:
            tensor = torch.tensor(values.to_numpy(dtype=float), dtype=torch.float32, device=device)
        except Exception:
            tensor = torch.tensor(values.to_numpy(dtype=float), dtype=torch.float32)
        with torch.no_grad():
            outputs = self._model(
                past_values=[tensor],
                forecast_context_len=min(self.config.context_length, len(values)),
                return_dict=True,
            )
        return timesfm_level_forecast_to_results(
            mean_predictions=_to_numpy(outputs.mean_predictions),
            quantile_predictions=_to_numpy(getattr(outputs, "full_predictions", None)),
            last_value=float(values.iloc[-1]),
            horizons=horizons,
            etf_id=etf_id,
            forecast_date=forecast_date,
            run_id=run_id,
            model_version="timesfm_2_5_transformers",
        )

    def _forecast_with_timesfm_package(
        self,
        series: pd.Series,
        horizons: list[int],
        *,
        etf_id: str,
        forecast_date: date,
        run_id: str,
    ) -> list[ForecastResult]:
        values = _trim_to_complete_patches(
            _clean_positive_series(series).tail(self.config.context_length),
            self._patch_length(),
        )
        point, quantile = self._model.forecast(
            horizon=max(horizons),
            inputs=[values.to_numpy(dtype=float)],
        )
        return timesfm_level_forecast_to_results(
            mean_predictions=np.asarray(point),
            quantile_predictions=np.asarray(quantile) if self.config.use_quantiles else None,
            last_value=float(values.iloc[-1]),
            horizons=horizons,
            etf_id=etf_id,
            forecast_date=forecast_date,
            run_id=run_id,
            model_version="timesfm_2_5_pytorch",
        )

    def _mock_forecast(
        self,
        series: pd.Series,
        horizons: list[int],
        *,
        etf_id: str,
        forecast_date: date,
        run_id: str,
    ) -> list[ForecastResult]:
        returns = daily_log_returns(series.astype(float)).dropna()
        mean = float(returns.tail(120).mean() * 0.4) if not returns.empty else 0.0
        vol = float(returns.tail(60).std() * np.sqrt(252)) if len(returns) >= 60 else 0.0
        out: list[ForecastResult] = []
        for horizon in horizons:
            expected = mean * horizon
            horizon_vol = vol * np.sqrt(horizon / 252) if vol else 0.0
            out.append(
                ForecastResult(
                    run_id=run_id,
                    model_name=self.model_name,
                    model_version=self.model_version + "_mock",
                    etf_id=etf_id,
                    forecast_date=forecast_date,
                    horizon_days=horizon,
                    expected_return=expected,
                    expected_excess_return=expected,
                    q10_return=expected - 1.28 * horizon_vol,
                    q50_return=expected,
                    q90_return=expected + 1.28 * horizon_vol,
                    forecast_vol=horizon_vol,
                    prob_positive_return=float(1 / (1 + np.exp(-expected / max(horizon_vol, 1e-6)))),
                    status="ok",
                    calibration_status="mock_not_for_live_scoring",
                )
            )
        return out

    def _patch_length(self) -> int:
        local_path = self._local_model_path()
        if local_path is not None:
            config_path = local_path / "config.json" if local_path.is_dir() else local_path.with_name("config.json")
            if config_path.exists():
                try:
                    raw = json.loads(config_path.read_text(encoding="utf-8"))
                    patch_length = int(raw.get("patch_length", raw.get("patch_size", 32)))
                    return patch_length if patch_length > 0 else 32
                except Exception:
                    return 32
        return 32

    def _status_results(
        self,
        horizons: list[int],
        *,
        etf_id: str,
        forecast_date: date,
        run_id: str,
        status: str,
        message: str,
    ) -> list[ForecastResult]:
        return [
            ForecastResult(
                run_id=run_id,
                model_name=self.model_name,
                model_version=self.model_version,
                etf_id=etf_id,
                forecast_date=forecast_date,
                horizon_days=horizon,
                expected_return=None,
                expected_excess_return=None,
                status=status,  # type: ignore[arg-type]
                error_message=message,
                model_allowed_in_score=False,
                is_fallback=False,
                fallback_model="baseline",
                reason_unavailable=message,
                calibration_status="unavailable" if status == "unavailable" else "failed",
            )
            for horizon in horizons
        ]


def timesfm_level_forecast_to_results(
    *,
    mean_predictions: Any,
    quantile_predictions: Any,
    last_value: float,
    horizons: list[int],
    etf_id: str,
    forecast_date: date,
    run_id: str,
    model_version: str,
) -> list[ForecastResult]:
    mean = _first_series(np.asarray(mean_predictions, dtype=float))
    quantiles = _first_quantile_matrix(quantile_predictions)
    results: list[ForecastResult] = []
    for horizon in horizons:
        index = horizon - 1
        if index < 0 or index >= len(mean):
            message = f"TimesFM returned {len(mean)} forecast steps; requested horizon {horizon}."
            results.append(
                ForecastResult(
                    run_id=run_id,
                    model_name="timesfm",
                    model_version=model_version,
                    etf_id=etf_id,
                    forecast_date=forecast_date,
                    horizon_days=horizon,
                    expected_return=None,
                    expected_excess_return=None,
                    status="skipped",
                    error_message=message,
                    model_allowed_in_score=False,
                    reason_unavailable=message,
                    calibration_status="unsupported_horizon",
                )
            )
            continue
        expected = _level_to_log_return(mean[index], last_value)
        q10 = _level_to_log_return(_quantile_at(quantiles, index, "q10"), last_value)
        q50 = _level_to_log_return(_quantile_at(quantiles, index, "q50"), last_value)
        q90 = _level_to_log_return(_quantile_at(quantiles, index, "q90"), last_value)
        results.append(
            ForecastResult(
                run_id=run_id,
                model_name="timesfm",
                model_version=model_version,
                etf_id=etf_id,
                forecast_date=forecast_date,
                horizon_days=horizon,
                expected_return=expected,
                expected_excess_return=expected,
                q10_return=q10,
                q50_return=q50 if q50 is not None else expected,
                q90_return=q90,
                forecast_vol=_quantile_vol_proxy(q10, q90, horizon),
                prob_positive_return=float(expected is not None and expected > 0),
                status="ok",
                calibration_status="not_evaluated",
            )
        )
    return results


def _has_weight_files(path: Path) -> bool:
    if path.is_file():
        return _is_runtime_weight_file(path)
    if not path.exists() or not path.is_dir():
        return False
    return any(child.is_file() and _is_runtime_weight_file(child) for child in path.rglob("*"))


def _is_runtime_weight_file(path: Path) -> bool:
    lower_name = path.name.lower()
    if not lower_name.endswith(WEIGHT_SUFFIXES):
        return False
    return ".original" not in lower_name and ".backup" not in lower_name


def _package_available(name: str) -> bool:
    return find_spec(name) is not None


def _torch_cuda_available() -> bool:
    try:
        torch = __import__("torch")
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _is_compatible_local_checkpoint(path: Path, backend: str) -> bool:
    if not path.exists():
        return False
    normalized_backend = backend.lower()
    if normalized_backend == "transformers":
        return path.is_dir() and (path / "config.json").exists() and _has_weight_files(path)
    if normalized_backend in {"timesfm", "official"}:
        if path.is_file():
            return path.name.lower().endswith(WEIGHT_SUFFIXES)
        return path.is_dir() and (path / "model.safetensors").exists()
    return _has_weight_files(path)


def _clean_positive_series(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    values = values[np.isfinite(values)]
    values = values[values > 0]
    if len(values) < 2:
        raise ValueError("TimesFM requires at least two positive price observations.")
    return values


def _trim_to_complete_patches(series: pd.Series, patch_length: int) -> pd.Series:
    if patch_length <= 0:
        return series
    usable_rows = (len(series) // patch_length) * patch_length
    if usable_rows <= 0:
        raise ValueError(f"TimesFM requires at least one complete {patch_length}-step context patch.")
    return series.tail(usable_rows)


def _to_numpy(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def _first_series(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 0:
        return array.reshape(1)
    if array.ndim == 1:
        return array
    return np.asarray(array[0], dtype=float).reshape(-1)


def _first_quantile_matrix(values: Any) -> np.ndarray | None:
    if values is None:
        return None
    array = np.asarray(values, dtype=float)
    if array.ndim == 3:
        return array[0]
    if array.ndim == 2:
        return array
    return None


def _quantile_at(matrix: np.ndarray | None, horizon_index: int, label: str) -> float | None:
    if matrix is None or horizon_index >= matrix.shape[0]:
        return None
    width = matrix.shape[1]
    if width >= 10:
        indices = {"q10": 1, "q50": 5, "q90": 9}
    elif width >= 9:
        indices = {"q10": 0, "q50": 4, "q90": 8}
    else:
        return None
    index = indices[label]
    if index >= width:
        return None
    return float(matrix[horizon_index, index])


def _level_to_log_return(level: float | None, last_value: float) -> float | None:
    if level is None or not np.isfinite(level) or not np.isfinite(last_value) or level <= 0 or last_value <= 0:
        return None
    return float(np.log(level / last_value))


def _quantile_vol_proxy(q10: float | None, q90: float | None, horizon: int) -> float | None:
    if q10 is None or q90 is None or horizon <= 0:
        return None
    horizon_vol = max((q90 - q10) / 2.563, 0.0)
    return float(horizon_vol / np.sqrt(horizon / 252))
