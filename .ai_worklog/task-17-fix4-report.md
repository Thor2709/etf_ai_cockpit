# Task 17 fix4 report

## Task completed

Closed the three blocking findings from the fresh Task 17 review. Legacy score-history stores are normalised before duplicate detection, malformed DataFrame comparison input is fail-safe and deterministic, and What Changed now uses responsive per-instrument cards instead of a wide DataTable. The history and comparison paths remain informational; `execution_allowed` remains `false`.

## Files and symbols examined

- `src/etf_cockpit/data/score_history.py`: `append_score_run`, `_normalise_history_frame`, `_read_history_raw`.
- `src/etf_cockpit/data/run_changes.py`: `compare_runs`, `_safe_frame`.
- `src/etf_cockpit/app/pages/what_changed.py`: filter rendering and comparison result presentation.
- `tests/test_score_history.py`, `tests/test_run_changes.py`, `tests/test_task17_ui_contracts.py`: focused regressions.
- `.ai_worklog/task-17-brief.md` and prior Task 17 fix reports for acceptance boundaries.

## Findings or changes

- `append_score_run` now passes any existing store through `_normalise_history_frame` before reading `run_id` or `snapshot_hash`. Legacy rows missing `snapshot_hash` and newer columns are therefore safely upgraded in-memory; the first compatible rewrite persists the complete v2 schema and later retries remain idempotent.
- `_safe_frame` now adds aligned `run_id` and `instrument_id` columns to non-empty malformed DataFrames. Named comparisons with missing run identity produce an empty, deterministic report rather than an unalignable boolean-index error.
- What Changed now renders each visible instrument as a compact panel with a responsive metric grid containing score/rank deltas, all seven comparison dimensions, current action and summary text. The page retains the existing instrument, dimension and changed-only filters and only uses the page’s vertical scroll; no horizontal DataTable is created.
- Added one real regression per finding. No closure-ledger or issue-state files were edited.

## Evidence

- RED: `$env:PYTHONPATH='src'; ..\\..\\.venv\\Scripts\\python.exe -m pytest -q tests/test_score_history.py::test_score_history_append_normalises_legacy_store_before_duplicate_detection tests/test_run_changes.py::test_run_comparison_malformed_frame_without_run_id_returns_empty_report tests/test_task17_ui_contracts.py::test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table --tb=short` — `FFF`; failures were the expected `KeyError: 'snapshot_hash'`, pandas `IndexingError: Unalignable boolean Series`, and the existing `ft.DataTable` assertion.
- GREEN: the same focused command after implementation — `...`; exit 0.
- Focused Task 17 suite: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py::test_production_score_history_replaces_complete_run_snapshot_when_scope_narrows tests/test_trust_critical_artifacts.py::test_production_score_history_persists_real_dimensions_and_explicit_unavailable_values tests/test_trust_critical_artifacts.py::test_score_artifacts_write_history_components_and_drivers tests/test_trust_critical_artifacts.py::test_pending_model_label_persists_unavailable_without_model_row_or_version tests/test_task17_ui_contracts.py -q --tb=short -rA` — 37 passed.
- Scoped Ruff: `..\\..\\.venv\\Scripts\\python.exe -m ruff check src/etf_cockpit/data/score_history.py src/etf_cockpit/data/run_changes.py src/etf_cockpit/app/pages/what_changed.py tests/test_score_history.py tests/test_run_changes.py tests/test_task17_ui_contracts.py` — `All checks passed!`.
- Compilation: `..\\..\\.venv\\Scripts\\python.exe -m compileall -q src tests` — exit 0.
- Diff hygiene: `git diff --check` — exit 0 (Git only reported expected LF-to-CRLF conversion warnings).

## Commands or tests run

- The RED and GREEN focused commands above.
- The 37-test Task 17 regression bundle above.
- Ruff, `compileall` and `git diff --check` above.
- A broader `tests/test_simple_scores.py` selection was attempted; five pre-existing fixture failures remain because this isolated worktree lacks the expected secondary/candidate universe records. That suite is outside the edited paths.

## Remaining uncertainty and risk

The legacy first rewrite cannot recover a historical snapshot hash that was never persisted, so it deterministically replaces that run once; subsequent writes are idempotent. Full packaged/browser verification and fixture-dependent simple-score checks were not run in this isolated worktree. No authority or execution behaviour changed.

## Recommended next action

Cherry-pick the fix commit into the parent branch, then rerun the parent release matrix with its complete candidate fixtures.
