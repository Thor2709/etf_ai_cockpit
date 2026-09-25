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

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.timing import timing_summary
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
    "matured_rows",
    "mae",
    "mase",
    "directional_accuracy",
    "net_forward_value",
    "net_value_status",
    "interval_coverage",
    "conformal_coverage",
    "calibration_status",
    "drift_status",
    "drift_score",
    "resource_status",
    "runtime_ms",
    "promotion_state",
    "execution_allowed",
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


def latest_forecast_runtimes(records: Iterable[Mapping[str, object]]) -> dict[str, float]:
    """Return the latest measured run duration (ms) per forecast model family."""

    latest: dict[str, float] = {}
    for record in records:
        if record.get("action_id") != FORECAST_RUNTIME_ACTION:
            continue
        step = str(record.get("step") or "")
        if not step.startswith(FORECAST_RUNTIME_STEP_PREFIX):
            continue
        duration = _finite_or_none(record.get("duration_ms"))
        if duration is None or duration < 0:
            continue
        latest[step[len(FORECAST_RUNTIME_STEP_PREFIX):]] = duration
    return latest


def build_forecast_lab_workspace(
    config: AppConfig,
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of_date: date | str | None = None,
    timing_records: Iterable[Mapping[str, object]] | None = None,
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
    )


def build_forecast_lab_report(
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of_date: date | str | None = None,
    minimum_calibration_samples: int = 3,
    round_trip_cost_bps: Mapping[str, float] | None = None,
    model_runtime_ms: Mapping[str, float] | None = None,
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

    empty_models = pd.DataFrame(columns=LAB_MODEL_COLUMNS)
    empty_runs = pd.DataFrame(columns=LAB_RUN_COLUMNS)
    empty_splits = pd.DataFrame(columns=SPLIT_COLUMNS)
    empty_evaluation = pd.DataFrame(columns=WALK_FORWARD_EVALUATION_COLUMNS)
    model_catalogue = model_zoo_frame()
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
            "notes": tuple(
                [f"Forecast columns missing: {', '.join(missing_forecasts)}."] if missing_forecasts else []
            )
            + tuple([f"Adjusted-price columns missing: {', '.join(missing_prices)}."] if missing_prices else []),
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
            "notes": ("Unadjusted price rows were rejected; forecast diagnostics require adjusted_close.",),
            "execution_allowed": False,
        }

    price_frame["date"] = _naive_utc(price_frame["date"])
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.dropna(subset=["etf_id", "date", "adjusted_close"])

    frame = forecasts.copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["etf_id"] = frame["etf_id"].astype(str)
    frame["forecast_date"] = _naive_utc(frame["forecast_date"])
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
            "notes": ("No dated forecast rows are available in the local cache.",),
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
            "notes": ("No forecast rows are available at the selected as-of date.",),
            "execution_allowed": False,
        }

    # For a requested historical as-of, later outcomes were not yet knowable.
    known_prices = (
        price_frame.loc[price_frame["date"] <= effective_as_of]
        if pd.notna(requested_as_of)
        else price_frame
    )
    price_lookup = {
        str(instrument_id): group.sort_values("date").set_index("date")["adjusted_close"].astype(float)
        for instrument_id, group in known_prices.groupby("etf_id", sort=False)
    }
    matured = _matured_rows(frame, price_lookup, round_trip_cost_bps)
    model_rows = _model_summaries(frame, matured, minimum_calibration_samples, model_runtime_ms)
    run_rows = _run_summaries(frame)
    split_rows = build_walk_forward_splits(frame["forecast_date"].dt.date.unique())
    notes = [
        "Evaluation uses only local forecast artefacts and adjusted-close prices; a historical as-of replay "
        "uses only prices up to that date.",
        "Net forward value = forecast direction x matured adjusted return - canonical round-trip cost "
        "(2 x estimated_cost_bps); it is unavailable when a cost is unavailable.",
        "Walk-forward folds evaluate stored forecasts per model; model fitting and promotion belong to later issues.",
        "Resource use is the latest measured local run duration per model family; not_recorded until a run is timed.",
        "TimesFM and Toto remain optional challengers and are shadow-only.",
    ]
    return {
        "status": "ok",
        "as_of_date": effective_as_of.date().isoformat(),
        "outcomes_through": (
            known_prices["date"].max().date().isoformat() if not known_prices.empty else None
        ),
        "models": model_rows,
        "model_catalogue": model_catalogue,
        "runs": run_rows,
        "walk_forward_splits": split_rows,
        "walk_forward_evaluation": evaluate_walk_forward(split_rows, matured),
        "notes": tuple(notes),
        "execution_allowed": False,
    }


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


