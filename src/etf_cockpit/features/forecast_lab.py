"""Deterministic, local-only diagnostics for the Forecast Lab workspace.

This module deliberately evaluates stored forecast rows rather than training or
promoting models.  It is the first usable slice of ISSUE-0027; later issues add
the experiment store, feature/target contracts and governed promotion.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd


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
    "interval_coverage",
    "conformal_coverage",
    "calibration_status",
    "drift_status",
    "drift_score",
    "resource_status",
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


def build_forecast_lab_report(
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of_date: date | str | None = None,
    minimum_calibration_samples: int = 3,
) -> dict[str, object]:
    """Build a read-only report from local forecast and adjusted-price rows.

    Forecast rows after ``as_of_date`` are excluded.  A forecast is matured
    only when its target session exists in the adjusted-close price history.
    Conformal widths use only residuals from *earlier matured forecasts* for
    the same model/horizon, so the current observation cannot calibrate itself.
    """

    empty_models = pd.DataFrame(columns=LAB_MODEL_COLUMNS)
    empty_runs = pd.DataFrame(columns=LAB_RUN_COLUMNS)
    empty_splits = pd.DataFrame(columns=SPLIT_COLUMNS)
    missing_forecasts = sorted(FORECAST_REQUIRED_COLUMNS - set(forecasts.columns))
    missing_prices = sorted(PRICE_REQUIRED_COLUMNS - set(prices.columns))
    if missing_forecasts or missing_prices:
        return {
            "status": "unavailable",
            "as_of_date": None,
            "models": empty_models,
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
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
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
            "notes": ("Unadjusted price rows were rejected; forecast diagnostics require adjusted_close.",),
            "execution_allowed": False,
        }

    price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce")
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.dropna(subset=["etf_id", "date", "adjusted_close"])
    price_lookup = {
        str(instrument_id): group.sort_values("date").set_index("date")["adjusted_close"].astype(float)
        for instrument_id, group in price_frame.groupby("etf_id", sort=False)
    }

    frame = forecasts.copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["etf_id"] = frame["etf_id"].astype(str)
    frame["forecast_date"] = pd.to_datetime(frame["forecast_date"], errors="coerce")
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="coerce")
    for column in ("expected_return", "q10_return", "q90_return"):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame["status"] = frame["status"].astype(str).str.lower()
    frame = frame.dropna(subset=["model_name", "etf_id", "forecast_date", "horizon_days"])
    if frame.empty:
        return {
            "status": "unavailable",
            "as_of_date": None,
            "models": empty_models,
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
            "notes": ("No dated forecast rows are available in the local cache.",),
            "execution_allowed": False,
        }

    requested_as_of = pd.to_datetime(as_of_date, errors="coerce") if as_of_date is not None else pd.NaT
    effective_as_of = requested_as_of if pd.notna(requested_as_of) else frame["forecast_date"].max()
    frame = frame.loc[frame["forecast_date"] <= effective_as_of].copy()
    if frame.empty:
        return {
            "status": "unavailable",
            "as_of_date": effective_as_of.date().isoformat(),
            "models": empty_models,
            "runs": empty_runs,
            "walk_forward_splits": empty_splits,
            "notes": ("No forecast rows are available at the selected as-of date.",),
            "execution_allowed": False,
        }

    matured = _matured_rows(frame, price_lookup)
    model_rows = _model_summaries(frame, matured, minimum_calibration_samples)
    run_rows = _run_summaries(frame)
    split_rows = build_walk_forward_splits(frame["forecast_date"].dt.date.unique())
    notes = [
        "Evaluation uses only local forecast artefacts and adjusted-close prices.",
        "Walk-forward rows are evaluation splits; model fitting and promotion belong to later issues.",
        "TimesFM and Toto remain optional challengers and are shadow-only.",
    ]
    return {
        "status": "ok",
        "as_of_date": effective_as_of.date().isoformat(),
        "models": model_rows,
        "runs": run_rows,
        "walk_forward_splits": split_rows,
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


def _matured_rows(frame: pd.DataFrame, price_lookup: dict[str, pd.Series]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in frame.sort_values(["model_name", "horizon_days", "forecast_date"]).iterrows():
        if row["status"] != "ok" or not np.isfinite(row.get("expected_return", np.nan)):
            continue
        series = price_lookup.get(str(row["etf_id"]))
        actual = _actual_return(series, row["forecast_date"], int(row["horizon_days"])) if series is not None else None
        if actual is None:
            continue
        expected = float(row["expected_return"])
        q10 = _finite_or_none(row.get("q10_return"))
        q90 = _finite_or_none(row.get("q90_return"))
        rows.append(
            {
                "model_name": str(row["model_name"]),
                "etf_id": str(row["etf_id"]),
                "forecast_date": row["forecast_date"],
                "horizon_days": int(row["horizon_days"]),
                "expected_return": expected,
                "actual_return": actual,
                "absolute_error": abs(expected - actual),
                "direction_hit": float(np.sign(expected) == np.sign(actual)),
                "q10_return": q10,
                "q90_return": q90,
                "interval_hit": None if q10 is None or q90 is None else float(q10 <= actual <= q90),
            }
        )
    return pd.DataFrame(rows)


def _model_summaries(frame: pd.DataFrame, matured: pd.DataFrame, minimum_samples: int) -> pd.DataFrame:
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
                "interval_coverage": _rounded(interval.mean() if not interval.empty else None),
                "conformal_coverage": conformal["coverage"],
                "calibration_status": conformal["status"],
                "drift_status": drift_status,
                "drift_score": drift_score,
                "resource_status": "not_recorded",
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


def _conformal_diagnostics(evaluated: pd.DataFrame, minimum_samples: int) -> dict[str, object]:
    if evaluated.empty:
        return {"coverage": None, "status": "conformal_pending"}
    calibrated_hits = []
    for _, group in evaluated.groupby(["etf_id", "horizon_days"], sort=True):
        group = group.sort_values("forecast_date")
        prior_errors: list[float] = []
        for _, row in group.iterrows():
            if len(prior_errors) >= minimum_samples:
                radius = float(np.quantile(prior_errors, 0.90, method="higher"))
                calibrated_hits.append(float(abs(float(row["actual_return"]) - float(row["expected_return"])) <= radius))
            prior_errors.append(float(row["absolute_error"]))
    if not calibrated_hits:
        return {"coverage": None, "status": "conformal_pending"}
    return {"coverage": _rounded(float(np.mean(calibrated_hits))), "status": "conformal_diagnostic"}


def _actual_return(series: pd.Series | None, forecast_date: pd.Timestamp, horizon_days: int) -> float | None:
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
    return target_value / start_value - 1.0


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
