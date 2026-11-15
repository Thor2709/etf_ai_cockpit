# INT-11 — skfolio optimiser backend

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G2`; lane `C`; estimated size `medium`
- Logical prerequisites: `INT-01`; source-file serialization: `-`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `portfolio/optimiser_skfolio.py; portfolio/optimiser.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

skfolio optimiser backend
- Gate G2 | Priority P2 | Size medium | Depends on: INT-01 | Features: F0122, F0123, F0124, F0126
- Upstream: `skfolio/skfolio@77210905` (1.12.9, BSD-3-Clause): `src/skfolio/optimization/convex/_base.py` (shared parameters), `convex/_mean_risk.py` (`MeanRisk`), `convex/_risk_budgeting.py`, `convex/_benchmark_tracker.py`, `optimization/hierarchical/_seriation/_hrp.py`, `hierarchical/_clustering/_herc.py`, `hierarchical/_clustering/_nco.py`, `measures/_enums.py` (`RiskMeasure.CVAR`).
- Targets: `portfolio/optimiser_skfolio.py` (new), `portfolio/optimiser.py` (`METHODS:22-31`, `OptimiserConstraints:56`, `OptimiserSolution:73`, `PortfolioOptimiser.solve:132`, fallback `:213-239`, `_project_weights`), `application/portfolio_optimiser.py`.
- Capability matrix (parameters confirmed in the upstream constructors at the pin). The native `cash_weight` is fixed and invested weights sum to `1 - cash_weight` (`portfolio/optimiser.py:59-64`). A constraint that a method cannot honour gives `status="unavailable"` with reason `constraint_unsupported:<name>`; nothing is dropped or rescaled silently.

| Method id | skfolio class | Cash (`cash_weight > 0`) | Min / max weight | Group caps | Turnover limit | Tracking error |
|---|---|---|---|---|---|---|
| `sk_mean_variance`, `sk_min_cvar` | `MeanRisk` | yes, `budget = 1 - cash_weight` | yes | yes (`groups`, `linear_constraints`) | yes (`max_turnover`, `previous_weights`) | optional (`max_tracking_error`) |
| `sk_risk_budgeting` | `RiskBudgeting` | no (no `budget` parameter) | yes | yes | no | no |
| `sk_min_tracking_error` | `BenchmarkTracker` | no (budget fixed at 1.0) | yes | yes | no | objective |
| `sk_hrp`, `sk_herc` | `HierarchicalRiskParity`, `HierarchicalEqualRiskContribution` | no | yes | no | no | no |
| `sk_nco` | `NestedClustersOptimization` | no | by inner estimator | no | no | no |

- Steps: map the constraints per the matrix; after every solve run the native feasibility check (sum, caps, group caps, turnover, within tolerance) and return `unavailable` when it fails; map skfolio and solver exceptions (infeasible, solver error, non-convergence) to the native statuses, never let them escape; return `OptimiserSolution` with `model_version="skfolio-1.12.9"` and `execution_allowed=False`. Old method ids and their results do not change.
- Acceptance (solver correctness only): a 2-asset minimum-variance case equals the closed form; every supported constraint is met on a fixture; each unsupported combination returns `constraint_unsupported`; an infeasible problem and a missing package return `unavailable` without an exception. Out-of-sample value is measured in INT-15A, not here.

## Gate G3 - economic capabilities
