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
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.versioning import current_settings_revision

PRIMARY_MODEL_HORIZON_DAYS = 60
FALLBACK_MODEL_HORIZONS_DAYS = (120, 20, 5, 180)


def forecast_request_identity(
    config: AppConfig,
    horizons: list[int] | None = None,
    *,
    live_optional_models: bool = True,
) -> dict[str, object]:
    requested = horizons if horizons is not None else config.models.forecast_horizons_trading_days
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in requested):
        raise ValueError("forecast horizons must be positive integers")
    normalized = sorted(set(requested))
    if not normalized:
        raise ValueError("at least one forecast horizon is required")
    return {
        "schema": "forecast-cache-request.v1",
        "requested_horizons": normalized,
        "live_optional_models": live_optional_models is True,
    }


def configured_forecast_request_identity(config: AppConfig) -> dict[str, object]:
    """Return the one canonical request published by the interactive scoring workflow."""

    return forecast_request_identity(
        config,
        [PRIMARY_MODEL_HORIZON_DAYS],
        live_optional_models=False,
    )


def _valid_forecast_request_identity(identity: Mapping[str, object]) -> bool:
    horizons = identity.get("requested_horizons")
    return (
        identity.get("schema") == "forecast-cache-request.v1"
        and isinstance(horizons, list)
        and bool(horizons)
        and all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in horizons)
        and horizons == sorted(set(horizons))
        and type(identity.get("live_optional_models")) is bool
    )


def _canonical_price_binding_required(reference_identity: Mapping[str, object] | None) -> bool:
    return isinstance(reference_identity, Mapping) and "analysis" in reference_identity


def _reference_identity_hash(identity: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(identity), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cache_binding_matches(metadata: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    return _valid_price_binding(expected) and all(metadata.get(key) == value for key, value in expected.items())


def _valid_price_binding(binding: Mapping[str, object]) -> bool:
    checksum = binding.get("price_snapshot_checksum")
    revision = binding.get("price_snapshot_revision")
    cutoff = binding.get("effective_cutoff")
    window = binding.get("calculation_window")
    return (
        isinstance(checksum, str)
        and len(checksum) == 64
        and all(character in "0123456789abcdef" for character in checksum)
        and revision == checksum
        and isinstance(cutoff, str)
        and bool(cutoff)
        and isinstance(window, Mapping)
        and window.get("decision_time") == cutoff
        and all(isinstance(window.get(key), str) and window.get(key) for key in ("start_date", "end_date"))
    )


def _forecast_cache_matches(
    path: Path,
    universe_revision: str | None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> bool:
    metadata_path = Path(f"{path}.meta.json")
    if not path.is_file() or not metadata_path.is_file():
        return False
    try:
        payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (OSError, ValueError, TypeError, RecursionError):
        return False
    return _forecast_cache_snapshot_matches(
        payload_bytes,
        payload,
        universe_revision,
        settings_revision,
        reference_identity,
        price_binding,
        forecast_request_identity,
    )


def _forecast_cache_snapshot_matches(
    payload_bytes: bytes,
    metadata: object,
    universe_revision: str | None,
    settings_revision: str | None,
    reference_identity: Mapping[str, object] | None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
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
        return (
            (checksum is None or checksum == hashlib.sha256(payload_bytes).hexdigest())
            and (price_binding is None or _cache_binding_matches(metadata, price_binding))
            and (
                forecast_request_identity is None
                or _forecast_request_matches(metadata, forecast_request_identity)
            )
        )
    if metadata.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest():
        return False
    if price_binding is not None and not _cache_binding_matches(metadata, price_binding):
        return False
    if forecast_request_identity is not None and not _forecast_request_matches(metadata, forecast_request_identity):
        return False
    return _reference_identity_matches(
        metadata.get("reference_identity"),
        metadata.get("reference_identity_hash"),
        reference_identity,
    )


def _reference_identity_matches(
    stored: object,
    claimed_hash: object,
    expected: Mapping[str, object],
) -> bool:
    if not isinstance(stored, Mapping):
        return False
    try:
        expected_hash = _reference_identity_hash(expected)
        return (
            str(claimed_hash or "") == expected_hash
            and _reference_identity_hash(stored) == expected_hash
        )
    except (TypeError, ValueError, RecursionError):
        return False


def _forecast_request_matches(metadata: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    return _valid_forecast_request_identity(expected) and _reference_identity_matches(
        metadata.get("forecast_request_identity"),
        metadata.get("forecast_request_identity_hash"),
        expected,
    )


def latest_forecast_file(
    pattern: str = "forecast_results_*.csv",
    directory: Path = FORECASTS_DIR,
    *,
    universe_revision: str | None = None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> Path | None:
    if _canonical_price_binding_required(reference_identity) and price_binding is None:
        return None
    if reference_identity is not None and (
        forecast_request_identity is None or not _valid_forecast_request_identity(forecast_request_identity)
    ):
        return None
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if (
        universe_revision is not None
        or settings_revision is not None
        or reference_identity is not None
        or price_binding is not None
        or forecast_request_identity is not None
    ):
        expected_settings = settings_revision
        if universe_revision is not None and expected_settings is None:
            expected_settings = current_settings_revision()
        files = [
            path
            for path in files
            if _forecast_cache_matches(
                path,
                universe_revision,
                expected_settings,
                reference_identity,
                price_binding,
                forecast_request_identity,
            )
        ]
    return files[0] if files else None


def load_latest_forecasts(
    pattern: str = "forecast_results_*.csv",
    directory: Path = FORECASTS_DIR,
    *,
    universe_revision: str | None = None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    path = latest_forecast_file(
        pattern,
        directory,
        universe_revision=universe_revision,
        settings_revision=settings_revision,
        reference_identity=reference_identity,
        price_binding=price_binding,
        forecast_request_identity=forecast_request_identity,
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
                price_binding,
                forecast_request_identity,
            ):
                return pd.DataFrame()
        else:
            if (
                universe_revision is not None
                or settings_revision is not None
                or reference_identity is not None
                or price_binding is not None
                or forecast_request_identity is not None
            ):
                return pd.DataFrame()
            payload_bytes = path.read_bytes()
        frame = pd.read_csv(BytesIO(payload_bytes))
    except (OSError, TypeError, ValueError, RecursionError):
        return pd.DataFrame()
    frame["source_file"] = str(path)
    return frame


def filter_forecasts_for_universe(
    forecasts: pd.DataFrame,
    universe_revision: str | None,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Drop configured forecast rows whose source cache is not for this universe revision."""

    if _canonical_price_binding_required(reference_identity) and price_binding is None:
        return forecasts.iloc[0:0].copy()
    if reference_identity is not None and (
        forecast_request_identity is None or not _valid_forecast_request_identity(forecast_request_identity)
    ):
        return forecasts.iloc[0:0].copy()
    if forecasts.empty or (
        not universe_revision
        and settings_revision is None
        and reference_identity is None
        and price_binding is None
        and forecast_request_identity is None
    ):
        return forecasts
    if "source_file" not in forecasts.columns:
        return forecasts.iloc[0:0].copy()
    expected_settings = settings_revision
    if universe_revision and expected_settings is None:
        expected_settings = current_settings_revision()
    valid = forecasts["source_file"].map(
        lambda value: _forecast_cache_matches(
            Path(str(value)),
            universe_revision,
            expected_settings,
            reference_identity,
            price_binding,
            forecast_request_identity,
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
