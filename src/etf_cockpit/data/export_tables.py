from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file

def export_table(table_id: str, frame: pd.DataFrame, destination: Path) -> Path:
    if frame is None:
        raise ValueError(f"Table {table_id} is unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".csv":
        atomic_write_bytes(destination, frame.to_csv(index=False).encode("utf-8"), lambda path: pd.read_csv(path))
    elif destination.suffix.lower() in {".parquet", ".pq"}:
        atomic_write_bytes(destination, parquet_payload(frame), validate_parquet_file)
    else:
        raise ValueError("Exports must use CSV or Parquet")
    return destination


def table_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    return tuple(str(column) for column in frame.columns)
