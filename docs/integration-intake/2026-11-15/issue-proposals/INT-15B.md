# INT-15B — Paper-bot ranker challenger (B1-r)

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `C`; estimated size `small`
- Logical prerequisites: `INT-08, INT-15A`; source-file serialization: `-`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `portfolio/paper_bots.py; configs/paper_bots_v1.yaml`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Paper-bot ranker challenger (B1-r)
- Gate G3 | Priority P2 | Size small | Depends on: INT-08, INT-15A | Features: F0104, F0140
- Targets: `portfolio/paper_bots.py`, `configs/paper_bots_v1.yaml`.
- Steps: `B1-r` = top 10 by `gbdt_rank_63`, equal weight, same caps and cadence as B1, through the INT-15A mechanism. The ordinal score selects; it does not size.
- Acceptance: as INT-15A; with the ranker `unavailable` or `insufficient_evidence` the record is `NO_NEW_TRADE`.
