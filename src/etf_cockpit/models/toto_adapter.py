from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from etf_cockpit.core.config import ModelRuntimeConfig
from etf_cockpit.core.paths import ROOT
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.models.base import ModelInput
from etf_cockpit.models.timesfm_adapter import _has_weight_files


class TotoAdapter:
    model_name = "toto"
    model_version = "toto_2_0_optional"

    def __init__(self, config: ModelRuntimeConfig):
        self.config = config
        self._model: Any = None
        self._device: Any = None

    def is_available(self) -> bool:
        if not self.config.enabled or self.config.mode == "disabled":
            return False
        if self.config.mode == "mock":
            return True
        if self._checkpoint_reference() is None:
            return False
        try:
            module = __import__("toto2", fromlist=["Toto2Model"])
            return hasattr(module, "Toto2Model")
        except Exception:
            return False

    def load_model(self) -> None:
        if not self.is_available():
            raise RuntimeError("Toto unavailable - using baselines only.")
        if self.config.mode == "mock":
            self._model = "mock"
            return
        checkpoint = self._checkpoint_reference()
        if checkpoint is None:
            raise RuntimeError("Toto checkpoint is missing.")
        torch = __import__("torch")
        module = __import__("toto2", fromlist=["Toto2Model"])
        kwargs = {"local_files_only": self.config.local_files_only, "map_location": _torch_device(torch, self.config.device)}
        try:
            model = module.Toto2Model.from_pretrained(checkpoint, **kwargs)
        except TypeError:
            model = module.Toto2Model.from_pretrained(checkpoint)
        self._device = _torch_device(torch, self.config.device)
        self._model = model.to(self._device).eval()

    def build_multivariate_input(self, etf_id: str, as_of_date: date, prices: pd.DataFrame) -> ModelInput:
        frame = prices.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame = frame[frame["date"] <= as_of_date]
        pivot = frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
        returns = np.log(pivot / pivot.shift(1)).dropna(how="all")
        columns = [etf_id] + [column for column in returns.columns if column != etf_id]
        series = returns[columns].tail(self.config.context_length)
        patch_size = self._patch_size()
        usable_rows = (len(series) // patch_size) * patch_size
        if usable_rows <= 0:
            raise ValueError(f"Toto requires at least one complete {patch_size}-step context patch.")
        return ModelInput(etf_id=etf_id, as_of_date=as_of_date, series=series.tail(usable_rows))

    def forecast_etf(
        self,
        etf_id: str,
        as_of_date: date,
        horizons: list[int],
        prices: pd.DataFrame | None = None,
        run_id: str = "manual",
    ) -> list[ForecastResult]:
        if not self.is_available():
            return self._status_results(
                horizons,
                etf_id=etf_id,
                as_of_date=as_of_date,
                run_id=run_id,
                status="unavailable",
                message="Toto disabled or compatible package/checkpoint missing.",
            )
        if prices is None:
            if self.config.mode == "mock":
                return self._mock_forecast_without_prices(etf_id, as_of_date, horizons, run_id=run_id)
            return self._status_results(
                horizons,
                etf_id=etf_id,
                as_of_date=as_of_date,
                run_id=run_id,
                status="failed",
                message="Toto live forecasting requires adjusted price history.",
            )
        try:
            if self.config.mode == "mock":
                return self._mock_forecast(etf_id, as_of_date, horizons, prices, run_id=run_id)
            if self._model is None:
                self.load_model()
            return self._forecast_live(etf_id, as_of_date, horizons, prices, run_id=run_id)
        except Exception as exc:
            return self._status_results(
                horizons,
                etf_id=etf_id,
                as_of_date=as_of_date,
                run_id=run_id,
                status="failed",
                message=f"Toto live forecast failed: {type(exc).__name__}: {exc}",
            )

    def unload_model(self) -> None:
        self._model = None
        self._device = None

    def _checkpoint_reference(self) -> str | None:
        local_path = self._local_model_path()
        if local_path is not None and _is_compatible_toto2_checkpoint(local_path):
            return str(local_path)
        repo_id = self._repo_id()
        if self.config.allow_remote_download and not self.config.local_files_only and repo_id:
            return repo_id
        return None

    def _local_model_path(self) -> Path | None:
        if not self.config.model_path:
            return None
        path = Path(self.config.model_path)
        return path if path.is_absolute() else ROOT / path

    def _repo_id(self) -> str | None:
        if self.config.model_size and self.config.model_size.lower() in self.config.hf_repo_ids:
            return self.config.hf_repo_ids[self.config.model_size.lower()]
        return self.config.hf_repo_id

    def _patch_size(self) -> int:
        local_path = self._local_model_path()
        if local_path is not None and local_path.is_dir():
            config_path = local_path / "config.json"
            if config_path.exists():
                try:
                    raw = json.loads(config_path.read_text(encoding="utf-8"))
                    patch_size = int(raw.get("patch_size", 32))
                    return patch_size if patch_size > 0 else 32
                except Exception:
                    return 32
        return 32

    def _forecast_live(
        self,
        etf_id: str,
        as_of_date: date,
        horizons: list[int],
        prices: pd.DataFrame,
        *,
        run_id: str,
    ) -> list[ForecastResult]:
        torch = __import__("torch")
        model_input = self.build_multivariate_input(etf_id, as_of_date, prices)
        series = model_input.series.dropna(how="all")
        if series.empty or etf_id not in series.columns:
            raise ValueError("No adjusted return history available for Toto live forecast.")
        values = series.fillna(0.0).to_numpy(dtype=float).T[None, :, :]
        mask = series.notna().to_numpy(dtype=bool).T[None, :, :]
        target = torch.tensor(values, dtype=torch.float32, device=self._device)
        target_mask = torch.tensor(mask, dtype=torch.bool, device=self._device)
        series_ids = torch.arange(values.shape[1], dtype=torch.long, device=self._device).reshape(1, values.shape[1])
        with torch.no_grad():
            quantiles = self._model.forecast(
                {"target": target, "target_mask": target_mask, "series_ids": series_ids},
                horizon=max(horizons),
                decode_block_size=self.config.decode_block_size,
                has_missing_values=bool((~mask).any()),
            )
        return toto_quantiles_to_log_return_results(
            quantiles=_to_numpy(quantiles),
            horizons=horizons,
            etf_id=etf_id,
            forecast_date=as_of_date,
            run_id=run_id,
            model_version=f"toto_2_0_{self.config.model_size or 'live'}",
        )

    def _mock_forecast(
        self,
        etf_id: str,
        as_of_date: date,
        horizons: list[int],
        prices: pd.DataFrame,
        *,
        run_id: str,
    ) -> list[ForecastResult]:
        model_input = self.build_multivariate_input(etf_id, as_of_date, prices)
        target = model_input.series[etf_id].dropna()
        if target.empty:
            mean = 0.0
            vol = 0.0
        else:
            market = model_input.series.drop(columns=[etf_id], errors="ignore").mean(axis=1)
            blended = 0.65 * target.tail(180).mean() + 0.35 * market.tail(180).mean()
            mean = float(blended * 0.45)
            vol = float(target.tail(60).std() * np.sqrt(252))
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
                    forecast_date=as_of_date,
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

    def _mock_forecast_without_prices(self, etf_id: str, as_of_date: date, horizons: list[int], *, run_id: str) -> list[ForecastResult]:
        return [
            ForecastResult(
                run_id=run_id,
                model_name=self.model_name,
                model_version=self.model_version + "_mock",
                etf_id=etf_id,
                forecast_date=as_of_date,
                horizon_days=horizon,
                expected_return=0.0,
                expected_excess_return=0.0,
                q10_return=0.0,
                q50_return=0.0,
                q90_return=0.0,
                forecast_vol=0.0,
                prob_positive_return=0.5,
                status="ok",
                is_fallback=True,
                fallback_model="zero_return_mock",
                calibration_status="mock_not_for_live_scoring",
            )
            for horizon in horizons
        ]

    def _status_results(
        self,
        horizons: list[int],
        *,
        etf_id: str,
        as_of_date: date,
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
                forecast_date=as_of_date,
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


def toto_quantiles_to_log_return_results(
    *,
    quantiles: Any,
    horizons: list[int],
    etf_id: str,
    forecast_date: date,
    run_id: str,
    model_version: str,
) -> list[ForecastResult]:
    values = np.asarray(quantiles, dtype=float)
    if values.ndim != 4 or values.shape[0] < 9 or values.shape[1] < 1 or values.shape[2] < 1:
        raise ValueError("Expected Toto quantiles with shape (9, batch, n_variates, horizon).")
    target = values[:, 0, 0, :]
    results: list[ForecastResult] = []
    for horizon in horizons:
        if horizon < 1 or horizon > target.shape[1]:
            message = f"Toto returned {target.shape[1]} forecast steps; requested horizon {horizon}."
            results.append(
                ForecastResult(
                    run_id=run_id,
                    model_name="toto",
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
        q10 = float(np.nansum(target[0, :horizon]))
        q50 = float(np.nansum(target[4, :horizon]))
        q90 = float(np.nansum(target[8, :horizon]))
        results.append(
            ForecastResult(
                run_id=run_id,
                model_name="toto",
                model_version=model_version,
                etf_id=etf_id,
                forecast_date=forecast_date,
                horizon_days=horizon,
                expected_return=q50,
                expected_excess_return=q50,
                q10_return=q10,
                q50_return=q50,
                q90_return=q90,
                forecast_vol=_quantile_vol_proxy(q10, q90, horizon),
                prob_positive_return=float(q50 > 0),
                status="ok",
                calibration_status="not_evaluated",
            )
        )
    return results


def _torch_device(torch: Any, configured_device: str) -> Any:
    if configured_device == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(configured_device)


def _is_compatible_toto2_checkpoint(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    has_config = (path / "config.json").exists()
    has_single_weight = (path / "model.safetensors").exists()
    has_sharded_weights = (path / "model.safetensors.index.json").exists() and _has_weight_files(path)
    return has_config and (has_single_weight or has_sharded_weights)


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def _quantile_vol_proxy(q10: float | None, q90: float | None, horizon: int) -> float | None:
    if q10 is None or q90 is None or horizon <= 0:
        return None
    horizon_vol = max((q90 - q10) / 2.563, 0.0)
    return float(horizon_vol / np.sqrt(horizon / 252))
