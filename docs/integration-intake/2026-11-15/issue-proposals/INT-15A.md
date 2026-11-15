# INT-15A — Paper-bot optimiser challenger (B2-o)

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `C`; estimated size `medium`
- Logical prerequisites: `INT-09, INT-11`; source-file serialization: `-`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `portfolio/paper_bots.py; configs/paper_bots_v1.yaml`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Paper-bot optimiser challenger (B2-o)
- Gate G3 | Priority P2 | Size medium | Depends on: INT-09, INT-11 | Features: F0140, F0146, F0156
- Reference only: `AI4Finance-Foundation/FinRL-Trading@4409abe9` `src/strategies/base_strategy.py`.
- Targets: `portfolio/paper_bots.py` (`_build_decision:864`, `_challenger_spec:470`, `_REQUIRED_FAMILIES:51`, strategy set `:513`, `targets` `:1051`), `portfolio/paper_bots_execution.py` (`_plan:883`), `portfolio/paper_bots_replay.py`, `configs/paper_bots_v1.yaml`.
- Steps: B0-B3 stay immutable. Add the engine-challenger mechanism: a `WeightEngine` protocol receives matched score rows and price history and returns `targets: dict[str, float]`. First challenger `B2-o`: 80% VWCE and a 20% sleeve over the canonical `CANDIDATE_BUY` set (INT-09 makes that set forecast-aware), sleeve weights from `sk_min_cvar` with `budget = 0.20` and the existing caps. When the engine or its inputs are unavailable the decision record is `NO_NEW_TRADE` with a reason: existing positions are held, nothing is substituted. The challenger report adds a no-trade utility line and the out-of-sample walk-forward result net of costs with turnover, against B2.
- Acceptance: B0-B3 decision files are byte-identical before and after; challenger records are separate; a missing engine gives `NO_NEW_TRADE`; all paper-only guards hold (`portfolio/paper_bots.py:42`, `portfolio/paper_trading.py:2639`).
