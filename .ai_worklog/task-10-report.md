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
- Full `...python.exe -m pytest -q` - 8 unrelated pre-existing failures in
  decision-journal path creation, generated candidate/secondary fixtures and
  trust identity fixture cardinality; no Data Health failure observed.

Skipped checks: no browser screenshot/package build or external write was run
in this implementer slice. Router/dashboard were inspected but unchanged.

## Remaining uncertainty and risk

The full-suite failures above remain outside Task 10 ownership. Browser and
packaged UI evidence, export checksum capture and final issue-closure matrix
gates remain for the parent integration/review phase. Generated schema-marker
line-ending churn from local smoke/startup runs is intentionally unstaged and
excluded from this commit.

## Recommended next action

Review this focused diff and run the parent Wave 4 package/browser evidence
gates. Keep `execution_allowed=false` and do not close `ISSUE-0035` until those
independent checks pass.

Commit hashes: `d1711628071d2b0959e205792f2fb6d0b87c8f34` (implementation),
`85b469e` (export schema), `87559ed` (macro sibling visibility fix),
`ea03216` (timestamp ordering and migration history fix pass).
