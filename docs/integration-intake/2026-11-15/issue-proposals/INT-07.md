# INT-07 — Estimates store and revision features

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G3`; lane `D`; estimated size `medium`
- Logical prerequisites: `INT-06`; source-file serialization: `-`
- Readiness: `BLOCKED_BY_DATA (no entitled estimates source)`
- Intended files: `data/estimates_store.py; data/fmp_provider.py; data/finnhub_provider.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Estimates store and revision features
- Gate G3 | Priority P1 | Size medium | Depends on: INT-06 | Features: F0030, F0056, F0014
- Readiness: blocked by data (no entitled source of observed estimate snapshots).
- Field reference only: `openbq-org/OpenBB@11290d8b` `openbb_platform/core/openbb_core/provider/standard_models/{analyst_estimates,forward_eps_estimates}.py`.
- Targets: `data/estimates_store.py` (new), `data/stock_research.py` (`consensus.csv` import `:34`, provider rejection `:1299`), `data/fmp_provider.py`, `data/finnhub_provider.py` (`_ENDPOINTS:33-38`), `data/forward_evidence_diary.py`, `analysis/stock_evidence.py` (`AnalystInputs:57`), `configs/score_engine_v3.yaml` (`analyst_revision` stays 0.0), `configs/data_source_policy.yaml`.
- Record: `EstimateObservation(instrument_id, metric, fiscal_period, mean, high, low, n_analysts, captured_at, source, entitlement, pit_grade)`.
- PIT rule: a revision is the difference between two **observed** snapshots. Only a snapshot captured by the Cockpit, or a vendor record with its own capture timestamp, is `observed`. A present-day history file with restated or undated values is `approximated`; it gives no revision feature and is not used in training.
- Features (from `observed` rows only): 30- and 90-day change in mean EPS scaled by price, breadth `(up - down) / n`, estimate-based surprise.
- Acceptance: a snapshot captured after the decision time is not used; `approximated` rows produce no feature; with no data every feature is `unavailable` and the weight stays 0.
