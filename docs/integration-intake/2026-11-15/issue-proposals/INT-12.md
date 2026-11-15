# INT-12 — Covariance and expected-return estimators

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `C`; estimated size `small`
- Logical prerequisites: `INT-11`; source-file serialization: `-`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `portfolio/robust_risk.py; portfolio/optimiser.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Covariance and expected-return estimators
- Gate G3 | Priority P2 | Size small | Depends on: INT-11 | Features: F0119, F0125
- Upstream: skfolio `src/skfolio/moments/covariance/{_oas,_denoise_covariance,_gerber_covariance,_ew_covariance}.py`, `moments/expected_returns/{_shrunk_mu,_equilibrium_mu}.py`, `prior/_black_litterman.py`.
- Targets: `portfolio/robust_risk.py` (`ledoit_wolf_covariance:254`, `_out_of_sample_selection:452`), `portfolio/optimiser.py` (`_covariance:470`, `_return_shrinkage_factor:463`).
- Steps: add the four estimators as candidates in `_out_of_sample_selection`; feed the selected estimator to the optimiser (today only Ledoit-Wolf or sample, `portfolio/optimiser.py:42`); add `ShrunkMu`, `EquilibriumMu`. Black-Litterman views come only from forecasts that are calibrated and promoted (INT-09 contract), with confidence from out-of-sample error; with no such forecast there are no views.
- Acceptance: the diagnostics name the estimator that `_out_of_sample_selection` chose; with no admissible view the posterior equals the equilibrium prior; inputs use only returns before the decision date.
