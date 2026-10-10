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
from etf_cockpit.core.values import finite_float_or_none as _finite_or_none
from etf_cockpit.core.pandas_values import stripped_text_or_none as _text_or_none
from etf_cockpit.core.versioning import current_settings_revision
from etf_cockpit.models.distribution_store import (
    HORIZON_VALIDATION_STATUSES,
    QUANTILE_FIELDS,
    build_distribution_record,
)
from etf_cockpit.models.uncertainty import unavailable_decomposition

PRIMARY_MODEL_HORIZON_DAYS = 60
FALLBACK_MODEL_HORIZONS_DAYS = (120, 20, 5, 180)
CANONICAL_DISTRIBUTION_HORIZONS_DAYS = frozenset({5, 20, 60, 120, 180, 504, 1260})


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
    decision_time: object = None,
    return_components_by_instrument: Mapping[str, Mapping[str, object]] | None = None,
    cost_deductions_by_instrument: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, dict[str, object]]:
    """Return point-in-time return distributions for the score consumers.

    This is deliberately separate from ``forecast_component_maps``.  A
    normalised model score is ordinal evidence; it must not be treated as a
    percentage return. Only allowed, successful rows at the exact requested
    horizon contribute; horizons are never substituted or combined. The
    legacy three-quantile view remains available to existing consumers while
    the canonical total-return contract reports unavailable components,
    coverage, calibration or costs explicitly.
    """

    output: dict[str, dict[str, object]] = {}
    if forecasts.empty or not {"model_name", "etf_id", "horizon_days", "expected_return", "status", "model_allowed_in_score"}.issubset(forecasts.columns):
        return output
    frame = forecasts.copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["horizon_days"] = pd.to_numeric(frame["horizon_days"], errors="coerce")
    decision_cutoff = _normalise_decision_time(decision_time)
    has_forecast_date = "forecast_date" in frame.columns
    instrument_ids = forecasts["etf_id"].dropna().astype(str).drop_duplicates().tolist()
    if has_forecast_date:
        frame["forecast_date"] = pd.to_datetime(frame["forecast_date"], errors="coerce", utc=True, format="mixed")
    usable_forecast_dates_by_instrument = {
        instrument_id: bool(
            frame.loc[frame["etf_id"].astype(str).eq(instrument_id), "forecast_date"].notna().any()
        )
        for instrument_id in instrument_ids
    } if has_forecast_date else {}
    usable_forecast_date = any(usable_forecast_dates_by_instrument.values())
    point_in_time_bound = decision_cutoff is not None and usable_forecast_date
    # Legacy consumers (no decision time) keep the unbound three-quantile view, flagged
    # point_in_time_bound=False; a supplied decision time without usable forecast dates fails closed.
    legacy_view = decision_time is None
    if not legacy_view and not point_in_time_bound:
        reason = "A valid decision time and usable forecast date are required for point-in-time filtering."
        for instrument_id in instrument_ids:
            output[instrument_id] = _unavailable_contract_distribution(
                reason,
                horizon_days=horizon_days,
                decision_time=decision_cutoff,
                point_in_time_bound=False,
            )
        return output
    if point_in_time_bound:
        frame = frame.loc[frame["forecast_date"].le(decision_cutoff)]
    canonical_horizon = _canonical_distribution_horizon(horizon_days)
    if canonical_horizon is None:
        reason = "The requested horizon is not in the canonical 1W–5Y set."
        for instrument_id in instrument_ids:
            output[instrument_id] = _unavailable_contract_distribution(
                reason,
                horizon_days=horizon_days,
                decision_time=decision_cutoff,
                point_in_time_bound=usable_forecast_dates_by_instrument.get(instrument_id, False),
            )
        return output
    horizon_days = canonical_horizon
    numeric_columns = (
        "expected_return",
        "q05_return",
        "q10_return",
        "q25_return",
        "q50_return",
        "q75_return",
        "q90_return",
        "q95_return",
        "forecast_vol",
        "coverage_ratio",
        "calibration_horizon_days",
        "model_horizon_days",
        "target_horizon_days",
        "prob_positive_return",
        "prob_beat_cash",
        "prob_beat_benchmark",
        "price_return",
        "income_return",
        "fx_return",
    )
    for column in numeric_columns:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "calibration_status" not in frame:
        frame["calibration_status"] = "unavailable"
    if "target_id" not in frame:
        frame["target_id"] = None
    if "model_id" not in frame:
        frame["model_id"] = None
    allowed = frame["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    frame = frame[(frame["status"].astype(str).str.lower() == "ok") & allowed]
    frame = frame.dropna(subset=["etf_id", "model_name", "horizon_days", "expected_return"])
    model_horizons_by_id = _declared_horizons_by_id(frame, "model_id", "model_horizon_days")
    target_horizons_by_id = _declared_horizons_by_id(frame, "target_id", "target_horizon_days")
    if frame.empty:
        for instrument_id in instrument_ids:
            output[instrument_id] = _unavailable_contract_distribution(
                "No allowed successful forecast row is available.",
                horizon_days=horizon_days,
                decision_time=decision_cutoff,
                point_in_time_bound=usable_forecast_dates_by_instrument.get(instrument_id, False) and decision_cutoff is not None,
            )
        return output

    for instrument_id, instrument_frame in frame.groupby(frame["etf_id"].astype(str), sort=True):
        selected_rows: list[dict[str, float | int]] = []
        per_model_distributions: list[dict[str, object]] = []
        canonical_quantiles: list[dict[str, float]] = []
        canonical_coverages: list[float] = []
        canonical_components: list[dict[str, float]] = []
        probabilities: list[dict[str, float | None]] = []
        targets_by_model: dict[str, str | None] = {}
        validations_by_model: dict[str, dict[str, object]] = {}
        model_identities_valid_by_model: dict[str, bool] = {}
        for _, model_frame in instrument_frame.groupby("model_name", sort=True):
            exact_horizon = model_frame.loc[model_frame["horizon_days"].eq(horizon_days)]
            if exact_horizon.empty:
                continue
            selected = _latest_row(exact_horizon)
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
            model_distribution: dict[str, object] = {
                "model_name": str(selected.get("model_name") or ""),
                "model_id": _text_or_none(selected.get("model_id")),
                "target_id": _text_or_none(selected.get("target_id")),
                "horizon_days": int(selected["horizon_days"]),
                "q10_return": q10,
                "q50_return": q50,
                "q90_return": q90,
                "coverage_ratio": _finite_or_none(selected.get("coverage_ratio")),
                "forecast_date": _timestamp_iso_or_none(selected.get("forecast_date")),
            }
            for field in QUANTILE_FIELDS:
                if field not in {"q10_return", "q50_return", "q90_return"}:
                    model_distribution[field] = _finite_or_none(selected.get(field))
            per_model_distributions.append(model_distribution)
            quantiles = {field: _finite_or_none(selected.get(field)) for field in QUANTILE_FIELDS}
            if all(value is not None for value in quantiles.values()):
                canonical_quantiles.append({field: float(value) for field, value in quantiles.items() if value is not None})
            coverage = _finite_or_none(selected.get("coverage_ratio"))
            if coverage is not None:
                canonical_coverages.append(coverage)
            components = {
                field: _finite_or_none(selected.get(field))
                for field in ("price_return", "income_return", "fx_return")
            }
            if all(value is not None for value in components.values()):
                canonical_components.append({field: float(value) for field, value in components.items() if value is not None})
            model_name = str(selected["model_name"])
            model_id = selected.get("model_id")
            model_horizon = _finite_integer(selected.get("model_horizon_days"))
            model_identity_valid = _horizon_identity_is_valid(
                model_id,
                model_horizon,
                horizon_days,
                model_horizons_by_id,
            )
            model_identities_valid_by_model[model_name] = model_identity_valid
            target = selected.get("target_id")
            target_horizon = _finite_integer(selected.get("target_horizon_days"))
            target_identity_valid = _horizon_identity_is_valid(
                target,
                target_horizon,
                horizon_days,
                target_horizons_by_id,
            )
            targets_by_model[model_name] = target if target_identity_valid else None
            calibration_status = str(selected.get("calibration_status") or "unavailable").strip().lower()
            calibration_horizon = _finite_or_none(selected.get("calibration_horizon_days"))
            validations_by_model[model_name] = {
                "calibration_status": calibration_status,
                "horizon_days": int(calibration_horizon) if calibration_horizon is not None and calibration_horizon.is_integer() else None,
            }
            positive = _bounded_probability(selected.get("prob_positive_return"))
            beat_cash = _bounded_probability(selected.get("prob_beat_cash"))
            beat_benchmark = _bounded_probability(selected.get("prob_beat_benchmark"))
            if calibration_status == "good" and calibration_horizon == horizon_days and all(
                value is not None for value in (positive, beat_cash, beat_benchmark)
            ):
                probabilities.append({
                    "probability_loss": 1.0 - positive,
                    "probability_beat_cash": beat_cash,
                    "probability_beat_benchmark": beat_benchmark,
                })
            else:
                probabilities.append({
                    "probability_loss": None,
                    "probability_beat_cash": None,
                    "probability_beat_benchmark": None,
                })
        if not selected_rows:
            output[instrument_id] = _unavailable_contract_distribution(
                "No successful forecast row exists at the exact requested horizon.",
                horizon_days=horizon_days,
                decision_time=decision_cutoff,
                point_in_time_bound=usable_forecast_dates_by_instrument.get(instrument_id, False) and decision_cutoff is not None,
            )
            continue
        distribution: dict[str, object] = {
            "q10_return": round(float(np.median([row["q10"] for row in selected_rows])), 12),
            "q50_return": round(float(np.median([row["q50"] for row in selected_rows])), 12),
            "q90_return": round(float(np.median([row["q90"] for row in selected_rows])), 12),
            "horizon_days": int(horizon_days),
            "model_count": len(selected_rows),
            "status": "available",
            "reason": "Median of allowed successful model return distributions at the selected horizon.",
            "source_dataset": "forecast_return_distribution",
            "targets_by_model": targets_by_model,
            "validation_by_model": validations_by_model,
        }
        quantile_vector = None
        if len(canonical_quantiles) == len(selected_rows):
            quantile_vector = {
                field: float(np.median([row[field] for row in canonical_quantiles]))
                for field in QUANTILE_FIELDS
            }
        components = None
        if return_components_by_instrument is not None:
            components = return_components_by_instrument.get(instrument_id)
        elif len(canonical_components) == len(selected_rows):
            components = {
                field: float(np.median([row[field] for row in canonical_components]))
                for field in ("price_return", "income_return", "fx_return")
            }
        coverage_ratio = min(canonical_coverages) if len(canonical_coverages) == len(selected_rows) else None
        probabilities_complete = len(probabilities) == len(selected_rows) and all(
            all(row[field] is not None for field in ("probability_loss", "probability_beat_cash", "probability_beat_benchmark"))
            for row in probabilities
        )
        calibrated_probabilities = {
            field: float(np.median([row[field] for row in probabilities])) if probabilities_complete else None
            for field in ("probability_loss", "probability_beat_cash", "probability_beat_benchmark")
        }
        costs = cost_deductions_by_instrument.get(instrument_id) if cost_deductions_by_instrument is not None else None
        canonical = build_distribution_record(
            quantile_vector,
            horizon_days=horizon_days,
            coverage_ratio=coverage_ratio,
            return_components=components,
            calibration_status="good" if probabilities_complete else None,
            calibration_horizon_days=horizon_days if probabilities_complete else None,
            probability_positive_return=(
                1.0 - calibrated_probabilities["probability_loss"]
                if calibrated_probabilities["probability_loss"] is not None else None
            ),
            probability_beat_cash=calibrated_probabilities["probability_beat_cash"],
            probability_beat_benchmark=calibrated_probabilities["probability_beat_benchmark"],
            cost_deductions=costs,
            per_model_distributions=per_model_distributions,
        )
        targets_complete = len(targets_by_model) == len(selected_rows) and all(targets_by_model.values())
        models_complete = len(model_identities_valid_by_model) == len(selected_rows) and all(model_identities_valid_by_model.values())
        validations_complete = len(validations_by_model) == len(selected_rows) and all(
            row["horizon_days"] == horizon_days and row["calibration_status"] in HORIZON_VALIDATION_STATUSES
            for row in validations_by_model.values()
        )
        canonical["target_status"] = "available" if targets_complete else "unavailable"
        canonical["model_status"] = "available" if models_complete else "unavailable"
        canonical["validation_status"] = "available" if validations_complete else "unavailable"
        canonical["point_in_time_status"] = "available" if has_forecast_date and decision_cutoff is not None else "unavailable"
        canonical["decision_time"] = None if decision_cutoff is None else decision_cutoff.isoformat()
        canonical["targets_by_model"] = targets_by_model
        canonical["validation_by_model"] = validations_by_model
        if canonical["status"] == "available" and not (targets_complete and models_complete and validations_complete):
            canonical["status"] = "unavailable"
            canonical["reason"] = "A horizon-bound model and target identity and horizon-matched validation are required for each model."
        if canonical["status"] == "available" and canonical["point_in_time_status"] != "available":
            canonical["status"] = "unavailable"
            canonical["reason"] = "A decision time and forecast date are required for point-in-time filtering."
        output[instrument_id] = _attach_distribution_contract(
            distribution, canonical, calibrated_probabilities, legacy_view=legacy_view
        )
    for instrument_id in instrument_ids:
        if instrument_id not in output:
            output[instrument_id] = _unavailable_contract_distribution(
                "No allowed successful forecast row is available at or before the decision time.",
                horizon_days=horizon_days,
                decision_time=decision_cutoff,
                point_in_time_bound=usable_forecast_dates_by_instrument.get(instrument_id, False),
            )
    return output


def _distribution_with_contract(
    distribution: dict[str, object],
    *,
    instrument_id: str,
    horizon_days: object,
    return_components_by_instrument: Mapping[str, Mapping[str, object]] | None,
    cost_deductions_by_instrument: Mapping[str, Mapping[str, object]] | None,
    decision_time: pd.Timestamp | None,
    point_in_time_bound: bool,
) -> dict[str, object]:
    components = return_components_by_instrument.get(instrument_id) if return_components_by_instrument is not None else None
    costs = cost_deductions_by_instrument.get(instrument_id) if cost_deductions_by_instrument is not None else None
    canonical = build_distribution_record(
        None,
        horizon_days=horizon_days,
        coverage_ratio=None,
        return_components=components,
        cost_deductions=costs,
    )
    canonical["point_in_time_status"] = "available" if point_in_time_bound else "unavailable"
    canonical["decision_time"] = None if decision_time is None else decision_time.isoformat()
    if canonical["status"] == "available" and not point_in_time_bound:
        canonical["status"] = "unavailable"
        canonical["reason"] = "A decision time and forecast date are required for point-in-time filtering."
    return _attach_distribution_contract(distribution, canonical, {})


def _unavailable_contract_distribution(
    reason: str,
    *,
    horizon_days: object,
    decision_time: pd.Timestamp | None,
    point_in_time_bound: bool,
) -> dict[str, object]:
    distribution = _distribution_with_contract(
        _unavailable_distribution(reason),
        instrument_id="",
        horizon_days=horizon_days,
        return_components_by_instrument=None,
        cost_deductions_by_instrument=None,
        decision_time=decision_time,
        point_in_time_bound=point_in_time_bound,
    )
    distribution.update({
        "status": "unavailable",
        "reason": reason,
        "horizon_days": None,
        "model_count": 0,
        "canonical_status": "unavailable",
        "canonical_reason": reason,
    })
    for field in QUANTILE_FIELDS:
        distribution[field] = None
        distribution[f"net_{field}"] = None
    return distribution


def _attach_distribution_contract(
    distribution: dict[str, object],
    canonical: dict[str, object],
    probabilities: Mapping[str, float | None],
    *,
    legacy_view: bool = False,
) -> dict[str, object]:
    legacy = {field: distribution.get(field) for field in ("q10_return", "q50_return", "q90_return")}
    gross = canonical.get("gross_quantiles")
    net = canonical.get("net_quantiles")
    if isinstance(gross, Mapping):
        for field in ("q10_return", "q50_return", "q90_return"):
            distribution[field] = gross.get(field)
    for field in QUANTILE_FIELDS:
        distribution[field] = gross.get(field) if isinstance(gross, Mapping) else None
        distribution[f"net_{field}"] = net.get(field) if isinstance(net, Mapping) else None
    distribution.update({
        "canonical_status": canonical["status"],
        "canonical_reason": canonical["reason"],
        "target_status": canonical.get("target_status", "unavailable"),
        "model_status": canonical.get("model_status", "unavailable"),
        "validation_status": canonical.get("validation_status", "unavailable"),
        "point_in_time_status": canonical.get("point_in_time_status", "unavailable"),
        "decision_time": canonical.get("decision_time"),
        "targets_by_model": canonical.get("targets_by_model", {}),
        "validation_by_model": canonical.get("validation_by_model", {}),
        "coverage_ratio": canonical["coverage_ratio"],
        "gross_status": canonical["gross_status"],
        "return_components": canonical["return_components"],
        "components_status": canonical["components_status"],
        "cost_deductions": canonical["cost_deductions"],
        "per_model_distributions": canonical.get("per_model_distributions"),
        "net_status": canonical["net_status"],
        "net_reason": canonical["net_reason"],
        "probability_loss": probabilities.get("probability_loss") if canonical["status"] == "available" else None,
        "probability_beat_cash": probabilities.get("probability_beat_cash") if canonical["status"] == "available" else None,
        "probability_beat_benchmark": probabilities.get("probability_beat_benchmark") if canonical["status"] == "available" else None,
        "schema_version": canonical["schema_version"],
        "execution_allowed": False,
    })
    if canonical["status"] != "available":
        for field in QUANTILE_FIELDS:
            distribution[field] = None
            distribution[f"net_{field}"] = None
        if legacy_view:
            # Legacy callers pass no decision time: the canonical contract is unavailable
            # (canonical_reason), but the pre-existing three-quantile median view is kept for
            # them. Any supplied decision time, valid or not, never takes this path.
            distribution.update(legacy)
        else:
            distribution.update({
                "status": "unavailable",
                "reason": canonical["reason"],
                "horizon_days": None,
                "model_count": 0,
            })
    distribution.setdefault(
        "uncertainty_decomposition",
        unavailable_decomposition("Uncertainty thresholds are applied by the signal pipeline."),
    )
    return distribution


def _bounded_probability(value: object) -> float | None:
    probability = _finite_or_none(value)
    return probability if probability is not None and 0 <= probability <= 1 else None


def _normalise_decision_time(value: object) -> pd.Timestamp | None:
    if value is None or not pd.api.types.is_scalar(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True, format="mixed")
    except (TypeError, ValueError):
        return None
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _canonical_distribution_horizon(value: object) -> int | None:
    horizon = _finite_integer(value)
    return horizon if horizon in CANONICAL_DISTRIBUTION_HORIZONS_DAYS else None


def _finite_integer(value: object) -> int | None:
    number = _finite_or_none(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _declared_horizons_by_id(frame: pd.DataFrame, identity_column: str, horizon_column: str) -> dict[str, frozenset[int]]:
    horizons_by_id: dict[str, set[int]] = {}
    for identity, raw_horizon in zip(frame[identity_column], frame[horizon_column], strict=False):
        if not isinstance(identity, str) or not identity.strip():
            continue
        horizon = _finite_integer(raw_horizon)
        if horizon is not None:
            horizons_by_id.setdefault(identity.strip(), set()).add(horizon)
    return {identity: frozenset(horizons) for identity, horizons in horizons_by_id.items()}


def _horizon_identity_is_valid(
    identity: object,
    declared_horizon: int | None,
    requested_horizon: int,
    horizons_by_id: Mapping[str, frozenset[int]],
) -> bool:
    if not isinstance(identity, str) or not identity.strip() or declared_horizon != requested_horizon:
        return False
    return horizons_by_id.get(identity.strip()) == frozenset({requested_horizon})


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
            return _latest_row(matches)
    highest_horizon = group["horizon_days"].astype(int).max()
    return _latest_row(group[group["horizon_days"].astype(int) == highest_horizon])


def _latest_row(frame: pd.DataFrame) -> pd.Series:
    sort_columns = ["forecast_date"]
    if "run_id" in frame.columns:
        sort_columns.append("run_id")
    return frame.sort_values(sort_columns, kind="stable").iloc[-1]


def _timestamp_iso_or_none(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else parsed.isoformat()


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
