"""Read-only view model for the Forecast Lab charts (spec 6.6, section 8).

Pass-through of stored forecast evidence: no model is scored, selected or promoted here. Missing values stay
``None`` with a reason; an error difference needs the model and the baseline graded on the same forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

HORIZON_LIMITS = {"1M": 21, "3M": 63, "1Y": 252}
_DAYS_PER_MONTH = 30.4375
MAX_FOLDS = 8
CONFORMAL_TARGET = 0.90  # target_coverage of the stored conformal diagnostic
_KEYS = ["model_name", "etf_id", "forecast_date", "horizon_days"]


@dataclass(frozen=True)
class ErrorSeries:
    """MAE minus baseline MAE in percentage points, per evaluated horizon."""

    horizons: tuple[int, ...]
    baseline: str | None
    lines: dict[str, list[float | None]]
    reason: str | None


@dataclass(frozen=True)
class FoldBars:
    labels: tuple[str, ...]
    train_months: tuple[float, ...]
    test_months: tuple[float, ...]
    total: int
    reason: str | None


def is_baseline(model_name: object) -> bool:
    return "baseline" in str(model_name).casefold()


def _naive_day(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True, format="mixed").dt.tz_convert(None).dt.normalize()


def _graded(forecasts: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Matured outcomes joined to the stored point forecast (never to later data)."""
    needed = {"model_name", "etf_id", "forecast_date", "horizon_days", "expected_return"}
    if forecasts is None or outcomes is None or forecasts.empty or outcomes.empty or not needed <= set(forecasts.columns):
        return pd.DataFrame()
    stored = forecasts[list(needed)].copy()
    stored["forecast_date"] = _naive_day(stored["forecast_date"])
    stored["horizon_days"] = pd.to_numeric(stored["horizon_days"], errors="coerce")
    stored["expected_return"] = pd.to_numeric(stored["expected_return"], errors="coerce")
    stored = stored.dropna().drop_duplicates(_KEYS, keep="last")
    done = outcomes.loc[outcomes["outcome_status"] == "matured", [*_KEYS, "actual_return"]].copy()
    done["forecast_date"] = _naive_day(done["forecast_date"])
    done["horizon_days"] = pd.to_numeric(done["horizon_days"], errors="coerce")
    done["actual_return"] = pd.to_numeric(done["actual_return"], errors="coerce")
    merged = done.merge(stored, on=_KEYS, how="inner").dropna(subset=["actual_return", "expected_return"])
    merged["abs_error"] = (merged["expected_return"] - merged["actual_return"]).abs()
    return merged


def error_vs_baseline(forecasts: pd.DataFrame, outcomes: pd.DataFrame, models: list[str], *, max_horizon: int) -> ErrorSeries:
    graded = _graded(forecasts, outcomes)
    baseline = next((name for name in models if is_baseline(name)), None)
    if baseline is None:
        return ErrorSeries((), None, {}, "No baseline model rows are stored, so there is nothing to compare against.")
    if graded.empty:
        return ErrorSeries((), baseline, {}, "No matured forecast outcomes are available yet.")
    graded = graded.loc[graded["horizon_days"] <= max_horizon]
    base = graded.loc[graded["model_name"] == baseline]
    horizons = tuple(sorted(int(h) for h in base["horizon_days"].unique()))
    if not horizons:
        return ErrorSeries((), baseline, {}, f"The baseline has no matured outcomes up to {max_horizon} days.")
    lines: dict[str, list[float | None]] = {baseline: [0.0 for _ in horizons]}
    for name in models:
        if name == baseline:
            continue
        values: list[float | None] = []
        for horizon in horizons:
            own = graded.loc[(graded["model_name"] == name) & (graded["horizon_days"] == horizon)]
            ref = base.loc[base["horizon_days"] == horizon]
            same = own.merge(ref, on=["etf_id", "forecast_date"], suffixes=("", "_base"))
            values.append(None if same.empty else float((same["abs_error"] - same["abs_error_base"]).mean() * 100.0))
        if any(value is not None for value in values):
            lines[name] = values
    return ErrorSeries(horizons, baseline, lines, None)


def fold_bars(splits: pd.DataFrame, first_date: object) -> FoldBars:
    """Expanding train window and test window of the latest folds, in months of history."""
    if splits is None or splits.empty:
        return FoldBars((), (), (), 0, "Not enough distinct forecast dates for a walk-forward split.")
    start = pd.to_datetime(first_date, errors="coerce")
    if pd.isna(start):
        return FoldBars((), (), (), 0, "The first stored forecast date is unavailable.")
    recent = splits.tail(MAX_FOLDS)
    offset = len(splits) - len(recent)
    labels: list[str] = []
    train: list[float] = []
    test: list[float] = []
    for number, row in enumerate(recent.itertuples(), start=offset + 1):
        train_end, test_end = (pd.to_datetime(getattr(row, name)) for name in ("train_end", "test_end"))
        labels.append(f"Fold {number}")
        train.append(max((train_end - start).days, 0) / _DAYS_PER_MONTH)
        test.append(max((test_end - train_end).days, 0) / _DAYS_PER_MONTH)
    return FoldBars(tuple(labels), tuple(train), tuple(test), len(splits), None)
