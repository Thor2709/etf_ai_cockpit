"""Forecast orchestration: baseline and optional-model forecasts, benchmark post-processing and bound forecast artefacts (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import (
    asdict,
    replace,
)
from collections import Counter
import math
from datetime import date
from pathlib import Path
import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import FORECASTS_DIR
from etf_cockpit.core.timing import timed_step
from etf_cockpit.core.types import ForecastResult
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.core.versioning import (
    current_settings_identity,
    current_settings_revision,
    ensure_run_manifest,
    settings_bound_run_id,
)
from etf_cockpit.data.duckdb_store import load_prices
from etf_cockpit.features.forecast_lab import build_forecast_lab_workspace as build_forecast_lab_workspace
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity as configured_forecast_request_identity, forecast_request_identity
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry
from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    clip_to_decision_window,
    unavailable_reference_projection,
)
from etf_cockpit.application.derived_cache import (
    _calculation_window,
    _current_universe_revision,
    _price_snapshot_binding,
    _write_bound_cache_group,
)


def _live_optional_models_from_config(config: AppConfig) -> bool:
    return any(
        config.models.runtime(name).enabled and config.models.runtime(name).mode == "live"
        for name in ("timesfm", "toto")
    )


class ForecastService:
    def __init__(self, config: AppConfig, *, reference_context: CanonicalReferenceContext | None = None):
        self.config = config
        self.reference_context = reference_context or CanonicalReferenceContext(
            CanonicalBenchmarkRegistry(),
            None,
            unavailable_reference_projection(),
        )

    def run_forecasts(
        self,
        as_of_date: date,
        etf_ids: list[str],
        prices: pd.DataFrame | None = None,
        *,
        output_path: Path | None = None,
        horizons: list[int] | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
        publish_guard: PublicationScopeFactory | None = None,
        reference_context: CanonicalReferenceContext | None = None,
        cache_request_identity: Mapping[str, object] | None = None,
        live_optional_models: bool | None = None,
    ) -> list[ForecastResult]:
        settings_identity = current_settings_identity()
        price_frame = prices if prices is not None else load_prices()
        price_frame = price_frame.copy()
        price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce", utc=True, format="mixed")
        context = reference_context if reference_context is not None else self.reference_context
        calculation_window = _calculation_window(context, as_of_date, price_frame)
        if calculation_window is None:
            raise ValueError("canonical forecast calculation window is unavailable")
        price_frame = clip_to_decision_window(price_frame, **calculation_window)
        price_binding = _price_snapshot_binding(price_frame, calculation_window=calculation_window)
        if price_binding is None:
            raise ValueError("adjusted-price snapshot identity is unavailable")
        horizons = horizons or self.config.models.forecast_horizons_trading_days
        resolved_live_optional_models = (
            _live_optional_models_from_config(self.config)
            if live_optional_models is None
            else live_optional_models
        )
        derived_request_identity = forecast_request_identity(
            self.config,
            horizons,
            live_optional_models=resolved_live_optional_models,
        )
        if cache_request_identity is not None and dict(cache_request_identity) != derived_request_identity:
            raise ValueError("forecast cache request identity does not match the calculation request")
        pivot = price_frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
        benchmark_id = context.benchmark_data_id if context is not None else None
        benchmark_returns = pivot[benchmark_id].pct_change(fill_method=None).dropna() if benchmark_id in pivot else None
        forecasts: list[ForecastResult] = []
        run_id = settings_bound_run_id(
            f"forecast_{as_of_date:%Y%m%d}",
            settings_identity=settings_identity,
        )
        if progress_callback is not None:
            progress_callback("Running baseline forecasts", 1, 4)
        # Per-family durations are the Forecast Lab's measured resource use.
        with timed_step("forecasts", "model:baseline", run_id=run_id):
            for etf_id in etf_ids:
                if etf_id not in pivot:
                    continue
                series = pivot[etf_id].dropna()
                forecasts.extend(
                    baseline_forecast(
                        etf_id,
                        series,
                        horizons,
                        as_of_date,
                        run_id=run_id,
                        benchmark_returns=benchmark_returns,
                    )
                )
        if progress_callback is not None:
            progress_callback("Checking cached TimesFM forecasts", 2, 4)
        with timed_step("forecasts", "model:timesfm", run_id=run_id):
            forecasts.extend(self._run_timesfm_forecasts(pivot, etf_ids, horizons, as_of_date, run_id))
        if progress_callback is not None:
            progress_callback("Checking cached Toto forecasts", 3, 4)
        with timed_step("forecasts", "model:toto", run_id=run_id):
            forecasts.extend(self._run_toto_forecasts(price_frame, etf_ids, horizons, as_of_date, run_id))
        forecasts = _postprocess_forecast_benchmark_fields(forecasts, benchmark_returns)
        with publication_scope(publish_guard):
            ensure_run_manifest(
                run_id,
                (
                    "schema:local-storage",
                    "dataset:prices",
                    "policy:model-settings",
                    "formula:score-engine-v3",
                    "model:baseline",
                    "model:timesfm",
                    "model:toto",
                ),
                settings_identity=settings_identity,
            )
        if progress_callback is not None:
            progress_callback("Writing forecast outputs", 3, 4)
        self._write_forecasts(
            forecasts,
            as_of_date,
            output_path=output_path,
            settings_revision=str(settings_identity["settings_revision"]),
            reference_identity=context.identity,
            price_binding=price_binding,
            cache_request_identity=derived_request_identity,
            live_optional_models=resolved_live_optional_models,
            publish_guard=publish_guard,
        )
        return forecasts

    def _run_timesfm_forecasts(
        self,
        pivot: pd.DataFrame,
        etf_ids: list[str],
        horizons: list[int],
        as_of_date: date,
        run_id: str,
    ) -> list[ForecastResult]:
        from etf_cockpit.models.timesfm_adapter import TimesFMAdapter

        adapter = TimesFMAdapter(self.config.models.runtime("timesfm"))
        forecasts: list[ForecastResult] = []
        try:
            for etf_id in etf_ids:
                if etf_id not in pivot:
                    continue
                forecasts.extend(
                    adapter.forecast_series(
                        pivot[etf_id].dropna(),
                        horizons,
                        etf_id=etf_id,
                        forecast_date=as_of_date,
                        run_id=run_id,
                    )
                )
        finally:
            adapter.unload_model()
        return forecasts

    def _run_toto_forecasts(
        self,
        price_frame: pd.DataFrame,
        etf_ids: list[str],
        horizons: list[int],
        as_of_date: date,
        run_id: str,
    ) -> list[ForecastResult]:
        from etf_cockpit.models.toto_adapter import TotoAdapter

        adapter = TotoAdapter(self.config.models.runtime("toto"))
        forecasts: list[ForecastResult] = []
        try:
            for etf_id in etf_ids:
                forecasts.extend(
                    adapter.forecast_etf(
                        etf_id,
                        as_of_date,
                        horizons,
                        prices=price_frame[["date", "etf_id", "adjusted_close"]],
                        run_id=run_id,
                    )
                )
        finally:
            adapter.unload_model()
        return forecasts

    def _write_forecasts(
        self,
        forecasts: list[ForecastResult],
        as_of_date: date,
        *,
        output_path: Path | None = None,
        settings_revision: str | None = None,
        reference_identity: Mapping[str, object] | None = None,
        price_binding: Mapping[str, object] | None = None,
        cache_request_identity: Mapping[str, object] | None = None,
        live_optional_models: bool | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> None:
        output = output_path or FORECASTS_DIR / f"forecast_results_{as_of_date:%Y%m%d}.csv"
        if cache_request_identity is None:
            cache_request_identity = forecast_request_identity(
                self.config,
                sorted({forecast.horizon_days for forecast in forecasts}) or None,
                live_optional_models=(
                    _live_optional_models_from_config(self.config)
                    if live_optional_models is None
                    else live_optional_models
                ),
            )
        else:
            requested_horizons = cache_request_identity.get("requested_horizons")
            requested_mode = cache_request_identity.get("live_optional_models")
            if not isinstance(requested_horizons, list) or type(requested_mode) is not bool:
                raise ValueError("forecast cache request identity is malformed")
            validated_identity = forecast_request_identity(
                self.config,
                requested_horizons,
                live_optional_models=requested_mode,
            )
            output_horizons = {forecast.horizon_days for forecast in forecasts}
            if dict(cache_request_identity) != validated_identity or not output_horizons.issubset(requested_horizons):
                raise ValueError("forecast cache request identity does not match forecast output")
        payload = pd.DataFrame([_forecast_to_row(forecast) for forecast in forecasts]).to_csv(index=False).encode("utf-8")

        def validate(path: Path) -> None:
            _validate_csv(path)

        with timed_step("forecasts", "write_output"):
            with publication_scope(publish_guard):
                _write_bound_cache_group(
                    output,
                    payload,
                    validate,
                    _current_universe_revision(),
                    settings_revision or current_settings_revision(),
                    reference_identity,
                    price_binding,
                    cache_request_identity,
                )


def _forecast_to_row(forecast: ForecastResult) -> dict[str, object]:
    data = asdict(forecast)
    data["forecast_date"] = forecast.forecast_date.isoformat()
    return data


def _postprocess_forecast_benchmark_fields(
    forecasts: list[ForecastResult],
    benchmark_returns: pd.Series | None,
) -> list[ForecastResult]:
    """Derive relative forecast fields uniformly after every model adapter."""

    if benchmark_returns is None or benchmark_returns.empty:
        return [
            replace(forecast, expected_excess_return=None, prob_beat_benchmark=None)
            for forecast in forecasts
        ]
    benchmark_daily = float(benchmark_returns.tail(180).mean() * 0.35)
    output: list[ForecastResult] = []
    for forecast in forecasts:
        if forecast.expected_return is None:
            output.append(replace(forecast, expected_excess_return=None, prob_beat_benchmark=None))
            continue
        excess = float(forecast.expected_return - benchmark_daily * forecast.horizon_days)
        try:
            volatility = float(forecast.forecast_vol)
        except (TypeError, ValueError):
            volatility = None
        if volatility is None or not math.isfinite(volatility) or volatility <= 0:
            output.append(
                replace(
                    forecast,
                    expected_excess_return=excess,
                    prob_beat_benchmark=None,
                    reason_unavailable=(
                        f"{forecast.reason_unavailable}; forecast_vol_unavailable_for_benchmark_probability"
                        if forecast.reason_unavailable
                        else "forecast_vol_unavailable_for_benchmark_probability"
                    ),
                )
            )
            continue
        output.append(
            replace(
                forecast,
                expected_excess_return=excess,
                prob_beat_benchmark=float(1 / (1 + math.exp(-excess / volatility))),
            )
        )
    return output


def _validate_csv(path: Path, *, index_col: int | None = None) -> None:
    # Empty trade/signal/forecast frames are valid unavailable artefacts.
    if path.stat().st_size:
        pd.read_csv(path, index_col=index_col)


def _forecast_status_summary(forecasts: list[ForecastResult]) -> str:
    if not forecasts:
        return "no rows"
    counts = Counter((forecast.model_name, forecast.status) for forecast in forecasts)
    return ", ".join(f"{model} {status} {count}" for (model, status), count in sorted(counts.items()))


def _forecast_frame_status_summary(frame: pd.DataFrame) -> str:
    if frame.empty or not {"model_name", "status"}.issubset(frame.columns):
        return "no rows"
    counts = frame.groupby(["model_name", "status"], dropna=False).size()
    return ", ".join(f"{model} {status} {count}" for (model, status), count in counts.sort_index().items())


def _config_with_optional_models_disabled(config: AppConfig) -> AppConfig:
    quick_config = config.model_copy(deep=True)
    for model_name in ("timesfm", "toto"):
        model_config = dict(quick_config.models.models.get(model_name, {}))
        model_config.update(
            {
                "enabled": False,
                "mode": "disabled",
            }
        )
        quick_config.models.models[model_name] = model_config
    return quick_config
