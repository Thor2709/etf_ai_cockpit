# Task 17 fix1 report

## Task completed

Fixed all three blocking Task 17 review findings in the production score and UI paths. Score history writes now use complete-run snapshot hashes and replace a changed run as one deterministic snapshot. Live `SimpleInstrumentScore` rows carry ranked comparison dimensions and real model/news metadata where available, with explicit unavailable markers otherwise. What Changed has instrument, dimension and changed-only filters; Dashboard includes a deterministic run-change digest; Instrument Detail renders ordered driver groups as structured table rows.

## Files and symbols examined

- `src/etf_cockpit/data/trust_artifacts.py`: `append_score_history`, `_append_parquet`, score-history schema and model/forecast dimension helpers.
- `src/etf_cockpit/signals/simple_scores.py`: `SimpleInstrumentScore`, `build_simple_instrument_scores`, configured/candidate builders and production metadata lookup helpers.
- `src/etf_cockpit/app/pages/what_changed.py`: comparison page and filter controls.
- `src/etf_cockpit/app/pages/dashboard.py`: Dashboard composition and run-change digest.
- `src/etf_cockpit/app/selectors/instrument_detail.py`: driver grouping/order model.
- `src/etf_cockpit/app/pages/instrument_detail.py`: structured driver-row renderer.
- `tests/test_trust_critical_artifacts.py`, `tests/test_instrument_detail.py`, `tests/test_task17_ui_contracts.py`: RED regressions and production/UI coverage.

## Findings or changes

- Added a complete-run `snapshot_hash` to production trust-artifact score history. `_append_parquet` removes all prior rows for a changed `run_id` before atomic publication, so a narrowed retry cannot retain stale instruments; row ordering is deterministic and legacy columns remain readable.
- Added rank/score-rank assignment after the real production score ordering, propagated signal model versions, derived forecast status from actual forecast components, counted canonical local news rows where present, and persisted explicit `unavailable` values for absent comparison dimensions. `execution_allowed` remains literal `False`.
- Added What Changed controls (`Search instrument`, `Filter dimension`, `Changed only`) that re-render deterministic comparison rows without changing authority.
- Added Dashboard `Run changes digest` with deterministic report summary and instrument lines linking to What Changed.
- Added ordered positive, negative, missing/N/A, low-authority and stale/partial driver groups and structured DataTable rows on Instrument Detail; driver text is no longer rendered as a stringified dict.

## Evidence

- RED: the five new regression tests failed before implementation: stale instrument `B` survived a narrowed trust write; production rows lacked ranks; Instrument Detail lacked structured driver groups; What Changed lacked filters; Dashboard lacked a run-change digest.
- GREEN: `python -m pytest tests/test_trust_critical_artifacts.py::test_production_score_history_replaces_complete_run_snapshot_when_scope_narrows tests/test_trust_critical_artifacts.py::test_production_score_history_persists_real_dimensions_and_explicit_unavailable_values tests/test_instrument_detail.py::test_instrument_detail_driver_groups_are_ordered_structured_rows tests/test_task17_ui_contracts.py tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py -q --tb=short` — 19 passed.
- Affected UI/trust checks passed: `tests/test_simple_scores.py -k score_history_panel` (3 passed), `tests/test_trust_critical_artifacts.py::test_score_artifacts_write_history_components_and_drivers` plus `tests/test_instrument_detail.py` (11 passed).
- Ruff, `compileall` and `git diff --check` passed for all edited sources/tests.

## Commands or tests run

- `python -m pytest ...` focused RED/GREEN suites above.
- `python -m pytest tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py tests/test_simple_scores.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py tests/test_task17_ui_contracts.py -q --tb=short` — 7 known isolated-worktree baseline failures remain in fixture-dependent universe/identity tests; no new Task 17 failure was observed.
- `python -m ruff check` on all edited sources/tests — passed.
- `python -m compileall -q src` — passed.
- `git diff --check` — passed (only Git LF/CRLF conversion warnings).

## Remaining uncertainty and risk

The broad score/universe suite still expects ignored `data/raw/trade_candidates` fixtures that are absent from this isolated worktree, matching the pre-existing Task 17 report. Full packaged/browser verification was not run in this fix worktree. Model version fields remain unavailable when forecast stores omit a version column; this is surfaced explicitly rather than inferred.

## Recommended next action

Review and cherry-pick the fix commit from this worktree, then rerun the parent branch's full release matrix with the candidate fixture restored.
