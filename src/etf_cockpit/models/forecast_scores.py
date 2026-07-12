from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.paths import FORECASTS_DIR

PRIMARY_MODEL_HORIZON_DAYS = 60
FALLBACK_MODEL_HORIZONS_DAYS = (120, 20, 5, 180)


def _forecast_cache_matches(path: Path, universe_revision: str) -> bool:
    metadata_path = Path(f"{path}.meta.json")
    if not metadata_path.exists():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(payload, dict) and str(payload.get("universe_revision") or "") == universe_revision


def latest_forecast_file(
    pattern: str = "forecast_results_*.csv",
    directory: Path = FORECASTS_DIR,
    *,
    universe_revision: str | None = None,
) -> Path | None:
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if universe_revision is not None:
        files = [path for path in files if _forecast_cache_matches(path, universe_revision)]
    return files[0] if files else None


def load_latest_forecasts(
    pattern: str = "forecast_results_*.csv",
    directory: Path = FORECASTS_DIR,
    *,
    universe_revision: str | None = None,
) -> pd.DataFrame:
    path = latest_forecast_file(pattern, directory, universe_revision=universe_revision)
    if path is None:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame["source_file"] = str(path)
    return frame


def filter_forecasts_for_universe(forecasts: pd.DataFrame, universe_revision: str | None) -> pd.DataFrame:
    """Drop configured forecast rows whose source cache is not for this universe revision."""

    if forecasts.empty or not universe_revision or "source_file" not in forecasts.columns:
        return forecasts
    valid = forecasts["source_file"].map(
        lambda value: _forecast_cache_matches(Path(str(value)), universe_revision)
    )
    return forecasts.loc[valid].copy()


def forecast_component_maps(forecasts: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Return per-model score maps from validated forecast rows."""
    output: dict[str, dict[str, float]] = {"toto": {}, "timesfm": {}, "baseline": {}}
    if forecasts.empty:
        return output

    required = {"model_name", "etf_id", "horizon_days", "expected_return", "status", "model_allowed_in_score"}
    if not required.issubset(forecasts.columns):
        return output

    frame = forecasts.copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="coerce")
    frame["expected_return"] = pd.to_numeric(frame["expected_return"], errors="coerce")
    allowed = frame["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    frame = frame[(frame["status"].astype(str).str.lower() == "ok") & allowed]
    frame = frame.dropna(subset=["etf_id", "model_name", "horizon_days", "expected_return"])
    if frame.empty:
        return output

    for model_name in output:
        model_frame = frame[frame["model_name"] == model_name]
        for etf_id, group in model_frame.groupby("etf_id", sort=False):
            row = _choose_horizon_row(group)
            if row is None:
                continue
            output[model_name][str(etf_id)] = _forecast_score(float(row["expected_return"]), int(row["horizon_days"]))
    return output


def forecast_score_details(forecasts: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty:
        return pd.DataFrame(columns=["etf_id", "model_name", "horizon_days", "expected_return", "score"])
    rows: list[dict[str, object]] = []
    maps = forecast_component_maps(forecasts)
    for model_name, scores in maps.items():
        for etf_id, score in scores.items():
            selected = _selected_forecast_row(forecasts, model_name, etf_id)
            rows.append(
                {
                    "etf_id": etf_id,
                    "model_name": model_name,
                    "horizon_days": None if selected is None else int(selected["horizon_days"]),
                    "expected_return": None if selected is None else float(selected["expected_return"]),
                    "score": score,
                }
            )
    return pd.DataFrame(rows)


def _selected_forecast_row(forecasts: pd.DataFrame, model_name: str, etf_id: str) -> pd.Series | None:
    frame = forecasts.copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="coerce")
    frame["expected_return"] = pd.to_numeric(frame["expected_return"], errors="coerce")
    allowed = frame["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    frame = frame[
        (frame["model_name"] == model_name)
        & (frame["etf_id"].astype(str) == etf_id)
        & (frame["status"].astype(str).str.lower() == "ok")
        & allowed
    ].dropna(subset=["horizon_days", "expected_return"])
    return _choose_horizon_row(frame)


def _choose_horizon_row(group: pd.DataFrame) -> pd.Series | None:
    if group.empty:
        return None
    for horizon in (PRIMARY_MODEL_HORIZON_DAYS, *FALLBACK_MODEL_HORIZONS_DAYS):
        matches = group[group["horizon_days"].astype(int) == horizon]
        if not matches.empty:
            return matches.iloc[-1]
    return group.sort_values("horizon_days").iloc[-1]


def _forecast_score(expected_return: float, horizon_days: int) -> float:
    if horizon_days <= 0 or not np.isfinite(expected_return):
        return 0.0
    annualised = expected_return * (252.0 / horizon_days)
    return float(np.tanh(annualised / 0.30).clip(-1.0, 1.0))
