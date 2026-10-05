from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file


@dataclass(frozen=True)
class ExportResult:
    table_id: str
    destination: Path | None
    rows: int
    ok: bool
    error: str = ""
    status: str = "exported"
    execution_allowed: bool = False

    @property
    def path(self) -> Path | None:
        return self.destination

    def __fspath__(self) -> str:
        return str(self.destination or "")

    def exists(self) -> bool:
        return bool(self.destination and self.destination.exists())


def export_table(table_id: str, frame: pd.DataFrame | None, destination: Path) -> ExportResult:
    output = Path(destination)
    if frame is None or not isinstance(frame, pd.DataFrame):
        return ExportResult(str(table_id), output, 0, False, f"Table {table_id} is unavailable", "failed")
    if output.suffix.lower() not in {".csv", ".parquet", ".pq"}:
        return ExportResult(str(table_id), output, 0, False, "Exports must use CSV or Parquet", "failed")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() == ".csv":
            atomic_write_bytes(output, frame.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path))
        else:
            atomic_write_bytes(output, parquet_payload(frame), validate_parquet_file)
    except Exception as exc:
        return ExportResult(str(table_id), output, 0, False, f"export_failed:{type(exc).__name__}:{exc}", "failed")
    return ExportResult(str(table_id), output, len(frame), True)


def table_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    return tuple(str(column) for column in frame.columns)
