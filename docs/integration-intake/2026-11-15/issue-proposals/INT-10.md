# INT-10 — Valuation completion

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `A`; estimated size `medium`
- Logical prerequisites: `INT-03`; source-file serialization: `INT-04 (data/stock_research.py)`
- Readiness: `READY`
- Intended files: `data/capital_efficiency.py; data/stock_research.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Valuation completion: WACC, EBITDA, peer statistics, Monte Carlo
- Gate G3 | Priority P2 | Size medium | Depends on: INT-03 | Features: F0055, F0057, F0066, F0067, F0068
- Upstream (reference only): `AI4Finance-Foundation/FinRobot@63e1884a` `finrobot_desktop/finrobot/engine/compute/operators/wacc.py` (`calculate_wacc`, `adjust_beta_blume`), `.../monte_carlo.py` (`run_monte_carlo`, `deterministic_seed`).
- Targets: `data/capital_efficiency.py` (`build_cost_of_capital_ledger:92`, CAPM `:101-102`), `data/stock_research.py` (`_intrinsic_value:2915`, `_driver_dcf:3128`, `_reverse_dcf:2986`, EV/EBITDA `:445-448`, `_peer_relative_valuation_metrics:3285`), `analysis/peer_cohorts.py` (`normalize_peer_metric:403`), `application/valuation_views.py`.
- WACC: market-weighted CAPM cost of equity (Blume-adjusted beta) and after-tax cost of debt. Cost of debt is a **proxy** (`interest_expense / average debt`, status `proxy`, not the marginal forward rate) and has an override input; risk-free rate and equity premium are in the valuation currency; tax-rate source is stated; financials, zero or negative debt, and capitalised-interest cases give `not_meaningful`.
- EBITDA = EBIT + D&A when not supplied. Peer z-score and shrunk percentile through `normalize_peer_metric`.
- Monte Carlo: seeded draws over the assumptions of the native `_driver_dcf` (growth, margin, WACC, terminal growth), independent unless a correlation is configured; seed from `(instrument_id, as_of)`; output percentiles, labelled scenario-dependent with the assumption set. The native DCF stays the only DCF definition.
- Acceptance: WACC equals a hand fixture; with all dispersions at zero the Monte Carlo result equals the deterministic DCF exactly; a one-driver toy case with a linear value function matches its analytic mean and variance within sampling tolerance; the same seed gives the same output; a bank gives `not_applicable`. (No requirement that the median equals the central DCF: the DCF is non-linear.)
