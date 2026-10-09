"""Derived-artefact cache bindings: universe/settings/price/forecast/reference identity metadata and codecs for cached feature, forecast and backtest artefacts (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import (
    Callable,
    Mapping,
)
from datetime import date
import math
import json
import hashlib
from numbers import (
    Integral,
    Real,
)
from pathlib import Path
import pandas as pd

from etf_cockpit.backtest.metrics import (
    max_drawdown,
    tail_event_diagnostics,
)
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.atomic_io import (
    AtomicWriteRequest,
    atomic_write_group,
    read_atomic_group,
)
from etf_cockpit.core.versioning import current_settings_revision
from etf_cockpit.data.duckdb_store import _cache_binding_matches as _price_binding_matches
from etf_cockpit.data.etf_structure import structure_confidence_caps
from etf_cockpit.data.universe_store import load_universe
from etf_cockpit.models.forecast_scores import forecast_request_identity
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkReferenceError,
    validate_execution_disabled,
)
from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    adjusted_price_snapshot_binding,
)


# Broad-market anchor for relative strength when the canonical benchmark has no imported
# total-return evidence (FTSE All-World tracker, accumulating). Part of the feature cache identity.
RELATIVE_STRENGTH_FALLBACK_ANCHOR = "VWCE"

def _universe_cache_meta_path(path: Path) -> Path:
    return Path(f"{path}.meta.json")


def _current_universe_revision() -> str:
    try:
        return load_universe().revision
    except (OSError, ValueError, TypeError, KeyError):
        return ""


def _cache_matches_universe(
    path: Path,
    revision: str,
    settings_revision: str | None = None,
    reference_identity: Mapping[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> bool:
    metadata_path = _universe_cache_meta_path(path)
    if not path.is_file() or not metadata_path.is_file():
        return False
    try:
        payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (OSError, ValueError, TypeError, RecursionError):
        return False
    expected_settings = settings_revision or current_settings_revision()
    matches = (
        isinstance(payload, dict)
        and str(payload.get("universe_revision") or "") == revision
        and str(payload.get("settings_revision") or "") == expected_settings
    )
    if not matches or reference_identity is None:
        if not matches:
            return False
        checksum = payload.get("payload_sha256") if isinstance(payload, dict) else None
        return (
            (checksum is None or checksum == hashlib.sha256(payload_bytes).hexdigest())
            and (price_binding is None or _price_binding_matches(payload, price_binding))
            and (
                forecast_request_identity is None
                or _forecast_request_matches(payload, forecast_request_identity)
            )
        )
    if payload.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest():
        return False
    if price_binding is not None and not _price_binding_matches(payload, price_binding):
        return False
    if forecast_request_identity is not None and not _forecast_request_matches(payload, forecast_request_identity):
        return False
    return _reference_identity_matches(
        payload.get("reference_identity"),
        payload.get("reference_identity_hash"),
        reference_identity,
    )


def _read_bound_cache_payload(
    path: Path,
    revision: str,
    settings_revision: str,
    reference_identity: Mapping[str, object],
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> bytes | None:
    metadata_path = _universe_cache_meta_path(path)
    try:
        payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except (OSError, TypeError, ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("universe_revision") or "") != revision:
        return None
    if str(payload.get("settings_revision") or "") != settings_revision:
        return None
    if not _reference_identity_matches(
        payload.get("reference_identity"),
        payload.get("reference_identity_hash"),
        reference_identity,
    ):
        return None
    if price_binding is not None and not _price_binding_matches(payload, price_binding):
        return None
    if forecast_request_identity is not None and not _forecast_request_matches(payload, forecast_request_identity):
        return None
    if payload.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest():
        return None
    return payload_bytes


def _cached_structure_columns_match(
    signal_log: pd.DataFrame,
    structural_caps: pd.Series,
    structural_hashes: pd.Series,
    structure_evidence: object,
    allowed_instrument_ids: object,
) -> bool:
    """Validate cached structural identity without replaying once per row."""

    decision_times = pd.to_datetime(signal_log["date"], errors="coerce")
    raw_instrument_ids = signal_log["etf_id"]
    instrument_ids = raw_instrument_ids.astype(str).str.strip()
    invalid_instrument_ids = raw_instrument_ids.isna() | instrument_ids.str.lower().isin(
        {"", "<na>", "nan", "none", "null"}
    )
    allowed_ids = {
        str(item).strip()
        for item in (allowed_instrument_ids or ())
        if str(item).strip()
    }
    if (
        decision_times.isna().any()
        or invalid_instrument_ids.any()
        or not allowed_ids
        or not instrument_ids.isin(allowed_ids).all()
    ):
        return False
    evidence_channels = (
        structure_evidence.document_registry,
        structure_evidence.report_records,
        structure_evidence.supplemental_rows,
        structure_evidence.holdings,
    )
    if all(isinstance(channel, pd.DataFrame) and channel.empty for channel in evidence_channels):
        return bool(structural_caps.eq(0.0).all() and structural_hashes.eq("unavailable").all())

    replay_rows = pd.DataFrame(
        {
            "decision_date": decision_times.dt.date,
            "instrument_id": instrument_ids,
            "stored_cap": structural_caps,
            "stored_hash": structural_hashes,
        }
    )
    for decision_date, rows in replay_rows.groupby("decision_date", sort=True):
        expected_caps = structure_confidence_caps(
            sorted(rows["instrument_id"].unique()),
            document_registry=structure_evidence.document_registry,
            report_records=structure_evidence.report_records,
            supplemental_rows=structure_evidence.supplemental_rows,
            holdings=structure_evidence.holdings,
            decision_time=decision_date,
        )
        for row in rows.itertuples(index=False):
            expected_cap = float(expected_caps.get(row.instrument_id, 0.0))
            expected_hash = str(
                expected_caps.provenance.get(row.instrument_id, {}).get(
                    "structure_provenance_hash", "unavailable"
                )
            ).strip()
            if float(row.stored_cap) != expected_cap or row.stored_hash != expected_hash:
                return False
    return True


def _bound_cache_metadata_payload(
    revision: str,
    settings_revision: str,
    reference_identity: Mapping[str, object] | None,
    payload: bytes,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> bytes:
    record: dict[str, object] = {
        "schema_version": 3,
        "universe_revision": revision,
        "settings_revision": settings_revision,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }
    if reference_identity is not None:
        record["reference_identity"] = dict(reference_identity)
        record["reference_identity_hash"] = _reference_identity_hash(reference_identity)
    if price_binding is not None:
        record.update(dict(price_binding))
    if forecast_request_identity is not None:
        record["forecast_request_identity"] = dict(forecast_request_identity)
        record["forecast_request_identity_hash"] = _reference_identity_hash(forecast_request_identity)
    return json.dumps(record, sort_keys=True).encode("utf-8")


def _write_bound_cache_group(
    path: Path,
    payload: bytes,
    validator: Callable[[Path], None],
    revision: str,
    settings_revision: str,
    reference_identity: Mapping[str, object] | None,
    price_binding: Mapping[str, object] | None = None,
    forecast_request_identity: Mapping[str, object] | None = None,
) -> None:
    metadata_path = _universe_cache_meta_path(path)
    metadata_payload = _bound_cache_metadata_payload(
        revision,
        settings_revision,
        reference_identity,
        payload,
        price_binding,
        forecast_request_identity,
    )
    atomic_write_group(
        (
            AtomicWriteRequest(path, payload, validator),
            AtomicWriteRequest(
                metadata_path,
                metadata_payload,
                lambda candidate: json.loads(candidate.read_text(encoding="utf-8")),
            ),
        )
    )


def _reference_identity_hash(identity: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _canonical_json_value(identity),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_json_value(value: object) -> object:
    """Return JSON-safe canonical data without coercing primitive types."""

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("canonical mappings require string keys")
        return {key: _canonical_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return value
    raise TypeError("canonical JSON contains an unsupported primitive")


def _calculation_window(
    context: CanonicalReferenceContext,
    as_of_date: date,
    prices: pd.DataFrame,
) -> dict[str, str] | None:
    """Return the exact canonical window, with a deterministic local fallback."""

    try:
        requested_as_of = pd.Timestamp(as_of_date).date()
    except (TypeError, ValueError):
        return None
    resolution = getattr(context, "resolution", None)
    if resolution is not None:
        declaration = resolution.declaration
        try:
            end_date = date.fromisoformat(declaration.end_date)
        except (TypeError, ValueError):
            return None
        if requested_as_of > end_date:
            return None
        if requested_as_of < end_date:
            return {
                "start_date": declaration.start_date,
                "end_date": requested_as_of.isoformat(),
                "decision_time": f"{requested_as_of.isoformat()}T23:59:59+00:00",
            }
        return {
            "start_date": declaration.start_date,
            "end_date": declaration.end_date,
            "decision_time": declaration.decision_time,
        }

    if not isinstance(prices, pd.DataFrame) or "date" not in prices.columns:
        start_date = requested_as_of
    else:
        dates = pd.to_datetime(prices["date"], errors="coerce", utc=True)
        valid = dates.dropna()
        start_date = valid.min().date() if not valid.empty else requested_as_of
    return {
        "start_date": start_date.isoformat(),
        "end_date": requested_as_of.isoformat(),
        "decision_time": f"{requested_as_of.isoformat()}T23:59:59+00:00",
    }


def _price_snapshot_binding(
    prices: pd.DataFrame,
    *,
    calculation_window: Mapping[str, str],
) -> dict[str, object] | None:
    """Build the adjusted-price identity used by derived-cache sidecars."""

    return adjusted_price_snapshot_binding(prices, calculation_window=calculation_window)


def _forecast_request_identity(
    config: AppConfig,
    horizons: list[int] | None,
    *,
    live_optional_models: bool,
) -> dict[str, object]:
    return forecast_request_identity(
        config,
        horizons,
        live_optional_models=live_optional_models,
    )


def _forecast_request_matches(metadata: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    return _reference_identity_matches(
        metadata.get("forecast_request_identity"),
        metadata.get("forecast_request_identity_hash"),
        expected,
    )


def _reference_binding(reference_context: CanonicalReferenceContext) -> dict[str, object]:
    """Build the one cache binding from the freshly resolved context."""

    projection = reference_context.projection
    identity = reference_context.identity
    identity_hash = _reference_identity_hash(identity)
    strategy = (
        "canonical_price_series"
        if projection.get("status") == "available" and reference_context.benchmark_data_id
        else "unavailable"
    )
    strategy_identity = {
        "strategy": strategy,
        "benchmark_data_id": reference_context.benchmark_data_id,
        "relative_strength_fallback_anchor": RELATIVE_STRENGTH_FALLBACK_ANCHOR,
        "reference_identity_hash": identity_hash,
    }
    return {
        "benchmark_reference": projection,
        "benchmark_reference_hash": _reference_identity_hash(projection),
        "benchmark_strategy": strategy,
        "benchmark_strategy_hash": _reference_identity_hash(strategy_identity),
        "benchmark_strategy_identity": strategy_identity,
        "reference_identity": identity,
        "reference_identity_hash": identity_hash,
    }


def _cached_backtest_binding_matches(
    metadata: Mapping[str, object],
    reference_context: CanonicalReferenceContext,
) -> bool:
    """Require cached benchmark metadata to match canonical context exactly."""

    try:
        validate_execution_disabled(metadata)
        expected = _reference_binding(reference_context)
        return all(
            metadata.get(field) == value
            for field, value in expected.items()
        ) and all(
            _reference_identity_hash(metadata[field]) == expected[hash_field]
            for field, hash_field in (
                ("benchmark_reference", "benchmark_reference_hash"),
                ("benchmark_strategy_identity", "benchmark_strategy_hash"),
                ("reference_identity", "reference_identity_hash"),
            )
        )
    except (BenchmarkReferenceError, TypeError, ValueError, KeyError, RecursionError):
        return False


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


def _decode_negative_contribution_periods(value: object) -> list[dict[str, object]] | None:
    if type(value) is not str:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, list):
        return None
    records: list[dict[str, object]] = []
    for record in decoded:
        if not isinstance(record, dict) or set(record) != {"date", "return"}:
            return None
        raw_date = record["date"]
        raw_return = record["return"]
        if type(raw_date) is not str or type(raw_return) not in {int, float}:
            return None
        try:
            contribution_date = date.fromisoformat(raw_date)
            contribution_return = float(raw_return)
        except (TypeError, ValueError):
            return None
        if contribution_date.isoformat() != raw_date:
            return None
        if not math.isfinite(contribution_return) or contribution_return >= 0:
            return None
        records.append({"date": contribution_date, "return": contribution_return})
    return records


_NULLABLE_INTEGER_DIAGNOSTIC_FIELDS = frozenset(
    {
        "high_volatility_loss_sessions",
        "loss_sessions_observed",
        "regime_stress_loss_sessions",
        "regime_stress_sessions_observed",
        "worst_drawdown_duration_days",
        "worst_drawdown_duration_sessions",
    }
)


def _encode_nullable_integer_diagnostic(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("nullable diagnostic count must be an integer")
    number = float(value)
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError("nullable diagnostic count must be a non-negative integer")
    return int(number)


def _decode_nullable_integer_diagnostic(value: str) -> object:
    if value == "":
        return pd.NA
    if not value.isascii() or not value.isdecimal() or (len(value) > 1 and value.startswith("0")):
        raise ValueError("persisted diagnostic count is not a canonical integer")
    return int(value)


def _cached_value_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_cached_value_matches(actual_item, expected_item) for actual_item, expected_item in zip(actual, expected, strict=True))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and all(_cached_value_matches(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, date):
        if isinstance(actual, date):
            return actual == expected
        return type(actual) is str and actual == expected.isoformat()
    if expected is None:
        return bool(pd.isna(actual))
    if type(expected) is bool:
        return type(actual) is bool and actual is expected
    if type(expected) is int:
        return isinstance(actual, Integral) and not isinstance(actual, bool) and int(actual) == expected
    if type(expected) is float:
        if not isinstance(actual, Real) or isinstance(actual, (Integral, bool)):
            return False
        number = float(actual)
        return math.isfinite(number) and math.isclose(
            number,
            float(expected),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    if type(expected) is str:
        if expected == "" and pd.isna(actual):
            return True
        return type(actual) is str and actual == expected
    return False


def _cached_tail_diagnostics_are_valid(results: pd.DataFrame, equity_curves: pd.DataFrame) -> bool:
    strategy_names = results["strategy_name"]
    if (
        strategy_names.duplicated().any()
        or not strategy_names.map(lambda value: type(value) is str).all()
        or set(strategy_names) != set(equity_curves.columns)
    ):
        return False
    decoded_contributions = results["largest_negative_contribution_periods"].map(
        _decode_negative_contribution_periods
    )
    if decoded_contributions.isna().any():
        return False
    results["largest_negative_contribution_periods"] = decoded_contributions
    conditional_fields = {
        "high_volatility_threshold",
        "high_volatility_loss_sessions",
        "loss_sessions_observed",
        "regime_stress_loss_sessions",
        "regime_stress_sessions_observed",
    }
    for _, row in results.iterrows():
        strategy_name = row["strategy_name"]
        if type(strategy_name) is not str or strategy_name not in equity_curves:
            return False
        expected = {
            **tail_event_diagnostics(equity_curves[strategy_name]),
            "max_drawdown": max_drawdown(equity_curves[strategy_name]),
        }
        for diagnostic_field, expected_value in expected.items():
            if diagnostic_field not in results or not _cached_value_matches(
                row[diagnostic_field], expected_value
            ):
                return False
        for diagnostic_field in conditional_fields - set(expected):
            if diagnostic_field in results and not pd.isna(row[diagnostic_field]):
                return False
    return True
