# Wave 5 Task 18 - Crowding, Sector/Theme Attribution and Friction-Adjusted Edge

Owning issues: `ISSUE-0052`, `ISSUE-0059`, `ISSUE-0064`.

## Binding acceptance

- `build_correlation_clusters(prices, metadata, window=120) -> ClusterReport`
  computes rolling correlation clusters only when enough clean adjusted-price
  data exists, preserves `as_of`/sample/window evidence, uses configured
  metadata for sector/theme labels, and returns explicit unavailable states
  rather than inventing clusters.
- `build_benchmark_attribution(instrument_returns, broad_returns,
  sector_returns) -> AttributionResult` reports broad and sector-relative
  returns/alpha proxies, beta/correlation and sample/as-of/source evidence;
  missing or insufficient sector data is explicit `N/A`.
- `estimate_friction_edge(evidence_score, volatility, costs, scenario)
  -> FrictionEdgeResult` returns deterministic gross edge, volatility penalty,
  selected cost, net edge, ratio and scenario; unsupported inputs are
  unavailable and never execution authority.
- Scores, Risk and Instrument Detail expose cluster/crowding, broad/sector
  attribution and gross/net edge/cost scenario with honest `N/A` states.
- Trust/audit/export fields remain source-aware and `execution_allowed=False`;
  no score weights, model authority, portfolio targets, research thresholds,
  coverage scope or execution behaviour may change.
- Theme warnings come from configured sector/theme metadata and cluster
  membership only; do not infer themes from company names or model output.

## Existing seams to preserve

- `src/etf_cockpit/features/crowding.py` and
  `src/etf_cockpit/features/benchmark_attribution.py` are existing public
  calculation modules to strengthen compatibly.
- `src/etf_cockpit/features/regime.py` owns the existing benchmark lookup;
  preserve its wrapper and current score consumers.
- `src/etf_cockpit/signals/friction_edge.py` and
  `src/etf_cockpit/signals/simple_scores.py` own current edge fields and
  score-row integration; preserve action labels and authority boundaries.
- `src/etf_cockpit/data/trust_artifacts.py` owns canonical derived artifact
  schemas and atomic dual persistence for correlation and attribution.
- Reuse current `Scores`, `Risk`, `Instrument Detail` and trust-evidence
  controls/tokens; no page-specific design system or decorative filler.

## Required workflow

Use RED-GREEN-REFACTOR. Add deterministic numerical and insufficient-data
tests before behavioural implementation and record exact commands/output in
`.ai_worklog/task-18-report.md`. Cover known correlation clusters and theme
concentration, missing sector benchmark, gross/net bps, low/base/high costs,
provider/price absence, audit/export fields, and `execution_allowed=False`.
Run focused tests, affected regressions (`test_evidence_derivatives.py`,
`test_simple_scores.py`, `test_risk_analytics.py`, `test_signal_gates.py`,
trust/audit export tests), Ruff, compileall and diff checks. Do not edit issue
ledgers or closure matrix; parent handles integration and closure-pending
records. Commit implementation and report on the task branch.

## Explicit non-goals

No execution, broker integration, credential storage, product redesign,
sector-specific score weights, autonomous portfolio management or unrelated
repository refactor.
