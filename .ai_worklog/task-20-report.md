# Wave 5 Task 20 implementation report

## Task completed

Implemented the bounded local import/export, backup/restore, chart/table and
metadata UI seams for `ISSUE-0036`, `ISSUE-0042`, `ISSUE-0044` and
`ISSUE-0041`. `execution_allowed=false` remains explicit on import, export,
backup and restore results; no broker execution or credential export was added.

## RED

Command:

```powershell
python -m pytest tests\test_import_export.py tests\test_backup_restore.py tests\test_accessible_tables.py -q
```

Result: 10 intended behavioural failures. The failures covered missing
approved import commit/result contracts, export result/path/failure reporting,
secret/transient backup filtering, invalid-restore containment and accessible
table/chart descriptors. The failures were assertions/expected API behaviour,
not collection or syntax errors.

## GREEN

Command:

```powershell
python -m pytest tests\test_import_export.py tests\test_backup_restore.py tests\test_accessible_tables.py -q
```

Result: 16 passed.

Command:

```powershell
python -m pytest tests\test_flet_startup.py tests\test_task18_ui.py tests\test_risk_analytics.py tests\test_import_export.py tests\test_backup_restore.py tests\test_accessible_tables.py -q
```

Result: 41 passed.

## REFACTOR

Added stable aliases and canonical destination mapping for existing import
callers, centralised frame validation/checksums, made export failures a typed
controlled result, made restore revalidate a preview before atomic publication,
and kept Flet controls text-first with explicit labels and local paths.

## Changed files

- `.ai_worklog/task-20-report.md`
- `src/etf_cockpit/data/import_export.py`
- `src/etf_cockpit/data/export_tables.py`
- `src/etf_cockpit/data/backup_restore.py`
- `src/etf_cockpit/app/pages/import_export.py`
- `src/etf_cockpit/app/pages/settings.py`
- `src/etf_cockpit/app/components/tables.py`
- `src/etf_cockpit/app/components/charts.py`
- `src/etf_cockpit/app/pages/backtests.py`
- `src/etf_cockpit/app/pages/risk.py`
- `tests/test_import_export.py`
- `tests/test_backup_restore.py`
- `tests/test_accessible_tables.py`

## Compatibility and migration notes

Existing `ImportService.register/commit` and `validate_import` calls remain
available. The public `commit_import(preview_id)` uses the validated preview
registry and rejects unknown/invalid IDs. `export_table` now returns an
`ExportResult` with path/status/error metadata and keeps path-like access via
`path`/`__fspath__`/`exists`. Backup archives use schema version 1 manifests;
restore rejects traversal, duplicate/unlisted entries, corrupt archives and
checksum changes before writes. Secrets and transient cache/log/build paths
are excluded by default; `include_transient=True` is an explicit opt-in.

## Verification and pending strict gates

- `python -m compileall -q src tests` passed.
- Scoped Ruff and `git diff --check` passed.
- No execution-authority additions found in the changed seams.
- Full repository suite, packaged build, browser/computer-use file-picker and
  responsive screenshot gates were not run in this worktree and remain
  pending for the wave review/release gate.
- Two pre-existing Task 17 UI failures were observed when running the wider
  mixed bundle (`test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table`,
  `test_dashboard_digest_surfaces_deterministic_run_changes`); they are outside
  Task 20 ownership and unrelated to the changed files.
