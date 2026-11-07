# Portfolio Optimiser Lab

The optimiser is a local research boundary, not an order-generation path. It
consumes a return matrix derived only from `adjusted_close`, keeps cash outside
the invested weights and returns a versioned solution with feasibility,
binding-constraint, warning and fingerprint evidence.

`portfolio.optimiser.PortfolioOptimiser` provides equal weight, inverse
volatility, minimum variance, equal risk contribution, a deterministic
HRP-like heuristic (nearest-neighbour ordering plus recursive bisection; not
canonical hierarchical risk parity, the old `hrp` id is a reported alias), maximum diversification, historical CVaR and a
conservative robust mean-risk method. These methods use NumPy and pandas
already required by the application; no paid solver, API key or remote quota
is required.

Every solve applies long-only min/max bounds, optional cash, turnover and
group caps. Infeasible numerical output is never accepted silently: the
contract returns a visible equal-weight fallback when that fallback is itself
feasible, otherwise an unavailable result with the exact failure. The held-out
comparison always includes equal weight, and sensitivity reports show the
effect of a bounded input perturbation.

The Flet Portfolio Optimiser Lab exposes method comparisons, a compact
risk-return frontier table, constraints, solver fingerprints and the
`execution_allowed=false` boundary. Rebalancing, tax lots, trade proposals,
broker adapters and execution are intentionally deferred to their own issues.

## Estimation semantics (#947)

- Covariance: training-window Ledoit-Wolf shrinkage toward a scaled identity
  (numpy), annualised x252 and PSD-repaired; fewer than 20 shared rows is an
  `insufficient_sample` status, not a matrix.
- Expected returns: the annual historical mean shrunk toward the zero active
  baseline by n / (n + 252). It is never labelled expected alpha; promoted
  forecasts (#811) enter only through the explicit `expected_returns` argument.
- Robust mean-risk: score = mean - 0.5 x standard error of the annual mean
  (sigma / sqrt(years)); no positive score is `unavailable`.
- CVaR: 5% tail, at least 5 tail observations; below that the result is
  `unavailable` with `sample_status=insufficient` (no equal-weight stand-in).
- Comparison: `compare(core_id=...)` adds core-only and core + sleeve references;
  all rows share the training head, validation tail, `cost_bps` per unit of
  turnover and date-block weight-stability figures.
