from __future__ import annotations

from io import BytesIO
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import (
    AtomicWriteRequest,
    atomic_write_bytes,
    atomic_write_group,
    atomic_write_json,
)
from etf_cockpit.core.paths import CLEAN_DIR, RAW_DIR, SNAPSHOTS_DIR
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

    frame = result.data.copy()
    checksum = result.metadata.checksum if result.metadata else sha256_dataframe(frame)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    raw_path = _store_raw_import(result, frame, raw_dir, timestamp, checksum)
    previous_snapshot_path = _snapshot_existing_clean(compatibility_path, snapshots_dir, timestamp)
    _write_price_stores_atomically(frame, (compatibility_path, clean_path))

    metadata_path = snapshots_dir / f"{timestamp}_{checksum[:12]}_prices_metadata.json"
    atomic_write_json(
        metadata_path,
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
            "metadata": _metadata_to_json(result.metadata),
        },
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
) -> PriceImportRollback:
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(snapshots_dir.glob("*_previous_*.parquet"), key=lambda path: path.name)
    if not candidates:
        raise FileNotFoundError("No previous clean price snapshot is available to roll back.")

    restored_snapshot_path = candidates[-1]
    frame = pd.read_parquet(restored_snapshot_path)
    checksum = sha256_dataframe(frame)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)

    current_snapshot_path = None
    if compatibility_path.exists():
        current_snapshot_path = snapshots_dir / f"{timestamp}_rollback_replaced_{compatibility_path.name}"
        shutil.copy2(compatibility_path, current_snapshot_path)

    _write_price_stores_atomically(frame, (compatibility_path, clean_path))

    metadata_path = snapshots_dir / f"{timestamp}_{checksum[:12]}_prices_rollback.json"
    atomic_write_json(
        metadata_path,
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


def _write_price_stores_atomically(frame: pd.DataFrame, destinations: tuple[Path, ...]) -> None:
    payload = _parquet_bytes(frame)
    atomic_write_group(
        AtomicWriteRequest(destination, payload, _parquet_validator(len(frame)))
        for destination in destinations
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
