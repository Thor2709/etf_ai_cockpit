from __future__ import annotations

from io import BytesIO
import dataclasses
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


_REVISION_COLUMNS = ("open", "high", "low", "close", "volume", "currency", "is_adjusted",
                     "dividends", "stock_splits", "capital_gains")


def stamp_price_availability(stored: pd.DataFrame | None, incoming: pd.DataFrame, *, retrieved_at: datetime) -> pd.DataFrame:
    """Per-bar ``ingested_at``, ``known_at``, ``available_at`` and ``actions_evidenced`` (SDD contract C1).

    Key (``etf_id``, session). A new or revised bar gets ``retrieved_at``; a new bar is available at
    min(session 23:59:59 UTC, ``retrieved_at``), a revised bar at ``retrieved_at``. An unchanged bar takes the
    incoming values and keeps its stored stamps. A stored ``ingested_at`` without ``known_at`` gives
    ``known_at := ingested_at``; a bar with no stamps stays unstamped.
    """

    now = pd.Timestamp(retrieved_at).tz_convert("UTC")
    new = incoming.reset_index(drop=True)
    close = _sessions(new).dt.tz_localize("UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
    stamps = {"ingested_at": pd.Series(now, index=new.index), "known_at": pd.Series(now, index=new.index),
              "available_at": close.where(close < now, now), "actions_evidenced": _true(new, "actions_evidenced")}
    if stored is not None and not stored.empty:
        old = stored.reset_index(drop=True)
        ingested = _utc(old, "ingested_at")
        kept_stamps = {"ingested_at": ingested, "known_at": _utc(old, "known_at").fillna(ingested),
                       "available_at": _utc(old, "available_at"), "actions_evidenced": _true(old, "actions_evidenced")}
        lookup = pd.Series(old.index, index=_keys(old))
        position = lookup[~lookup.index.duplicated(keep="last")].reindex(_keys(new))
        rows, at = np.flatnonzero(position.notna().to_numpy()), position.dropna().astype(int).to_numpy()
        changed = np.zeros(len(rows), dtype=bool)
        for column in (name for name in _REVISION_COLUMNS if name in new and name in old):
            changed |= _differs(new[column].iloc[rows], old[column].iloc[at], rtol=1e-9)
        if "adjusted_close" in new and "adjusted_close" in old:
            (new_gross, new_prev), (old_gross, old_prev) = _session_gross(new), _session_gross(old)
            changed |= (new_prev.iloc[rows].to_numpy() & old_prev.iloc[at].to_numpy()
                        & _differs(new_gross.iloc[rows], old_gross.iloc[at], rtol=1e-6))
        stamps["available_at"].iloc[rows[changed]] = now
        for name, values in kept_stamps.items():
            stamps[name].iloc[rows[~changed]] = values.iloc[at[~changed]].to_numpy()
    out = incoming.copy()
    for name, values in stamps.items():
        out[name] = values.to_numpy()
    return out


def _sessions(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"]).dt.normalize()


def _keys(frame: pd.DataFrame) -> pd.MultiIndex:
    return pd.MultiIndex.from_arrays([frame["etf_id"].astype(str), _sessions(frame)])


def _utc(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return pd.to_datetime(frame[column], errors="coerce", utc=True)


def _true(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index)
    return frame[column].map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value)).astype(bool)


def _differs(new: pd.Series, old: pd.Series, *, rtol: float) -> np.ndarray:
    """Value inequality: numbers within ``rtol`` are equal; NaN equals NaN and differs from a number."""

    new, old = new.reset_index(drop=True), old.reset_index(drop=True)
    if pd.api.types.is_numeric_dtype(new) and pd.api.types.is_numeric_dtype(old):
        return ~np.isclose(new.to_numpy(float), old.to_numpy(float), rtol=rtol, atol=0.0, equal_nan=True)
    return ~((new == old) | (new.isna() & old.isna())).to_numpy()


def _session_gross(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """One-session gross return of ``adjusted_close`` per row, and whether the row has a previous session."""

    ordered = pd.DataFrame({"id": frame["etf_id"].astype(str), "session": _sessions(frame),
                            "adjusted": pd.to_numeric(frame["adjusted_close"], errors="coerce")})
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
    frame = stamp_price_availability(stored, incoming, retrieved_at=now)
    # The checksum always describes the frame that is persisted, never a pre-filter snapshot of it.
    checksum = sha256_dataframe(frame)
    metadata = dataclasses.replace(result.metadata, checksum=checksum) if result.metadata else None
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    raw_path = _store_raw_import(result, incoming, raw_dir, timestamp, checksum)
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
    current = pd.read_parquet(clean_path) if clean_path.exists() else None
    now = datetime.now(timezone.utc)
    frame = stamp_price_availability(current, pd.read_parquet(restored_snapshot_path), retrieved_at=now)
    checksum = sha256_dataframe(frame)
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    with publication_scope(publish_guard):
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
    checksum: str,
) -> Path:
    source_path = _source_path(result.metadata)
    if source_path and source_path.exists() and source_path.is_file():
        raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_{source_path.name}"
        atomic_write_bytes(raw_path, source_path.read_bytes(), validator=lambda _: None)
        return raw_path

    raw_path = raw_dir / f"{timestamp}_{checksum[:12]}_prices.parquet"
    payload = _parquet_bytes(frame)
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
