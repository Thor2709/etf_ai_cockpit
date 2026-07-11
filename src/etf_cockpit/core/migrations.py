from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from etf_cockpit.core.atomic_io import (
    BackupManifest,
    atomic_write_json,
    backup_paths,
    restore_backup_manifest,
)
from etf_cockpit.core.paths import ROOT


@dataclass(frozen=True)
class MigrationContext:
    root: Path
    backup_root: Path
    managed_paths: tuple[Path, ...] = ()

    @property
    def state_path(self) -> Path:
        return self.root / "data" / ".migration_state.json"

    @property
    def metadata_root(self) -> Path:
        return self.root / "data" / ".schema_versions"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[MigrationContext], None]


@dataclass(frozen=True)
class MigrationReport:
    applied_versions: tuple[int, ...]
    current_version: int
    backup_manifest: BackupManifest | None
    state_path: Path


def _write_schema_marker(context: MigrationContext, version: int, name: str) -> None:
    atomic_write_json(
        context.metadata_root / f"{name}.json",
        {
            "schema_version": version,
            "name": name,
            "migration_policy": "preserve existing values; absent values remain unavailable",
        },
    )


def migrate_provider_identity(context: MigrationContext) -> None:
    _write_schema_marker(context, 1, "provider_identity_evidence_v1")


def migrate_official_documents(context: MigrationContext) -> None:
    _write_schema_marker(context, 2, "official_documents_v1")


def migrate_universe(context: MigrationContext) -> None:
    _write_schema_marker(context, 3, "universe_watchlists_v1")


def migrate_history(context: MigrationContext) -> None:
    _write_schema_marker(context, 4, "history_changes_v1")


MIGRATIONS = (
    Migration(1, "provider_identity_evidence_v1", migrate_provider_identity),
    Migration(2, "official_documents_v1", migrate_official_documents),
    Migration(3, "universe_watchlists_v1", migrate_universe),
    Migration(4, "history_changes_v1", migrate_history),
)


def _load_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"schema_version": 0, "applied": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("applied"), list):
        raise ValueError("migration state applied field must be a list")
    return payload


def run_migrations(context: MigrationContext) -> MigrationReport:
    from etf_cockpit.operations.recovery import recover_incomplete_transactions

    recovery_results = recover_incomplete_transactions(context.root)
    blocked = [result for result in recovery_results if result.state == "recovery_required"]
    if blocked:
        reasons = "; ".join(result.reason for result in blocked)
        raise OSError(f"migration blocked by incomplete atomic transaction: {reasons}")
    state = _load_state(context.state_path)
    current_version = int(state.get("schema_version", 0))
    pending = tuple(migration for migration in MIGRATIONS if migration.version > current_version)
    if not pending:
        return MigrationReport((), current_version, None, context.state_path)

    migration_paths = tuple(context.metadata_root / f"{migration.name}.json" for migration in pending)
    protected_paths = tuple(dict.fromkeys((*context.managed_paths, context.state_path, *migration_paths)))
    existing_paths = tuple(path for path in protected_paths if path.is_file())
    absent_paths = tuple(path for path in protected_paths if not path.exists())
    backup = backup_paths(existing_paths, context.backup_root)
    applied = list(state["applied"])
    applied_versions: list[int] = []
    try:
        for migration in pending:
            migration.apply(context)
            applied.append(
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            applied_versions.append(migration.version)
        atomic_write_json(
            context.state_path,
            {
                "schema_version": applied_versions[-1],
                "applied": applied,
                "backup_manifest": str(backup.manifest_path),
            },
        )
    except Exception as original_error:
        recovery_errors: list[str] = []
        try:
            restore_backup_manifest(backup)
        except Exception as recovery_error:
            recovery_errors.append(f"backup restore: {recovery_error}")
        for path in absent_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as recovery_error:
                recovery_errors.append(f"partial file cleanup {path}: {recovery_error}")
        if recovery_errors:
            raise OSError(
                f"migration failed ({original_error}); recovery also failed: {'; '.join(recovery_errors)}"
            ) from original_error
        raise
    return MigrationReport(
        tuple(applied_versions),
        applied_versions[-1],
        backup,
        context.state_path,
    )


def default_migration_context(root: Path = ROOT) -> MigrationContext:
    dual_store_stems = (
        root / "data" / "clean" / "instrument_identity",
        root / "data" / "clean" / "source_conflicts",
        root / "data" / "clean" / "filings_statements",
        root / "data" / "clean" / "etf_disclosures",
        root / "data" / "clean" / "news_context",
        root / "data" / "derived" / "evidence_ledger",
        root / "data" / "derived" / "score_history",
        root / "data" / "derived" / "score_metric_history",
        root / "data" / "derived" / "score_components",
        root / "data" / "derived" / "feature_drivers",
    )
    return MigrationContext(
        root=root,
        backup_root=root / "backups" / "schema_migrations",
        managed_paths=tuple(
            [
            root / "configs" / "universe.yaml",
            root / "configs" / "data_providers.yaml",
            ]
            + [stem.with_suffix(suffix) for stem in dual_store_stems for suffix in (".parquet", ".csv")]
        ),
    )


def run_startup_migrations() -> MigrationReport:
    return run_migrations(default_migration_context())
