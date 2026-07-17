from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.migrations import MIGRATIONS
from etf_cockpit.data.bitemporal import BitemporalStore
from etf_cockpit.data.hybrid_platform import HybridPlatform


class DataHealthStatus(StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    MISSING = "missing"
    CORRUPT = "corrupt"
    SCHEMA_MISMATCH = "schema_mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DataHealthLink:
    """A safe, local route related to one inventory row."""

    label: str
    route: str


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
    links: tuple[DataHealthLink, ...] = ()

    @property
    def actions(self) -> tuple[DataHealthLink, ...]:
        """Compatibility alias for consumers that call links actions."""

        return self.links


@dataclass(frozen=True)
class DataHealthReport:
    created_at: str
    as_of_date: str
    rows: tuple[DataHealthRow, ...]

    @property
    def has_failures(self) -> bool:
        return any(row.status is not DataHealthStatus.HEALTHY for row in self.rows)

    @property
    def migration_status(self) -> DataHealthRow:
        """Return the explicit migration inventory row."""

        return next(row for row in self.rows if row.dataset == "migration_status")


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
    rows.append(_inspect_macro(project_root / "data" / "raw" / "macro", as_of, stale_after_days))
    rows.append(_inspect_migrations(project_root))
    rows.append(_inspect_local_storage(project_root))
    return DataHealthReport(datetime_now(), as_of.isoformat(), tuple(rows))


def filter_data_health_rows(
    rows: Iterable[DataHealthRow] | DataHealthReport,
    *,
    status: str | DataHealthStatus | None = None,
    dataset: str | None = None,
    provider: str | None = None,
) -> tuple[DataHealthRow, ...]:
    """Filter inventory rows without changing their deterministic order."""

    def _normalise(value: object | None) -> str:
        return str(value or "").strip().lower()

    wanted_status = _normalise(status)
    wanted_dataset = _normalise(dataset)
    wanted_provider = _normalise(provider)
    source = rows.rows if isinstance(rows, DataHealthReport) else rows
    return tuple(
        row
        for row in source
        if (not wanted_status or wanted_status == "all" or row.status.value == wanted_status)
        and (not wanted_dataset or wanted_dataset == "all" or row.dataset.lower() == wanted_dataset)
        and (not wanted_provider or wanted_provider == "all" or (row.provider or "").lower() == wanted_provider)
    )


def export_data_health(report: DataHealthReport, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for row in report.rows:
        payload = asdict(row)
        payload.pop("links", None)
        records.append(
            payload
            | {
                "status": row.status.value,
                "warnings": "|".join(row.warnings),
            }
        )
    pd.DataFrame(records).to_csv(destination, index=False)
    return destination


def _inspect_dataset(dataset: str, root: Path, relative: str, provider: str, required: tuple[str, ...], as_of: date, stale_after_days: int) -> DataHealthRow:
    return _inspect_file(dataset, root / Path(relative), provider, required, as_of, stale_after_days)


def _inspect_latest_csv(dataset: str, directory: Path, provider: str, required: tuple[str, ...], as_of: date, stale_after_days: int) -> DataHealthRow:
    candidates = sorted(directory.glob("*.csv")) if directory.exists() else []
    if not candidates:
        return _make_row(dataset, DataHealthStatus.MISSING, directory, provider, warnings=("store_missing",), history_root=directory.parents[1])
    return _inspect_file(dataset, candidates[-1], provider, required, as_of, stale_after_days)


def _inspect_file(dataset: str, path: Path, provider: str, required: tuple[str, ...], as_of: date, stale_after_days: int) -> DataHealthRow:
    if not path.exists():
        return _make_row(dataset, DataHealthStatus.MISSING, path, provider, warnings=("store_missing",), history_root=_history_root(path))
    checksum = _sha256(path)
    try:
        frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    except Exception as exc:
        return _make_row(dataset, DataHealthStatus.CORRUPT, path, provider, row_count=0, checksum=checksum, warnings=(f"read_failed:{type(exc).__name__}",), history_root=_history_root(path))
    missing = tuple(column for column in required if column not in frame.columns)
    if missing:
        return _make_row(dataset, DataHealthStatus.SCHEMA_MISMATCH, path, provider, row_count=len(frame), checksum=checksum, warnings=(f"missing_columns:{','.join(missing)}",), history_root=_history_root(path))
    as_of_value = _latest_date(frame, required)
    if as_of_value is None:
        return _make_row(dataset, DataHealthStatus.UNAVAILABLE, path, provider, row_count=len(frame), checksum=checksum, freshness="unknown", warnings=("as_of_unavailable",), history_root=_history_root(path))
    status = DataHealthStatus.HEALTHY if as_of_value >= as_of - timedelta(days=stale_after_days) else DataHealthStatus.STALE
    freshness = "fresh" if status is DataHealthStatus.HEALTHY else "stale"
    warnings = () if status is DataHealthStatus.HEALTHY else (f"as_of_older_than_{stale_after_days}_days",)
    return _make_row(dataset, status, path, provider, row_count=len(frame), checksum=checksum, as_of=as_of_value.isoformat(), freshness=freshness, warnings=warnings, history_root=_history_root(path))


def _inspect_macro(path: Path, as_of: date, stale_after_days: int) -> DataHealthRow:
    if not path.exists():
        return _make_row("macro", DataHealthStatus.MISSING, path, "macro", warnings=("store_missing",), history_root=_history_root(path))
    files = sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {".csv", ".parquet", ".pq", ".json", ".jsonl"})
    if not files:
        return _make_row("macro", DataHealthStatus.UNAVAILABLE, path, "macro", freshness="unknown", warnings=("macro_files_unavailable",), history_root=_history_root(path))
    inspected: list[tuple[Path, pd.DataFrame, date]] = []
    failures: list[DataHealthRow] = []
    for item in files:
        try:
            if item.suffix.lower() == ".csv":
                frame = pd.read_csv(item)
            elif item.suffix.lower() in {".json", ".jsonl"}:
                frame = pd.read_json(item, lines=item.suffix.lower() == ".jsonl")
            else:
                frame = pd.read_parquet(item)
        except Exception as exc:
            failures.append(_make_row("macro", DataHealthStatus.CORRUPT, item, "macro", checksum=_sha256(item), warnings=(f"read_failed:{type(exc).__name__}",), history_root=_history_root(item)))
            continue
        date_columns = tuple(column for column in ("date", "as_of_date", "published_at", "timestamp") if column in frame.columns)
        if not date_columns:
            failures.append(_make_row("macro", DataHealthStatus.SCHEMA_MISMATCH, item, "macro", row_count=len(frame), checksum=_sha256(item), warnings=("missing_columns:date",), history_root=_history_root(item)))
            continue
        dated = _latest_date(frame, date_columns)
        if dated is None:
            failures.append(_make_row("macro", DataHealthStatus.UNAVAILABLE, item, "macro", row_count=len(frame), checksum=_sha256(item), freshness="unknown", warnings=("as_of_unavailable",), history_root=_history_root(item)))
            continue
        inspected.append((item, frame, dated))
    if not inspected:
        return failures[0] if failures else _make_row("macro", DataHealthStatus.UNAVAILABLE, path, "macro", freshness="unknown", warnings=("as_of_unavailable",), history_root=_history_root(path))
    latest, frame, dated = max(inspected, key=lambda item: (item[2], item[0].name))
    status = DataHealthStatus.HEALTHY if dated >= as_of - timedelta(days=stale_after_days) else DataHealthStatus.STALE
    freshness = "fresh" if status is DataHealthStatus.HEALTHY else "stale"
    warnings = (() if status is DataHealthStatus.HEALTHY else (f"as_of_older_than_{stale_after_days}_days",)) + (f"latest_file:{latest.name}",)
    if failures:
        severity = {
            DataHealthStatus.UNAVAILABLE: 1,
            DataHealthStatus.SCHEMA_MISMATCH: 2,
            DataHealthStatus.CORRUPT: 3,
        }
        failure_status = max((failure.status for failure in failures), key=lambda item: severity.get(item, 0))
        warnings += tuple(f"invalid_file:{Path(failure.path).name}:{failure.status.value}" for failure in failures)
        return _make_row("macro", failure_status, latest, "macro", row_count=len(frame), checksum=_sha256(latest), as_of=dated.isoformat(), freshness="unavailable", warnings=warnings, history_root=_history_root(latest))
    return _make_row("macro", status, latest, "macro", row_count=len(frame), checksum=_sha256(latest), as_of=dated.isoformat(), freshness=freshness, warnings=warnings, history_root=_history_root(latest))


def _inspect_migrations(root: Path) -> DataHealthRow:
    path = root / "data" / ".migration_state.json"
    if not path.exists():
        return _make_row("migration_status", DataHealthStatus.MISSING, path, "migration", freshness="unknown", warnings=("migration_state_missing", "migration_markers_not_inferred"), history_root=root)
    checksum = _sha256(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _make_row("migration_status", DataHealthStatus.CORRUPT, path, "migration", checksum=checksum, warnings=(f"read_failed:{type(exc).__name__}",), history_root=root)
    applied = payload.get("applied") if isinstance(payload, dict) else None
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if not isinstance(applied, list) or not isinstance(version, int):
        return _make_row("migration_status", DataHealthStatus.SCHEMA_MISMATCH, path, "migration", checksum=checksum, warnings=("missing_columns:schema_version,applied",), history_root=root)
    expected_names = {migration.version: migration.name for migration in MIGRATIONS}
    expected = max(expected_names, default=0)
    applied_versions = sorted(
        int(item["version"])
        for item in applied
        if isinstance(item, dict) and isinstance(item.get("version"), int)
    )
    if len(applied_versions) != len(applied) or applied_versions != list(range(1, min(version, expected) + 1)):
        return _make_row("migration_status", DataHealthStatus.SCHEMA_MISMATCH, path, "migration", row_count=len(applied), checksum=checksum, warnings=("applied_versions_mismatch",), history_root=root)
    if any(item.get("name") != expected_names.get(item["version"]) for item in applied):
        return _make_row("migration_status", DataHealthStatus.SCHEMA_MISMATCH, path, "migration", row_count=len(applied), checksum=checksum, warnings=("applied_names_mismatch",), history_root=root)
    parsed_applied_at = []
    for item in applied:
        value = item.get("applied_at")
        parsed = _parse_timezone_aware_timestamp(value)
        if parsed is None:
            return _make_row("migration_status", DataHealthStatus.UNAVAILABLE, path, "migration", row_count=len(applied), checksum=checksum, freshness="unknown", warnings=("applied_at_unavailable",), history_root=root)
        parsed_applied_at.append((str(value), parsed))
    as_of = max(parsed_applied_at, key=lambda item: (item[1], item[0]))[0] if parsed_applied_at else None
    if version > expected:
        status = DataHealthStatus.SCHEMA_MISMATCH
        warnings = (f"future_schema_version:{version}",)
    elif version < expected:
        status = DataHealthStatus.STALE
        warnings = (f"pending_migrations:{expected - version}",)
    else:
        status = DataHealthStatus.HEALTHY
        warnings = ()
    return _make_row("migration_status", status, path, "migration", row_count=len(applied), checksum=checksum, as_of=as_of, freshness="fresh" if status is DataHealthStatus.HEALTHY else "stale", warnings=warnings, history_root=root)


def _inspect_local_storage(root: Path) -> DataHealthRow:
    path = root / "data" / "storage" / "cockpit.sqlite3"
    if not path.is_file():
        return _make_row(
            "local_storage",
            DataHealthStatus.MISSING,
            path,
            "sqlite+duckdb",
            freshness="unknown",
            warnings=("transactional_store_missing", "analytical_catalog_unavailable"),
            history_root=root,
        )
    try:
        with HybridPlatform(root) as platform:
            summary = platform.summary()
        with BitemporalStore(root) as bitemporal:
            observations = bitemporal.observations(None)
        integrity = summary.integrity
        status = DataHealthStatus.HEALTHY if integrity.ok else DataHealthStatus.CORRUPT
        warnings = (
            f"schema_version:{summary.schema_version}",
            f"migrations:{','.join(map(str, summary.migration_versions)) or 'none'}",
            f"transactional_bytes:{summary.transactional_bytes}",
            f"analytics_bytes:{summary.analytics_bytes}",
            f"published_generations:{summary.published_generations}",
            f"last_compaction:{summary.last_compaction or 'never'}",
            f"integrity:{integrity.sqlite_integrity}",
            f"bitemporal_observations:{len(observations)}",
            f"bitemporal_retractions:{sum(row.status == 'retracted' for row in observations)}",
        ) + integrity.errors
        return _make_row(
            "local_storage",
            status,
            path,
            "sqlite+duckdb",
            row_count=summary.transactional_rows,
            checksum=_sha256(path),
            as_of=summary.last_compaction,
            freshness="fresh" if status is DataHealthStatus.HEALTHY else "unavailable",
            warnings=warnings,
            history_root=root,
        )
    except Exception as exc:
        return _make_row(
            "local_storage",
            DataHealthStatus.CORRUPT,
            path,
            "sqlite+duckdb",
            checksum=_sha256(path),
            warnings=(f"storage_inspection_failed:{type(exc).__name__}",),
            history_root=root,
        )


def _make_row(
    dataset: str,
    status: DataHealthStatus,
    path: Path,
    provider: str | None,
    *,
    row_count: int = 0,
    checksum: str | None = None,
    as_of: str | None = None,
    freshness: str = "unavailable",
    warnings: Iterable[str] = (),
    history_root: Path | None = None,
    last_success: str | None = None,
    last_failure: str | None = None,
) -> DataHealthRow:
    warning_values = list(warnings)
    if last_success is None and last_failure is None and history_root is not None:
        last_success, last_failure = _history_provenance(history_root, path)
        if last_success is None and last_failure is None:
            warning_values.append("history_unavailable")
    return DataHealthRow(
        dataset=dataset,
        status=status,
        path=str(path),
        row_count=int(row_count),
        checksum=checksum,
        as_of=as_of,
        freshness=freshness,
        provider=provider,
        last_success=last_success,
        last_failure=last_failure,
        warnings=tuple(dict.fromkeys(warning_values)),
        links=_links_for(dataset),
    )


def _links_for(_dataset: str) -> tuple[DataHealthLink, ...]:
    """Expose stable local actions for the related evidence and recovery views."""

    return (
        DataHealthLink("Provider status", "/providers"),
        DataHealthLink("Filings", "/filings"),
        DataHealthLink("ETF", "/etf"),
        DataHealthLink("Errors", "/errors"),
    )


def _history_root(path: Path) -> Path:
    parts = path.parts
    try:
        index = next(index for index, part in enumerate(parts) if part.lower() == "data")
    except StopIteration:
        return path.parent
    return Path(*parts[:index]) if index else Path(path.anchor or ".")


def _history_provenance(root: Path, target: Path) -> tuple[str | None, str | None]:
    events: list[dict[str, object]] = []
    for candidate in (root / "logs" / "session.jsonl", root / "logs" / "workflow.jsonl", root / "logs" / "activity.jsonl"):
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    payload = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    events.append(payload)
        except OSError:
            continue
    successes: list[str] = []
    failures: list[str] = []
    for event in events:
        if not _event_matches_path(event, root, target):
            continue
        timestamp = _event_timestamp(event)
        if not timestamp:
            continue
        status = str(event.get("status") or "").strip().lower()
        event_type = str(event.get("event_type") or event.get("event") or "").strip().lower()
        if status in {"failed", "failure", "error"} or "fail" in event_type or "error" in event_type:
            failures.append(timestamp)
        elif status in {"success", "ok", "complete", "completed"} or "complete" in event_type or event_type.endswith("_finish"):
            successes.append(timestamp)
    return (_latest_timestamp(successes), _latest_timestamp(failures))


def _event_matches_path(event: dict[str, object], root: Path, target: Path) -> bool:
    paths: list[object] = []
    for key in ("file_paths", "output_paths", "paths"):
        value = event.get(key)
        if isinstance(value, (list, tuple)):
            paths.extend(value)
        elif value:
            paths.append(value)
    output_summary = event.get("output_summary")
    if isinstance(output_summary, dict):
        for key in ("file_paths", "output_paths", "path"):
            value = output_summary.get(key)
            if isinstance(value, (list, tuple)):
                paths.extend(value)
            elif value:
                paths.append(value)
    target_text = _normalise_path(target)
    for value in paths:
        candidate = Path(str(value))
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate_text = _normalise_path(candidate)
        if candidate_text == target_text or candidate_text.startswith(target_text.rstrip("\\/") + "\\"):
            return True
    return False


def _normalise_path(path: Path) -> str:
    try:
        return str(path.resolve()).replace("/", "\\").rstrip("\\").lower()
    except OSError:
        return str(path).replace("/", "\\").rstrip("\\").lower()


def _event_timestamp(event: dict[str, object]) -> str | None:
    for key in ("timestamp_local", "timestamp_utc", "finished_at", "timestamp"):
        value = event.get(key)
        if value:
            return str(value)
    return None


def _latest_timestamp(values: Iterable[str]) -> str | None:
    candidates = tuple(str(value) for value in values if value)
    if not candidates:
        return None
    parsed = tuple((value, _parse_timestamp(value)) for value in candidates)
    valid = tuple(item for item in parsed if item[1] is not None)
    if valid:
        return max(valid, key=lambda item: (item[1], item[0]))[0]
    return max(candidates)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_timezone_aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


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
