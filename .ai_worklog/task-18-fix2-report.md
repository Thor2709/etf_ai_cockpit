# Task 18 fix2 report

## Scope

Fixed the fresh-review blockers for ranking-scoped crowding evidence, covariance-aware cluster risk, honest pair coverage, no-forward-fill attribution, and friction evidence on Instrument Detail and Risk. Execution remains disabled (`execution_allowed=false`); score weights, models, portfolio logic and execution paths were not changed.

## RED-GREEN-REFACTOR

- RED: `python -m pytest tests/test_crowding.py tests/test_evidence_derivatives.py tests/test_instrument_detail.py tests/test_task18_ui.py -q` failed with 6 expected failures: singleton risk contribution was `0.0`, mixed-pair coverage published the maximum (`119` instead of the minimum `89`), a single peer observation was made available by forward-fill, and the new friction surfaces had no scoreboard path/UI implementation.
- GREEN: the same focused command passed (`29 passed`).
- GREEN with integration coverage: `python -m pytest tests/test_crowding.py tests/test_evidence_derivatives.py tests/test_instrument_detail.py tests/test_task18_ui.py tests/test_task18_integration.py -q` passed (`31 passed`).
- Refactor/static checks after GREEN: Ruff, compileall and diff checks passed.

## Changes

- `features.crowding`: use the minimum clean observation count across valid peer pairs; compute covariance-adjusted cluster risk with a singleton fallback that preserves selected weight; leave unselected instruments without selected-cohort risk weight.
- `signals.simple_scores`: pass an explicit top-10 ranked cohort to crowding evidence instead of all scored rows with equal weights.
- `features.regime`: remove forward-fill from return panels used by regime volatility, portfolio fit and broad/sector/theme attribution; peer joins remain clean-overlap only and publish N/A when insufficient.
- Instrument Detail selector/page: load persisted scoreboard friction fields and render gross edge, estimated cost, net edge, edge/cost ratio, stress scenario and unavailable states.
- Risk page: render the same friction fields and explicit broad/sector/theme attribution availability summary.
- Focused regression tests cover singleton and ranked concentration, mixed pair sample (`119/89`), missing peer history, and friction UI states.

## Validation commands

1. `python -m pytest tests/test_crowding.py tests/test_evidence_derivatives.py tests/test_instrument_detail.py tests/test_task18_ui.py tests/test_task18_integration.py -q` - **31 passed**.
2. `python -m pytest tests/test_simple_scores.py tests/test_task18_integration.py tests/test_trust_critical_artifacts.py tests/test_benchmark_attribution.py tests/test_signal_gates.py tests/test_risk_analytics.py -q --tb=no` - 7 pre-existing data-fixture failures remain (missing trade-candidate CSV/secondary universe rows and identity artefact count); the affected attribution, gates, risk, integration and audit tests passed.
3. `python -m ruff check src/etf_cockpit/features/crowding.py src/etf_cockpit/features/regime.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py src/etf_cockpit/app/pages/risk.py tests/test_crowding.py tests/test_evidence_derivatives.py tests/test_instrument_detail.py tests/test_task18_ui.py` - **All checks passed**.
4. `python -m compileall -q src tests` - **passed**.
5. `git diff --check` - **passed**; Git only reported existing LF/CRLF warnings for tracked files.

## Remaining uncertainty and risk

The affected regression command still reports the seven baseline fixture failures listed above. Existing generated `data/.schema_versions/*.json` modifications were left untouched as required. Persisted scoreboard parquet is the source for the new UI friction panels; before a score run those panels intentionally show unavailable/N/A.
