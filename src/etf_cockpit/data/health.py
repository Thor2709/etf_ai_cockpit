from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import pandas as pd

from etf_cockpit.core.config import AppConfig


class DataHealthStatus(StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    MISSING = "missing"
    CORRUPT = "corrupt"
    SCHEMA_MISMATCH = "schema_mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DataHealthRow:
    dataset: str
    status: DataHealthStatus
    path: str
    row_count: int
    checksum: str | None
    as_of: str | None
    freshness: str
    provider: str | None
    last_success: str | None
    last_failure: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DataHealthReport:
    created_at: str
    as_of_date: str
    rows: tuple[DataHealthRow, ...]

    @property
    def has_failures(self) -> bool:
        return any(row.status is not DataHealthStatus.HEALTHY for row in self.rows)


_DATASETS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "prices": ("data/clean/prices.parquet", "price", ("date",)),
    "fx": ("data/clean/fx.parquet", "fx", ("date",)),
    "holdings": ("data/clean/etf_holdings.parquet", "holdings", ("as_of_date",)),
    "fundamentals": ("data/clean/fundamentals.parquet", "fundamentals", ("as_of_date",)),
    "news": ("data/clean/news_context.parquet", "news", ("published_at",)),
    "filings": ("data/clean/filings_statements.parquet", "official", ("as_of_date",)),
    "provider_probes": ("data/clean/provider_probe_results.parquet", "provider", ("last_probe_at",)),
    "score_history": ("data/derived/score_history.parquet", "derived", ("run_completed_at",)),
}


def build_data_health(
    config: AppConfig,
    project_root: Path,
    *,
    as_of_date: str | date | None = None,
    stale_after_days: int = 3,
) -> DataHealthReport:
    del config
    as_of = _as_date(as_of_date) or date.today()
    rows = [
        _inspect_dataset(dataset, project_root, relative, provider, required, as_of, stale_after_days)
        for dataset, (relative, provider, required) in _DATASETS.items()
    ]
    rows.append(_inspect_latest_csv("forecasts", project_root / "data" / "forecasts", "model", ("forecast_date",), as_of, stale_after_days))
    rows.append(_inspect_file("backtest", project_root / "data" / "backtests" / "backtest_results.csv", "derived", ("end_date",), as_of, stale_after_days))
    rows.append(_inspect_directory("macro", project_root / "data" / "raw" / "macro", "macro", as_of))
    return DataHealthReport(datetime_now(), as_of.isoformat(), tuple(rows))


def export_data_health(report: DataHealthReport, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(row) | {"status": row.status.value, "warnings": "|".join(row.warnings)} for row in report.rows]).to_csv(destination, index=False)
    return destination


def _inspect_dataset(dataset: str, root: Path, relative: str, provider: str, required: tuple[str, ...], as_of: date, stale_after_days: int) -> DataHealthRow:
    return _inspect_file(dataset, root / Path(relative), provider, required, as_of, stale_after_days)


def _inspect_latest_csv(dataset: str, directory: Path, provider: str, required: tuple[str, ...], as_of: date, stale_after_days: int) -> DataHealthRow:
    candidates = sorted(directory.glob("*.csv")) if directory.exists() else []
    if not candidates:
        return DataHealthRow(dataset, DataHealthStatus.MISSING, str(directory), 0, None, None, "unavailable", provider, None, None, ("store_missing",))
    return _inspect_file(dataset, candidates[-1], provider, required, as_of, stale_after_days)


def _inspect_file(dataset: str, path: Path, provider: str, required: tuple[str, ...], as_of: date, stale_after_days: int) -> DataHealthRow:
    if not path.exists():
        return DataHealthRow(dataset, DataHealthStatus.MISSING, str(path), 0, None, None, "unavailable", provider, None, None, ("store_missing",))
    checksum = _sha256(path)
    try:
        frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    except Exception as exc:
        return DataHealthRow(dataset, DataHealthStatus.CORRUPT, str(path), 0, checksum, None, "unavailable", provider, None, datetime_now(), (f"read_failed:{type(exc).__name__}",))
    missing = tuple(column for column in required if column not in frame.columns)
    if missing:
        return DataHealthRow(dataset, DataHealthStatus.SCHEMA_MISMATCH, str(path), len(frame), checksum, None, "unavailable", provider, None, datetime_now(), (f"missing_columns:{','.join(missing)}",))
    as_of_value = _latest_date(frame, required)
    if as_of_value is None:
        return DataHealthRow(dataset, DataHealthStatus.UNAVAILABLE, str(path), len(frame), checksum, None, "unknown", provider, None, None, ("as_of_unavailable",))
    status = DataHealthStatus.HEALTHY if as_of_value >= as_of - timedelta(days=stale_after_days) else DataHealthStatus.STALE
    freshness = "fresh" if status is DataHealthStatus.HEALTHY else "stale"
    warnings = () if status is DataHealthStatus.HEALTHY else (f"as_of_older_than_{stale_after_days}_days",)
    return DataHealthRow(dataset, status, str(path), len(frame), checksum, as_of_value.isoformat(), freshness, provider, datetime_now(), None, warnings)


def _inspect_directory(dataset: str, path: Path, provider: str, as_of: date) -> DataHealthRow:
    if not path.exists():
        return DataHealthRow(dataset, DataHealthStatus.MISSING, str(path), 0, None, None, "unavailable", provider, None, None, ("store_missing",))
    files = [item for item in path.iterdir() if item.is_file()]
    if not files:
        return DataHealthRow(dataset, DataHealthStatus.UNAVAILABLE, str(path), 0, None, None, "unknown", provider, None, None, ("as_of_unavailable",))
    latest = max(files, key=lambda item: item.stat().st_mtime)
    return DataHealthRow(dataset, DataHealthStatus.HEALTHY, str(path), len(files), _sha256(latest), as_of.isoformat(), "fresh", provider, datetime_now(), None, (f"latest_file:{latest.name}",))


def _latest_date(frame: pd.DataFrame, columns: tuple[str, ...]) -> date | None:
    for column in columns:
        parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
        if not parsed.empty:
            return parsed.max().date()
    return None


def _as_date(value: str | date | None) -> date | None:
    if isinstance(value, date):
        return value
    if value:
        return datetime.fromisoformat(str(value)).date()
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def datetime_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
