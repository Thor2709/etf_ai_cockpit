# INT-02 — Point-in-time cross-sectional panel

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P0`; gate `G1`; lane `B`; estimated size `medium`
- Logical prerequisites: `-`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `features/panel.py; features/feature_store.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Point-in-time cross-sectional panel
- Gate G1 | Priority P0 | Size medium | Depends on: none | Features: F0118, F0065, F0106
- Upstream: none. Name reference only: `microsoft/qlib@54355232` `qlib/contrib/data/handler.py` (`Alpha158`).
- Targets: `features/panel.py` (new), `features/feature_store.py` (`LocalFeatureStore.materialise:154`, `build_targets:238`, `leakage_check:336`), `analysis/decision/rank_validation.py` (`replay_rank_panel:232`, `price_momentum_risk_evidence:1677`, `_forward_return:1229`), `data/replay_membership.py`, `validation/protocol.py` (`build_walk_forward_splits:131`, read only).
- Interface:
  - `build_pit_panel(decision_times, membership, feature_ids, horizons=(63, 126)) -> DataFrame`, one row per `(decision_time, instrument_id)`.
  - Each feature group has a column `<group>_available_at`. A feature value is null when its `available_at > decision_time` or its `pit_grade` is `approximated`.
  - Labels: `fwd_total_<h>` and `fwd_excess_<h>` (candidate total return minus VWCE total return, EUR, simple return over `h` sessions), with `label_start`, `label_end`, `label_available_at` (= first session open after `label_end`). Delisting handling from `_forward_return`.
  - Versions: `panel_version`, `feature_set_version`, `label_version` stored with the Parquet file.
  - `date_grouped_folds(panel, spec) -> folds`: calls `build_walk_forward_splits(n_samples=<number of unique decision dates>, spec, strict_label_purge=True)` on the sorted **unique decision dates** and maps folds to rows by date. Then it removes every training row whose `label_available_at` is after the validation-fold start. It never splits by row position.
  - `panel_evidence_inventory(panel) -> dict`: unique decision dates, instruments per date, matured labels per horizon and fold, number of non-overlapping periods per horizon, share of delisted names, membership source and its PIT grade.
- Steps: build on replay membership (no survivors-only universe); join features and targets on `(instrument_id, decision_time)`; per-date cross-sectional transforms; interaction columns `quality_x_value`, `value_x_momentum` as per-date rank products; run `leakage_check` on the joined frame.
- Acceptance:
  - No feature with `available_at > decision_time` is non-null.
  - A late revision of an input after `decision_time` does not change the row.
  - Shuffling the input rows gives an identical panel and identical folds.
  - No decision date is in two folds; no training row has `label_available_at` after its validation-fold start.
  - A delisted name keeps its label.
- Out of scope: any model.