def _matured_rows(
    frame: pd.DataFrame,
    price_lookup: dict[str, pd.Series],
    round_trip_cost_bps: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in frame.sort_values(["model_name", "horizon_days", "forecast_date"]).iterrows():
        if row["status"] != "ok" or not np.isfinite(row.get("expected_return", np.nan)):
            continue
        series = price_lookup.get(str(row["etf_id"]))
        outcome = _actual_return(series, row["forecast_date"], int(row["horizon_days"])) if series is not None else None
        if outcome is None:
            continue
        actual, target_date = outcome
        expected = float(row["expected_return"])
        q10 = _finite_or_none(row.get("q10_return"))
        q90 = _finite_or_none(row.get("q90_return"))
        direction = float(np.sign(expected))
        if direction == 0.0:
            # A flat forecast implies no position, so no trade and no cost.
            round_trip_cost: float | None = 0.0
        else:
            cost_bps = _finite_or_none((round_trip_cost_bps or {}).get(str(row["etf_id"])))
            round_trip_cost = None if cost_bps is None or cost_bps < 0 else cost_bps / 10_000.0
        gross_value = direction * actual
        rows.append(
            {
                "model_name": str(row["model_name"]),
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
                "interval_hit": None if q10 is None or q90 is None else float(q10 <= actual <= q90),
                "gross_forward_value": gross_value,
                "round_trip_cost": round_trip_cost,
                "net_forward_value": None if round_trip_cost is None else gross_value - round_trip_cost,
            }
        )
    return pd.DataFrame(rows)


def _model_summaries(
    frame: pd.DataFrame,
    matured: pd.DataFrame,
    minimum_samples: int,
    model_runtime_ms: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    rows = []
    for model_name, group in frame.groupby("model_name", sort=True):
        ok_count = int(group["status"].eq("ok").sum())
        evaluated = matured.loc[matured["model_name"] == model_name].copy() if not matured.empty else pd.DataFrame()
        conformal = _conformal_diagnostics(evaluated, minimum_samples)
        errors = evaluated["absolute_error"] if not evaluated.empty else pd.Series(dtype=float)
        scale = _naive_scale(evaluated["actual_return"]) if not evaluated.empty else None
        expected = pd.to_numeric(group["expected_return"], errors="coerce").dropna()
        drift_score, drift_status = _drift(expected)
        interval = evaluated["interval_hit"].dropna() if not evaluated.empty else pd.Series(dtype=float)
        net_value, net_status = _net_value(evaluated)
        runtime = _finite_or_none((model_runtime_ms or {}).get(str(model_name))) if ok_count else None
        rows.append(
            {
                "model_name": model_name,
                "forecast_rows": int(len(group)),
                "ok_rows": ok_count,
                "status_summary": _status_summary(group["status"]),
                "matured_rows": int(len(evaluated)),
                "mae": _rounded(errors.mean() if not errors.empty else None),
                "mase": _rounded(errors.mean() / scale if not errors.empty and scale else None),
                "directional_accuracy": _rounded(evaluated["direction_hit"].mean() if not evaluated.empty else None),
                "net_forward_value": net_value,
                "net_value_status": net_status,
                "interval_coverage": _rounded(interval.mean() if not interval.empty else None),
                "conformal_coverage": conformal["coverage"],
                "calibration_status": conformal["status"],
                "drift_status": drift_status,
                "drift_score": drift_score,
                "resource_status": "measured" if runtime is not None else ("not_recorded" if ok_count else "not_run"),
                "runtime_ms": None if runtime is None else round(runtime, 1),
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
        return {"coverage": None, "status": "conformal_pending"}
    calibrated_hits = []
    for _, group in evaluated.groupby(["etf_id", "horizon_days"], sort=True):
        group = group.sort_values("forecast_date")
        earlier: list[tuple[pd.Timestamp, float]] = []
        for _, row in group.iterrows():
            # A residual is known only once its own target session has passed;
            # overlapping multi-day horizons must not calibrate earlier views.
            prior_errors = [error for target, error in earlier if target <= row["forecast_date"]]
            if len(prior_errors) >= minimum_samples:
                radius = float(np.quantile(prior_errors, 0.90, method="higher"))
                calibrated_hits.append(float(abs(float(row["actual_return"]) - float(row["expected_return"])) <= radius))
            earlier.append((row["target_date"], float(row["absolute_error"])))
    if not calibrated_hits:
        return {"coverage": None, "status": "conformal_pending"}
    return {"coverage": _rounded(float(np.mean(calibrated_hits))), "status": "conformal_diagnostic"}


def _actual_return(
    series: pd.Series | None, forecast_date: pd.Timestamp, horizon_days: int
) -> tuple[float, pd.Timestamp] | None:
    if series is None or horizon_days <= 0:
        return None
    clean = series.dropna().sort_index()
    start = clean.index.searchsorted(pd.Timestamp(forecast_date), side="right") - 1
    target = start + horizon_days
    if start < 0 or target >= len(clean):
        return None
    start_value, target_value = float(clean.iloc[start]), float(clean.iloc[target])
    if start_value <= 0 or target_value <= 0:
        return None
    return target_value / start_value - 1.0, pd.Timestamp(clean.index[target])


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


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


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
