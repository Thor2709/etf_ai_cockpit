# Synthetic scenarios

ISSUE-0118 provides a deterministic local fixture generator for robustness and
invariant tests. A `SyntheticScenarioSpec` records the seed and bounded rates
for regimes, jumps, volatility clustering, missing observations, restatements,
corporate actions, provider conflicts and execution failures.

Every output frame carries `synthetic=true`; the dataset metadata also records
the generator version, full specification and a content hash. The validation
report is evidence that invariants hold, not evidence of expected return.
`promotion_eligible=false` is structural and synthetic-only performance is
excluded by `promotion_guard`.

The Training Centre displays a seeded robustness summary. Generated data remain
separate from imported market data and no broker, model-fitting or live
execution path is called.
