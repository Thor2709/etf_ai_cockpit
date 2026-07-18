# Macro regime dashboard

ISSUE-0026 adds a bounded, local-first context view at `/macro`.

The dashboard consumes the existing bitemporal `MacroWarehouse` for saved
macro/factor observations and the existing adjusted-close price snapshot for
deterministic proxy context. It reports:

- equity, bond/cash and gold/defensive proxy availability;
- breadth as the share of local instruments above their 200-day adjusted-close
  moving average;
- median annualised 20-day volatility;
- the existing transparent market-regime label;
- a dashboard label constrained to `risk-on`, `neutral`, `defensive`,
  `stressed` or `unknown`;
- local inflation/rates observations when their availability cutoff is valid;
- as-of date, freshness and local provenance.

Missing proxy categories are rendered as unavailable. The dashboard never
fetches a provider, substitutes raw close for adjusted close, or silently
invents macro data. Stale price gaps are not forward-filled beyond five
observations. FRED remains an optional probe-only capability. All output
is `context_only`, with `score_eligible=false`, `execution_allowed=false` and
`executable_authority=false`; it cannot create scores, expected returns,
orders or broker actions.

Vintage-aware macro observations remain available through
`MacroWarehouse.as_of(root, dataset_id, decision_time)`. This first slice does
not implement revised-data scenario modelling, a remote refresh workflow or a
macro-to-order path.
