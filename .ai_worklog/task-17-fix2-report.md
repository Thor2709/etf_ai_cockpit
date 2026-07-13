# Task 17 fix2 report

## Task completed

Fixed the fresh Task 17 compatibility and persistence findings. Pending configured/candidate score rows now fail closed for model availability, legacy feature-driver stores are normalised before Instrument Detail grouping, zero-instrument retries remove only the supplied run, and canonical score-history publication uses the repository's grouped atomic writer with a CSV mirror. Run comparison now includes previous-only instruments as explicit removals.

## Files and symbols examined

- `src/etf_cockpit/data/score_history.py`: `append_score_run`, history reader/writer and model field normalisation.
- `src/etf_cockpit/data/trust_artifacts.py`: production score-history append and model metadata helpers.
- `src/etf_cockpit/app/selectors/instrument_detail.py`: `_feature_driver_panel` and legacy feature-driver normalisation.
- `src/etf_cockpit/data/run_changes.py`: `compare_runs`, `_change_for` and deterministic summaries.
- Focused score-history, trust-artifact, Instrument Detail and run-comparison regressions.

## Findings or changes

- Model labels such as `Model evidence pending` no longer imply model availability. Only a real model version, row or scored model component can produce `model_available=True`; otherwise persisted fields are `False` and `unavailable`.
- Empty score snapshots are accepted when the caller supplies an explicit `run_id`; replacing an empty snapshot removes all existing rows for that run while preserving unrelated runs.
- Canonical score history now publishes parquet and CSV through `atomic_write_group`, validating both payloads together and preserving the prior generation on injected failure.
- Instrument Detail adds compatibility defaults and aliases for legacy feature-driver stores missing `flags`, classifications, provenance and other newer columns before sorting/grouping.
- `compare_runs` unions current and previous instrument IDs and reports previous-only instruments with unavailable current state and removal summaries.

## Evidence

- RED: five new regressions failed before implementation (missing CSV mirror/atomic path, pending model marked available, legacy `flags` KeyError, and previous-only instrument omitted).
- GREEN: `python -m pytest tests/test_score_history.py tests/test_run_changes.py tests/test_feature_drivers.py tests/test_instrument_detail.py tests/test_trust_critical_artifacts.py::test_production_score_history_replaces_complete_run_snapshot_when_scope_narrows tests/test_trust_critical_artifacts.py::test_production_score_history_persists_real_dimensions_and_explicit_unavailable_values tests/test_trust_critical_artifacts.py::test_score_artifacts_write_history_components_and_drivers tests/test_trust_critical_artifacts.py::test_pending_model_label_persists_unavailable_without_model_row_or_version -q --tb=short` — 32 passed.
- `python -m ruff check` on edited source/tests — passed.
- `python -m compileall -q src` — passed.
- `git diff --check` — passed (only Git line-ending conversion warnings).

## Commands or tests run

- Focused RED/GREEN regression command above.
- `python -m pytest tests/test_simple_scores.py -q --tb=short` — six pre-existing fixture failures because `data/raw/trade_candidates` is absent in this isolated worktree.
- `python -m pytest tests/test_trust_critical_artifacts.py -q --tb=short` — one pre-existing fixture failure (`identity.shape[0]` is 16, expected at least 45).

## Remaining uncertainty and risk

The full universe/simple-score matrix and packaged/browser checks were not green in this isolated worktree because required candidate and identity fixtures are absent. No failure was observed in the edited Task 17 paths.

## Recommended next action

Review and cherry-pick this fix commit into the parent branch, restore the missing fixtures, then run the parent release matrix.
