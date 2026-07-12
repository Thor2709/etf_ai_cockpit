# Wave 4 Task 10 implementation report

Date: 2026-07-13
Branch: `wave4/task10-data-health`
Owner: `ISSUE-0035` / Data Health Centre

## Task completed

Implemented the approved Data Health hardening slice. The existing public
`build_data_health(config, project_root, ...)` API remains compatible. The
inventory now includes an explicit `migration_status` row, persisted
operational provenance, content-derived macro freshness, deterministic status
classification and stable local action links. The Data Health page now has
status, dataset and provider filters and exports only the visible rows.

`execution_allowed` and score/model/portfolio/execution behaviour were not
changed.

## Files and symbols examined

- `src/etf_cockpit/data/health.py`: `DataHealthStatus`, `DataHealthRow`,
  `DataHealthReport`, `build_data_health`, export and inspection helpers.
- `src/etf_cockpit/app/pages/data_health.py`: page inventory, Flet shell,
  export control and responsive evidence rows.
- `src/etf_cockpit/app/router.py`: confirmed `/data-health`, `/providers`,
  `/filings`, `/etf` and `/errors` are registered; no router edit required.
- `src/etf_cockpit/app/pages/dashboard.py`: confirmed existing Data Health
  summary card; no dashboard edit required.
- `src/etf_cockpit/core/migrations.py`, `core/session_log.py`,
  `operations/event_store.py` and related Provider/Filings/Error pages for
  persisted history and route conventions.
- `tests/test_data_health.py`: existing health, corruption/export and UI
  coverage plus the new regression cases below.

## Findings or changes

- Added `DataHealthLink` and `DataHealthRow.links` (`actions` compatibility
  alias) with local Provider, Filings, ETF and Errors routes.
- Added `DataHealthReport.migration_status` and deterministic migration-state
  inspection. Missing, corrupt, schema-mismatched, stale and future migration
  state are explicit; schema marker files are never treated as applied state.
- Replaced inspection-time success/failure values with matching persisted
  history from local session/workflow/activity JSONL. Missing history returns
  `None` plus `history_unavailable`.
- Macro inventory reads dated CSV, Parquet and JSON files, validates date
  columns/values and classifies stale, missing, corrupt, schema-mismatch and
  unavailable content from the data itself.
- Added case-insensitive `filter_data_health_rows` for status/dataset/provider
  filters. Export preserves the existing health CSV header while links remain
  stable UI actions.
- Added regression tests for migration status and non-inference, persisted
  timestamp provenance, macro ageing/schema/corruption, filters and UI links.

## Evidence

RED was observed before implementation:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py
3 passed, 5 failed
```

The five genuine failures were the missing migration row, inspection-time
provenance, macro always reported healthy, and missing filter API (the macro
fixture was then corrected to use an invalid Parquet payload for the corrupt
case).

The fresh review fix pass added a valid macro CSV beside a corrupt Parquet
file. Its RED result was one failure because the valid sibling was reported
healthy and the corrupt file was reduced to `ignored_files:1`. The minimal fix
promotes the highest-severity invalid sibling to the macro row status and adds
an `invalid_file:<name>:<status>` warning for each invalid sibling.

Fix-pass RED/GREEN commands:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py::test_macro_invalid_sibling_remains_visible_with_valid_file
1 failed (expected healthy-vs-corrupt masking)

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py
10 passed
```

The final provenance fix pass added offset-aware ordering and migration
history tests. RED was two failures: lexical ordering selected the earlier
instant with the larger local hour, and migration `last_success` incorrectly
reused its applied `as_of` marker. The fix compares parsed UTC instants while
returning the original persisted timestamp, and lets migration history load
independently from its applied marker.

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py::test_health_provenance_orders_timestamp_offsets_by_instant tests/test_data_health.py::test_migration_as_of_is_distinct_from_persisted_success_failure_history
2 failed (expected provenance defects)

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py
12 passed
```

GREEN focused result:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py
12 passed
```

