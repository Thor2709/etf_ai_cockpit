# work-R handoff — forecast return-distribution contract and uncertainty gate

ROOT CAUSE: three stacked defects hid the uncertainty gate. (1) No producer wrote q05/q25/q75/q95 or coverage_ratio, so the canonical vector was never complete. (2) Even when complete, `forecast_return_distributions` nulled q10/q90 whenever the total-return contract was unavailable (no price/income/fx components, identities or horizon validation exist in production rows), so the decomposition always saw "q10/q90 width unavailable". (3) Behind the gate: live-but-unpromoted Toto/TimesFM kept their ensemble weight, so every legacy total_score and confidence was NaN.

WHAT CHANGED (commits f8ec026e, b95a1510, e935e975, 1eef5d72):
- distribution_store: `complete_return_quantiles`, `history_coverage_ratio`, `derived_quantile_columns` (one rule for all producers); ForecastResult gains q05/q25/q75/q95, quantile_method, coverage_ratio (appended columns).
- baseline, TimesFM 2.5/3.0 (live + mock), Toto (live + mock) fill them; forecast_scores adds `uncertainty_band` (point-in-time, coverage-widened gross q10/q90); uncertainty.py falls back to it. Thresholds, weights, promotion, execution_allowed untouched.
- Bugs fixed with tests: baseline used prices after the forecast date; Toto mock returned NaN without peer series; scoring ensemble NaN for unbacked live models.

QUANTILE/COVERAGE RULES: keep the model's q10/q50/q90. q25/q75 = midpoint of the model's own q20/q30 and q70/q80 (TimesFM log-return space; Toto per step, half-widths aggregated in quadrature like q10/q90); baseline/mock models: normal approximation. q05/q95 = q50 -/+ half-width x z95/z90 (1.2835) for every producer. quantile_method = `normal_from_q10_q90.v1` or `native_deciles_q25_q75_interpolated+normal_tails_q05_q95.v1`. Crossing/missing input -> all derived fields stay missing. coverage_ratio = finite adjusted log returns known at the forecast date / 252, capped at 1, missing when none; model coverage in the distribution = min over models.

OWNER-COPY RESULT (two forecast runs, then signals): all 80 ok rows per model have the full monotone vector + coverage (min 0.31–0.33 for SPACEX/KMAR.OL). Uncertainty "available" for 80/81; the 1-day instrument stays "forecast_uncertainty_unavailable". blocked_by: portfolio_validation_block 81, forecast_confidence_below_threshold 80, insufficient_history 4, forecast_uncertainty_unavailable 1.

TESTS: tests/test_work_r_producers.py (4), test_work_r_uncertainty_band.py (2), test_work_r_unbacked_models.py (1). Requested suite, calibration, aggregation, work_b and signal tests pass.

GOLDENS REGENERATED: optional_models and persisted_schema only — forecast rows gained the six new columns (no existing value changed).

OPEN: forecast_confidence_below_threshold is the structure confidence cap = 0.0 for all 81 (no structural evidence in the owner copy) — data gap, not a forecast defect. portfolio_validation_block untouched. Canonical total-return contract (components, model/target identity, horizon validation) still has no producer, so canonical_status stays unavailable. Toto coverage counts returns on its aligned multivariate calendar (slightly below baseline, 69 rows <1). model_zoo research rows and Toto's no-price mock (zero quantiles) were not changed.
