# INT-08 — Cross-sectional LightGBM ranker

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G3`; lane `B`; estimated size `large`
- Logical prerequisites: `INT-01, INT-02`; source-file serialization: `INT-05 (configs/decision_cutover_v1.yaml)`
- Readiness: `READY (U1 approved 2026-11-15)`
- Intended files: `models/cross_sectional_ranker.py; models/model_zoo.py; configs/model_settings.yaml`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Cross-sectional LightGBM ranker
- Gate G3 | Priority P1 | Size large | Depends on: INT-01, INT-02 | Features: F0065, F0089, F0103, F0104, F0107
- Upstream: `lightgbm-org/LightGBM` v4.7.0 (`8f7036f0`, MIT), `python-package/lightgbm/sklearn.py`: `LGBMRanker` (lambdarank; rows sorted by query, `group` = list of rows per query), `LGBMRegressor(objective="quantile", alpha=...)`. Model files in the LightGBM text format (the registry rejects pickle and joblib, `features/training_centre.py:57`).
- Targets: `models/cross_sectional_ranker.py` (new), `models/model_zoo.py` (`tree_boosting` card), `configs/model_settings.yaml` (`lightgbm:` block), `features/training_centre.py` (`LocalTrainingRegistry:83`), `configs/decision_cutover_v1.yaml`, `analysis/decision/rank_validation.py`.
- Frozen inventory:

| Model id | Kind | Target | Output contract |
|---|---|---|---|
| `gbdt_rank_63`, `gbdt_rank_126` | `LGBMRanker` | per-date quintile of `fwd_total_<h>` (subtracting the VWCE return per date does not change within-date ranks) | ordinal score, unitless, ranking only |
| `gbdt_q_63`, `gbdt_q_126` | 3 x `LGBMRegressor` (0.1, 0.5, 0.9) | `fwd_excess_<h>` | return distribution: VWCE-relative simple return, EUR, horizon `h` sessions, uncalibrated until its out-of-sample coverage check passes |

  A 252-session model is not built: the history gives too few non-overlapping periods. B2 uses the 126-session models; B3 uses no learned model.
- Preflight gate (before any training run): `panel_evidence_inventory` must meet the minima set in `configs/model_settings.yaml` (unique decision dates, instruments per date, matured labels per fold, non-overlapping out-of-sample periods per horizon, PIT-graded membership). If not, the card reports `insufficient_evidence` and no artefact is registered.
- Training rules: folds from `date_grouped_folds` only; every fitted transform (imputation, encoders) is fitted on the training fold; training cut-off stored with the artefact; rows sorted by decision date and `group` built from per-date counts; fixed seed, deterministic mode, CPU.
- Outputs: `score_column` values `gbdt_rank_63`, `gbdt_rank_126` as challengers against `QV`, `QVM`, `v3`. Quantile models write `ForecastResult` rows (`core/types.py:46`) with `model_allowed_in_score=False`; crossing quantiles are sorted and flagged; they reach INT-09 only through the calibration path.
- Evaluation: rank-IC and top-minus-bottom net of costs on out-of-sample dates through the existing rank validation; coverage of the quantile models out of sample.
- Acceptance: the same input gives the same model text twice; shuffled input rows give the same model; no date is in both training and validation; no training row has `label_available_at` after the validation start; a failed preflight gives `insufficient_evidence`; without `lightgbm` the card is `unavailable`.
- Out of scope: promotion, CatBoost, search beyond `validation/optimisation.py:312`.