Affected UI/startup/navigation result:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py tests/test_flet_startup.py tests/test_e2e_workflow.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/test_feature_registry.py
36 passed (one existing gluonts warning)
```

## Commands or tests run

- Focused RED/GREEN and affected regression commands above.
- `...python.exe -m compileall -q src tests` - pass.
- Scoped `...python.exe -m ruff check src/etf_cockpit/data/health.py src/etf_cockpit/app/pages/data_health.py tests/test_data_health.py --no-cache` - pass.
- `...python.exe scripts/run_app.py --smoke` - `snapshot_ok as_of=2026-07-13 signals=16 backtests=5`.
- Full `...python.exe -m pytest -q` - exit 0 at 100% after the bounded atomic
  staging fix; warnings only and no Data Health failure observed.

Skipped checks: no browser screenshot/package build or external write was run
in this implementer slice. Router/dashboard were inspected but unchanged.

## Remaining uncertainty and risk

Browser and packaged UI evidence, export checksum capture and final
issue-closure matrix gates remain for the parent integration/review phase.
Generated schema-marker line-ending churn from local smoke/startup runs is
intentionally unstaged and excluded from this commit.

## Recommended next action

Review this focused diff and run the parent Wave 4 package/browser evidence
gates. Keep `execution_allowed=false` and do not close `ISSUE-0035` until those
independent checks pass.

Commit hashes: `d1711628071d2b0959e205792f2fb6d0b87c8f34` (implementation),
`85b469e` (export schema), `87559ed` (macro sibling visibility fix),
`ea03216` (timestamp ordering and migration history fix pass).

## Final review-fix cycle: migration-state truthfulness

Independent review found two Important defects: migration `as_of` was still
selected lexically rather than by UTC instant, and records with wrong names or
missing timezone-aware `applied_at` values could be reported healthy.

RED (recorded during this fix pass):

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py::test_migration_as_of_orders_mixed_offsets_by_utc_instant tests/test_data_health.py::test_migration_wrong_name_is_a_schema_mismatch tests/test_data_health.py::test_migration_missing_applied_at_is_unavailable
3 failed (expected migration timestamp/name/provenance defects)
```

The minimal fix parses migration timestamps as timezone-aware UTC instants,
preserves the original selected string, validates each persisted migration
name against the expected version/name pair and fails closed when
`applied_at` is missing, malformed or timezone-naive.

GREEN (recorded during this fix pass):

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_data_health.py::test_migration_as_of_orders_mixed_offsets_by_utc_instant tests/test_data_health.py::test_migration_wrong_name_is_a_schema_mismatch tests/test_data_health.py::test_migration_missing_applied_at_is_unavailable
3 passed
```

The corresponding full Data Health suite now has 16 passed and the affected
six-file UI/start-up/navigation bundle has 40 passed with one existing
GluonTS warning. The bounded atomic staging fix then allowed the authoritative
suite to complete successfully; this closure evidence is refreshed on top of
that fix.

## Task 10 closure checklist

| Gate | State | Evidence or reason |
|---|---|---|
| Required Data Health functionality | passed | `src/etf_cockpit/data/health.py`, `src/etf_cockpit/app/pages/data_health.py` |
| Acceptance criteria and migration truthfulness | passed | focused 16-test suite, including mixed-offset/name/missing-timestamp and failed-completion provenance regressions |
| Persistence/provenance and export schema | passed | persisted history tests and 12-row CSV export checksum |
| Source and affected regression tests | passed | 16 focused; 40 affected |
| Compile and scoped lint | passed | compileall exit 0; Ruff all checks passed |
| Source smoke | passed | `snapshot_ok as_of=2026-07-13 signals=16 backtests=5` |
| Full authoritative suite | passed | exit 0 at 100%; warnings only and no Data Health failure |
| Package build | passed | `cmd /c scripts\\build_windows.bat` exit 0; portable package recreated; the rebuild venv did not contain PyInstaller, so the existing native output was retained |
| Package smoke | passed | `scripts/smoke_app.py --mode native --port 8601` and `--mode portable-native --port 8600` both returned `smoke_ok`; local ignored candidate fixtures supplied the deterministic AURG/Sparebanken rows |
| Direct packaged launch/readiness | passed | fresh native and portable-native smoke returned HTTP-ready URLs on ports 8601 and 8600 |
| Browser visual source/package parity | passed | source desktop/mobile and packaged screenshots; console only `Flutter app loaded` |
| Keyboard/focus/semantic accessibility | passed | accessibility semantics enabled in the running source app; Data Health exposed labelled navigation, filters, export, status and action buttons; Tab moved focus through the semantic tree |
| Audit/manifest/issue synchronisation | pending | local issue transition is recorded; GitHub issue read-back is the remaining synchronisation action |
| Independent task review | passed for implementation | final fresh re-review at `8ceafce`: SPEC PASS, CODE PASS; implementation ready, issue closure still pending integration/synchronisation; report `.ai_worklog/task10-final-rereview.md` |
| Closure evaluator | passed | `scripts/closure_status.py` reports `ISSUE-0035 ready=true` with checksum-verified source/tests/UI/export/build/browser evidence |
| Issue transition | passed locally | canonical record moved to `issues/closed.md` after merge; GitHub issue closure and reconciliation remain pending |

The task must not be represented as fully closed while any blocked or pending
gate remains. `execution_allowed=false` and all approved authority boundaries
are unchanged.

## Final verification after provenance fix and independent re-review

Fresh commands on commit `8ceafce`:

```text
& 'C:\\Users\\thor2\\Desktop\\Trading App\\etf_ai_cockpit\\.venv\\Scripts\\python.exe' -m pytest -q tests/test_data_health.py tests/test_atomic_io.py tests/operations/test_recovery.py tests/operations/test_transactions.py
first attempt: one intermittent Windows PermissionError in the existing
test_group_reader_cannot_observe_mixed_generation_during_activation; rerun:
72 passed at 100%.

