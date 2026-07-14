# Wave 5 Task 20 - Import/Export, Backup/Restore, Charts and Accessible Tables

## Objective

Implement the approved Task 20 contract for `ISSUE-0036`, `ISSUE-0042`,
`ISSUE-0044` and `ISSUE-0041` on branch `wave5/task20-import-export`, based on
`a9e3469`. Existing code is a foundation, not proof of completion. Extend it
without replacing atomic I/O, revision-protected stores, evidence contracts,
the current Flet shell or safety boundaries.

## Binding requirements

- `execution_allowed` remains `false`; no broker execution, credential storage
  or autonomous portfolio action may be introduced.
- Imports must preview and validate before any write. Support the approved
  broker, candidate, manual notes, ETF holdings and news CSV/RSS-list shapes;
  reject malformed or empty inputs with explicit errors and preserve the
  previous clean state on failure.
- Exports must cover scoreboard, audit packet, watchlist, paper-trade journal,
  decision journal and plan/issues snapshot plus major analytical tables. Show
  the actual destination path and controlled failure state.
- Use stable public interfaces:
  `validate_import(import_type, path) -> ImportPreview`;
  `commit_import(preview_id) -> ImportCommitResult`;
  `export_table(table_id, frame, destination) -> ExportResult`;
  `create_backup(paths, destination) -> BackupManifest`;
  `validate_restore(archive) -> RestorePreview`;
  `commit_restore(preview) -> RestoreResult`.
- Backup/restore must include data/config/version/changelog and a deterministic
  checksum manifest, exclude secrets/transient build and log caches unless
  explicitly selected, reject corrupt archives and zip traversal, validate all
  checksums before writes, and publish atomically so failed restore leaves the
  previous destination intact.
- Preserve compatibility with existing callers and schemas. Use atomic I/O
  and migration/recovery primitives already in the repository.
- Improve visible Import/Export and Settings surfaces with one clear primary
  action, explicit preview/commit/result states, path/error text, version,
  changelog, last rebuild timestamp and data root. Reuse the dark evidence
  cockpit tokens and existing controls; no decorative filler.
- Improve table/chart surfaces with semantic labels, search/sort where useful,
  keyboard-operable controls where Flet permits, text status independent of
  colour, responsive narrow layouts, price/history and backtest equity/
  drawdown evidence plus CSV exports.

## Owned files

Create or modify only the Task 20 seams unless a directly required route/test
update is necessary:

- `src/etf_cockpit/data/import_export.py`
- `src/etf_cockpit/data/backup_restore.py`
- `src/etf_cockpit/data/export_tables.py`
- `src/etf_cockpit/app/pages/import_export.py`
- `src/etf_cockpit/app/pages/settings.py`
- `src/etf_cockpit/app/components/tables.py`
- `src/etf_cockpit/app/components/charts.py`
- `src/etf_cockpit/app/pages/backtests.py`
- `src/etf_cockpit/app/pages/risk.py`
- `tests/test_import_export.py`
- `tests/test_backup_restore.py`
- `tests/test_accessible_tables.py`

## RED-GREEN-REFACTOR

1. Add focused observable tests before behavioural implementation for preview
   gating, all approved import types, export result/path/failure behaviour,
   checksum and traversal validation, failed-restore containment, and visible
   labels/accessible chart-table contracts. Run each focused test and record a
   genuine behavioural failure (not an import/syntax failure).
2. Implement the smallest coherent repository-consistent change. Do not test
   private call counts or duplicate implementation logic in tests.
3. Refactor only to preserve shared interfaces and remove duplication; rerun
   focused and affected regression suites.

## Verification required before review

- Focused Task 20 tests and affected existing import/export, backup, tables,
  charts, settings, backtest, risk, startup and UI acceptance tests.
- Scoped Ruff, compileall and `git diff --check`.
- Full `tests` suite if affordable; record pre-existing failures separately.
- Source smoke and applicable rendered/browser checks. If a gate cannot run,
  record the exact command, output and reason as pending rather than claiming
  closure.

## Review hand-off

Produce `.ai_worklog/task-20-report.md` with RED/GREEN/REFACTOR commands,
changed files, migration/compatibility notes, evidence paths, known pending
strict closure gates and `execution_allowed=false`. Parent will dispatch a
fresh independent reviewer; do not self-approve or spawn child agents.
