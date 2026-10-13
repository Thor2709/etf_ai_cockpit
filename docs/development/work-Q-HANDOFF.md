# Work-Q handoff
BASE: fix/work-G 54c25f4e; branch fix/work-Q; local commits only (no push, no weights written, execution_allowed=false).
WHAT CHANGED: new models/model_promotion.py decides per optional model (timesfm, timesfm3, toto) from stored forecasts + prices known at as-of; ForecastService applies it to every run (CLI, refresh workflow, candidates), so model_allowed_in_score follows the evidence. Rows carry oos_mase/oos_directional_accuracy, promotion_state, leakage flags. Weights and ensemble untouched.
WHAT CHANGED: Forecast Lab live: shadow/beta wording gone; per-model state, MASE/direction vs baseline, leakage flags (new "Promotion and leakage" card); tests/ui assertion "shadow_only" -> "Not yet proven" (framing replaced, same strength).
PROMOTION RULE: at the 60-day scoring horizon, model vs baseline on identical (instrument, origin date) pairs matured from prices <= as-of: pooled oos_mase lower, oos_directional_accuracy not lower, calibration grade not "weak".
THRESHOLD (configs/model_settings.yaml `promotion`): 100 matured pairs AND 5 distinct origin dates; conservative because pairs from one date share the market move. `enabled: false` = diagnostic only.
LEAKAGE: origin must be strictly after the cutoff (timesfm3 2023-11-30) or, for unknown cutoffs (timesfm, toto), after the model's first stored forecast date.
PER-MODEL STATE (owner copy, as-of 2026-10-09; run_forecasts.py + refresh-path DataService run): all 0 counting.
 timesfm 2.5: not yet proven, 33 of 100 matured, 3 of 5 dates; MASE 0.911 vs 0.966, direction 48.5% vs 57.6%.
 timesfm 3.0: not yet proven, 0 of 100 (only the 2026-10-09 origin exists, not matured).
 toto: not yet proven, 33 of 100, 3 of 5 dates; MASE 1.125 vs 0.966, direction 51.5% vs 57.6%.
 Contrary to expectation, June-July 2026 TimesFM/Toto runs already matured 33 pairs each; still below the minimum.
BUGS FIXED: (1) Forecast Lab graded only the latest run, so matured/walk-forward/error panels were empty; now uses all stored runs (1,903 rows, 312 matured, 4 folds). (2) Workflow summary claimed optional models are kept out of the main workflow. (3) Promotion MASE changed with the price window; evidence now uses the full stored history.
TESTS: tests/test_work_q_promotion.py (4) + test_work_q_page.py (2) pass. Requested suite 146 pass, 0 fail.
PARITY IMPACT: none new. tests/refactor_parity: same 9 failures with identical difference counts (368/281/231/46) on base 54c25f4e and this branch; test_optional_models_golden passes. Goldens not regenerated.
OPEN: repo default stays shadow_optional_models=false (work-G test pins it); owner config has true, so the refresh workflow runs the models only there. timesfm3 has no ensemble weight, so once promoted it enters distributions but not forecast_component_maps. Toto now returns ok on the owner copy (global package changed since work-G) with implausible 60-day bands (vol 1.0-2.5): Toto branch should validate; June "toto" rows predate that. First-run date comes from stored history, so a backfilled old run would lower it.
