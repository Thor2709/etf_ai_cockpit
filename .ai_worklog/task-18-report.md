# Task 18 implementation report

## Task completed

Implemented the approved crowding, broad/sector attribution and friction-adjusted edge evidence contract. Calculations remain descriptive, configured metadata is the only sector/theme source, unavailable inputs remain explicit, and every new trust/UI/export path preserves `execution_allowed=false`.

## Files and symbols examined

- `src/etf_cockpit/features/crowding.py`: `ClusterRow`, `ClusterReport`, `build_correlation_clusters`.
- `src/etf_cockpit/features/benchmark_attribution.py`: `AttributionResult`, `build_benchmark_attribution`.
- `src/etf_cockpit/features/regime.py`: existing benchmark lookup wrapper and score consumer compatibility.
- `src/etf_cockpit/signals/friction_edge.py`: `FrictionEdgeResult`, `estimate_friction_edge`.
- `src/etf_cockpit/signals/simple_scores.py`: score row, scoreboard export and authority seams.
- `src/etf_cockpit/data/trust_artifacts.py`: canonical correlation/attribution schemas and dual writers.
- Scores, Risk, Instrument Detail and Trust Evidence Flet consumers.

## Findings or changes

- Correlation clustering now accepts long or wide adjusted-price panels, requires clean sample evidence, uses deterministic connected clusters, preserves window/sample/as-of/source fields, and emits configured sector/theme labels plus theme concentration warnings.
- Benchmark attribution now exposes broad and sector returns, beta/correlation, alpha proxies, sector-relative status, sample/as-of/source evidence and explicit `N/A` when sector overlap is absent.
- Friction edge now validates finite 0-10 scores, non-negative volatility/costs and low/base/high scenarios; unsupported inputs return unavailable values and reason text.
- Simple Scores, trust artefacts, Trust Evidence, Risk and Instrument Detail expose the new fields while retaining existing actions, weights, benchmark wrapper behaviour and fail-closed authority.
- Added deterministic numerical, insufficient-data, boundary, export and UI authority tests.

## Evidence

### RED

`python -m pytest tests/test_crowding.py tests/test_benchmark_attribution.py tests/test_friction_edge.py -q` initially returned `6 failed, 1 passed`; failures were the intentionally missing status, metadata and unavailable-state contract fields.

### GREEN

`python -m pytest tests/test_task18_integration.py tests/test_crowding.py tests/test_benchmark_attribution.py tests/test_friction_edge.py tests/test_evidence_derivatives.py tests/test_signal_gates.py tests/test_instrument_detail.py tests/test_risk_analytics.py -q` returned `36 passed`.

The direct trust-writer smoke check produced both parquet schemas with configured crowding/sector fields and `execution_allowed` false for every row. The full trust suite returned `17 passed, 1 failed`; the remaining failure is the known baseline fixture assertion that the local identity store contains at least 45 rows (the fixture currently contains 16).

## Commands or tests run

- Focused RED/GREEN pytest commands above.
- `python -m pytest tests/test_trust_critical_artifacts.py -q` (`17 passed, 1 known fixture failure`).
- `python -m ruff check` on all edited source/tests: passed.
- `python -m compileall -q src`: passed.
- `git diff --check`: passed.

## Remaining uncertainty and risk

- Full release/browser/build gates were not run in this focused task branch.
- Sector benchmarks are derived from configured same-sector peer returns when at least one clean peer exists; otherwise the sector-relative fields remain `N/A`.
- Existing test startup rewrites four schema-version JSON files as local generated noise; they are not part of this implementation commit.

## Recommended next action

Review this task branch commit and rerun the parent branch's full release matrix after restoring the missing candidate/identity fixture data.
