# Portfolio Optimiser Lab

The optimiser is a local research boundary, not an order-generation path. It
consumes a return matrix derived only from `adjusted_close`, keeps cash outside
the invested weights and returns a versioned solution with feasibility,
binding-constraint, warning and fingerprint evidence.

`portfolio.optimiser.PortfolioOptimiser` provides equal weight, inverse
volatility, minimum variance, equal risk contribution, a deterministic
HRP/HERC baseline, maximum diversification, historical CVaR and a
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
