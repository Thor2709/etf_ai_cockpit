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

## Fix pass: independent review findings

Date: 2026-07-13
Base: `070ec8b` plus the pre-existing unstaged `universe_store.py` validation change
Fix commit: `e6a4193` (`fix: close Task 11 universe review findings`)

### Findings addressed

1. Universe manager now has functional add, full-field edit, disable and
   remove callbacks, reactive query rebuilding, visible Primary/Secondary/
   Sparebanken tabs, per-row status/`needs_verification` labels and explicit
   pending-refresh messaging. The save callback uses the revision captured at
   page snapshot load and never starts a workflow.
2. `leveraged` and `inverse` are persisted with backwards-compatible false
   defaults, exported through compatibility YAML/CSV and loaded into
   `ETFConfig`. Enabled IDs, yfinance symbol mapping and candidate scoring now
   exclude unsupported cadence/assets and high-risk records; futures/options
   remain persistable research-only records.
3. Offline onboarding now requires positive local ticker evidence; online
   validation can opt in through the validator callback. Clean roots disable
   regex-valid unknown symbols while configured local VWCE evidence remains
   enabled, with the explanatory note preserved and no default network call.
4. Legacy migration removes candidate Sparebanken identities (including
   secondary NONG) before appending the authoritative 15-row fallback, giving
   exactly one Sparebanken row per canonical ID.
5. `allow_cross_tier_duplicates` remains an explicit validation override with
   warning/accept behaviour; unknown ISIN states remain explicit.

### RED / GREEN evidence

Observed REDs while closing the findings:

- `pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py`
  first reported the clean-root VWCE expectation mismatch after the offline
  evidence guard was introduced.
- `pytest -q tests/test_button_contracts.py ...` first reported missing stable
  acceptance entries for the new `universe.add`, `universe.disable.*` and
  `universe.remove.*` controls.
- The new candidate boundary regression first returned no rows because NaN
  boolean fields were interpreted as true; the guard was corrected before
  GREEN.

GREEN:

```text
python -m pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_universe_manager.py
21 passed

python -m pytest -q tests/test_flet_startup.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/test_feature_registry.py tests/test_data_validation.py
24 passed

python -m compileall -q src tests
exit 0

python -m ruff check src/etf_cockpit/data/universe_store.py src/etf_cockpit/app/pages/universe_manager.py src/etf_cockpit/app/pages/onboarding.py src/etf_cockpit/core/config.py src/etf_cockpit/data/yfinance_provider.py src/etf_cockpit/signals/simple_scores.py tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_universe_manager.py --no-cache
All checks passed
```

The broader simple-score/provider bundle ran with six known baseline failures
because this isolated worktree has no ignored `data/raw/trade_candidates`
fixture; those failures are the existing candidate/inventory baseline recorded
above, not fix-pass regressions. Generated `data/.schema_versions/*` churn and
the untracked task brief remain unstaged by design.

## Final review fix pass: important findings

Date: 2026-07-13

### Findings and changes

- Threaded the explicit `allow_cross_tier_duplicates=False` default through
  `add_record`, `edit_record` and `save_universe`; the UI now exposes a keyed,
  auditable override checkbox and persists the selected flag in the canonical
  store payload. Default validation still rejects cross-tier duplicates.
- Added editable enabled state to add/edit dialogs and an Enable action for
  disabled rows, retaining Disable for enabled rows.
- Updated the save callback's captured revision after each successful save so
  subsequent edits in the same page session use the new revision.
- Removed trailing whitespace from this report section.

### RED / GREEN evidence

RED:

```text
python -m pytest -q tests/test_universe_store.py::test_crud_and_save_thread_cross_tier_override
TypeError: add_record() got an unexpected keyword argument 'allow_cross_tier_duplicates'

python -m pytest -q tests/test_button_contracts.py
ValueError: source controls missing stable keys (conditional enable/disable action)
```

GREEN:

```text
python -m pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_universe_manager.py tests/test_flet_startup.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/test_feature_registry.py tests/test_data_validation.py
46 passed

python -m compileall -q src tests
exit 0

python -m ruff check src/etf_cockpit/data/universe_store.py src/etf_cockpit/app/pages/universe_manager.py src/etf_cockpit/app/pages/onboarding.py src/etf_cockpit/core/config.py src/etf_cockpit/data/yfinance_provider.py src/etf_cockpit/signals/simple_scores.py tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_universe_manager.py --no-cache
All checks passed
```

