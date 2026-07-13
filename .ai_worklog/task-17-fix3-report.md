# Task 17 fix3 report

## Task completed

Closed the remaining production-path recovery gap identified by the independent fix2 review. A zero-row score snapshot now removes the complete supplied run from the production trust-artifact history while preserving unrelated runs, including when the retry has no payload rows from which to infer the run identifier.

## Files changed

- `src/etf_cockpit/data/trust_artifacts.py`: pass the authoritative production `run_id` into complete-run replacement and preserve the empty-snapshot branch.
- `tests/test_trust_critical_artifacts.py`: add a production-wrapper regression covering an empty retry, the CSV mirror and preservation of an unrelated run.

## Evidence

- RED: the fix2 independent review reproduced the missing production behaviour: `write_trust_artifacts_for_scores(..., empty scores ...)` left stale rows for the supplied run because `_append_parquet` could only infer run IDs from the new frame. The new regression is the executable form of that finding.
- GREEN: `python -m pytest -q tests/test_trust_critical_artifacts.py::test_production_wrapper_empty_snapshot_removes_supplied_run_only` — 1 passed.
- Focused Task 17 regression: `python -m pytest -q tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py::test_production_wrapper_empty_snapshot_removes_supplied_run_only tests/test_trust_critical_artifacts.py::test_production_score_history_replaces_complete_run_snapshot_when_scope_narrows tests/test_trust_critical_artifacts.py::test_production_score_history_persists_real_dimensions_and_explicit_unavailable_values tests/test_trust_critical_artifacts.py::test_score_artifacts_write_history_components_and_drivers tests/test_trust_critical_artifacts.py::test_pending_model_label_persists_unavailable_without_model_row_or_version` — 33 passed.
- `python -m ruff check src/etf_cockpit/data/trust_artifacts.py tests/test_trust_critical_artifacts.py` — passed.
- `python -m compileall -q src tests` — passed.
- `git diff --check` — passed (Git reported only line-ending conversion warnings).

## Limitations

The repository-wide simple-score and identity suites retain the documented pre-existing fixture failures in this isolated worktree; they are outside the edited Task 17 production path. Packaged/browser and clean-first-run gates remain closure-pending later release evidence.
