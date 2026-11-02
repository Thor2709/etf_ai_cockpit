"""Canonical local forecast recipe and derived pipeline runner.

Open defaults: forecast the configured enabled universe at its latest stored price
date, use configured horizons, disable optional live models, and never run a
single-instrument forecast. Forecast cache files are dated and shared by the
snapshot loader, so a partial-universe write could replace a complete cache.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from etf_cockpit.application.backtest_service import BacktestService
from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.application.forecast_service import ForecastService, _config_with_optional_models_disabled
from etf_cockpit.application.reference_context import _benchmark_reference_snapshot_inputs, _reference_context_from_inputs
from etf_cockpit.application.signal_service import SignalService
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import FORECASTS_DIR
from etf_cockpit.core.workflow import PublicationScopeFactory
from etf_cockpit.data.duckdb_store import load_holdings, load_prices
from etf_cockpit.models.forecast_scores import configured_forecast_request_identity, forecast_request_identity


PIPELINE_STEPS = ("features", "signals", "forecasts", "scores", "backtest")


def pipeline_request_payload(snapshot: Any, steps: Sequence[str]) -> dict[str, object]:
    """Fingerprint submitted steps against the snapshot and current settings revision."""

    from etf_cockpit.core.versioning import current_settings_revision

    return {
        "steps": tuple(steps),
        "live_optional_models": False,
        "universe_revision": getattr(snapshot, "universe_revision", None),
        "data_as_of": getattr(getattr(snapshot, "data_report", None), "as_of_date", None),
        "settings_revision": current_settings_revision(),
    }


def run_forecast_recipe(
    config: AppConfig,
    *,
    as_of_date: date | str | None = None,
    instrument_ids: Sequence[str] | None = None,
    live_optional_models: bool | None = False,
    prices: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> dict[str, Any]:
    """Run the canonical forecast service for the full configured universe."""

    price_frame = (prices if prices is not None else load_prices(config=config)).copy()
    if price_frame.empty or not {"etf_id", "date"}.issubset(price_frame.columns):
        raise ValueError("Cached prices contain no dated observations.")
    enabled_ids = tuple(str(value) for value in config.universe.enabled_ids)
    if not enabled_ids:
        raise ValueError("The configured enabled universe is unavailable.")
    if instrument_ids is not None:
        selected_ids = tuple(dict.fromkeys(str(value).strip() for value in instrument_ids if str(value).strip()))
        if len(selected_ids) != len(enabled_ids) or set(selected_ids) != set(enabled_ids):
            raise ValueError("Per-instrument forecast runs are unavailable; run the configured universe.")
    price_frame = price_frame.loc[price_frame["etf_id"].astype(str).isin(set(enabled_ids))].copy()
    parsed_dates = pd.to_datetime(price_frame["date"], errors="coerce", utc=True)
    if parsed_dates.dropna().empty:
        raise ValueError("Cached prices contain no valid dates.")
    price_frame["date"] = parsed_dates.dt.tz_convert(None)
    if as_of_date is None or str(as_of_date).strip().casefold() == "latest":
        effective_as_of = parsed_dates.max().date()
    else:
        parsed_as_of = pd.to_datetime(as_of_date, errors="coerce", utc=True)
        if pd.isna(parsed_as_of):
            raise ValueError("date must be 'latest' or a valid date.")
        effective_as_of = parsed_as_of.date()

    reference_holdings = holdings if holdings is not None else load_holdings(config=config)
    reference_context = _reference_context_from_inputs(
        _benchmark_reference_snapshot_inputs(config, effective_as_of, reference_holdings),
        purpose="comparison",
        analysis_id=f"forecast:{effective_as_of.isoformat()}",
    )
    configured_identity = configured_forecast_request_identity(config)
    if live_optional_models is None:
        live_optional_models = bool(configured_identity["live_optional_models"])
    if not isinstance(live_optional_models, bool):
        raise ValueError("live_optional_models must be a boolean.")
    request_identity = forecast_request_identity(
        config,
        list(configured_identity["requested_horizons"]),
        live_optional_models=live_optional_models,
    )
    forecast_config = config if live_optional_models else _config_with_optional_models_disabled(config)
    service = ForecastService(forecast_config, reference_context=reference_context)
    promotions = service.evaluate_promotions(effective_as_of, price_frame) if config.models.promotion.enabled else {}
    forecasts = service.run_forecasts(
        effective_as_of,
        list(enabled_ids),
        price_frame,
        horizons=list(request_identity["requested_horizons"]),
        cache_request_identity=request_identity,
        live_optional_models=live_optional_models,
        progress_callback=progress_callback,
        publish_guard=publish_guard,
        promotions=promotions,
        promotion_prices=price_frame,
    )
    counts = Counter((forecast.model_name, forecast.status) for forecast in forecasts)
    statuses = {forecast.status for forecast in forecasts}
    status = "unavailable" if not forecasts or statuses == {"unavailable"} else "partial" if "failed" in statuses or "unavailable" in statuses else "available"
    return {
        "status": status,
        "as_of_date": effective_as_of.isoformat(),
        "instrument_count": len(enabled_ids),
        "forecast_row_count": len(forecasts),
        "model_status_counts": [
            {"model": model, "status": forecast_status, "count": count}
            for (model, forecast_status), count in sorted(counts.items())
        ],
        "live_optional_models": live_optional_models,
        "promotions": {
            name: {"state": item.state, "reason": item.reason}
            for name, item in promotions.items()
        },
        "output_path": str(FORECASTS_DIR / f"forecast_results_{effective_as_of:%Y%m%d}.csv"),
        "execution_allowed": False,
    }


def run_pipeline_steps(
    session: Any,
    steps: Sequence[str],
    *,
    live_optional_models: bool = False,
) -> dict[str, Any]:
    """Run selected cached-data application steps in dependency order."""

    selected = tuple(dict.fromkeys(str(step).strip().casefold() for step in steps))
    unknown = sorted(set(selected) - set(PIPELINE_STEPS))
    if not selected or unknown:
        raise ValueError(f"steps must be a non-empty subset of {', '.join(PIPELINE_STEPS)}.")
    if live_optional_models:
        raise ValueError("live_optional_models must be false for a pipeline run.")

    snapshot = session.snapshot
    config = snapshot.config
    outputs: dict[str, Any] = {}
    for step in PIPELINE_STEPS:
        if step not in selected:
            continue
        if step == "features":
            frame = FeatureService(config).compute_features(publish_guard=session.activity_publication)
            outputs[step] = {"status": "available" if not frame.empty else "unavailable", "row_count": len(frame)}
        elif step == "signals":
            with session.activity_publication():
                service = SignalService(config)
                signals = service.generate_signals()
            outputs[step] = {
                "status": "unavailable" if service.last_unavailable_reason else "available",
                "reason": service.last_unavailable_reason,
                "signal_count": len(signals),
            }
        elif step == "forecasts":
            outputs[step] = run_forecast_recipe(
                config,
                live_optional_models=False,
                publish_guard=session.activity_publication,
            )
        elif step == "scores":
            session.refresh_snapshot()
            path = session.publish()
            outputs[step] = {"status": "available", "output_path": str(path)}
        elif step == "backtest":
            report = BacktestService(config).run_backtest(publish_guard=session.activity_publication)
            outputs[step] = {
                "status": "available" if not report.results.empty else "unavailable",
                "quality_label": report.quality_label if not report.results.empty else None,
                "strategy_count": len(report.results),
                "notes": list(report.quality_notes or ())[:5],
            }
    return {"status": "complete", "steps": outputs, "execution_allowed": False}