& '.venv\\Scripts\\python.exe' scripts/smoke_app.py --mode source --port 8597 --timeout 60
smoke_ok mode=source url=http://127.0.0.1:8597/

cmd /c scripts\\build_windows.bat
exit 0; portable folder created; PyInstaller unavailable in the isolated build venv

& '.venv\\Scripts\\python.exe' scripts/smoke_app.py --mode portable-native --port 8600 --timeout 60
smoke_ok mode=portable-native url=http://127.0.0.1:8600/

& '.venv\\Scripts\\python.exe' scripts/smoke_app.py --mode native --port 8601 --timeout 60
smoke_ok mode=native url=http://127.0.0.1:8601/
```

The first affected-bundle flake is recorded as a pre-existing
concurrency-test instability; the immediate rerun passed. No Data Health
failure occurred and no authority boundary changed.

## Post-merge integration and verification

PR 180 (`https://github.com/Thor2709/etf_ai_cockpit/pull/180`) merged into
`main` at `3eab7a414a54c74553b09ebc4085902af0ffc33e`. The Task 10 worktree was
removed after the clean merge; generated schema-marker churn was preserved
outside Git.

Fresh post-merge checks on `main`:

```text
pytest -q tests/test_data_health.py tests/test_atomic_io.py tests/operations/test_recovery.py tests/operations/test_transactions.py
72 passed

pytest -q
exit 0 at 100%; warnings only

compileall -q src tests
exit 0

ruff check src/etf_cockpit/data/health.py src/etf_cockpit/app/pages/data_health.py src/etf_cockpit/core/atomic_io.py tests/test_data_health.py tests/test_atomic_io.py --no-cache
All checks passed

scripts/smoke_app.py --mode source --port 8610 --timeout 60
smoke_ok mode=source url=http://127.0.0.1:8610/

scripts/smoke_app.py --mode native --port 8611 --timeout 60
smoke_ok mode=native url=http://127.0.0.1:8611/

scripts/smoke_app.py --mode portable-native --port 8612 --timeout 60
smoke_ok mode=portable-native url=http://127.0.0.1:8612/
```

The first post-merge full-suite attempt failed only because the nested Task 10
worktree was still scanned by the production package-inventory boundary check;
removing that merged worktree made the targeted package-inventory test and the
fresh full suite pass. This was repository workspace state, not a product or
authority defect.

## Post-closure fix: bounded grouped staging on Windows

The remaining full-suite failure was reproduced in this worktree on the
Windows path used by pytest. A 128-character source journal ID is stored under
its 64-character SHA-256 basename; `_stage_request` then passed that basename
in full as the temporary-file prefix. `NamedTemporaryFile` raised
`FileNotFoundError` while constructing the resulting overlong path.

