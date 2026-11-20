from __future__ import annotations

from io import BytesIO
import dataclasses
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.atomic_io import (
    AtomicWriteRequest,
    atomic_write_bytes,
    atomic_write_group,
)
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR, SNAPSHOTS_DIR
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.core.types import DatasetMetadata
from etf_cockpit.data.duckdb_store import PRICE_PARQUET
from etf_cockpit.data.provenance import sha256_dataframe
from etf_cockpit.data.providers import ProviderResult


@dataclass(frozen=True)
class PriceImportCommit:
    raw_path: Path
    clean_path: Path
    compatibility_path: Path
    previous_snapshot_path: Path | None
    metadata_path: Path
    rows: int
    checksum: str


@dataclass(frozen=True)
class PriceImportRollback:
    restored_snapshot_path: Path
    current_snapshot_path: Path | None
    clean_path: Path
    compatibility_path: Path
    metadata_path: Path
    rows: int
    checksum: str


_ACTION_DOWNLOAD_PROVIDERS = frozenset({"yfinance"})  # downloads that request actions (require_actions=True)
_REVISION_COLUMNS = ("open", "high", "low", "close", "volume", "currency", "is_adjusted",
                     "dividends", "stock_splits", "capital_gains")


def stamp_price_availability(stored: pd.DataFrame | None, incoming: pd.DataFrame, *, retrieved_at: datetime) -> pd.DataFrame:
    """Per-bar ``ingested_at``, ``known_at``, ``available_at`` and ``actions_evidenced`` (SDD contract C1).

    Key (``etf_id``, else ``instrument_id``; session). A new or revised bar gets ``retrieved_at``; a new bar is
    available at min(session 23:59:59 UTC, ``retrieved_at``), a revised bar at ``retrieved_at``. An unchanged bar
    takes the incoming values and keeps its stored stamps. A stored ``ingested_at`` without ``known_at`` gives
    ``known_at := ingested_at``; a bar with no stamps stays unstamped.
    """

    now = pd.Timestamp(retrieved_at).tz_convert("UTC")
    new = incoming.reset_index(drop=True)
    new_keys = _keys(new)
    sessions = pd.Series(new_keys.get_level_values(1).to_numpy(), index=new.index)
    close = sessions.dt.tz_localize("UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
    stamps = {"ingested_at": pd.Series(now, index=new.index), "known_at": pd.Series(now, index=new.index),
              "available_at": close.where(close < now, now), "actions_evidenced": _true(new, "actions_evidenced")}
    if stored is not None and not stored.empty:
        old = stored.reset_index(drop=True)
        old_keys = _keys(old)
        ingested = _utc(old, "ingested_at")
        kept_stamps = {"ingested_at": ingested, "known_at": _utc(old, "known_at").fillna(ingested),
                       "available_at": _utc(old, "available_at"), "actions_evidenced": _true(old, "actions_evidenced")}
        lookup = pd.Series(old.index, index=old_keys)
        position = lookup[~lookup.index.duplicated(keep="last")].reindex(new_keys)
        rows, at = np.flatnonzero(position.notna().to_numpy()), position.dropna().astype(int).to_numpy()
        changed = np.zeros(len(rows), dtype=bool)
        for column in (name for name in _REVISION_COLUMNS if name in new and name in old):
            changed |= _differs(new[column].iloc[rows], old[column].iloc[at], rtol=1e-9)
        if "adjusted_close" in new and "adjusted_close" in old:
            (new_gross, new_prev), (old_gross, old_prev) = _session_gross(new, new_keys), _session_gross(old, old_keys)
            changed |= (new_prev.iloc[rows].to_numpy() & old_prev.iloc[at].to_numpy()
                        & _differs(new_gross.iloc[rows], old_gross.iloc[at], rtol=1e-6))
        stamps["available_at"].iloc[rows[changed]] = now
        for name, values in kept_stamps.items():
            stamps[name].iloc[rows[~changed]] = values.iloc[at[~changed]].to_numpy()
    out = incoming.copy()
    for name, values in stamps.items():
        out[name] = values.to_numpy()
    return out


def _keys(frame: pd.DataFrame) -> pd.MultiIndex:
    """(instrument, session) per row; the import path accepts ``etf_id`` or ``instrument_id``."""

    column = next((name for name in ("etf_id", "instrument_id") if name in frame), None)
    if column is None:
        raise ValueError("Price rows need an etf_id or instrument_id column for per-bar stamps.")
    return pd.MultiIndex.from_arrays([frame[column].astype(str), pd.to_datetime(frame["date"]).dt.normalize()])


def _utc(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return pd.to_datetime(frame[column], errors="coerce", utc=True)


def _true(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index)
    values = frame[column]
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False).astype(bool)
    # Mixed or text values: only a real boolean True counts.
    return values.map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value)).astype(bool)


