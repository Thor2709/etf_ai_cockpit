# T-STORE handoff

## Bug IDs

- CHAT-P08-N002: fixed; focused full-chain and tamper test written.
- P02-N001: fixed; same stable ID is selected per entity; focused test written.
- P02-N002: fixed; retraction revision uses the source maximum and only matching targets are removed; focused same-source and cross-source cases written.
- P02-N007: fixed; reversed and equal validity intervals are rejected; focused cases written.
- P02-N008: fixed; missing custom paths raise without bootstrapping; focused test written.
- P02-N010: fixed; cache key includes the active formula version; focused test written.
- P02-N011: fixed; mixed holdings dates invalidate preview before writing; focused test written.
- P04-N013: fixed; terminal runs cannot return to queued or running; focused cases written.
- P04-N017: fixed; non-empty canonical parameters participate in generated run IDs; focused test written.
- P07-N019: fixed; paper-ledger read errors propagate; focused corrupt and empty-ledger assertions written.
- P08-N004: fixed; credential set/delete read-modify-write sections use the persistent file guard; concurrent set test written.

## Validation

Authored 11 focused test functions (14 cases after parametrization). The focused command passed:

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-store.py
```

Result: 14 passed.

The 16-file direct regression batch completed with exit 1 and reported 12 failures. A failure-only diagnostic run reproduced 12 failed tests (0 passed):

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_backtest_lab.py::test_backtest_cache_reader_uses_one_complete_snapshot_under_interleaving tests/test_score_history.py::test_score_history_append_is_idempotent_by_run_and_snapshot tests/test_score_history.py::test_invalid_history_rows_are_dropped_without_crashing tests/test_score_history.py::test_score_history_preserves_run_dimensions_and_never_grants_execution_authority tests/test_score_history.py::test_score_history_replaces_changed_snapshot_for_same_run_without_duplicate_instruments tests/test_score_history.py::test_score_history_append_normalises_legacy_store_before_duplicate_detection tests/test_score_history.py::test_empty_complete_run_replaces_only_supplied_run_rows tests/test_score_history.py::test_score_history_publishes_paired_csv_and_rolls_back_on_group_failure tests/test_score_history.py::test_classification_override_invalidates_canonical_history_read_but_preserves_raw_audit_row tests/test_import_export.py::test_settings_references_actual_version_and_changelog_files tests/test_application_api.py::test_jobs_page_consumes_application_api_view_models tests/test_credentials.py::test_settings_saves_resolves_and_deletes_credentials_by_active_provider_id
```

The failures were `KeyError: ['effective_at'] not in index` in the backtest/score-history tests, two static source expectations in settings/jobs, and a `StopIteration` while looking for a settings control. Their causes are unverified and do not match the listed bug rows. The separate module-name-selected 78-file command ended with exit `-1` and no summary. The packet's full existing-test validation is therefore not green. `git diff --check`, `git diff --stat`, and `git status --porcelain` are run as handoff checks.

## Files changed

- `src/etf_cockpit/core/job_scheduler.py`
- `src/etf_cockpit/data/bitemporal.py`
- `src/etf_cockpit/data/duckdb_store.py`
- `src/etf_cockpit/data/score_history.py`
- `src/etf_cockpit/data/import_export.py`
- `src/etf_cockpit/features/training_centre.py`
- `src/etf_cockpit/application/api.py`
- `src/etf_cockpit/security/credentials.py`
- `tests/test_bugfix_t-store.py`
- `docs/development/bf-t-store-HANDOFF.md`

## NEEDS_OPUS_DECISION

- None for the listed implementation scope. The required existing-test validation is not green, so the conditional commit was not created.
