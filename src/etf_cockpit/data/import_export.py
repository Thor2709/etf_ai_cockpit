from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file

@dataclass(frozen=True)
class ImportPreview:
    preview_id: str
    import_type: str
    path: Path
    valid: bool
    rows: int
    columns: tuple[str, ...]
    errors: tuple[str, ...]
    frame: pd.DataFrame


@dataclass(frozen=True)
class ImportCommitResult:
    import_type: str
    rows: int
    frame: pd.DataFrame
    destination: Path


_REQUIRED = {"prices": ("date", "etf_id", "adjusted_close"), "fx": ("date",), "manual_news": ("headline",)}


def validate_import(import_type: str, path: Path) -> ImportPreview:
    preview_id = f"preview_{uuid.uuid4().hex[:12]}"
    try:
        frame = _read(path)
    except Exception as exc:
        return ImportPreview(preview_id, import_type, path, False, 0, (), (f"read_failed:{type(exc).__name__}",), pd.DataFrame())
    missing = tuple(column for column in _REQUIRED.get(import_type, ()) if column not in frame.columns)
    errors = tuple(f"missing_column:{column}" for column in missing)
    if frame.empty:
        errors += ("empty_file",)
    return ImportPreview(preview_id, import_type, path, not errors, len(frame), tuple(map(str, frame.columns)), errors, frame)


class ImportService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._previews: dict[str, ImportPreview] = {}

    def register(self, preview: ImportPreview) -> None:
        self._previews[preview.preview_id] = preview

    def commit(self, preview_id: str) -> ImportCommitResult:
        preview = self._previews.get(preview_id)
        if preview is None or not preview.valid:
            raise ValueError("A valid import preview is required before commit")
        destination = self.root / "data" / "clean" / f"{preview.import_type}.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(destination, parquet_payload(preview.frame), validate_parquet_file)
        return ImportCommitResult(preview.import_type, len(preview.frame), preview.frame, destination)


def _read(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    raise ValueError("Unsupported import file type")
