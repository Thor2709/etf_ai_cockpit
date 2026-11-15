# INT-16 — Point-in-time factor exposures

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `C`; estimated size `medium`
- Logical prerequisites: `INT-02`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `portfolio/factor_risk.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Point-in-time factor exposures
- Gate G3 | Priority P2 | Size medium | Depends on: INT-02 | Features: F0079, F0120
- Upstream (one-day spike, not adoption): skfolio `src/skfolio/prior/_characteristics_factor_model.py`.
- Targets: `portfolio/factor_risk.py` (`EXPOSURE_BASIS:23`, `build_factor_exposures:35`, `_fit_cross_sectional:447`).
- Steps: fit factor returns on descriptors and membership as known at each date (INT-02 panel), not on today's exposures; keep the Huber fit; state in the report that factor returns are estimates conditional on the descriptor set.
- Acceptance: a descriptor or membership change after date `t` does not change the factor return at `t`.
