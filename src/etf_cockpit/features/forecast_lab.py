"""Deterministic, local-only diagnostics for the Forecast Lab workspace.

This module deliberately evaluates stored forecast rows rather than training or
promoting models.  Outcomes are matured only from adjusted prices known at the
evaluation as-of date, each forecast is valued net of the canonical round-trip
execution cost, walk-forward folds are evaluated per model, and measured local
run durations are reported as resource use.  Promotion stays shadow-only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

import numpy as np
import pandas as pd

from etf_cockpit.core.values import finite_float_or_none as _finite_or_none
from etf_cockpit.core.pandas_values import stripped_text_or_none as _noneable_text
from etf_cockpit.models.calibration import coverage_confidence_interval, conformal_quantile_adjustment
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.resource_profiles import ResourcePolicy, estimate_workflow_resources
from etf_cockpit.core.timing import timing_summary
from etf_cockpit.models.coverage_audit import build_coverage_audit
from etf_cockpit.models.model_zoo import model_zoo_frame
from etf_cockpit.portfolio.costs import estimated_cost_bps


FORECAST_REQUIRED_COLUMNS = {
    "model_name",
    "etf_id",
    "forecast_date",
    "horizon_days",
    "expected_return",
    "status",
}
PRICE_REQUIRED_COLUMNS = {"etf_id", "date", "adjusted_close"}
LAB_MODEL_COLUMNS = [
    "model_name",
    "forecast_rows",
    "ok_rows",
    "status_summary",
    "latest_forecast_value",
    "latest_forecast_date",
    "latest_forecast_horizon_days",
    "latest_forecast_etf_id",
    "latest_forecast_status",
    "configured_horizons",
    "observed_horizons",
    "skipped_horizons",
    "matured_rows",
    "mae",
    "mase",
    "directional_accuracy",
    "net_forward_value",
    "net_value_status",
    "interval_coverage",
    "conformal_coverage",
    "conformal_coverage_ci_lower",
    "conformal_coverage_ci_upper",
    "calibration_status",
    "drift_status",
    "drift_score",
    "resource_status",
    "runtime_ms",
    "resource_run_id",
    "promotion_state",
    "execution_allowed",
]
FORECAST_OUTCOME_COLUMNS = [
    "run_id",
    "model_name",
    "etf_id",
    "forecast_date",
    "horizon_days",
    "forecast_status",
    "outcome_status",
    "outcome_reason",
    "target_date",
    "actual_return",
    "prediction_id",
    "fold_id",
    "out_of_fold",
]
LAB_RUN_COLUMNS = [
    "run_id",
    "forecast_rows",
    "models",
    "as_of_date",
    "status",
    "promotion_state",
    "execution_allowed",
]
SPLIT_COLUMNS = ["split_id", "train_end", "test_start", "test_end", "status"]
WALK_FORWARD_EVALUATION_COLUMNS = [
    "split_id",
    "model_name",
    "test_start",
    "test_end",
    "matured_rows",
    "mae",
    "directional_accuracy",
    "net_forward_value",
    "net_value_status",
]
FORECAST_RUNTIME_ACTION = "forecasts"
FORECAST_RUNTIME_STEP_PREFIX = "model:"


def forecast_round_trip_cost_bps(config: AppConfig, instrument_ids: Iterable[object]) -> dict[str, float]:
    """Return the canonical round-trip (entry and exit) cost per instrument.

    Uses the same ``estimated_cost_bps`` path as score and signal net-return
    views.  An instrument whose cost cannot be estimated is omitted, so its
    net value stays explicitly unavailable instead of being treated as free.
    """

    costs: dict[str, float] = {}
    for instrument_id in sorted({str(value) for value in instrument_ids}):
        try:
            one_way = float(estimated_cost_bps(config, instrument_id))
        except (KeyError, TypeError, ValueError):
            continue
        if np.isfinite(one_way) and one_way >= 0:
            costs[instrument_id] = 2.0 * one_way
    return costs


def latest_forecast_runtimes(records: Iterable[Mapping[str, object]]) -> dict[tuple[str, str], float]:
    """Return measured durations keyed by forecast artifact and model family."""

    latest: dict[tuple[str, str], float] = {}
    for record in records:
        if record.get("action_id") != FORECAST_RUNTIME_ACTION:
            continue
        run_id = str(record.get("run_id") or "").strip()
        if not run_id:
            continue
        step = str(record.get("step") or "")
        if not step.startswith(FORECAST_RUNTIME_STEP_PREFIX):
            continue
        duration = _finite_or_none(record.get("duration_ms"))
        if duration is None or duration < 0:
            continue
        latest[(run_id, step[len(FORECAST_RUNTIME_STEP_PREFIX):])] = duration
    return latest


def build_forecast_lab_workspace(
    config: AppConfig,
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of_date: date | str | None = None,
    timing_records: Iterable[Mapping[str, object]] | None = None,
    scenario_records: Mapping[str, Mapping[str, object]] | None = None,
    profile_id: str = "auto",
) -> dict[str, object]:
    """Build the Forecast Lab report with canonical costs and measured runtimes."""

    instrument_ids = forecasts["etf_id"].dropna().unique() if "etf_id" in forecasts.columns else ()
    if timing_records is None:
        logged = timing_summary(limit=500)["records"]
        timing_records = logged if isinstance(logged, list) else []
    records = timing_records
    return build_forecast_lab_report(
        forecasts,
        prices,
        as_of_date=as_of_date,
        round_trip_cost_bps=forecast_round_trip_cost_bps(config, instrument_ids),
        model_runtime_ms=latest_forecast_runtimes(records),
        configured_horizons=config.models.forecast_horizons_trading_days,
        scenario_records=scenario_records,
        subgroup_universe=config.universe.etfs,
        profile_id=profile_id,
    )


def build_forecast_lab_report(
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of_date: date | str | None = None,
    minimum_calibration_samples: int = 3,
    round_trip_cost_bps: Mapping[str, float] | None = None,
    model_runtime_ms: Mapping[tuple[str, str], float] | None = None,
    configured_horizons: Iterable[int] | None = None,
    scenario_records: Mapping[str, Mapping[str, object]] | None = None,
    subgroup_universe: Iterable[object] | None = None,
    profile_id: str = "auto",
) -> dict[str, object]:
    """Build a read-only report from local forecast and adjusted-price rows.

    Forecast rows after ``as_of_date`` are excluded.  A forecast is matured
    only when its target session exists in the adjusted-close price history;
    for a requested ``as_of_date`` only prices up to that date count, so later
    prices can never grade a historical replay.
    Conformal widths use only residuals from *earlier matured forecasts* for
    the same model/horizon, so the current observation cannot calibrate itself.
    Net forward value is the forecast direction times the matured return less
    ``round_trip_cost_bps`` for that instrument; without a cost it is unavailable.
    """

    policy = ResourcePolicy(requested_profile=profile_id)
    resource_estimate = estimate_workflow_resources(
        "analysis", requested_profile=profile_id, snapshot=policy.snapshot
    )
    policy.require_allowed(resource_estimate)

    empty_models = pd.DataFrame(columns=LAB_MODEL_COLUMNS)
    empty_runs = pd.DataFrame(columns=LAB_RUN_COLUMNS)
    empty_splits = pd.DataFrame(columns=SPLIT_COLUMNS)
    empty_evaluation = pd.DataFrame(columns=WALK_FORWARD_EVALUATION_COLUMNS)
    empty_outcomes = pd.DataFrame(columns=FORECAST_OUTCOME_COLUMNS)
    model_catalogue = model_zoo_frame()
    scenario_replay_inputs = _scenario_replay_inputs(scenario_records)
    missing_forecasts = sorted(FORECAST_REQUIRED_COLUMNS - set(forecasts.columns))
    missing_prices = sorted(PRICE_REQUIRED_COLUMNS - set(prices.columns))
    if missing_forecasts or missing_prices:
        return {
            "status": "unavailable",
            "as_of_date": None,
            "models": empty_models,
            "model_catalogue": model_catalogue,
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
            "walk_forward_evaluation": empty_evaluation,
            "forecast_outcomes": empty_outcomes,
            "scenario_replay_inputs": scenario_replay_inputs,
            "notes": tuple(
                [f"Forecast columns missing: {', '.join(missing_forecasts)}."] if missing_forecasts else []
            )
            + tuple([f"Adjusted-price columns missing: {', '.join(missing_prices)}."] if missing_prices else []),
            "resource_profile": resource_estimate,
            "execution_allowed": False,
        }

    price_frame = prices.copy()
    if "is_adjusted" in price_frame.columns and not price_frame["is_adjusted"].map(_adjusted_flag).all():
        return {
            "status": "unavailable",
            "as_of_date": None,
            "models": empty_models,
            "model_catalogue": model_catalogue,
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
            "walk_forward_evaluation": empty_evaluation,
            "forecast_outcomes": empty_outcomes,
            "scenario_replay_inputs": scenario_replay_inputs,
            "notes": ("Unadjusted price rows were rejected; forecast diagnostics require adjusted_close.",),
            "resource_profile": resource_estimate,
            "execution_allowed": False,
        }

    price_frame["date"] = _naive_utc(price_frame["date"]).dt.normalize()
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.dropna(subset=["etf_id", "date", "adjusted_close"])

    frame = forecasts.copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["etf_id"] = frame["etf_id"].astype(str)
    frame["forecast_date"] = _naive_utc(frame["forecast_date"]).dt.normalize()
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="coerce")
    for column in ("expected_return", "q10_return", "q90_return"):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame["status"] = frame["status"].astype(str).str.lower()
    optional_status = {
        model: bool((frame.loc[frame["model_name"] == model, "status"] == "ok").any())
        for model in ("timesfm", "toto")
    }
    model_catalogue = model_zoo_frame(optional_status=optional_status)
    frame = frame.dropna(subset=["model_name", "etf_id", "forecast_date", "horizon_days"])
    if frame.empty:
        return {
            "status": "unavailable",
            "as_of_date": None,
            "models": empty_models,
            "model_catalogue": model_catalogue,
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
            "walk_forward_evaluation": empty_evaluation,
            "forecast_outcomes": empty_outcomes,
            "scenario_replay_inputs": scenario_replay_inputs,
            "notes": ("No dated forecast rows are available in the local cache.",),
            "resource_profile": resource_estimate,
            "execution_allowed": False,
        }

    requested_as_of = (
        _naive_utc(pd.Series([as_of_date])).iloc[0] if as_of_date is not None else pd.NaT
    )
    effective_as_of = requested_as_of if pd.notna(requested_as_of) else frame["forecast_date"].max()
    frame = frame.loc[frame["forecast_date"] <= effective_as_of].copy()
    if frame.empty:
        return {
            "status": "unavailable",
            "as_of_date": effective_as_of.date().isoformat(),
            "models": empty_models,
            "model_catalogue": model_catalogue,
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
            "walk_forward_evaluation": empty_evaluation,
            "forecast_outcomes": empty_outcomes,
            "scenario_replay_inputs": scenario_replay_inputs,
            "notes": ("No forecast rows are available at the selected as-of date.",),
            "resource_profile": resource_estimate,
            "execution_allowed": False,
        }

    subgroup_results_by_model: dict[str, list[dict[str, object]]] = {}
    if subgroup_universe is not None:
        known_model_ids = set(model_catalogue["model_id"].astype(str))
        for model_name, model_forecasts in frame.groupby("model_name", sort=True):
            if str(model_name) not in known_model_ids:
                continue
            subgroup_results_by_model[str(model_name)] = build_coverage_audit(
                subgroup_universe,
                price_frame,
                model_forecasts,
                as_of_date=effective_as_of.date(),
            ).to_dict()["groups"]
        model_catalogue = model_zoo_frame(
            optional_status=optional_status,
            subgroup_results_by_model=subgroup_results_by_model,
        )

    # For a requested historical as-of, later outcomes were not yet knowable.
    known_prices = (
        price_frame.loc[price_frame["date"] <= effective_as_of]
        if pd.notna(requested_as_of)
        else price_frame
    )
    stale_columns = [
        column
        for column in ("is_stale", "stale", "staleness_status", "freshness_status")
        if column in known_prices.columns
    ]
    price_lookup = {
        str(instrument_id): group.sort_values("date").set_index("date")[["adjusted_close", *stale_columns]]
        for instrument_id, group in known_prices.groupby("etf_id", sort=False)
    }
    split_rows = build_walk_forward_splits(frame["forecast_date"].dt.date.unique())
    frame = _mark_walk_forward_provenance(frame, split_rows)
    matured, outcomes = _matured_rows(frame, price_lookup, round_trip_cost_bps)
    model_rows = _model_summaries(
        frame,
        matured,
        outcomes,
        minimum_calibration_samples,
        model_runtime_ms,
        configured_horizons,
    )
    run_rows = _run_summaries(frame)
    notes = [
        "Evaluation uses only local forecast artefacts and adjusted-close prices; a historical as-of replay "
        "uses only prices up to that date.",
        "Net forward value = forecast direction x matured adjusted return - canonical round-trip cost "
        "(2 x estimated_cost_bps); it is unavailable when a cost is unavailable.",
        "Walk-forward folds evaluate stored forecasts per model; model fitting and promotion belong to later issues.",
        "Resource use is the duration measured for the displayed forecast run; not_recorded when no matching run measurement exists.",
        "A forecast is graded only from its exact origin session to the exact target session; missing or stale sessions are unavailable.",
        "Forecasts are low-authority and cannot rescue or upgrade weak deterministic evidence.",
        "TimesFM and Toto remain optional challengers and are shadow-only.",
    ]
    return {
        "status": "ok",
        "as_of_date": effective_as_of.date().isoformat(),
        "outcomes_through": (
            known_prices["date"].max().date().isoformat() if not known_prices.empty else None
        ),
        "models": model_rows,
        "forecast_outcomes": outcomes,
        "model_catalogue": model_catalogue,
        "runs": run_rows,
        "walk_forward_splits": split_rows,
        "walk_forward_evaluation": evaluate_walk_forward(split_rows, matured),
        "scenario_replay_inputs": scenario_replay_inputs,
        "notes": tuple(notes),
        "resource_profile": resource_estimate,
        "execution_allowed": False,
    }


def _scenario_replay_inputs(
    records: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, dict[str, object]]:
    """Persist replay seeds and inputs while leaving generated paths untouched."""

    if not isinstance(records, Mapping):
        return {}
    output: dict[str, dict[str, object]] = {}
    for instrument_id, record in sorted(records.items(), key=lambda item: str(item[0])):
        if not isinstance(record, Mapping):
            continue
        seed = record.get("scenario_seed")
        inputs = record.get("scenario_inputs")
        if isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0 and isinstance(inputs, Mapping):
            output[str(instrument_id)] = {
                "scenario_seed": seed,
                "scenario_inputs": dict(inputs),
            }
    return output


def build_walk_forward_splits(
    dates: Iterable[date | str], *, minimum_train_dates: int = 3, test_dates: int = 1
) -> pd.DataFrame:
    """Return deterministic expanding-window date splits for evaluation only."""

    clean = sorted({pd.Timestamp(value).date() for value in dates if pd.notna(pd.to_datetime(value, errors="coerce"))})
    rows = []
    if len(clean) < minimum_train_dates + test_dates:
        return pd.DataFrame(columns=SPLIT_COLUMNS)
    split_id = 1
    for test_start in range(minimum_train_dates, len(clean) - test_dates + 1):
        rows.append(
            {
                "split_id": f"wf-{split_id:02d}",
                "train_end": clean[test_start - 1].isoformat(),
                "test_start": clean[test_start].isoformat(),
                "test_end": clean[test_start + test_dates - 1].isoformat(),
                "status": "evaluation_only",
            }
        )
        split_id += 1
    return pd.DataFrame(rows, columns=SPLIT_COLUMNS)


def evaluate_walk_forward(splits: pd.DataFrame, matured: pd.DataFrame) -> pd.DataFrame:
    """Evaluate matured forecasts inside each walk-forward test window per model."""

    if splits.empty or matured.empty:
        return pd.DataFrame(columns=WALK_FORWARD_EVALUATION_COLUMNS)
    forecast_days = pd.to_datetime(matured["forecast_date"]).dt.normalize()
    rows = []
    for split in splits.itertuples():
        start, end = pd.Timestamp(split.test_start), pd.Timestamp(split.test_end)
        window = matured.loc[(forecast_days >= start) & (forecast_days <= end)]
        for model_name, group in window.groupby("model_name", sort=True):
            net_value, net_status = _net_value(group)
            rows.append(
                {
                    "split_id": split.split_id,
                    "model_name": model_name,
                    "test_start": split.test_start,
                    "test_end": split.test_end,
                    "matured_rows": int(len(group)),
                    "mae": _rounded(group["absolute_error"].mean()),
                    "directional_accuracy": _rounded(group["direction_hit"].mean()),
                    "net_forward_value": net_value,
                    "net_value_status": net_status,
                }
            )
    return pd.DataFrame(rows, columns=WALK_FORWARD_EVALUATION_COLUMNS)


def _mark_walk_forward_provenance(frame: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    marked = frame.copy()
    marked["prediction_id"] = marked.apply(_prediction_identifier, axis=1)
    marked["fold_id"] = None
    marked["out_of_fold"] = False
    fold_count = pd.Series(0, index=marked.index, dtype="int64")
    for split in splits.itertuples(index=False):
        forecast_days = _naive_utc(marked["forecast_date"]).dt.normalize()
        start, end = pd.Timestamp(split.test_start), pd.Timestamp(split.test_end)
        mask = forecast_days.ge(start) & forecast_days.le(end)
        fold_count.loc[mask] += 1
        first_assignment = mask & fold_count.eq(1)
        marked.loc[first_assignment, "fold_id"] = str(split.split_id)
        marked.loc[first_assignment, "out_of_fold"] = True
    overlapping = fold_count.ne(1)
    marked.loc[overlapping, "fold_id"] = None
    marked.loc[overlapping, "out_of_fold"] = False
    return marked


def _prediction_identifier(row: pd.Series) -> str:
    existing = _noneable_text(row.get("prediction_id"))
    if existing is not None:
        return existing
    model_id = _noneable_text(row.get("model_id")) or str(row.get("model_name") or "")
    forecast_date = pd.Timestamp(row["forecast_date"]).isoformat()
    return "|".join(
        (
            model_id,
            str(_noneable_text(row.get("run_id")) or ""),
            str(row.get("etf_id") or ""),
            forecast_date,
            str(int(row["horizon_days"])),
        )
    )


def _matured_rows(
    frame: pd.DataFrame,
    price_lookup: dict[str, pd.DataFrame],
    round_trip_cost_bps: Mapping[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    outcome_rows: list[dict[str, object]] = []
    for _, row in frame.sort_values(["model_name", "horizon_days", "forecast_date"]).iterrows():
        run_id = _noneable_text(row.get("run_id"))
        horizon = int(row["horizon_days"])
        outcome_row: dict[str, object] = {
            "run_id": run_id,
            "model_name": str(row["model_name"]),
            "etf_id": str(row["etf_id"]),
            "forecast_date": row["forecast_date"],
            "horizon_days": horizon,
            "forecast_status": str(row["status"]),
            "outcome_status": "unavailable",
            "outcome_reason": None,
            "target_date": None,
            "actual_return": None,
            "prediction_id": row["prediction_id"],
            "fold_id": row["fold_id"],
            "out_of_fold": bool(row["out_of_fold"]),
        }
        if row["status"] != "ok":
            outcome_row["outcome_status"] = "skipped" if row["status"] == "skipped" else "unavailable"
            outcome_row["outcome_reason"] = _forecast_row_reason(row)
            outcome_rows.append(outcome_row)
            continue
        if _finite_or_none(row.get("expected_return")) is None:
            outcome_row["outcome_reason"] = "forecast_value_unavailable"
            outcome_rows.append(outcome_row)
            continue
        series = price_lookup.get(str(row["etf_id"]))
        actual, target_date, reason = _actual_return(series, row["forecast_date"], horizon)
        if reason is not None:
            outcome_row["outcome_reason"] = reason
            outcome_rows.append(outcome_row)
            continue
        expected = float(row["expected_return"])
        q10 = _finite_or_none(row.get("q10_return"))
        q90 = _finite_or_none(row.get("q90_return"))
        outcome_row.update(
            {
                "outcome_status": "matured",
                "target_date": target_date,
                "actual_return": actual,
            }
        )
        outcome_rows.append(outcome_row)
        direction = float(np.sign(expected))
        if direction == 0.0:
            # A flat forecast implies no position, so no trade and no cost.
            round_trip_cost: float | None = 0.0
        else:
            cost_bps = _finite_or_none((round_trip_cost_bps or {}).get(str(row["etf_id"])))
            round_trip_cost = None if cost_bps is None or cost_bps < 0 else cost_bps / 10_000.0
        # Money boundary: the log-return outcome becomes a simple return before costs.
        gross_value = direction * float(np.expm1(actual))
        rows.append(
            {
                "model_name": str(row["model_name"]),
                "run_id": run_id,
                "etf_id": str(row["etf_id"]),
                "forecast_date": row["forecast_date"],
                "target_date": target_date,
                "horizon_days": int(row["horizon_days"]),
                "expected_return": expected,
                "actual_return": actual,
                "absolute_error": abs(expected - actual),
                "direction_hit": float(np.sign(expected) == np.sign(actual)),
                "q10_return": q10,
                "q90_return": q90,
                "prediction_id": row["prediction_id"],
                "fold_id": row["fold_id"],
                "out_of_fold": bool(row["out_of_fold"]),
                "interval_hit": None if q10 is None or q90 is None else float(q10 <= actual <= q90),
                "gross_forward_value": gross_value,
                "round_trip_cost": round_trip_cost,
                "net_forward_value": None if round_trip_cost is None else gross_value - round_trip_cost,
            }
        )
    return (
        pd.DataFrame(rows),
        pd.DataFrame(outcome_rows, columns=FORECAST_OUTCOME_COLUMNS),
    )


def _model_summaries(
    frame: pd.DataFrame,
    matured: pd.DataFrame,
    outcomes: pd.DataFrame,
    minimum_samples: int,
    model_runtime_ms: Mapping[tuple[str, str], float] | None = None,
    configured_horizons: Iterable[int] | None = None,
) -> pd.DataFrame:
    rows = []
    configured = _normalise_horizons(configured_horizons)
    for model_name, group in frame.groupby("model_name", sort=True):
        ok_count = int(group["status"].eq("ok").sum())
        evaluated = matured.loc[matured["model_name"] == model_name].copy() if not matured.empty else pd.DataFrame()
        model_outcomes = outcomes.loc[outcomes["model_name"] == model_name] if not outcomes.empty else pd.DataFrame()
        conformal = _conformal_diagnostics(evaluated, minimum_samples)
        errors = evaluated["absolute_error"] if not evaluated.empty else pd.Series(dtype=float)
        scale = _naive_scale(evaluated["actual_return"]) if not evaluated.empty else None
        drift_score, drift_status = _comparable_drift(group)
        interval = evaluated["interval_hit"].dropna() if not evaluated.empty else pd.Series(dtype=float)
        net_value, net_status = _net_value(evaluated)
        latest_sort_columns = ["forecast_date", "etf_id", "horizon_days"]
        if "run_id" in group.columns:
            latest_sort_columns.append("run_id")
        latest_rows = group.sort_values(latest_sort_columns, kind="stable")
        latest = latest_rows.iloc[-1]
        latest_run_id = _noneable_text(latest.get("run_id"))
        artifact_rows = (
            group.loc[group["run_id"].astype(str) == latest_run_id]
            if latest_run_id is not None and "run_id" in group.columns
            else pd.DataFrame()
        )
        artifact_ok = not artifact_rows.empty and artifact_rows["status"].eq("ok").any()
        runtime = (
            _finite_or_none((model_runtime_ms or {}).get((latest_run_id, str(model_name))))
            if latest_run_id is not None and artifact_ok
            else None
        )
        observed, skipped = _horizon_diagnostics(group, model_outcomes, configured)
        rows.append(
            {
                "model_name": model_name,
                "forecast_rows": int(len(group)),
                "ok_rows": ok_count,
                "status_summary": _status_summary(group["status"]),
                "latest_forecast_value": (
                    _finite_or_none(latest.get("expected_return")) if latest["status"] == "ok" else None
                ),
                "latest_forecast_date": pd.Timestamp(latest["forecast_date"]).date().isoformat(),
                "latest_forecast_horizon_days": int(latest["horizon_days"]),
                "latest_forecast_etf_id": str(latest["etf_id"]),
                "latest_forecast_status": str(latest["status"]),
                "configured_horizons": configured,
                "observed_horizons": observed,
                "skipped_horizons": skipped,
                "matured_rows": int(len(evaluated)),
                "mae": _rounded(errors.mean() if not errors.empty else None),
                "mase": _rounded(errors.mean() / scale if not errors.empty and scale else None),
                "directional_accuracy": _rounded(evaluated["direction_hit"].mean() if not evaluated.empty else None),
                "net_forward_value": net_value,
                "net_value_status": net_status,
                "interval_coverage": _rounded(interval.mean() if not interval.empty else None),
                "conformal_coverage": conformal["coverage"],
                "conformal_coverage_ci_lower": conformal["coverage_ci_lower"],
                "conformal_coverage_ci_upper": conformal["coverage_ci_upper"],
                "calibration_status": conformal["status"],
                "drift_status": drift_status,
                "drift_score": drift_score,
                "resource_status": "measured" if runtime is not None else ("not_recorded" if ok_count else "not_run"),
                "runtime_ms": None if runtime is None else round(runtime, 1),
                "resource_run_id": latest_run_id,
                "promotion_state": "shadow_only",
                "execution_allowed": False,
            }
        )
    return pd.DataFrame(rows, columns=LAB_MODEL_COLUMNS)


def _run_summaries(frame: pd.DataFrame) -> pd.DataFrame:
    run_column = frame["run_id"].astype(str) if "run_id" in frame.columns else pd.Series("local-cache", index=frame.index)
    work = frame.assign(_run_id=run_column)
    rows = []
    for run_id, group in work.groupby("_run_id", sort=True):
        rows.append(
            {
                "run_id": run_id,
                "forecast_rows": int(len(group)),
                "models": ", ".join(sorted(group["model_name"].unique())),
                "as_of_date": group["forecast_date"].max().date().isoformat(),
                "status": "available" if group["status"].eq("ok").any() else "unavailable",
                "promotion_state": "shadow_only",
                "execution_allowed": False,
            }
        )
    return pd.DataFrame(rows, columns=LAB_RUN_COLUMNS)


def _net_value(evaluated: pd.DataFrame) -> tuple[float | None, str]:
    if evaluated.empty:
        return None, "net_value_pending"
    values = pd.to_numeric(evaluated["net_forward_value"], errors="coerce")
    if values.isna().any():
        return None, "cost_unavailable"
    mean = float(values.mean())
    return _rounded(mean), "positive_net_edge" if mean > 0 else "no_net_edge"


def _conformal_diagnostics(evaluated: pd.DataFrame, minimum_samples: int) -> dict[str, object]:
    if evaluated.empty:
        return {"coverage": None, "coverage_ci_lower": None, "coverage_ci_upper": None, "status": "conformal_pending"}
    calibrated_hits = []
    for _, group in evaluated.groupby(["etf_id", "horizon_days"], sort=True):
        group = group.sort_values("forecast_date")
        earlier: list[tuple[pd.Timestamp, float]] = []
        for _, row in group.iterrows():
            # The strict comparison excludes an outcome maturing at the view time.
            forecast_time = pd.to_datetime(row.get("forecast_date"), errors="coerce", utc=True)
            prior_errors = [
                error for target, error in earlier
                if pd.notna(forecast_time) and target < forecast_time and np.isfinite(error)
            ]
            conformal = conformal_quantile_adjustment(
                prior_errors,
                minimum_matured_samples=minimum_samples,
                target_coverage=0.90,
            )
            if conformal["status"] == "available":
                radius = float(conformal["adjustment"])
                calibrated_hits.append(float(abs(float(row["actual_return"]) - float(row["expected_return"])) <= radius))
            target_time = pd.to_datetime(row.get("target_date"), errors="coerce", utc=True)
            error = pd.to_numeric(pd.Series([row.get("absolute_error")]), errors="coerce").iloc[0]
            if pd.notna(target_time) and pd.notna(error):
                earlier.append((target_time, float(error)))
    if not calibrated_hits:
        return {"coverage": None, "coverage_ci_lower": None, "coverage_ci_upper": None, "status": "conformal_pending"}
    interval = coverage_confidence_interval(calibrated_hits)
    return {
        "coverage": _rounded(float(np.mean(calibrated_hits))),
        "coverage_ci_lower": _rounded(interval[0]) if interval is not None else None,
        "coverage_ci_upper": _rounded(interval[1]) if interval is not None else None,
        "status": "conformal_diagnostic",
    }


def _actual_return(
    series: pd.DataFrame | None, forecast_date: pd.Timestamp, horizon_days: int
) -> tuple[float | None, pd.Timestamp | None, str | None]:
    if series is None or series.empty:
        return None, None, "price_series_missing"
    if horizon_days <= 0:
        return None, None, "invalid_horizon"
    # ``price_lookup`` is normalised and sorted once before forecasts are
    # evaluated, so each row can look up its sessions without copying history.
    clean = series
    if not clean.index.is_unique:
        return None, None, "conflicted_price_session"
    origin_date = pd.Timestamp(forecast_date).normalize()
    start = int(clean.index.get_indexer([origin_date])[0])
    if start < 0:
        return None, None, "origin_session_missing"
    if _price_row_is_stale(clean.iloc[start]):
        return None, None, "origin_session_stale"
    target = start + horizon_days
    if start < 0 or target >= len(clean):
        return None, None, "target_session_missing"
    if _price_row_is_stale(clean.iloc[target]):
        return None, None, "target_session_stale"
    start_value = _finite_or_none(clean.iloc[start]["adjusted_close"])
    target_value = _finite_or_none(clean.iloc[target]["adjusted_close"])
    if start_value is None or start_value <= 0:
        return None, None, "origin_adjusted_price_invalid"
    if target_value is None or target_value <= 0:
        return None, None, "target_adjusted_price_invalid"
    # Forecast returns are log returns (see models.base); keep outcomes in log units.
    return float(np.log(target_value / start_value)), pd.Timestamp(clean.index[target]), None


def _naive_utc(values: pd.Series) -> pd.Series:
    """Parse dates to tz-naive UTC so aware and naive sources compare safely."""

    return pd.to_datetime(values, errors="coerce", utc=True, format="mixed").dt.tz_convert(None)


def _naive_scale(actual: pd.Series) -> float | None:
    changes = pd.to_numeric(actual, errors="coerce").diff().abs().dropna()
    if changes.empty:
        return None
    return max(float(changes.mean()), 1e-9)


def _drift(values: pd.Series) -> tuple[float | None, str]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 4:
        return None, "drift_pending"
    midpoint = max(1, len(clean) // 2)
    earlier, recent = clean.iloc[:midpoint], clean.iloc[midpoint:]
    scale = max(float(clean.std(ddof=0)), 1e-9)
    score = abs(float(recent.mean() - earlier.mean())) / scale
    return _rounded(score), "monitor" if score >= 1.0 else "stable"


def _comparable_drift(group: pd.DataFrame) -> tuple[float | None, str]:
    scores: list[float] = []
    for _, comparable in group.groupby(["etf_id", "horizon_days"], sort=True):
        sort_columns = ["forecast_date"]
        if "run_id" in comparable.columns:
            sort_columns.append("run_id")
        ordered = comparable.sort_values(sort_columns, kind="stable")
        score, _status = _drift(ordered["expected_return"])
        if score is not None:
            scores.append(score)
    if not scores:
        return None, "drift_pending"
    score = max(scores)
    return score, "monitor" if score >= 1.0 else "stable"


def _horizon_diagnostics(
    group: pd.DataFrame,
    outcomes: pd.DataFrame,
    configured_horizons: list[int],
) -> tuple[list[int], list[dict[str, object]]]:
    observed = sorted({int(value) for value in pd.to_numeric(group["horizon_days"], errors="coerce").dropna()})
    skipped_reasons: dict[int, set[str]] = {
        horizon: {"no_forecast_row"} for horizon in configured_horizons if horizon not in observed
    }
    for row in outcomes.itertuples(index=False):
        if row.outcome_status == "matured":
            continue
        reason = _noneable_text(row.outcome_reason) or str(row.outcome_status)
        skipped_reasons.setdefault(int(row.horizon_days), set()).add(reason)
    skipped = [
        {"horizon_days": horizon, "reason": "; ".join(sorted(reasons))}
        for horizon, reasons in sorted(skipped_reasons.items())
    ]
    return observed, skipped


def _normalise_horizons(values: Iterable[int] | None) -> list[int]:
    output: set[int] = set()
    for value in values or ():
        number = _finite_or_none(value)
        if number is not None and number > 0 and number.is_integer():
            output.add(int(number))
    return sorted(output)


def _forecast_row_reason(row: pd.Series) -> str:
    for column in ("reason_unavailable", "error_message"):
        value = _noneable_text(row.get(column))
        if value is not None:
            return value
    calibration = _noneable_text(row.get("calibration_status"))
    if calibration not in {None, "not_evaluated"}:
        return calibration
    return str(row.get("status") or "forecast_unavailable")


def _price_row_is_stale(row: pd.Series) -> bool:
    for column in ("is_stale", "stale"):
        value = row.get(column)
        if value is not None and not pd.isna(value) and _adjusted_flag(value):
            return True
    for column in ("staleness_status", "freshness_status"):
        value = _noneable_text(row.get(column))
        if value is not None and value.casefold() in {"stale", "warning", "block", "unknown"}:
            return True
    return False


def _adjusted_flag(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value) if value is not None and not pd.isna(value) else False


def _status_summary(values: pd.Series) -> str:
    counts = values.astype(str).str.lower().value_counts().sort_index()
    return "; ".join(f"{status}={int(count)}" for status, count in counts.items()) or "none"


def _rounded(value: object) -> float | None:
    number = _finite_or_none(value)
    return None if number is None else round(number, 4)
