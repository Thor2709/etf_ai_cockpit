"""MCP forecast, model-status, Forecast Lab, backtest, and derived-pipeline tools.

Open defaults: forecast and backtest pages contain 25 records (maximum 100),
Forecast Lab uses the caller's exact horizon, optional model computation is off,
and a forecast run always covers the full configured enabled universe. Stress
defaults to current holdings, a 1-day horizon, 100,000 EUR notional, and 25
contributors per page (maximum 100); a saved scenario keeps its stored horizon
unless the caller supplies one. Reverse stress uses the canonical 5.0 maximum
shock bound and has no time horizon.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from etf_cockpit.core.paths import ROOT
from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, tool


_CURSORS = CursorCodec()
_MAX_INSTRUMENTS = 100
_MAX_HORIZONS = 20
_MODEL_FIELDS = (
    "model_name", "forecast_rows", "matured_rows", "mae", "mase", "directional_accuracy",
    "interval_coverage", "conformal_coverage", "calibration_status", "oos_rows", "oos_mae",
    "oos_mase", "oos_directional_accuracy", "excluded_rows", "drift_status", "promotion_state",
)
_EQUITY_FIELDS = ("strategy_name", "start_date", "end_date", "final_value_eur", "max_drawdown", "backtest_quality")


def _session() -> Any:
    active = current_call_context().session
    if active is not None and getattr(active, "snapshot", None) is not None:
        session = active
    else:
        from etf_cockpit.application.headless_session import HeadlessSession
        from etf_cockpit.application.snapshot_builder import build_snapshot

        session = HeadlessSession(build_snapshot(force_sample=False), root=ROOT)
    if Path(getattr(session, "root", ROOT)).resolve() != ROOT.resolve():
        raise MCPToolError("DATA_ROOT_MISMATCH", "The analysis session is outside the configured data root", "Restart the MCP server with the configured owner data root.")
    return session


def _snapshot() -> tuple[Any, Any]:
    session = _session()
    snapshot = getattr(session, "snapshot", None)
    if snapshot is None:
        raise MCPToolError("FORECAST_DATA_UNAVAILABLE", "The application snapshot is unavailable", "Load the configured local snapshot before requesting forecast analysis.")
    return session, snapshot


def _records(frame: object, *, fields: Sequence[str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame):
        return []
    selected = frame
    if fields is not None:
        selected = frame.loc[:, [field for field in fields if field in frame.columns]]
    return selected.to_dict("records")


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _simple_return(value: object) -> float | None:
    log_return = _number(value)
    if log_return is None:
        return None
    try:
        result = math.expm1(log_return)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _instrument_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise InvalidArgumentsError("instrument_ids must be a list of 1 to 100 non-empty identifiers")
    selected = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not selected or len(selected) > _MAX_INSTRUMENTS:
        raise InvalidArgumentsError("instrument_ids must contain 1 to 100 non-empty identifiers")
    return selected


def _horizons(values: Sequence[int]) -> tuple[int, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise InvalidArgumentsError("horizons must be a list of positive integers")
    selected: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 2520:
            raise InvalidArgumentsError("horizons must contain positive integer trading-day counts up to 2520")
        if value not in selected:
            selected.append(value)
    if not selected or len(selected) > _MAX_HORIZONS:
        raise InvalidArgumentsError("horizons must contain 1 to 20 positive integer trading-day counts")
    return tuple(selected)


def _page(values: list[dict[str, Any]], *, cursor: str | None, limit: int, filters: Mapping[str, object]) -> tuple[list[dict[str, Any]], str | None]:
    try:
        page_size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters=filters) if cursor else 0
    page = values[offset : offset + page_size]
    next_cursor = _CURSORS.encode(offset + page_size, filters=filters) if offset + page_size < len(values) else None
    return page, next_cursor


@tool(tier="read", description="Read point-in-time forecasts and simple-return quantiles for requested instruments and horizons.", read_only_hint=True, idempotent_hint=True)
def forecast_get(
    instrument_ids: Sequence[str],
    horizons: Sequence[int],
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    selected_ids = _instrument_ids(instrument_ids)
    selected_horizons = _horizons(horizons)
    _session_value, snapshot = _snapshot()
    frame = getattr(snapshot, "forecasts", None)
    forecasts: list[dict[str, Any]] = []
    for instrument_id in selected_ids:
        for horizon in selected_horizons:
            matching = (
                frame.loc[
                    frame["etf_id"].astype(str).eq(instrument_id)
                    & pd.to_numeric(frame["horizon_days"], errors="coerce").eq(horizon)
                ].copy()
                if isinstance(frame, pd.DataFrame)
                and {"etf_id", "horizon_days"}.issubset(frame.columns)
                else pd.DataFrame()
            )
            if not matching.empty:
                if "forecast_date" in matching.columns:
                    matching["_sort_date"] = pd.to_datetime(matching["forecast_date"], errors="coerce", utc=True)
                    matching = matching.sort_values("_sort_date", kind="stable")
                if "model_name" in matching.columns:
                    matching = matching.drop_duplicates("model_name", keep="last")
            if matching.empty:
                forecasts.append({
                    "instrument_id": instrument_id, "horizon_days": horizon, "model": None,
                    "status": "unavailable", "unavailable_reason": "forecast_cache_unavailable",
                    "expected_simple_return": None, "q10_simple_return": None,
                    "q50_simple_return": None, "q90_simple_return": None,
                    "promotion_status": "unknown", "model_allowed_in_score": None,
                    "leakage_flag": "unknown",
                })
                continue
            for _, row in matching.iterrows():
                status = str(row.get("status") or "unavailable").casefold()
                available = status == "ok"
                model_name = str(row.get("model_name") or "unknown")
                forecasts.append({
                    "instrument_id": instrument_id,
                    "horizon_days": horizon,
                    "model": model_name,
                    "forecast_date": row.get("forecast_date"),
                    "status": status,
                    "unavailable_reason": row.get("reason_unavailable") or row.get("error_message") if not available else None,
                    "expected_simple_return": _simple_return(row.get("expected_return")) if available else None,
                    "q10_simple_return": _simple_return(row.get("q10_return")) if available else None,
                    "q50_simple_return": _simple_return(row.get("q50_return")) if available else None,
                    "q90_simple_return": _simple_return(row.get("q90_return")) if available else None,
                    "promotion_status": row.get("promotion_status", "unknown"),
                    "model_allowed_in_score": row.get("model_allowed_in_score"),
                    "leakage_flag": row.get("contamination_status", "not_applicable" if model_name == "baseline" else "unknown"),
                })
    filters = {"instrument_ids": selected_ids, "horizons": selected_horizons}
    page, next_cursor = _page(forecasts, cursor=cursor, limit=limit, filters=filters)
    available_count = sum(row["status"] == "ok" for row in forecasts)
    status = "unavailable" if available_count == 0 else "partial" if available_count < len(forecasts) else "available"
    return {
        "status": status,
        "forecasts": page,
        "forecast_count": len(forecasts),
        "available_count": available_count,
        "execution_allowed": False,
        "next_cursor": next_cursor,
    }


@tool(tier="read", description="Show local model runtime, weight, promotion, and cutoff status.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def forecast_models_status(cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    from etf_cockpit.application.forecast_lab_inputs import assemble_forecast_lab_inputs, load_forecast_model_diagnostics
    from etf_cockpit.application.forecast_service import build_forecast_lab_workspace

    _session_value, snapshot = _snapshot()
    try:
        diagnostics = load_forecast_model_diagnostics(snapshot.config)
        forecasts, history, prices = assemble_forecast_lab_inputs(snapshot)
        report = build_forecast_lab_workspace(snapshot.config, forecasts, prices, forecast_history=history)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise MCPToolError("MODEL_STATUS_UNAVAILABLE", "Local model status could not be read", f"Check local model and forecast evidence ({type(exc).__name__}).") from None
    promotion_frame = report.get("promotion")
    promotions = {
        str(row.get("model_name")): row
        for row in _records(promotion_frame)
        if row.get("model_name") is not None
    }
    stored_rows = getattr(snapshot, "forecasts", None)
    latest_by_model: dict[str, dict[str, Any]] = {}
    if isinstance(stored_rows, pd.DataFrame) and {"model_name", "forecast_date"}.issubset(stored_rows.columns):
        ordered = stored_rows.copy()
        ordered["_sort_date"] = pd.to_datetime(ordered["forecast_date"], errors="coerce", utc=True)
        ordered = ordered.sort_values("_sort_date", kind="stable").drop_duplicates("model_name", keep="last")
        latest_by_model = {
            str(row.get("model_name")): row
            for row in ordered.drop(columns="_sort_date").to_dict("records")
        }
    rows: list[dict[str, Any]] = []
    for item in diagnostics:
        model_name = str(getattr(item, "model_name", "unknown"))
        promotion = promotions.get(model_name, {})
        latest = latest_by_model.get(model_name, {})
        weight_files = tuple(getattr(item, "weight_files", ()) or ())
        rows.append({
            "model": model_name,
            "model_id": getattr(item, "model_id", None),
            "status": getattr(item, "status", "unavailable"),
            "live_ready": bool(getattr(item, "live_ready", False)),
            "weights_present": bool(getattr(item, "present", False)),
            "weight_count": len(weight_files),
            "weight_bytes": getattr(item, "total_bytes", None) if weight_files else None,
            "runtime_packages": getattr(item, "runtime_packages", {}),
            "promotion_status": latest.get("promotion_status", promotion.get("state", "not_proven")),
            "promotion_reason": latest.get("promotion_reason", promotion.get("reason")),
            "pretraining_cutoff": latest.get("pretraining_cutoff", promotion.get("pretraining_cutoff")),
            "cutoff_scope": latest.get("cutoff_scope", promotion.get("cutoff_scope")),
            "model_allowed_in_score": latest.get("model_allowed_in_score"),
            "message": getattr(item, "message", None),
        })
    page, next_cursor = _page(rows, cursor=cursor, limit=limit, filters={"view": "forecast_models_status"})
    return {"status": report.get("status", "unavailable"), "models": page, "model_count": len(rows), "next_cursor": next_cursor}


@tool(tier="read", description="Compare stored local forecast models using canonical Forecast Lab metrics, folds, exclusions, and promotion evidence.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def forecast_lab_compare(
    horizon: int,
    models: Sequence[str] | None = None,
    instrument_ids: Sequence[str] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    from etf_cockpit.application.forecast_lab_inputs import assemble_forecast_lab_inputs
    from etf_cockpit.application.forecast_service import build_forecast_lab_workspace

    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1 or horizon > 2520:
        raise InvalidArgumentsError("horizon must be a positive trading-day count up to 2520")
    if models is not None and (isinstance(models, (str, bytes)) or not isinstance(models, Sequence)):
        raise InvalidArgumentsError("models must be a list of model identifiers")
    selected_models = tuple(dict.fromkeys(str(value).strip().casefold() for value in (models or ()) if str(value).strip()))
    if len(selected_models) > 20:
        raise InvalidArgumentsError("models may contain at most 20 identifiers")
    selected_ids = _instrument_ids(instrument_ids) if instrument_ids is not None else None
    _session_value, snapshot = _snapshot()
    forecasts, history, prices = assemble_forecast_lab_inputs(snapshot)
    if isinstance(forecasts, pd.DataFrame) and "horizon_days" in forecasts.columns:
        forecasts = forecasts.loc[pd.to_numeric(forecasts["horizon_days"], errors="coerce").eq(horizon)].copy()
    if isinstance(history, pd.DataFrame) and "horizon_days" in history.columns:
        history = history.loc[pd.to_numeric(history["horizon_days"], errors="coerce").eq(horizon)].copy()
    if selected_ids is not None:
        if isinstance(forecasts, pd.DataFrame) and "etf_id" in forecasts.columns:
            forecasts = forecasts.loc[forecasts["etf_id"].astype(str).isin(selected_ids)].copy()
        if isinstance(history, pd.DataFrame) and "etf_id" in history.columns:
            history = history.loc[history["etf_id"].astype(str).isin(selected_ids)].copy()
        if isinstance(prices, pd.DataFrame) and "etf_id" in prices.columns:
            prices = prices.loc[prices["etf_id"].astype(str).isin(selected_ids)].copy()
    report = build_forecast_lab_workspace(snapshot.config, forecasts, prices, forecast_history=history)
    model_frame = report.get("models")
    model_records = _records(model_frame, fields=_MODEL_FIELDS)
    if selected_models:
        model_records = [row for row in model_records if str(row.get("model_name") or "").casefold() in selected_models]
    evaluation = report.get("walk_forward_evaluation")
    folds = _records(evaluation)
    if selected_models:
        folds = [row for row in folds if str(row.get("model_name") or "").casefold() in selected_models]
    promotion_records = _records(report.get("promotion"))
    if selected_models:
        promotion_records = [row for row in promotion_records if str(row.get("model_name") or "").casefold() in selected_models]
    excluded = _records(report.get("excluded"))
    exclusion_filters = {"horizon": horizon, "models": selected_models, "instrument_ids": selected_ids}
    exclusion_page, next_cursor = _page(excluded, cursor=cursor, limit=limit, filters=exclusion_filters)
    notes = list(report.get("notes", ()))
    return {
        "status": report.get("status", "unavailable"),
        "as_of_date": report.get("as_of_date"),
        "horizon_days": horizon,
        "models": model_records,
        "walk_forward_evaluation": folds[:MAX_PAGE_SIZE],
        "promotions": promotion_records,
        "exclusions": exclusion_page,
        "exclusion_count": len(excluded),
        "notes": notes[:5],
        "next_cursor": next_cursor,
        "execution_allowed": False,
    }


@tool(tier="read", description="Read a matching cached backtest report without running or regenerating a backtest.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def backtest_get(
    cost_regime: str,
    strategy: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    from etf_cockpit.application.backtest_service import BacktestService

    if not isinstance(cost_regime, str) or not cost_regime.strip():
        raise InvalidArgumentsError("cost_regime must be a non-empty identifier")
    if strategy is not None and (not isinstance(strategy, str) or not strategy.strip()):
        raise InvalidArgumentsError("strategy must be a non-empty identifier when provided")
    _session_value, snapshot = _snapshot()
    service = BacktestService(snapshot.config)
    report = service.load_cached_backtest()
    if report is None:
        return {
            "status": "unavailable", "unavailable_reason": "cached_backtest_unavailable",
            "results": [], "equity_summary": [], "quality_label": None,
        }
    actual_cost_regime = str((report.metadata or {}).get("cost_regime") or "")
    if actual_cost_regime != cost_regime:
        return {
            "status": "unavailable", "unavailable_reason": "requested_cost_regime_not_cached",
            "cost_regime": cost_regime, "cached_cost_regime": actual_cost_regime or None,
            "results": [], "equity_summary": [], "quality_label": None,
        }
    results = report.results if isinstance(report.results, pd.DataFrame) else pd.DataFrame()
    if strategy is not None and "strategy_name" in results.columns:
        results = results.loc[results["strategy_name"].astype(str).eq(strategy)].copy()
    records = _records(results)
    filters = {"cost_regime": cost_regime, "strategy": strategy}
    page, next_cursor = _page(records, cursor=cursor, limit=limit, filters=filters)
    equity_summary = _records(results, fields=_EQUITY_FIELDS)
    status = "available" if records else "unavailable"
    return {
        "status": status,
        "unavailable_reason": None if records else "requested_strategy_not_cached",
        "cost_regime": actual_cost_regime,
        "results": page,
        "result_count": len(records),
        "equity_summary": equity_summary,
        "quality_label": report.quality_label if records else None,
        "quality_notes": list(report.quality_notes or ())[:5],
        "next_cursor": next_cursor,
        "execution_allowed": False,
    }


@tool(
    tier="read",
    description="Run a canonical local stress scenario or reverse-stress threshold against current, candidate, or paper holdings.",
    read_only_hint=True,
    idempotent_hint=True,
    profiles=("full",),
)
def stress_test(
    scenario: str | None = None,
    shocks: Mapping[str, object] | None = None,
    horizon: int | None = None,
    notional: float = 100_000.0,
    portfolio: str = "current",
    reverse_shock_name: str | None = None,
    loss_limit: float | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    from dataclasses import replace

    from etf_cockpit.application.stress_lab import (
        StressLabFacade,
        StressLabPersistenceError,
        StressPortfolioNotFoundError,
        StressScenarioError,
        build_stress_scenario,
        resolve_stress_portfolio,
    )

    if not isinstance(portfolio, str) or not portfolio.strip():
        raise InvalidArgumentsError("portfolio must be current, candidate, or paper:<account_id>")
    selected_portfolio = portfolio.strip()
    if scenario is not None and (not isinstance(scenario, str) or not scenario.strip()):
        raise InvalidArgumentsError("scenario must be a saved scenario identifier")
    if shocks is not None and not isinstance(shocks, Mapping):
        raise InvalidArgumentsError("shocks must be a mapping of supported shock names to fractions")
    if horizon is not None and (isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 3650):
        raise InvalidArgumentsError("horizon must be an integer from 1 to 3650")
    try:
        validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    selected_notional = _number(notional)
    if selected_notional is None or selected_notional <= 0:
        raise InvalidArgumentsError("notional must be finite and greater than zero")
    reverse_requested = reverse_shock_name is not None or loss_limit is not None
    if reverse_requested:
        if horizon is not None:
            raise InvalidArgumentsError("horizon does not apply to reverse stress")
        if scenario is not None or shocks is not None:
            raise InvalidArgumentsError("reverse stress accepts reverse_shock_name and loss_limit instead of scenario or shocks")
        if not isinstance(reverse_shock_name, str) or not reverse_shock_name.strip() or loss_limit is None:
            raise InvalidArgumentsError("reverse stress requires reverse_shock_name and loss_limit")
        selected_loss_limit = _number(loss_limit)
        if selected_loss_limit is None or selected_loss_limit <= 0:
            raise InvalidArgumentsError("loss_limit must be finite and greater than zero")
        if cursor is not None:
            raise InvalidArgumentsError("reverse stress results do not have additional pages")
    else:
        selected_loss_limit = None
        if (scenario is None) == (shocks is None):
            raise InvalidArgumentsError("provide exactly one saved scenario identifier or shocks mapping")

    session, snapshot = _snapshot()
    root = Path(getattr(session, "root", ROOT))
    facade = StressLabFacade(snapshot, root=root)
    try:
        allocation, unavailable_reason = resolve_stress_portfolio(snapshot, selected_portfolio, root=root)
    except StressPortfolioNotFoundError:
        raise MCPToolError("NOT_FOUND", "No paper account matches account_id", "Check the account_id with paper_portfolio and retry.") from None
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    except StressLabPersistenceError as exc:
        raise MCPToolError("STRESS_PORTFOLIO_UNAVAILABLE", "The selected portfolio could not be read", f"Check local portfolio evidence ({type(exc).__name__}).") from None
    if allocation.empty and unavailable_reason is None:
        unavailable_reason = "portfolio_allocation_unavailable"
    filters = {"portfolio": selected_portfolio, "mode": "reverse" if reverse_requested else "scenario"}

    if allocation.empty:
        return {
            "status": "unavailable",
            "portfolio": selected_portfolio,
            "scenario": None,
            "loss": None,
            "total_pnl": None,
            "instrument_count": 0,
            "contributors": [],
            "threshold": None,
            "unavailable_reason": unavailable_reason or "portfolio_allocation_unavailable",
            "next_cursor": None,
            "execution_allowed": False,
        }

    if reverse_requested:
        try:
            report = facade.reverse(
                shock_name=reverse_shock_name.strip(),  # type: ignore[union-attr]
                loss_limit=selected_loss_limit,  # type: ignore[arg-type]
                notional=selected_notional,
                allocation=allocation,
            )
        except StressScenarioError as exc:
            raise InvalidArgumentsError(str(exc)) from None
        binding = report.get("binding_exposure")
        contributors = [dict(binding)] if isinstance(binding, Mapping) else []
        filters["shock_name"] = reverse_shock_name.strip()
        page, next_cursor = _page(contributors, cursor=cursor, limit=limit, filters=filters)
        reverse_status = str(report.get("status", "unavailable"))
        return {
            "status": reverse_status,
            "portfolio": selected_portfolio,
            "scenario": None,
            "loss": None,
            "loss_limit": selected_loss_limit,
            "total_pnl": None,
            "instrument_count": binding.get("instrument_count") if isinstance(binding, Mapping) else None,
            "contributors": page,
            "threshold": _number(report.get("threshold")),
            "unavailable_reason": str(report.get("reason") or "reverse_stress_unavailable") if reverse_status == "unavailable" else None,
            "next_cursor": next_cursor,
            "execution_allowed": False,
        }

    try:
        if scenario is not None:
            saved = facade.load(scenario.strip())
            stress_scenario = saved.scenario if horizon is None else replace(saved.scenario, horizon_days=horizon)
        else:
            selected_horizon = horizon if horizon is not None else 1
            encoded = json.dumps(
                {"shocks": dict(shocks or {}), "horizon_days": selected_horizon},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            scenario_id = "mcp-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]
            stress_scenario = build_stress_scenario(
                scenario_id=scenario_id,
                name="MCP inline stress scenario",
                shocks=shocks or {},
                horizon_days=selected_horizon,
            )
        report = facade.run(stress_scenario, notional=selected_notional, allocation=allocation)
    except StressScenarioError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    except StressLabPersistenceError as exc:
        raise MCPToolError("STRESS_SCENARIO_UNAVAILABLE", "The saved stress scenario could not be read", f"Check local scenario evidence ({type(exc).__name__}).") from None

    payload = report.to_payload()
    contributors = [
        {
            "instrument_id": item.get("instrument_id"),
            "weight": item.get("weight"),
            "pnl": item.get("pnl"),
            "shock": item.get("shock"),
            "source": item.get("source"),
        }
        for item in payload.get("instrument_contributions", [])
        if isinstance(item, Mapping)
    ]
    filters.update({"scenario_id": stress_scenario.scenario_id})
    page, next_cursor = _page(contributors, cursor=cursor, limit=limit, filters=filters)
    total_pnl = _number(payload.get("total_pnl"))
    status = str(payload.get("status", "unavailable"))
    limitations = payload.get("limitations", [])
    return {
        "status": status,
        "portfolio": selected_portfolio,
        "scenario": {
            "scenario_id": stress_scenario.scenario_id,
            "name": stress_scenario.name,
            "horizon_days": stress_scenario.horizon_days,
            "historical_date": stress_scenario.historical_date,
            "shock_count": len(stress_scenario.shocks),
        },
        "loss": None if total_pnl is None else max(0.0, -total_pnl),
        "total_pnl": total_pnl,
        "instrument_count": payload.get("coverage", {}).get("instrument_count") if isinstance(payload.get("coverage"), Mapping) else None,
        "contributors": page,
        "threshold": None,
        "unavailable_reason": (unavailable_reason or (str(limitations[0]) if limitations and status == "unavailable" else None)),
        "next_cursor": next_cursor,
        "execution_allowed": False,
    }


@tool(
    tier="read_job",
    description="Submit local derived steps for features, signals, forecasts, scores, or backtest; writes derived artifacts only.",
    read_only_hint=False,
    idempotent_hint=False,
    requires_confirmation=False,
    profiles=("full",),
)
def pipeline_run(steps: Sequence[str], live_optional_models: bool = False) -> dict[str, Any]:
    from etf_cockpit.application.api import LocalApplicationApi
    from etf_cockpit.application.contracts import ApiStatus, SubmitWorkflowCommand
    from etf_cockpit.application.forecast_run import PIPELINE_STEPS, pipeline_request_payload, run_pipeline_steps

    if isinstance(steps, (str, bytes)) or not isinstance(steps, Sequence):
        raise InvalidArgumentsError(f"steps must be a subset of {', '.join(PIPELINE_STEPS)}")
    selected = tuple(dict.fromkeys(str(value).strip().casefold() for value in steps))
    if not selected or set(selected) - set(PIPELINE_STEPS):
        raise InvalidArgumentsError(f"steps must be a non-empty subset of {', '.join(PIPELINE_STEPS)}")
    if not isinstance(live_optional_models, bool) or live_optional_models:
        raise InvalidArgumentsError("live_optional_models must be false")
    session, snapshot = _snapshot()
    payload = pipeline_request_payload(snapshot, selected)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    dedupe_key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    api = LocalApplicationApi(lambda: snapshot, root=Path(session.root))
    try:
        submission = api.execute(SubmitWorkflowCommand(
            idempotency_key=f"mcp-pipeline-{dedupe_key}",
            workflow_type="pipeline_run",
            label="MCP derived pipeline run",
            input_payload=payload,
            job_keys=("run",),
            dedupe_key=dedupe_key,
        ))
        if submission.status not in {ApiStatus.ACCEPTED, ApiStatus.REPLAYED} or not submission.resource_id:
            raise MCPToolError("PIPELINE_SUBMISSION_UNAVAILABLE", "The derived pipeline job could not be submitted", "Check local job storage and resource policy.")
        workflow_id = submission.resource_id
        job = api.run_next_job(
            lambda _context: run_pipeline_steps(session, selected, live_optional_models=False),
            workflow_id=workflow_id,
        )
    except MCPToolError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise MCPToolError("PIPELINE_UNAVAILABLE", "The local derived pipeline could not be started", f"Check local job storage and step inputs ({type(exc).__name__}).") from None
    status = getattr(getattr(job, "status", None), "value", getattr(job, "status", "queued"))
    return {
        "job_id": workflow_id,
        "workflow_id": workflow_id,
        "status": status,
        "result": getattr(job, "outputs", None) if job is not None else None,
        "execution_allowed": False,
    }