def _differs(new: pd.Series, old: pd.Series, *, rtol: float) -> np.ndarray:
    """Value inequality: numbers within ``rtol`` are equal; NaN equals NaN and differs from a number."""

    new, old = new.reset_index(drop=True), old.reset_index(drop=True)
    if pd.api.types.is_numeric_dtype(new) and pd.api.types.is_numeric_dtype(old):
        return ~np.isclose(new.to_numpy(float), old.to_numpy(float), rtol=rtol, atol=0.0, equal_nan=True)
    return ~((new == old) | (new.isna() & old.isna())).to_numpy()


def _session_gross(frame: pd.DataFrame, keys: pd.MultiIndex) -> tuple[pd.Series, pd.Series]:
    """One-session gross return of ``adjusted_close`` per row, and whether the row has a previous session."""

    ordered = pd.DataFrame({"id": keys.get_level_values(0).to_numpy(), "session": keys.get_level_values(1).to_numpy(),
                            "adjusted": pd.to_numeric(frame["adjusted_close"], errors="coerce").to_numpy()},
                           index=frame.index)
    groups = ordered.sort_values(["id", "session"], kind="stable").groupby("id", sort=False)
    gross = ordered["adjusted"] / groups["adjusted"].shift(1).sort_index()
    return gross, (groups.cumcount() > 0).sort_index()


