# Wave 4 Task 11 implementation report

Date: 2026-07-13
Branch: `wave4/task11-universe`
Scope: `ISSUE-0068`, `ISSUE-0018`, `ISSUE-0017`, `ISSUE-0056`

## Task completed

Implemented the approved local-first universe/watchlist, onboarding and asset
guardrail slice. The canonical `UniverseRecord` store now validates CRUD
identity across tiers, preserves explicit `needs_verification` ISIN states,
imports the primary YAML plus candidate CSV (including the 15 named
Sparebanken rows), writes a schema-versioned revision with backup and atomic
publication, and exports compatibility YAML/CSV views. A revision conflict
fails closed. Editing and onboarding only stage/persist local configuration;
they do not call yfinance, scoring, forecasts or broker execution.

The UI exposes Primary, Secondary and Sparebanken tabs, search/tier filtering,
status and validated edit controls, pending-refresh messaging and a first-run
wizard with offline unresolved-ticker disabling. `execution_allowed=false`
remains unchanged.

## Files and symbols examined

- `.ai_worklog/task-11-brief.md`, `docs/superpowers/plans/2026-07-10-all-41-issues-closure-plan.md`.
- `issues/open.md`: exact records for `ISSUE-0068`, `ISSUE-0018`, `ISSUE-0017` and `ISSUE-0056`.
- `src/etf_cockpit/data/universe_store.py`: `UniverseRecord`, validation, atomic/revision persistence, migration/export and support matrix.
- `src/etf_cockpit/core/config.py`: `ETFConfig`, `UniverseConfig`, persisted-universe loader and empty-config defaults.
- `src/etf_cockpit/app/router.py`: existing `/universe` and `/onboarding` routes (unchanged).
- `src/etf_cockpit/app/pages/settings.py`, `universe_manager.py`, `onboarding.py` and `configs/ui_acceptance.yaml`.
- Existing atomic/backup, migration, state and UI acceptance patterns and Task 10 report.

## Findings or changes

- Added case-insensitive duplicate ID/ISIN/ticker checks across tiers; disabled and unknown-ISIN states are warnings, not invented values.
- Added `add_record`, `edit_record`, `disable_record`, `remove_record`, `load_universe`, `migrate_legacy_universe`, `export_compatibility` and compatibility aliases through the canonical store.
- Added `SPAREBANKEN_ROWS` fallback/merge so a partial or absent legacy candidate CSV still retains all 15 requested rows; supplied unknown ISINs remain `needs_verification`, known values remain exact, and `NONG` belongs to Sparebanken.
- `save_universe` now creates a verified backup manifest for an existing store, checks expected revision, uses `atomic_write_json`, verifies the resulting revision and returns pending-refresh metadata.
- Added explicit guardrail states: daily ETF/stock/equity-certificate score eligible; intraday unsupported; futures/options research-only; crypto and other unsupported assets blocked; leveraged/inverse high-risk manual review and not score eligible.
- Added local/offline onboarding profile persistence and optional validator callback for online/yfinance validation. Unresolved symbols are persisted disabled with an explanatory note.
- Extended config model fields for instrument type/tier/provider policy/ISIN status/notes, migrated candidate inputs when present, and supplied safe defaults for missing clean-start config files.
- Added UI acceptance entries for new stable controls; no refresh/model workflow is reachable from the new save callbacks.

## Evidence

### RED

Exact command before implementation:

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py
```

Result: test collection failed as expected because `add_record`,
`complete_onboarding` and the migration/export APIs were absent:

```text
ImportError: cannot import name 'add_record' from etf_cockpit.data.universe_store
ImportError: cannot import name 'complete_onboarding' from etf_cockpit.app.pages.onboarding
```

### GREEN / REFACTOR

```text
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_flet_startup.py
25 passed

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_flet_startup.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/test_feature_registry.py tests/test_data_validation.py
37 passed

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src tests
exit 0

& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src/etf_cockpit/data/universe_store.py src/etf_cockpit/app/pages/universe_manager.py src/etf_cockpit/app/pages/onboarding.py src/etf_cockpit/core/config.py src/etf_cockpit/app/pages/settings.py tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py --no-cache
All checks passed
```

The authoritative full suite reached 100% execution but finished with 9
failures: seven existing candidate/trust-artifact tests because the isolated
worktree has no ignored `data/raw/trade_candidates/yahoo_trade_candidates_*.csv`
fixture, one package-inventory failure because the nested worktree is scanned,
and one intermittent Windows atomic transaction `PermissionError`. The
candidate fixture and generated schema-marker churn were intentionally not
created or staged. The atomic transaction test is a known flaky baseline and
was not touched by this task.

## Migration and compatibility notes

`import_legacy_universe(primary_yaml, candidate_csv)` accepts the historical
column aliases (`id`/`instrument_id`, `symbol`/`ticker`/`yahoo_symbol`,
`analysis_tier`, `isin_status`) and returns a typed import result. A partial
candidate source is merged with the authoritative 15-row Sparebanken list.
`migrate_legacy_universe` publishes the result into `configs/universe_store.json`;
`export_compatibility` emits `universe.yaml` and `yahoo_trade_candidates.csv`.
Existing `configs/universe.yaml` remains a readable compatibility input.

## UI/source/package evidence status

Source/UI acceptance checks passed, including stable keys and registered
routes. No browser computer-use, packaged build or native/portable smoke was
run in this implementer slice; those remain parent integration gates.

## Known baseline failures and concerns

- The isolated worktree lacks the generated/ignored candidate CSV used by
  existing Simple Scores and trust-artifact tests; those tests fail before
  Task 11 code can observe candidate rows.
- Full package inventory sees the nested worktree path; this is workspace
  state, not a Task 11 source change.
- One full-suite atomic transaction test had a Windows `PermissionError`; no
  atomic I/O foundation code was changed.
- Browser/package parity, clean-root computer-use onboarding and final issue
  closure evidence remain unverified.

## Commands or tests run

Focused RED/GREEN, affected UI/startup bundle, compileall and scoped Ruff are
listed above. The full `pytest -q` command was also run; see the baseline
failure summary above. No destructive command or external write was run.

## Commit hashes

Implementation commit: `9c8073a` (`feat: add universe store onboarding and guardrails`).
Generated schema-marker files remain unstaged by design.

## Recommended next action

Review this diff, run the parent source/package/browser and clean-first-run
gates with the generated candidate fixture available, then synchronise issue
evidence without changing the execution authority boundary.
