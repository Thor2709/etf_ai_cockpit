# Task 17 fix4 report

## Task completed

Resolved all three Important findings from the fresh Task 17 review. Legacy score-history stores are normalised before duplicate detection, malformed run-comparison frames are safe and deterministic, and What Changed now renders compact responsive instrument cards rather than a twelve-column table.

## Files changed

- `src/etf_cockpit/data/score_history.py`: normalise legacy persisted frames before accessing v2 columns.
- `src/etf_cockpit/data/run_changes.py`: add aligned identity columns for malformed non-empty frames.
- `src/etf_cockpit/app/pages/what_changed.py`: replace the wide DataTable with responsive metric cards retaining every comparison dimension and current action.
- `tests/test_score_history.py`: legacy store append/idempotency regression.
- `tests/test_run_changes.py`: malformed frame regression.
- `tests/test_task17_ui_contracts.py`: compact responsive layout regression proving no `DataTable` is rendered.

## RED-GREEN-REFACTOR evidence

- RED: fresh review reproductions established `KeyError: 'snapshot_hash'` for a valid legacy store, `pandas.errors.IndexingError` for a non-empty frame without `run_id`, and a twelve-column What Changed table with no horizontal constraint. The three regressions were added before the fixes.
- GREEN: `python -m pytest -q tests/test_score_history.py tests/test_run_changes.py tests/test_task17_ui_contracts.py` — 20 passed.
- Full Task 17 focused regression: `python -m pytest -q tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py tests/test_instrument_detail.py tests/test_task17_ui_contracts.py tests/test_trust_critical_artifacts.py::test_production_wrapper_empty_snapshot_removes_supplied_run_only tests/test_trust_critical_artifacts.py::test_production_score_history_replaces_complete_run_snapshot_when_scope_narrows tests/test_trust_critical_artifacts.py::test_production_score_history_persists_real_dimensions_and_explicit_unavailable_values tests/test_trust_critical_artifacts.py::test_score_artifacts_write_history_components_and_drivers tests/test_trust_critical_artifacts.py::test_pending_model_label_persists_unavailable_without_model_row_or_version` — 38 passed.
- `python -m ruff check src/etf_cockpit/data/score_history.py src/etf_cockpit/data/run_changes.py src/etf_cockpit/app/pages/what_changed.py tests/test_score_history.py tests/test_run_changes.py tests/test_task17_ui_contracts.py` — passed.
- `python -m compileall -q src tests` — passed.
- `git diff --check` — passed.

## Limitations

Repository-wide simple-score and identity tests retain the documented pre-existing fixture failures because this isolated worktree has no `data/raw/trade_candidates` fixture and the identity fixture is incomplete. Strict package, browser and clean-first-run closure evidence remains pending the later release verification wave.
