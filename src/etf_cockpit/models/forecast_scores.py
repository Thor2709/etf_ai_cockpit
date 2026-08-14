from __future__ import annotations

import hashlib
from io import BytesIO
import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.paths import FORECASTS_DIR
from etf_cockpit.core.atomic_io import read_atomic_group
from etf_cockpit.core.versioning import current_settings_revision

PRIMARY_MODEL_HORIZON_DAYS = 60
FALLBACK_MODEL_HORIZONS_DAYS = (120, 20, 5, 180)


def _reference_identity_hash(identity: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(identity), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _forecast_cache_matches(
    path: Path,
    universe_revision: str | None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
) -> bool:
    metadata_path = Path(f"{path}.meta.json")
    if not path.is_file() or not metadata_path.is_file():
        return False
    try:
        payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return _forecast_cache_snapshot_matches(
        payload_bytes,
        payload,
        universe_revision,
        settings_revision,
        reference_identity,
    )


def _forecast_cache_snapshot_matches(
    payload_bytes: bytes,
    metadata: object,
    universe_revision: str | None,
    settings_revision: str | None,
    reference_identity: Mapping[str, object] | None,
) -> bool:
    if not isinstance(metadata, dict):
        return False
    matches = True
    if universe_revision is not None:
        expected_settings = settings_revision or current_settings_revision()
        matches = str(metadata.get("universe_revision") or "") == universe_revision
        matches = matches and str(metadata.get("settings_revision") or "") == expected_settings
    elif settings_revision is not None:
        matches = str(metadata.get("settings_revision") or "") == settings_revision
    if not matches or reference_identity is None:
        if not matches:
            return False
        checksum = metadata.get("payload_sha256")
        return checksum is None or checksum == hashlib.sha256(payload_bytes).hexdigest()
    if metadata.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest():
        return False
    return (
        metadata.get("reference_identity") == dict(reference_identity)
        and str(metadata.get("reference_identity_hash") or "") == _reference_identity_hash(reference_identity)
    )


def latest_forecast_file(
    pattern: str = "forecast_results_*.csv",
    directory: Path = FORECASTS_DIR,
    *,
    universe_revision: str | None = None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
) -> Path | None:
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if universe_revision is not None or reference_identity is not None:
        expected_settings = settings_revision
        if universe_revision is not None and expected_settings is None:
            expected_settings = current_settings_revision()
        files = [
            path
            for path in files
            if _forecast_cache_matches(path, universe_revision, expected_settings, reference_identity)
        ]
    return files[0] if files else None


def load_latest_forecasts(
    pattern: str = "forecast_results_*.csv",
    directory: Path = FORECASTS_DIR,
    *,
    universe_revision: str | None = None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    path = latest_forecast_file(
        pattern,
        directory,
        universe_revision=universe_revision,
        settings_revision=settings_revision,
        reference_identity=reference_identity,
    )
    if path is None:
        return pd.DataFrame()
    metadata_path = Path(f"{path}.meta.json")
    try:
        if metadata_path.exists():
            payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
            metadata = json.loads(metadata_bytes.decode("utf-8"))
            if not _forecast_cache_snapshot_matches(
                payload_bytes,
                metadata,
                universe_revision,
                settings_revision,
                reference_identity,
            ):
                return pd.DataFrame()
        else:
            if universe_revision is not None or settings_revision is not None or reference_identity is not None:
                return pd.DataFrame()
            payload_bytes = path.read_bytes()
        frame = pd.read_csv(BytesIO(payload_bytes))
    except (OSError, TypeError, ValueError):
        return pd.DataFrame()
    frame["source_file"] = str(path)
    return frame


def filter_forecasts_for_universe(
    forecasts: pd.DataFrame,
    universe_revision: str | None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Drop configured forecast rows whose source cache is not for this universe revision."""

    if forecasts.empty or (not universe_revision and reference_identity is None):
        return forecasts
    if "source_file" not in forecasts.columns:
        return forecasts.iloc[0:0].copy()
    expected_settings = settings_revision
    if universe_revision and expected_settings is None:
        expected_settings = current_settings_revision()
    valid = forecasts["source_file"].map(
        lambda value: _forecast_cache_matches(
            Path(str(value)), universe_revision, expected_settings, reference_identity
        )
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


def forecast_return_distributions(
    forecasts: pd.DataFrame,
    *,
    horizon_days: int = PRIMARY_MODEL_HORIZON_DAYS,
) -> dict[str, dict[str, float | int | str | None]]:
    """Return point-in-time return distributions for the score consumers.

    This is deliberately separate from ``forecast_component_maps``.  A
    normalised model score is ordinal evidence; it must not be treated as a
    percentage return.  Only allowed, successful forecast rows are used and
    each model contributes its preferred horizon before the medians are
    combined.  Missing quantiles remain unavailable rather than being
    fabricated from an ordinal score.
    """

    output: dict[str, dict[str, float | int | str | None]] = {}
    if forecasts.empty or not {"model_name", "etf_id", "horizon_days", "expected_return", "status", "model_allowed_in_score"}.issubset(forecasts.columns):
        return output
    frame = forecasts.copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="coerce")
    for column in ("expected_return", "q10_return", "q50_return", "q90_return", "forecast_vol"):
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    allowed = frame["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    frame = frame[(frame["status"].astype(str).str.lower() == "ok") & allowed]
    frame = frame.dropna(subset=["etf_id", "model_name", "horizon_days", "expected_return"])
    if frame.empty:
        return output

    for instrument_id, instrument_frame in frame.groupby(frame["etf_id"].astype(str), sort=True):
        selected_rows: list[dict[str, float | int]] = []
        selected_horizons: list[int] = []
        for _, model_frame in instrument_frame.groupby("model_name", sort=True):
            selected = _choose_horizon_row_for(model_frame, horizon_days)
            if selected is None:
                continue
            expected = _finite_or_none(selected.get("expected_return"))
            if expected is None:
                continue
            q50 = _finite_or_none(selected.get("q50_return"))
            q50 = expected if q50 is None else q50
            q10 = _finite_or_none(selected.get("q10_return"))
            q90 = _finite_or_none(selected.get("q90_return"))
            volatility = _finite_or_none(selected.get("forecast_vol"))
            if q10 is None and volatility is not None and volatility >= 0:
                q10 = q50 - 1.28 * volatility
            if q90 is None and volatility is not None and volatility >= 0:
                q90 = q50 + 1.28 * volatility
            if q10 is None or q90 is None or not q10 <= q50 <= q90:
                continue
            selected_rows.append({"q10": q10, "q50": q50, "q90": q90, "horizon": int(selected["horizon_days"])})
            selected_horizons.append(int(selected["horizon_days"]))
        if not selected_rows:
            output[instrument_id] = _unavailable_distribution("No valid forecast quantiles are available for the selected horizon.")
            continue
        if len(set(selected_horizons)) != 1:
            output[instrument_id] = _unavailable_distribution("Allowed forecast rows do not share a common return horizon.")
            continue
        output[instrument_id] = {
            "q10_return": round(float(np.median([row["q10"] for row in selected_rows])), 12),
            "q50_return": round(float(np.median([row["q50"] for row in selected_rows])), 12),
            "q90_return": round(float(np.median([row["q90"] for row in selected_rows])), 12),
            "horizon_days": selected_horizons[0],
            "model_count": len(selected_rows),
            "status": "available",
            "reason": "Median of allowed successful model return distributions at the selected horizon.",
            "source_dataset": "forecast_return_distribution",
        }
    return output


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
    return _choose_horizon_row_for(group, PRIMARY_MODEL_HORIZON_DAYS)


def _choose_horizon_row_for(group: pd.DataFrame, primary_horizon: int) -> pd.Series | None:
    if group.empty:
        return None
    fallback_horizons = tuple(horizon for horizon in (PRIMARY_MODEL_HORIZON_DAYS, *FALLBACK_MODEL_HORIZONS_DAYS) if horizon != primary_horizon)
    for horizon in (primary_horizon, *fallback_horizons):
        matches = group[group["horizon_days"].astype(int) == horizon]
        if not matches.empty:
            return matches.iloc[-1]
    return group.sort_values("horizon_days").iloc[-1]


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _unavailable_distribution(reason: str) -> dict[str, float | int | str | None]:
    return {
        "q10_return": None,
        "q50_return": None,
        "q90_return": None,
        "horizon_days": None,
        "model_count": 0,
        "status": "unavailable",
        "reason": reason,
        "source_dataset": "forecast_return_distribution",
    }


def _forecast_score(expected_return: float, horizon_days: int) -> float:
    if horizon_days <= 0 or not np.isfinite(expected_return):
        return 0.0
    annualised = expected_return * (252.0 / horizon_days)
    return float(np.tanh(annualised / 0.30).clip(-1.0, 1.0))