RED evidence:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_decision_journal.py::test_journal_supersede_bounds_long_source_id
1 failed: FileNotFoundError in core/atomic_io.py::_stage_request NamedTemporaryFile

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_atomic_io.py::test_group_write_bounds_stage_name_for_long_destination
1 failed: FileNotFoundError in core/atomic_io.py::_stage_request NamedTemporaryFile
```

The regression `test_group_write_bounds_stage_name_for_long_destination`
stages and publishes a 64-character hashed destination and asserts that no
`.group.tmp` file remains. The minimal fix adds `_stage_prefix`, using the
resolved destination path's first 32 SHA-256 hex characters in a bounded
`.atomic-<digest>.` prefix. Recovery path validation accepts this new shape and
the existing destination-name shape, retaining destination-parent containment,
suffix checks and compatibility with already durable journals.

GREEN and regression evidence:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_atomic_io.py::test_group_write_bounds_stage_name_for_long_destination tests/test_decision_journal.py::test_journal_supersede_bounds_long_source_id
2 passed

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests/operations/test_recovery.py tests/operations/test_transactions.py tests/test_decision_journal.py tests/test_atomic_io.py -q
88 passed

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests/test_decision_journal.py tests/test_atomic_io.py -q -rA
25 passed
```

Authoritative validation after the fix:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q
exit 0; progress reached [100%]; warnings only (GluonTS, pandas FutureWarning and deprecated trade-proposal helper)

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src tests
exit 0

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src/etf_cockpit/core/atomic_io.py tests/test_atomic_io.py --no-cache
All checks passed; exit 0
```

Only `src/etf_cockpit/core/atomic_io.py`, `tests/test_atomic_io.py` and this
report are part of this fix. Existing schema-marker working-tree churn remains
unstaged and is not included. `execution_allowed=false` is unchanged.

## Status-precedence closure fix

### Task completed

Fixed `_history_provenance` so explicit failure statuses take precedence over
completion-looking event types. Added a regression proving a persisted
`status=failed` completion event contributes only to `last_failure`.

### Files and symbols examined

- `src/etf_cockpit/data/health.py`: `_history_provenance` event classification.
- `tests/test_data_health.py`: persisted provenance regression coverage.
- Task10 closure records listed below; generated schema markers and local
  candidate CSV fixtures were not edited.

### Findings or changes

- RED: `python -m pytest tests/test_data_health.py::test_failed_completion_event_is_failure_not_success -q` exited 1 with `row.last_success` incorrectly equal to `2026-07-10T11:00:00+10:00`.
- GREEN: failure classification now runs before success classification.
- Refreshed stale full-suite and head evidence while keeping ISSUE-0035
  implementation-complete/closure-pending.

### Evidence

- Focused regression: exit 0.
- Data Health suite: 16 passed.
- Affected six-file bundle: 40 passed with one existing GluonTS warning.
- Authoritative suite using the repository Python 3.13 environment: exit 0 at
  100%, warnings only.

### Commands or tests run

- `python -m pytest tests/test_data_health.py::test_failed_completion_event_is_failure_not_success -q` (RED exit 1, then GREEN exit 0).
- `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests/test_data_health.py -q` (exit 0).
- `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests/test_data_health.py tests/test_flet_startup.py tests/test_e2e_workflow.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/test_feature_registry.py -q` (exit 0, 40 passed).
- `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q` (exit 0 at 100%).

### Remaining uncertainty and risk

Package-smoke AURG/Sparebanken fixture, semantic accessibility focus
evidence, independent re-review and final integration/synchronisation remain
pending. No package or browser claim was changed by this fix.

### Recommended next action

Run the independent re-review and parent integration/synchronisation gates;
keep ISSUE-0035 open and `execution_allowed=false` until those gates pass.

### Authored file list

- `src/etf_cockpit/data/health.py`
- `tests/test_data_health.py`
- `.ai_worklog/task-10-report.md`
- `RUN_STATE.json`
- `evidence/final/tests/ISSUE-0035.md` and sidecar
- `evidence/final/build/ISSUE-0035.md` and sidecar
- `evidence/final/issues/ISSUE-0035.json` and sidecar
- `issues/open.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/CHANGES.md`
- `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-programme-index.md`
- `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-progress-ledger.md`
