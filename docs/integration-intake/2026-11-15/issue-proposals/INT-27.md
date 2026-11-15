# INT-27 — Chronos-2 forecast adapter (shadow)

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P4`; gate `G4`; lane `B`; estimated size `medium`
- Logical prerequisites: `INT-01, INT-09`; source-file serialization: `-`
- Readiness: `NEEDS_AUTHORITY (U1: extra not yet approved)`
- Intended files: `models/chronos2_adapter.py; application/forecast_service.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Chronos-2 forecast adapter (shadow)
- Gate G4 | Priority P4 | Size medium | Depends on: INT-01, INT-09 | Features: F0094, F0108
- Upstream: `amazon-science/chronos-forecasting` v2.3.2 (`0aba28e9`, Apache-2.0), `src/chronos/chronos2/pipeline.py` (`Chronos2Pipeline`); weights `amazon/chronos-2` (apache-2.0 per the model card; pinned by revision and hash).
- Targets: `models/chronos2_adapter.py` (new; duck contract of `models/timesfm_adapter.py:28`), `application/forecast_service.py` (`:193-202`, `:298-337`), `models/model_promotion.py` (`OPTIONAL_MODELS:35`), `models/local_weights.py` (`:48`), `models/registry.py` (`:13`), `configs/model_settings.yaml`.
- Target transformation: the input series is the adjusted log price level; level quantiles are converted to horizon log-return quantiles with the same conversion as `timesfm_level_forecast_to_results` (`models/timesfm_adapter.py:327`). Covariates: only series known at the forecast date (past values of benchmark and sector-ETF returns); no future covariates. The model's training cut-off is recorded; evaluation uses data after it; calibration through the existing conformal path; comparison against the baseline out of sample in the Forecast Lab.
- Acceptance: with weights absent `is_available()` is false and the run continues; output units match `ForecastResult`; the socket-denial test passes.

---

## Repair ledger (findings from the code audit; each has a disposition)

| Finding | Disposition |
|---|---|
| `pypdf` imported at `data/pillar3_extract.py:200`, declared nowhere | fix in INT-01 |
| Runtime SEC path uses the filing date as known-at | fix in INT-06 |
| No producer of `absolute_merit_evidence` | fix in INT-09 |
| Optimiser ignores the estimator chosen by `_out_of_sample_selection` | fix in INT-12 |
| `ytd_to_discrete` (`analysis/stock_metrics.py:801`) has no caller | fix in INT-03 |
| Registry formulas without callers (`analysis/stock_metrics.py:741`, `:750`, `:759`, `:768`) | fix in INT-04 |
| `ensemble.allow_dynamic_weights` in `configs/model_settings.yaml` has no reader | defer with F0111; the key stays and is listed here until dynamic weighting is built or the key is removed |
| `scikit-learn` declared but not imported in `src/` | keep; skfolio needs it |
| Stooq provider not registered in `ProviderRegistry` | scope exclusion (F0013, low value) |
| Paper-bot cost path excludes market impact (`portfolio/paper_bots_execution.py:395`) | scope exclusion: liquid names and a EUR 40,000 portfolio; revisit if position sizes grow |
| Model zoo "ridge / elastic-net / robust" entries are closed-form stubs | defer; INT-08 replaces the `tree_boosting` card only |

## Deferred (no issue until evidence exists)
CatBoost ranker; Kronos; statsforecast baselines; Optuna search; dynamic ensemble weights; triple-barrier labels; text sentiment; goal-based projections; a 252-session learned model. See `DECISIONS_210.csv`.
