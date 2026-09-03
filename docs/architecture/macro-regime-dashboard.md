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

## Snapshot-bound application projection

`application.macro_context.build_macro_context_binding` binds warehouse
summary, observations, curves and adjusted-price context to the same explicit
snapshot decision cutoff. A missing or invalid cutoff is unavailable; it does
not select an arbitrary future date. Date-only price closes are effective at
day end. Selected-row summaries use that decision cutoff rather than raw
history counts. The page distinguishes observation, publication, availability,
revision and ingestion timestamps, and renders country/currency, confidence,
transformation/source identities and explicit limitations.

Selected warehouse observations also pass through the existing
`macro-scenario-context.v1` producer. Warehouse observations do not establish
user-authored scenario links or financial driver semantics: derived links are
explicitly unavailable under that existing contract. Missing authority,
portfolio currency or a finite positive horizon is not replaced with guessed
context. This is not a persisted scenario registry, portfolio shock result,
validated causal relationship or forecast. Source/evidence/link identities and
limitations remain visible; `context_only=true`, `score_eligible=false`,
`forecast_authority=false` and `execution_allowed=false` remain unchanged.
No warehouse, transformation, storage, provider or order authority is added.
Existing warehouse initialization and availability-selection semantics remain
unchanged; this view does not claim ingestion-bound historical replay.