Final fix commits: `f6be9d3` (`fix: close final Task 11 review blockers`) and
`89e7958` (`fix: carry duplicate override through enable controls`). The latter
also carries the explicit override through Disable/Enable callbacks so an
audited duplicate configuration remains operable. Generated schema markers
remain unstaged.

## Final re-review fix pass: migration, snapshot and ticker validation

Date: 2026-07-13

### Findings and changes

- `import_legacy_universe` now filters canonical Sparebanken IDs and Yahoo
  tickers from both primary YAML and candidate CSV before appending exactly one
  authoritative set of all 15 fallback rows, including when no candidate CSV
  exists.
- `UniverseStoreSnapshot` now exposes the persisted
  `allow_cross_tier_duplicates` flag, with false compatibility defaults;
  `universe_manager_page` rehydrates its auditable override checkbox from that
  snapshot.
- Universe validation and CRUD now reject malformed local ticker syntax using
  the same bounded Yahoo-symbol shape check, while preserving explicit
  `needs_verification` ISIN states and offline/no-network behaviour.

### RED / GREEN evidence

RED:

```text
python -m pytest -q tests/test_universe_store.py::test_malformed_ticker_is_rejected_without_inventing_isin tests/test_universe_store.py::test_primary_sparebanken_identity_is_replaced_by_authoritative_fallback tests/test_universe_store.py::test_load_snapshot_preserves_cross_tier_override_state
3 failed: malformed ticker accepted; primary NONG remained primary; snapshot had no persisted override attribute.
```

GREEN:

```text
python -m pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_universe_manager.py tests/test_flet_startup.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/test_feature_registry.py tests/test_data_validation.py
50 passed

python -m compileall -q src tests
exit 0

python -m ruff check src/etf_cockpit/data/universe_store.py src/etf_cockpit/app/pages/universe_manager.py src/etf_cockpit/app/pages/onboarding.py src/etf_cockpit/core/config.py src/etf_cockpit/data/yfinance_provider.py src/etf_cockpit/signals/simple_scores.py tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_universe_manager.py --no-cache
All checks passed
```

Fix commit: `d8313b7` (`fix: harden Task 11 migration and snapshot state`).

## Final integration fix pass: active state/cache refresh and online onboarding seam

Date: 2026-07-13

### Findings and changes

- Successful universe saves now reload the canonical config into the active
  `AppState`, update the universe cache revision marker, and filter affected
  local prices, holdings, features, signals and forecast frames. No provider,
  model, forecast or broker workflow is started.
- Added `CockpitSnapshot.universe_revision` and
  `AppState.apply_universe_config` as the explicit safe reload/invalidation
  seam. `execution_allowed=false` remains unchanged.
- The first-run wizard now exposes a keyed opt-in online-validation toggle and
  injectable validator callback. Offline/no-network remains the default.

### RED / GREEN evidence

RED:

```text
python -m pytest -q tests/test_universe_manager.py::test_save_reloads_active_state_and_marks_universe_cache_revision
Initial callback regression failed because universe_manager had no load_config seam and did not update active state/cache revision.

python -m pytest -q tests/test_onboarding.py::test_onboarding_ui_exposes_opt_in_online_validator_seam
TypeError: onboarding_page() got an unexpected keyword argument 'validator'
```

GREEN:

```text
python -m pytest -q tests/test_universe_store.py tests/test_onboarding.py tests/test_asset_guardrails.py tests/test_universe_manager.py tests/test_flet_startup.py tests/test_accessibility_contracts.py tests/test_button_contracts.py tests/test_feature_registry.py tests/test_data_validation.py
52 passed

python -m compileall -q src tests
exit 0

python -m ruff check src/etf_cockpit/app/state.py src/etf_cockpit/app/pages/universe_manager.py src/etf_cockpit/app/pages/onboarding.py src/etf_cockpit/services.py src/etf_cockpit/data/universe_store.py tests/test_universe_manager.py tests/test_universe_store.py tests/test_onboarding.py --no-cache
All checks passed
```

Integration fix commit: `6b60fea` (`fix: refresh active universe state after save`).
