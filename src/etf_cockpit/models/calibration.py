from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.paths import DERIVED_DIR, FORECASTS_DIR


CALIBRATION_COLUMNS = [
    "instrument_id",
    "model_name",
    "evaluated_forecasts",
    "matured_forecasts",
    "oos_mase",
    "oos_directional_accuracy",
    "q10_q90_coverage",
    "calibration_score_10",
    "calibration_status",
    "calibration_label",
]


@dataclass(frozen=True)
class CalibrationSummary:
    instrument_id: str
    model_name: str
    evaluated_forecasts: int
    matured_forecasts: int
    oos_mase: float | None
    oos_directional_accuracy: float | None
    q10_q90_coverage: float | None
    calibration_score_10: float | None
    calibration_status: str
    calibration_label: str


def calibration_status() -> str:
    return "Forecast calibration is calculated from matured local forecast artefacts in data/forecasts."


def load_forecast_history(directory: Path = FORECASTS_DIR) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(directory.glob("*.csv")):
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if frame.empty:
            continue
        frame["source_file"] = str(path)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def evaluate_forecast_calibration(forecasts: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Evaluate only forecasts whose target date is present in local prices.

    The function deliberately leaves current, not-yet-matured forecasts as pending. It does
    not backfill missing model runs or pretend that TimesFM/Toto were calibrated when only
    current-date forecasts exist.
    """
    if forecasts.empty or prices.empty:
        return pd.DataFrame(columns=CALIBRATION_COLUMNS)
    required_forecasts = {"model_name", "etf_id", "forecast_date", "horizon_days", "expected_return", "status"}
    required_prices = {"etf_id", "date", "adjusted_close"}
    if not required_forecasts.issubset(forecasts.columns) or not required_prices.issubset(prices.columns):
        return pd.DataFrame(columns=CALIBRATION_COLUMNS)

    forecast_frame = forecasts.copy()
    forecast_frame["model_name"] = forecast_frame["model_name"].astype(str).str.lower()
    forecast_frame["instrument_id"] = forecast_frame["etf_id"].astype(str)
    forecast_frame["forecast_date"] = pd.to_datetime(forecast_frame["forecast_date"], errors="coerce")
    forecast_frame["horizon_days"] = pd.to_numeric(forecast_frame["horizon_days"], errors="coerce")
    forecast_frame["expected_return"] = pd.to_numeric(forecast_frame["expected_return"], errors="coerce")
    forecast_frame["q10_return"] = pd.to_numeric(forecast_frame.get("q10_return"), errors="coerce")
    forecast_frame["q90_return"] = pd.to_numeric(forecast_frame.get("q90_return"), errors="coerce")
    if "model_allowed_in_score" in forecast_frame:
        allowed = forecast_frame["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    else:
        allowed = pd.Series(True, index=forecast_frame.index)
    forecast_frame = forecast_frame[
        (forecast_frame["status"].astype(str).str.lower() == "ok")
        & allowed
        & forecast_frame["forecast_date"].notna()
        & forecast_frame["horizon_days"].notna()
        & forecast_frame["expected_return"].notna()
    ].copy()
    if forecast_frame.empty:
        return pd.DataFrame(columns=CALIBRATION_COLUMNS)

    price_frame = prices.copy()
    price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce")
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.dropna(subset=["date", "adjusted_close"])
    pivots = {
        str(instrument_id): group.sort_values("date").set_index("date")["adjusted_close"].astype(float)
        for instrument_id, group in price_frame.groupby("etf_id", sort=False)
    }

    rows: list[dict[str, object]] = []
    for (instrument_id, model_name), group in forecast_frame.groupby(["instrument_id", "model_name"], sort=False):
        series = pivots.get(str(instrument_id))
        if series is None or len(series) < 5:
            rows.append(_pending_row(str(instrument_id), str(model_name), len(group), "no_price_history"))
            continue
        matured: list[dict[str, float]] = []
        for _, forecast in group.iterrows():
            actual = _actual_horizon_return(series, forecast["forecast_date"], int(forecast["horizon_days"]))
            if actual is None:
                continue
            expected = float(forecast["expected_return"])
            q10 = _finite_or_none(forecast.get("q10_return"))
            q90 = _finite_or_none(forecast.get("q90_return"))
            matured.append(
                {
                    "expected": expected,
                    "actual": actual,
                    "absolute_error": abs(expected - actual),
                    "direction_hit": float(np.sign(expected) == np.sign(actual)),
                    "covered": float(q10 is not None and q90 is not None and q10 <= actual <= q90),
                    "has_interval": float(q10 is not None and q90 is not None),
                    "horizon_days": float(forecast["horizon_days"]),
                }
            )
        if not matured:
            rows.append(_pending_row(str(instrument_id), str(model_name), len(group), "pending_no_matured_forecasts"))
            continue
        eval_frame = pd.DataFrame(matured)
        scale = _mase_scale(series, int(round(float(eval_frame["horizon_days"].median()))))
        mase = float(eval_frame["absolute_error"].mean() / scale) if scale > 0 else None
        directional = float(eval_frame["direction_hit"].mean())
        interval_rows = eval_frame[eval_frame["has_interval"] > 0]
        coverage = float(interval_rows["covered"].mean()) if not interval_rows.empty else None
        score, status, label = _calibration_score_and_label(len(eval_frame), mase, directional)
        rows.append(
            {
                "instrument_id": str(instrument_id),
                "model_name": str(model_name),
                "evaluated_forecasts": int(len(group)),
                "matured_forecasts": int(len(eval_frame)),
                "oos_mase": None if mase is None else round(mase, 4),
                "oos_directional_accuracy": round(directional, 4),
                "q10_q90_coverage": None if coverage is None else round(coverage, 4),
                "calibration_score_10": score,
                "calibration_status": status,
                "calibration_label": label,
            }
        )
    return pd.DataFrame(rows, columns=CALIBRATION_COLUMNS)


def write_forecast_calibration(frame: pd.DataFrame, directory: Path = DERIVED_DIR) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    output = frame.copy() if not frame.empty else pd.DataFrame(columns=CALIBRATION_COLUMNS)
    parquet_path = directory / "model_calibration.parquet"
    csv_path = directory / "model_calibration.csv"
    output.to_parquet(parquet_path, index=False)
    output.to_csv(csv_path, index=False)
    return parquet_path, csv_path


def calibration_lookup(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame.empty:
        return {}
    output: dict[str, dict[str, object]] = {}
    for instrument_id, group in frame.groupby("instrument_id", sort=False):
        scored = pd.to_numeric(group.get("calibration_score_10"), errors="coerce").dropna()
        statuses = sorted({str(value) for value in group.get("calibration_status", pd.Series(dtype=str)).dropna().unique()})
        matured = int(pd.to_numeric(group.get("matured_forecasts"), errors="coerce").fillna(0).sum())
        if not scored.empty:
            score = round(float(scored.mean()), 1)
            label = _overall_label(score, matured, statuses)
        elif matured <= 0:
            score = None
            label = "Calibration pending: no matured local forecast rows"
        else:
            score = None
            label = "Calibration limited: forecast rows exist but metrics are incomplete"
        output[str(instrument_id)] = {
            "score": score,
            "label": label,
            "matured_forecasts": matured,
            "statuses": ", ".join(statuses) if statuses else "unknown",
        }
    return output


def _actual_horizon_return(series: pd.Series, forecast_date: pd.Timestamp, horizon_days: int) -> float | None:
    clean = series.dropna().sort_index()
    if horizon_days <= 0 or clean.empty:
        return None
    start_pos = clean.index.searchsorted(pd.Timestamp(forecast_date), side="right") - 1
    if start_pos < 0:
        return None
    target_pos = start_pos + horizon_days
    if target_pos >= len(clean):
        return None
    start_price = float(clean.iloc[start_pos])
    target_price = float(clean.iloc[target_pos])
    if start_price <= 0 or target_price <= 0:
        return None
    return (target_price / start_price) - 1.0


def _mase_scale(series: pd.Series, horizon_days: int) -> float:
    clean = series.dropna().sort_index().astype(float)
    returns = clean.pct_change(max(1, int(horizon_days))).replace([np.inf, -np.inf], np.nan).dropna().abs()
    if returns.empty:
        returns = clean.pct_change().replace([np.inf, -np.inf], np.nan).dropna().abs()
    if returns.empty:
        return 1.0
    return max(float(returns.mean()), 1e-9)


def _pending_row(instrument_id: str, model_name: str, evaluated: int, status: str) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "model_name": model_name,
        "evaluated_forecasts": int(evaluated),
        "matured_forecasts": 0,
        "oos_mase": None,
        "oos_directional_accuracy": None,
        "q10_q90_coverage": None,
        "calibration_score_10": None,
        "calibration_status": status,
        "calibration_label": "Calibration pending: wait until forecast horizons mature against later yfinance prices.",
    }


def _calibration_score_and_label(n: int, mase: float | None, directional: float) -> tuple[float, str, str]:
    if n < 3:
        return 4.0, "limited", f"Limited calibration: only {n} matured forecast rows."
    if mase is not None and mase <= 1.0 and directional >= 0.55:
        return 8.0, "good", "Good calibration: forecast errors beat the local naive scale and direction is useful."
    if mase is not None and mase <= 1.5 and directional >= 0.50:
        return 6.0, "mixed", "Mixed calibration: useful but not yet strong enough for high authority."
    return 3.5, "weak", "Weak calibration: forecast error or direction accuracy is not good enough."


def _overall_label(score: float, matured: int, statuses: list[str]) -> str:
    status_text = ", ".join(statuses) if statuses else "unknown"
    if score >= 7.0:
        return f"Calibrated evidence: {matured} matured rows, status {status_text}"
    if score >= 5.0:
        return f"Partly calibrated: {matured} matured rows, status {status_text}"
    return f"Low calibration trust: {matured} matured rows, status {status_text}"


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if np.isfinite(number) else None