def commit_price_import(
    result: ProviderResult,
    *,
    clean_path: Path = CLEAN_DIR / "prices.parquet",
    compatibility_path: Path = PRICE_PARQUET,
    raw_dir: Path = RAW_DIR / "prices",
    snapshots_dir: Path = SNAPSHOTS_DIR / "prices",
) -> PriceImportCommit:
    if not result.ok or result.data is None:
        raise ValueError("Cannot commit a provider result that did not load data.")

    incoming = result.data.copy()
    stored = pd.read_parquet(clean_path) if clean_path.exists() else None
    now = datetime.now(timezone.utc)
    # C1: only a download that asked for actions is action evidence; a local file never is.
    claimed = incoming if result.provider_name in _ACTION_DOWNLOAD_PROVIDERS else incoming.assign(actions_evidenced=False)
    frame = stamp_price_availability(stored, claimed, retrieved_at=now)
    # The checksum always describes the frame that is persisted, never a pre-filter snapshot of it.
    checksum = sha256_dataframe(frame)
    metadata = dataclasses.replace(result.metadata, checksum=checksum) if result.metadata else None
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    raw_path = _store_raw_import(result, incoming, raw_dir, timestamp)
    previous_snapshot_path = _snapshot_existing_clean(compatibility_path, snapshots_dir, timestamp)

    metadata_path = snapshots_dir / f"{timestamp}_{checksum[:12]}_prices_metadata.json"
    metadata_payload = json.dumps(
        {
            "dataset_type": result.dataset_type,
            "provider_name": result.provider_name,
            "message": result.message,
            "rows": len(frame),
            "checksum": checksum,
            "raw_path": str(raw_path),
            "clean_path": str(clean_path),
            "compatibility_path": str(compatibility_path),
            "previous_snapshot_path": str(previous_snapshot_path) if previous_snapshot_path else None,
            "metadata": _metadata_to_json(metadata),
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    # Metadata and prices are one atomic group: prices are never visible without their metadata.
    _write_price_stores_atomically(
        frame,
        (compatibility_path, clean_path),
        extra=(AtomicWriteRequest(metadata_path, metadata_payload, _json_validator),),
    )
    return PriceImportCommit(
        raw_path=raw_path,
        clean_path=clean_path,
        compatibility_path=compatibility_path,
        previous_snapshot_path=previous_snapshot_path,
        metadata_path=metadata_path,
        rows=len(frame),
        checksum=checksum,
    )


def rollback_latest_price_import(
    *,
    clean_path: Path = CLEAN_DIR / "prices.parquet",
    compatibility_path: Path = PRICE_PARQUET,
    snapshots_dir: Path = SNAPSHOTS_DIR / "prices",
    publish_guard: PublicationScopeFactory | None = None,
) -> PriceImportRollback:
    candidates = sorted(snapshots_dir.glob("*_previous_*.parquet"), key=lambda path: path.name)
    if not candidates:
        raise FileNotFoundError("No previous clean price snapshot is available to roll back.")

    restored_snapshot_path = candidates[-1]
    restored = pd.read_parquet(restored_snapshot_path)
    with publication_scope(publish_guard):
        # Read the current store under the guard, so no write comes between this read and the rollback write.
        current = pd.read_parquet(clean_path) if clean_path.exists() else None
        now = datetime.now(timezone.utc)
        frame = stamp_price_availability(current, restored, retrieved_at=now)
        checksum = sha256_dataframe(frame)
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        clean_path.parent.mkdir(parents=True, exist_ok=True)
        compatibility_path.parent.mkdir(parents=True, exist_ok=True)

        current_snapshot_path = None
        if compatibility_path.exists():
            current_snapshot_path = snapshots_dir / f"{timestamp}_rollback_replaced_{compatibility_path.name}"
            shutil.copy2(compatibility_path, current_snapshot_path)

        metadata_path = snapshots_dir / f"{timestamp}_{checksum[:12]}_prices_rollback.json"
        metadata_payload = json.dumps(
            {
                "dataset_type": "prices",
                "operation": "rollback_latest_price_import",
                "rows": len(frame),
                "checksum": checksum,
                "restored_snapshot_path": str(restored_snapshot_path),
                "current_snapshot_path": str(current_snapshot_path) if current_snapshot_path else None,
                "clean_path": str(clean_path),
                "compatibility_path": str(compatibility_path),
            },
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        _write_price_stores_atomically(
            frame,
            (compatibility_path, clean_path),
            extra=(AtomicWriteRequest(metadata_path, metadata_payload, _json_validator),),
        )
    return PriceImportRollback(
        restored_snapshot_path=restored_snapshot_path,
        current_snapshot_path=current_snapshot_path,
        clean_path=clean_path,
        compatibility_path=compatibility_path,
        metadata_path=metadata_path,
        rows=len(frame),
        checksum=checksum,
    )


def _store_raw_import(
    result: ProviderResult,
    frame: pd.DataFrame,
    raw_dir: Path,
    timestamp: str,
) -> Path:
    # The raw file name carries a hash of the bytes written, not of the stamped store.
    source_path = _source_path(result.metadata)
    if source_path and source_path.exists() and source_path.is_file():
        payload = source_path.read_bytes()
        raw_path = raw_dir / f"{timestamp}_{hashlib.sha256(payload).hexdigest()[:12]}_{source_path.name}"
        atomic_write_bytes(raw_path, payload, validator=lambda _: None)
        return raw_path

    payload = _parquet_bytes(frame)
    raw_path = raw_dir / f"{timestamp}_{hashlib.sha256(payload).hexdigest()[:12]}_prices.parquet"
    atomic_write_bytes(raw_path, payload, validator=_parquet_validator(len(frame)))
    return raw_path


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    output = BytesIO()
    stored = frame.copy()
    if "date" in stored.columns:
        stored["date"] = pd.to_datetime(stored["date"])
    stored.to_parquet(output, index=False)
    return output.getvalue()


def _parquet_validator(expected_rows: int):
    def validate(path: Path) -> None:
        if len(pd.read_parquet(path)) != expected_rows:
            raise ValueError(f"parquet row validation failed for {path.name}")

    return validate


def _json_validator(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def _write_price_stores_atomically(
    frame: pd.DataFrame,
    destinations: tuple[Path, ...],
    *,
    extra: tuple[AtomicWriteRequest, ...] = (),
) -> None:
    payload = _parquet_bytes(frame)
    atomic_write_group(
        (
            *(AtomicWriteRequest(destination, payload, _parquet_validator(len(frame))) for destination in destinations),
            *extra,
        )
    )


def _snapshot_existing_clean(clean_path: Path, snapshots_dir: Path, timestamp: str) -> Path | None:
    if not clean_path.exists():
        return None
    snapshot_path = snapshots_dir / f"{timestamp}_previous_{clean_path.name}"
    shutil.copy2(clean_path, snapshot_path)
    return snapshot_path


def _source_path(metadata: DatasetMetadata | None) -> Path | None:
    if metadata is None:
        return None
    try:
        return Path(metadata.provider_or_manual_source)
    except Exception:
        return None


def _metadata_to_json(metadata: DatasetMetadata | None) -> dict[str, object] | None:
    if metadata is None:
        return None
    return {
        "source_name": metadata.source_name,
        "source_type": metadata.source_type,
        "as_of_date": metadata.as_of_date.isoformat() if metadata.as_of_date else None,
        "ingested_at": metadata.ingested_at.isoformat() if metadata.ingested_at else None,
        "currency": metadata.currency,
        "timezone": metadata.timezone,
        "provider_or_manual_source": metadata.provider_or_manual_source,
        "checksum": metadata.checksum,
        "staleness_status": metadata.staleness_status,
        "age_days": metadata.age_days,
        "notes": metadata.notes,
    }
