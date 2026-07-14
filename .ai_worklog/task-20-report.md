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

## Review fix pass

### RED

Added adversarial coverage for canonical broker/candidate routes, manual/news
normalisation, checksum-bound preview mutation, NaN/blank text, malformed RSS
URLs, content-level secret exclusion, unsupported payload schemas, functional
table callbacks and chart data descriptors. The initial run produced 14
expected assertion failures (the tests exercised the old incompatible paths and
missing safeguards, not collection or syntax errors).

### GREEN and refactor evidence

- Broker imports now call the canonical holdings validator and publish
  `data/portfolios/current_holdings.csv` atomically.
- Candidate imports publish a runtime-compatible
  `data/raw/trade_candidates/yahoo_trade_candidates_*.csv` with
  `instrument_id`/`yahoo_symbol` fields.
- Manual notes, canonical news and ETF holdings use their existing
  normalisers/persistence contracts, retaining provenance and forced
  `executable_authority=false`.
- Commit recomputes the preview frame checksum and rejects stale/mutated
  previews before writes. RSS/news text and URLs fail closed for NaN, blanks,
  malformed URLs and empty feeds.
- Backup scans payload contents for credential material, records excluded paths
  in `manifest.json`, validates known JSON/YAML schema versions, and retains
  traversal, duplicate, checksum and stale-preview checks.
- Import/export UI exposes all six approved categories and separates restore
  validation preview from explicit commit/cancel controls with destination and
  controlled status text.
- Chart descriptors expose series tuples; accessible tables expose deterministic
  search and sort callbacks.

### Fix-pass validation

```powershell
python -m pytest tests/test_import_export.py tests/test_backup_restore.py tests/test_accessible_tables.py -q
# 32 passed

python -m pytest tests/test_flet_startup.py tests/test_task18_ui.py tests/test_risk_analytics.py tests/test_import_export.py tests/test_backup_restore.py tests/test_accessible_tables.py -q
# 57 passed

python -m ruff check src/etf_cockpit/data/import_export.py src/etf_cockpit/data/ingest_broker.py src/etf_cockpit/data/backup_restore.py src/etf_cockpit/data/export_tables.py src/etf_cockpit/app/components/charts.py src/etf_cockpit/app/components/tables.py src/etf_cockpit/app/pages/import_export.py tests/test_import_export.py tests/test_backup_restore.py tests/test_accessible_tables.py
# All checks passed

python -m compileall -q src tests
git diff --check
```

## Final review correction pass

This pass adds the approved RSS feed-list evidence path without network calls,
explicit Boolean parsing and timezone-aware publication checks, approved
restore payload roots, and visible table callback refreshes. Backup selection
now references the repository's actual `pyproject.toml` version metadata and
`.ai_worklog/CHANGES.md`; Settings displays those same paths. Focused RED
tests cover feed-only commits, malformed/ambiguous news values, unapproved
restore entries, metadata archive names and Flet control update spies.

Validation is pending the parent worktree's available Python runtime; source
diff and `git diff --check` are available here.

## Final blocker follow-up (Wave5 review corrections)

The follow-up review corrections add fail-closed guards for mixed-parent ETF
holdings previews, news rows that omit a publication timestamp, and named
restore payload schemas outside the explicit `cockpit.v1` allow-list. The
Backtests strategy-results table now exposes a visible search field, live sort
callbacks and a truthful CSV export; history/equity descriptors render recent
value rows rather than only row-count text. Risk evidence exports now report
unavailable canonical sources without writing placeholders. Stale
`import-export.backup-restore` metadata was removed and import/restore
commit/cancel controls were registered in `configs/ui_acceptance.yaml`.
Settings now records the `ISSUE-0044` packaged-app update workflow and checksum
plan.

The focused Python pytest command was attempted with the repository `.venv`
but Windows returned `Access denied` when creating the interpreter process
from this sandbox; Ruff and compileall use the same unavailable interpreter.
Source diff inspection and `git diff --check` remain available; parent review
must rerun the focused pytest, Ruff and compileall gates before integration.

## Final blocker follow-up

Fresh review identified additional acceptance gaps. The final follow-up now:

- commits the checksum-bound preview frame for broker imports without rereading
  a mutable source path;
- merges ETF holdings by instrument, retaining existing instruments;
- rejects RSS feed URL-list shapes during preview unless parsed item fields are
  present;
- rejects unsupported non-numeric known schema versions;
- reads the live decision journal under `data/` and the canonical derived
  scoreboard for watchlist exports; and
- connects the history chart and accessible searchable/sortable table helpers
  to the Backtests page.

Final scoped validation:

```powershell
python -m pytest tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_import_export.py tests/test_backup_restore.py tests/test_accessible_tables.py tests/test_flet_startup.py tests/test_task18_ui.py tests/test_risk_analytics.py -q
# 68 passed

python -m ruff check src/etf_cockpit/data/import_export.py src/etf_cockpit/data/ingest_broker.py src/etf_cockpit/data/backup_restore.py src/etf_cockpit/app/pages/import_export.py src/etf_cockpit/app/pages/backtests.py tests/test_import_export.py tests/test_backup_restore.py tests/test_accessible_tables.py
python -m compileall -q src tests
git diff --check
```

