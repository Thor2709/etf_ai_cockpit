# Task 18 fix4 report

## Task completed

Fixed the three Important Task 18 evidence-integrity findings at exact head `dd4a90f`. Ranked theme concentration is now calculated independently of correlation clusters from configured metadata; non-finite friction values remain unavailable across Scores and Instrument Detail as well as Risk; and correlation-cluster artefacts preserve the requested nominal window separately from observed return sample size. All new and existing evidence paths retain `execution_allowed=false`.

## Files and symbols examined

- `src/etf_cockpit/features/crowding.py`: `ClusterRow`, `ClusterReport`, `build_correlation_clusters` and ranked concentration calculations.
- `src/etf_cockpit/signals/simple_scores.py`: `SimpleInstrumentScore`, crowding adapters and `simple_scoreboard_frame`.
- `src/etf_cockpit/data/trust_artifacts.py`: correlation-cluster schema and `write_correlation_clusters`.
- `src/etf_cockpit/app/components/simple_scores.py`: `_number_badge`, `_bps_badge`, `_edge_colour`, `_ratio_colour` and crowding evidence text.
- `src/etf_cockpit/app/selectors/instrument_detail.py`: `_friction_panel` finite-value/status handling.
- `src/etf_cockpit/app/pages/instrument_detail.py` and `app/pages/trust_evidence.py`: friction formatters and exported crowding evidence visibility.
- Focused crowding, UI, integration and trust-artifact tests.

## Findings or changes

- Added `top_ranked_theme_concentration` and `top_ranked_theme_warning` to crowding reports/rows. The selected ranking's configured theme weights are aggregated separately from correlation groups, so ten AI-themed singleton clusters publish a 1.0 concentration and `theme_concentration_warning` without inferred metadata.
- Propagated those fields through score rows, scoreboard exports, persisted correlation-cluster artefacts, Scores text, Instrument Detail and Trust Evidence. Cluster-level `theme_warning` semantics remain intact.
- `_number_badge`, `_bps_badge`, `_edge_colour` and `_ratio_colour` now treat `NaN` and both infinities as unavailable/muted while retaining finite formatting and colours.
- Instrument Detail selectors and render formatters reject non-finite friction values and scenarios; all-invalid friction rows publish `status=unavailable`, `N/A` and `cost_stress_scenario=unavailable`.
- `write_correlation_clusters` accepts the requested `window` (default 120) and persists `calculation_window_days=report.window`; `sample_size` remains each instrument's observed clean return count (119 for 120 price rows).

## Evidence

### RED

`python -m pytest -q tests/test_crowding.py::test_ranked_theme_concentration_is_independent_of_singleton_clusters tests/test_task18_ui.py::test_scores_friction_helpers_hide_non_finite_values tests/test_task18_ui.py::test_instrument_detail_friction_non_finite_values_are_unavailable tests/test_trust_critical_artifacts.py::test_correlation_cluster_writer_preserves_nominal_window_and_observed_sample --tb=short` returned **4 failed** for the missing report fields, leaked `nan`, available non-finite friction and missing writer `window` parameter.

### GREEN

The same four-test command returned **4 passed** after the minimal fixes. The complete Task 18 focused bundle returned **51 passed**:

`python -m pytest tests/test_task18_integration.py tests/test_crowding.py tests/test_benchmark_attribution.py tests/test_friction_edge.py tests/test_evidence_derivatives.py tests/test_signal_gates.py tests/test_instrument_detail.py tests/test_risk_analytics.py tests/test_task18_ui.py -q --tb=short`

The affected regression command returned **61 passed, 7 failed**. The seven failures are the known baseline fixture/data-state failures: absent `yahoo_trade_candidates_*.csv`, missing secondary/Sparebanken universe rows and the static identity count (`16 < 45`); no changed assertion or new Task 18 path failed.

## Commands or tests run

- RED and GREEN four-test regression command above.
- Task 18 focused bundle above (`51 passed`).
- Affected regressions: `python -m pytest tests/test_simple_scores.py tests/test_instrument_detail.py tests/test_task18_integration.py tests/test_trust_critical_artifacts.py -q --tb=short` (`61 passed, 7 known baseline fixture failures`).
- `python -m pytest tests/test_trust_critical_artifacts.py -q --tb=short` (`18 passed, 1 known identity-fixture failure`).
- Scoped Ruff: `python -m ruff check src/etf_cockpit/features/crowding.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/data/trust_artifacts.py src/etf_cockpit/app/components/simple_scores.py src/etf_cockpit/app/pages/instrument_detail.py src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_crowding.py tests/test_task18_ui.py tests/test_task18_integration.py tests/test_trust_critical_artifacts.py --no-cache` (passed).
- `python -m compileall -q src tests` (passed).
- `git diff --check` (passed; Git reported only existing LF/CRLF conversion warnings).

## Remaining uncertainty and risk

- Full release/package/browser/clean-first-run gates were not run in this focused fix.
- The seven baseline regression failures require restoration of the repository's missing candidate/secondary/identity fixtures and are unrelated to this diff.
- Four pre-existing generated `data/.schema_versions/*.json` modifications were left untouched and are intentionally excluded from the commit.

## Recommended next action

Review commit `fix: complete Task 18 evidence integrity surfaces`, then run the parent branch's full release matrix after restoring the known fixture data.
