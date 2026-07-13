# Task 18 fix3 report

## Task completed

Closed the fresh Task 18 Important findings without expanding approved scope. Risk friction values now render non-finite numbers as `N/A` with an explicit unavailable scenario; regime and portfolio-fit consumers retain their original forward-fill compatibility; benchmark attribution remains clean-overlap/no-forward-fill; and selected cluster risk contributions remain normalised shares. Execution remains disabled (`execution_allowed=false`).

## Files and symbols examined

- `src/etf_cockpit/app/pages/risk.py`: `_pct`, `_number`, `_friction_edge_panel` and numeric display helpers.
- `src/etf_cockpit/features/regime.py`: `build_market_regime`, `build_portfolio_fit_lookup`, `build_benchmark_attribution_lookup`.
- `src/etf_cockpit/features/crowding.py`: `_cluster_risk_contributions` and selected-cluster row publication.
- `tests/test_task18_ui.py`, `tests/test_evidence_derivatives.py`, `tests/test_crowding.py`.

## Findings or changes

- Added a RED regression for `NaN`, `None` and `+/-inf` Risk friction values; finite checks now return `N/A` and non-finite cost scenarios return `unavailable` rather than leaking `nan`/`inf` text.
- Restored the exact prior `pivot.ffill().pct_change(fill_method=None)` path in `build_market_regime` and `sort_index().ffill()` path in `build_portfolio_fit_lookup`.
- Preserved `build_benchmark_attribution_lookup` without forward-fill. Added sparse-price compatibility coverage proving regime/portfolio expected forward-fill while a single clean peer remains sector attribution `N/A`.
- Added a focused assertion that selected cluster risk contributions sum to one normalised share across clusters; production normalisation was already present at this HEAD.

## Evidence

### RED

- `python -m pytest -q tests/test_task18_ui.py::test_risk_friction_panel_formats_non_finite_edge_values_as_unavailable` failed because the panel emitted `nan bps`, `inf bps`, `-inf` and `nan` scenario text.
- `python -m pytest -q tests/test_evidence_derivatives.py::test_sparse_price_compatibility_keeps_regime_and_portfolio_forward_fill_but_not_peer_attribution` failed because regime volatility and portfolio correlation used the no-forward-fill path.

### GREEN

- Focused RED-GREEN assertions passed: `3 passed` for the new Risk UI, sparse compatibility and cluster normalisation tests.
- Task 18 bundle passed with `48 passed`:
  `python -m pytest tests/test_task18_integration.py tests/test_crowding.py tests/test_benchmark_attribution.py tests/test_friction_edge.py tests/test_evidence_derivatives.py tests/test_signal_gates.py tests/test_instrument_detail.py tests/test_risk_analytics.py tests/test_task18_ui.py -q`.
- Ruff, compileall and diff checks passed.

## Commands or tests run

- `python -m pytest ...` focused RED and GREEN commands above.
- `python -m pytest tests/test_simple_scores.py tests/test_score_history.py tests/test_portfolio_review_reports.py tests/test_risk_analytics.py -q`: six known baseline fixture failures in `tests/test_simple_scores.py` (missing `yahoo_trade_candidates_*.csv` and secondary/Sparebanken fixture rows; affected risk/score-history/portfolio-review tests passed).
- `python -m ruff check src/etf_cockpit/app/pages/risk.py src/etf_cockpit/features/regime.py tests/test_task18_ui.py tests/test_evidence_derivatives.py tests/test_crowding.py --no-cache`: all checks passed.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed; only existing LF/CRLF warnings were reported.

## Remaining uncertainty and risk

The six simple-score failures are pre-existing fixture/data-state failures unrelated to this change. Generated `data/.schema_versions/*.json` modifications were left untouched as required. No full release/browser gate was run.

## Recommended next action

Review commit `fix: preserve regime compatibility and honest risk UI states` and rerun the parent branch's full release matrix after restoring the missing candidate fixture data.