The full repository suite, packaged build and browser/computer-use visual
checks remain outside this fix pass and were not run here. No issue closure
state was changed.

## Final safety follow-up

Fresh review blockers were addressed without changing authority boundaries:

- RSS feed evidence filenames now use deterministic zero-based ordinals and
  import previews reset index labels before checksum binding; row ordering
  remains checksum-bound.
- Canonical news ledgers are read strictly before raw or clean publication.
  Corrupt parquet or unsupported ledger schema raises and leaves the existing
  bytes and output directory unchanged for both parsed-news and feed-list
  imports.
- Accessible table view updates refresh both the data table and the textual
  status control when either exposes an update callback.

Adversarial tests cover malicious Parquet indices, corrupt parsed-news and RSS
ledgers, and status-control callback refresh. Python/Ruff were unavailable in
this sandbox (`python` and `ruff` not found); `git diff --check` passed. Parent
worktree should run the focused Task 20 tests and scoped Ruff/compileall gates.

## Button-contract follow-up

The post-fix inventory initially reported five uncovered source patterns:
`backtests.export-equity-drawdown`, `import-export.create-backup`,
`import-export.export-*`, `import-export.restore-validate` and
`risk.export-limits`. The export controls are now explicit keyed controls (one
per approved category), and `configs/ui_acceptance.yaml` declares each control
with its route, callback and controlled success/error signals.

Validation:

```powershell
python -m pytest tests/test_button_contracts.py tests/test_accessibility_contracts.py -q
# 6 passed

python -m pytest tests/test_import_export.py tests/test_backup_restore.py tests/test_accessible_tables.py tests/test_flet_startup.py tests/test_task18_ui.py tests/test_risk_analytics.py -q
# 57 passed

python -m ruff check src/etf_cockpit/app/pages/import_export.py
python -m compileall -q src tests
git diff --check
```

## Final reviewer blocker correction - news provenance

### RED

Added focused regression coverage for a parsed news row with a
timezone-aware publication timestamp but no ingestion or availability fields,
and for an explicit `available_at_decision_time=true` claim without an
ingestion timestamp.  The available Python command paths were attempted, but
this sandbox could not start Python (`python` is not installed on PATH and the
repository `.venv` executable returned Windows `Access denied`).

### GREEN/refactor

- News imports no longer substitute `published_at` for missing `ingested_at`;
  the canonical news validator therefore persists an empty ingestion value and
  marks the row unavailable/backtest-ineligible.
- Missing or unparseable availability defaults to `False`; explicit string
  `"false"` remains false.  Explicit positive availability now requires an
  ingestion column and fails closed when it is absent, preserving the
  context-only RSS/feed-list contract.
- Accessible-table search treats user text literally (`regex=False`), so
  punctuation cannot raise a regex error; callback-driven filtering refreshes
  visible rows and the text status through `control.update()`.

### Pending verification

Parent worktree should rerun the two focused news tests, the full Task 20
focused bundle, Ruff, compileall and `git diff --check` before integration.

## Final reviewer blocker correction - timestamp and canonical schema gates

### RED

Added focused tests for parsed-news timestamp metadata propagation and
fail-closed validation (`timestamp_confidence=ambiguous` and
`timezone_name=unknown`), explicit availability claims with ambiguous
metadata, readable malformed canonical ledgers for both parsed-news and RSS
imports, and the `BackupManifest.execution_allowed` authority field. The
tests were not runnable in this sandbox because no Python interpreter could
be started; the parent worktree must run them with its available runtime.

### GREEN/refactor

- `_news_items` now preserves explicit `timestamp_confidence` and
  `timezone_name`/`timezone` values so `validate_news_item` rejects ambiguous
  or unknown metadata instead of applying exact/UTC defaults.
- `_read_clean_strict` now requires the canonical point-in-time,
  provenance and authority columns (with compatibility aliases) before any
  parsed-news or RSS writes; malformed readable ledgers fail closed.
- `BackupManifest` reports an explicit `execution_allowed=False` field while
  preserving `RestoreResult` and existing authority boundaries.

Parent worktree should rerun the focused Task 20 bundle, scoped Ruff,
compileall and `git diff --check` before integration.

## Final canonical news-ledger correction

The news import destination now uses the existing `NEWS_CLEAN_PATH` contract
(`data/clean/news_context.parquet`) relative to the supplied import root. No
`news.parquet` alias is created. Parsed-news and RSS feed-list commits
therefore continue through the strict canonical-ledger read and atomic
publication path, preserving context-only and `executable_authority=false`
fields. The regression suite now checks the destination against
`NEWS_CLEAN_PATH`, reads it through `load_news_items`, and targets the same
canonical path for corrupt-ledger containment tests.

Validation in this worktree:

```text
git diff --check  # passed
python -m pytest tests/test_import_export.py -q  # unavailable: no Python executable on PATH
python -m ruff check src/etf_cockpit/data/import_export.py tests/test_import_export.py  # unavailable: no Python/Ruff executable on PATH
python -m compileall -q src tests  # unavailable: no Python executable on PATH
```

The parent worktree must rerun the focused pytest, Ruff and compileall gates
with its available runtime before integration. `execution_allowed=false`
remains unchanged.
