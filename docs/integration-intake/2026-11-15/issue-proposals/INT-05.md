# INT-05 — Shadow quality and value sub-scores

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G3`; lane `A`; estimated size `medium`
- Logical prerequisites: `INT-02, INT-04`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `configs/decision_cutover_v1.yaml; analysis/stock_evidence.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Shadow quality and value sub-scores
- Gate G3 | Priority P1 | Size medium | Depends on: INT-02, INT-04 | Features: F0052, F0054, F0055, F0151
- Targets: `configs/decision_cutover_v1.yaml` (`rankers:` with `score_column`), `analysis/decision/rank_validation.py` (`RankerSpec:72`, `_EVIDENCE_COLUMNS:60`, `evaluate_rank_validation:497`), `analysis/stock_evidence.py` (`:1219-1263`), `docs/architecture/canonical-score-engine-v3.md`.
- Candidates (each a `score_column` challenger, plus one combined `quality_v2`): gross profitability, Sloan accruals (negative), net share issuance (negative), Piotroski F, asset growth (negative), incremental ROIC (`data/capital_efficiency.py:759`), shareholder yield (`data/capital_allocation.py:432`).
- Steps: columns come from the INT-02 panel (so the PIT rule and date-grouped folds apply); add ranker entries; run the existing replay; write the result table to the existing validation artefact. No weight changes; canonical v3.3.0 is immutable here.
- Acceptance: each challenger appears with rank-IC and top-minus-bottom on out-of-sample dates only; canonical v3.3.0 scores are byte-identical.
