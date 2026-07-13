# Task 18 review-fix report

## Task completed

Closed the blocking review findings for `ISSUE-0052`, `ISSUE-0059` and `ISSUE-0064` without changing score weights, action labels, research/portfolio authority or execution behaviour. Crowding now records ranked concentration, weighted cluster risk contribution and per-row pair coverage; attribution supports configured sector and theme peer sets on the same overlapping interval; score friction fields are sourced from `estimate_friction_edge`; and the new evidence is visible in Scores, Risk, Instrument Detail and trust exports.

## Files and symbols examined

- `src/etf_cockpit/features/crowding.py`: `ClusterRow`, `ClusterReport`, `build_correlation_clusters`.
- `src/etf_cockpit/features/benchmark_attribution.py`: `AttributionResult`, `build_benchmark_attribution`.
- `src/etf_cockpit/features/regime.py`: `build_benchmark_attribution_lookup`, configured peer attribution.
- `src/etf_cockpit/signals/simple_scores.py`: score model, scoreboard frame, crowding integration and `_friction_edge_fields`.
- `src/etf_cockpit/data/trust_artifacts.py`: canonical crowding/attribution/score-history schemas and writers.
- Scores, Risk, Instrument Detail and Trust Evidence controls.
- Focused numerical and integration tests under `tests/`.

## Findings or changes

- Added optional `ranked_instruments` and `weights` keyword arguments while preserving the existing crowding call signature. Rows now expose clean sample size, pair sample size/coverage, ranking weight, cluster weight, cluster risk contribution and top-ranked concentration. Sparse singleton rows no longer inherit the global sample count.
- Recomputed final score ranking crowding after score ordering and passed ranked evidence through trust export. Risk and Instrument Detail show contribution and coverage rather than warning counts alone.
- Added configured theme peer attribution alongside sector peers. Theme-only metadata is accepted; no sector/theme metadata remains explicit `N/A`.
- Changed benchmark attribution returns, beta/correlation and alpha inputs to the same tail of the overlapping return join. Sector and theme peer calculations use the same interval and publish sample size.
- Routed score gross cost, net edge and edge-to-cost fields through `estimate_friction_edge` with configured low/base/high costs and volatility. Missing inputs remain unavailable with reason text; `execution_allowed` remains false.
- Extended scoreboard, score history, benchmark attribution and correlation-cluster trust schemas with the new evidence fields.

## Evidence

### RED

`pytest -q tests/test_crowding.py tests/test_evidence_derivatives.py tests/test_simple_scores.py -k 'ranked_weights or sparse_instrument or overlapping_horizon or theme_only or friction_fields_equal'` returned `4 failed` before production changes:

- `build_correlation_clusters` rejected `ranked_instruments`.
- Sparse singleton published global `sample_size`.
- Theme-only attribution had no `theme_attribution_status`.
- `_friction_edge_fields` did not accept calculator inputs.

### GREEN

`pytest -q tests/test_crowding.py tests/test_benchmark_attribution.py tests/test_evidence_derivatives.py tests/test_friction_edge.py tests/test_task18_integration.py tests/test_instrument_detail.py tests/test_risk_analytics.py tests/test_signal_gates.py` returned `40 passed`.

`pytest -q tests/test_trust_critical_artifacts.py -k 'production_score_history_persists_real_dimensions or trust_artifacts_for_scores or correlation or benchmark'` returned `1 passed`.

`python -m ruff check` on all edited source/tests passed; `python -m compileall -q src` passed; `git diff --check` passed.

## Commands or tests run

- Focused RED command above.
- Focused GREEN and trust-writer commands above.
- Ruff, compileall and diff checks.

## Remaining uncertainty and risk

- The complete trust suite retains one pre-existing fixture failure: `test_static_trust_artifacts_cover_providers_and_identity` expects at least 45 identity rows, while the local fixture contains 16. This is unrelated to the Task 18 changes.
- Full release/package/browser gates were not run in this focused fix branch.
- Low/base/high cost stress uses configured spread + slippage + FX bps with deterministic 0.75x/1x/1.5x multipliers; commission remains unavailable without a notional.

## Recommended next action

Review commit `fix: close Task 18 attribution and crowding review findings`, then run the parent branch release matrix after restoring the missing identity/candidate fixture data.
