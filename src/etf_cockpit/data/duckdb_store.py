from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
import hashlib
import json

import duckdb
import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group, read_atomic_group, wait_for_atomic_group
from etf_cockpit.core.config import AppConfig, load_config
from etf_cockpit.core.paths import FEATURES_DIR, PORTFOLIOS_DIR, VALIDATED_DIR
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.core.versioning import current_settings_revision
from etf_cockpit.data.sample_data import ensure_sample_files
from etf_cockpit.data.validation import validate_prices

PRICE_PARQUET = VALIDATED_DIR / "prices" / "prices_daily.parquet"
FEATURE_PARQUET = FEATURES_DIR / "features_daily.parquet"
HOLDINGS_CSV = PORTFOLIOS_DIR / "current_holdings.csv"


def read_price_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    if "calendar_identity" in frame.columns:
        frame["calendar_identity"] = frame["calendar_identity"].map(
            _normalise_calendar_identity
        )
    return frame


def _normalise_calendar_identity(value: object) -> dict[str, object] | None:
    if isinstance(value, Mapping):
        payload: object = dict(value)
    elif isinstance(value, str) and value.strip():
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    else:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return json.loads(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _serialise_calendar_identity(value: object) -> str | None:
    normalised = _normalise_calendar_identity(value)
    if normalised is None:
        return None
    return json.dumps(normalised, sort_keys=True, separators=(",", ":"), allow_nan=False)


def initialise_store(
    config: AppConfig | None = None,
    force_sample: bool = False,
    *,
    publish_guard: PublicationScopeFactory | None = None,
) -> None:
    cfg = config or load_config()
    price_csv, _ = ensure_sample_files(cfg, force=force_sample, publish_guard=publish_guard)
    if force_sample or not PRICE_PARQUET.exists():
        prices = read_price_csv(price_csv)
        report = validate_prices(prices)
        if report.status == "Blocked":
            blocked = ", ".join(sorted(report.blocked_etfs))
            raise ValueError(f"Sample data unexpectedly blocked for: {blocked}")
        with publication_scope(publish_guard):
            write_prices(prices)


def write_prices(prices: pd.DataFrame, path: Path = PRICE_PARQUET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    if "calendar_identity" in frame.columns:
        frame["calendar_identity"] = frame["calendar_identity"].map(
            _serialise_calendar_identity
        )
    frame.to_parquet(path, index=False)


def load_prices(path: Path = PRICE_PARQUET) -> pd.DataFrame:
    if not path.exists():
        initialise_store()
    wait_for_atomic_group(path)
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    if "calendar_identity" in frame.columns:
        frame["calendar_identity"] = frame["calendar_identity"].map(
            _normalise_calendar_identity
        )
    return frame


def load_holdings(path: Path = HOLDINGS_CSV) -> pd.DataFrame:
    if not path.exists():
        initialise_store()
    frame = pd.read_csv(path)
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"]).dt.date
    return frame


def _features_payload(features: pd.DataFrame) -> bytes:
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def write_features(
    features: pd.DataFrame,
    path: Path = FEATURE_PARQUET,
    *,
    cache_metadata: Mapping[str, object] | None = None,
) -> None:
    payload = _features_payload(features)
    requests = [
        AtomicWriteRequest(
            path,
            payload,
            lambda candidate: pd.read_parquet(candidate),
        )
    ]
    if cache_metadata is not None:
        metadata = dict(cache_metadata)
        metadata["schema_version"] = 3
        metadata["payload_sha256"] = hashlib.sha256(payload).hexdigest()
        reference_identity = metadata.get("reference_identity")
        if isinstance(reference_identity, Mapping) and "reference_identity_hash" not in metadata:
            metadata["reference_identity_hash"] = _reference_identity_hash(reference_identity)
        metadata_path = Path(f"{path}.meta.json")
        requests.append(
            AtomicWriteRequest(
                metadata_path,
                json.dumps(metadata, sort_keys=True).encode("utf-8"),
                lambda candidate: json.loads(candidate.read_text(encoding="utf-8")),
            )
        )
    atomic_write_group(tuple(requests))


def load_features(
    path: Path = FEATURE_PARQUET,
    *,
    universe_revision: str | None = None,
    settings_revision: str | None = None,
    reference_identity: dict[str, object] | None = None,
    price_binding: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    if isinstance(reference_identity, Mapping) and "analysis" in reference_identity and price_binding is None:
        return pd.DataFrame()
    if not path.exists():
        return pd.DataFrame()
    metadata_path = Path(f"{path}.meta.json")
    try:
        if metadata_path.exists():
            payload_bytes, metadata_bytes = read_atomic_group((path, metadata_path))
            metadata = json.loads(metadata_bytes.decode("utf-8"))
        else:
            if (
                universe_revision is not None
                or settings_revision is not None
                or reference_identity is not None
                or price_binding is not None
            ):
                return pd.DataFrame()
            payload_bytes = path.read_bytes()
            metadata = None
        if metadata is not None:
            if not isinstance(metadata, dict):
                return pd.DataFrame()
            expected_settings = settings_revision or current_settings_revision()
            if universe_revision is not None and str(metadata.get("universe_revision") or "") != universe_revision:
                return pd.DataFrame()
            if (universe_revision is not None or settings_revision is not None) and str(metadata.get("settings_revision") or "") != expected_settings:
                return pd.DataFrame()
            if reference_identity is not None and (
                not _reference_identity_matches(
                    metadata.get("reference_identity"),
                    metadata.get("reference_identity_hash"),
                    reference_identity,
                )
                or metadata.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest()
            ):
                return pd.DataFrame()
            if price_binding is not None and not _cache_binding_matches(metadata, price_binding):
                return pd.DataFrame()
            if metadata.get("payload_sha256") is not None and metadata["payload_sha256"] != hashlib.sha256(payload_bytes).hexdigest():
                return pd.DataFrame()
        frame = pd.read_parquet(BytesIO(payload_bytes))
        if "date" not in frame.columns:
            return pd.DataFrame()
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.date
    except (OSError, TypeError, ValueError, KeyError, RecursionError):
        return pd.DataFrame()
    return frame


def _cache_binding_matches(metadata: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    checksum = expected.get("price_snapshot_checksum")
    revision = expected.get("price_snapshot_revision")
    cutoff = expected.get("effective_cutoff")
    window = expected.get("calculation_window")
    valid = (
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
    return valid and all(metadata.get(key) == value for key, value in expected.items())


def _reference_identity_hash(identity: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(identity), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def query_parquet(sql: str) -> pd.DataFrame:
    with duckdb.connect(database=":memory:") as con:
        con.execute("SET enable_progress_bar=false")
        return con.execute(sql).df()
