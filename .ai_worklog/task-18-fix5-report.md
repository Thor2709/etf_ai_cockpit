# Task 18 fix5 report

## Task completed

Aligned `write_trust_artifacts_for_scores` with the Scores crowding contract: the persisted Trust/audit correlation-cluster artefact now uses the incoming ranked order's first ten instruments and unit weights, matching `build_simple_instrument_scores`. A high-level 20-score regression proves that the persisted top-ranked theme concentration is identical to the Scores-equivalent cohort. The existing non-executable boundary remains unchanged (`execution_allowed=false`).

## Files and symbols examined

- `src/etf_cockpit/signals/simple_scores.py`: `build_simple_instrument_scores` top-ranked crowding cohort construction.
- `src/etf_cockpit/data/trust_artifacts.py`: `write_trust_artifacts_for_scores`, `write_correlation_clusters` and `_configured_metadata`.
- `src/etf_cockpit/features/crowding.py`: `build_correlation_clusters` ranked weights and theme concentration semantics.
- `tests/test_crowding.py`: ranked cohort and theme concentration coverage.
- `tests/test_trust_critical_artifacts.py`: high-level trust persistence and authority regressions.

## Findings or changes

- The trust writer previously passed every score with equal weight, producing a universe-wide theme concentration that could differ from Scores' explicit top-ten ranked cohort.
- Added `ranked_instruments = scores[:10]` projection before writing Trust correlation clusters, preserving incoming order/rank and using unit weights for exactly that cohort.
- Added `test_score_trust_writer_uses_same_top_ten_theme_cohort_as_scores`, using twenty scores (ten AI, ten Bonds) and persisted Parquet output. It checks the expected 1.0 concentration, warning, and `execution_allowed=false`.
- Edited only `src/etf_cockpit/data/trust_artifacts.py`, `tests/test_trust_critical_artifacts.py` and this report. Existing four `data/.schema_versions/*.json` worktree modifications were left untouched and excluded.

## Evidence

### RED

`python -m pytest -q tests/test_trust_critical_artifacts.py::test_score_trust_writer_uses_same_top_ten_theme_cohort_as_scores --tb=short` failed as intended: persisted concentration was `0.5`, while the Scores-equivalent top-ten cohort expected `1.0`.

### GREEN

The same regression passed after the two-line cohort correction. The focused high-level trust regressions passed (`4 passed`), including the new regression, existing score-artifact persistence, nominal-window/sample evidence and score-history dimensions.

## Commands or tests run

- Task 18 focused bundle: `python -m pytest tests/test_task18_integration.py tests/test_crowding.py tests/test_benchmark_attribution.py tests/test_friction_edge.py tests/test_evidence_derivatives.py tests/test_signal_gates.py tests/test_instrument_detail.py tests/test_risk_analytics.py tests/test_task18_ui.py -q --tb=short` - 51 passed.
- Affected regression bundle: `python -m pytest tests/test_simple_scores.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_trust_critical_artifacts.py -q --tb=short` - 61 passed, 7 established fixture failures (`test_two_tier_universe_config_contains_requested_primary_and_secondary_without_duplicates`, `test_simple_scores_show_all_two_tier_instruments_as_pending_without_refresh`, `test_simple_scores_group_into_required_main_page_sections`, `test_scoreboard_frame_preserves_needs_verification_isin_status`, `test_simple_score_tiles_render_instrument_rows`, `test_simple_score_grouped_sections_render_required_labels_and_sparebanken_isin_status`, `test_static_trust_artifacts_cover_providers_and_identity`).
- High-level trust subset: `python -m pytest -q tests/test_trust_critical_artifacts.py -k "score_trust_writer_uses_same_top_ten_theme_cohort_as_scores or score_artifacts_write_history_components_and_drivers or correlation_cluster_writer_preserves_nominal_window_and_observed_sample or production_score_history_persists_real_dimensions" --tb=short` - 4 passed.
- Ruff: `python -m ruff check src/etf_cockpit/features/crowding.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/app/components/simple_scores.py src/etf_cockpit/app/pages/instrument_detail.py src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_crowding.py tests/test_task18_ui.py tests/test_task18_integration.py tests/test_trust_critical_artifacts.py --no-cache` - passed.
- `python -m compileall -q src tests` - passed.
- `git diff --check` - passed; only existing line-ending conversion warnings were reported.

## Remaining uncertainty and risk

- Full release/package/browser/clean-first-run validation was not run; it is outside this focused fix.
- The seven affected-bundle failures are unchanged fixture/data-state gaps (missing candidate/secondary/identity artefacts) and are unrelated to the cohort change.
- Existing generated schema-version modifications remain in the worktree and were not included in the commit.

## Recommended next action

Review and integrate commit `fix: align trust crowding cohort with scores`, then run the parent branch release matrix after restoring the known fixture data.
