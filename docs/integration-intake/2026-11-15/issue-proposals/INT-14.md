# INT-14 — Volatility, tail and bootstrap models

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `C`; estimated size `medium`
- Logical prerequisites: `INT-01`; source-file serialization: `INT-12 (portfolio/robust_risk.py)`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `models/volatility_models.py; portfolio/robust_risk.py; validation/protocol.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Volatility, tail and bootstrap models (arch)
- Gate G3 | Priority P2 | Size medium | Depends on: INT-01 | Features: F0105, F0113, F0121, F0136
- Upstream: `bashtage/arch` v9.0.0 (`ef63ff46`, NCSA): `arch/univariate/mean.py` (`arch_model`, `HARX`), `arch/univariate/volatility.py` (`GARCH(p, o, q)`; GJR = `o=1`), `arch/bootstrap/base.py` (`StationaryBootstrap`, `optimal_block_length`), `arch/bootstrap/multiple_comparison.py` (`SPA`, `MCS`).
- Targets: `models/volatility_models.py` (new), `features/volatility.py` (`ewma_volatility:13`), `signals/signal_pipeline.py` (`:208`), `portfolio/robust_risk.py` (`_bootstrap_uncertainty:496`, `_tail_risk_report:541`), `validation/protocol.py` (`_paired_block_bootstrap:540`).
- Steps: GJR-GARCH(1,1) and HAR as shadow challengers to EWMA; evaluation by QLIKE on **variance**: forecast variance of the `h`-session log return against the realised-variance proxy (sum of squared daily log returns over the same `h` sessions, floored at a small epsilon), out of sample, same dates for all models; convergence status stored; stationary bootstrap with `optimal_block_length` as an option; EVT tail with `scipy.stats.genpareto`; `SPA` / `MCS` as optional validation reports.
- Acceptance: non-convergence returns the EWMA value with a warning status; the report shows QLIKE per model with the horizon and the number of out-of-sample points.
