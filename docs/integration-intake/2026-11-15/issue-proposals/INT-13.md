# INT-13 — Portfolio-aware Top-N and sizing

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `C`; estimated size `medium`
- Logical prerequisites: `INT-11, INT-12`; source-file serialization: `-`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `portfolio/top_n_selection.py; portfolio/sizing.py; portfolio/risk_profiles.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Portfolio-aware Top-N and sizing
- Gate G3 | Priority P2 | Size medium | Depends on: INT-11, INT-12 | Features: F0124, F0142, F0143, F0150
- Targets: `portfolio/top_n_selection.py` (`_marginal_impact:608-618`, `_utility_scores:577`), `application/selection_views.py` (`:276-293`), `portfolio/factor_risk.py` (read only), `portfolio/rebalancing.py` (`proposed_new_weight:105`), `portfolio/risk_profiles.py` (`:419-421`), `portfolio/sizing.py` (new).
- Steps: marginal contribution to active risk against VWCE from the selected covariance becomes `marginal_impact` (cash has zero risk and is part of the portfolio); `cost` from `portfolio/costs.py`; portfolio-level volatility targeting; fractional Kelly **only** when a calibrated return distribution exists for the candidate (INT-09 contract) and never from a ranker score; without it `sizing_method="caps_only"`; `risk_budget_ratio` becomes an active-risk limit. All existing caps stay and bind first.
- Acceptance: a candidate highly correlated with current holdings ranks below an equal-merit diversifier; no size exceeds an existing cap; without a calibrated distribution the Kelly path is not taken and the state says so.
