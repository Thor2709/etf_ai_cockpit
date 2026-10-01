# Ordinary-fund exact-horizon forecasts

`analysis.fund_forecasts` produces an empirical total-return distribution from
available `FundReturnDecomposition.total_return` values for the same share
class, exact horizon, and selected currency. It accepts a sample only when its
decision time is in the past and its NAV window ends on or before the forecast
decision date. It does not recalculate NAV returns. Quantiles use the linear
empirical method at the configured 5th, 50th, and 95th percentiles.

The forecast policy is required under `forecast` in
`configs/fund_analysis_v1.yaml`: at least 30 baseline observations, at least
20 matured calibration observations, 90% target coverage, and q05/q50/q95
levels of 0.05/0.50/0.95. These are conservative deterministic defaults. The
loader rejects a missing section, unknown keys, invalid counts, out-of-range
coverage, or changed quantile levels.

The caller supplies the share class's known dealing frequency and out-of-sample
calibration evidence. Calibration entries carry a cohort key, exact horizon and
currency, a nonconformity score, `known_at`, and `matured_at`. The existing
`conformal_quantile_adjustment` helper selects the finite-sample adjustment;
quantiles expand by that amount on both tails. Entries matured at or after the
decision time, or not known by it, are excluded. When an `active_from` bound is
provided, both the known and matured dates must be on or after it; `active_to`
continues to bound the matured date. The evaluator does not exclude a fund
because it is currently closed or merged, so matured evidence inside its active
window remains available.

Calibration first checks the leaf key and then each parent key available in the
`FundPeerCohort` fallback hierarchy. It selects the first key with the required
number of matured observations and records the keys tried. Without sufficient
evidence the empirical quantiles remain `research_only` and probabilities stay
`None`. Calibrated loss probability is the baseline empirical share below zero;
beat-benchmark probability is the share strictly above the caller-supplied
same-horizon benchmark return and is `None` when either benchmark input is
missing.

`project_fund_recommendation` seals one analysis record through all five
configured risk-profile presets. Missing fee stack, benchmark, blocked analysis,
unavailable horizon, or uncalibrated distribution blocks every profile with
binding reasons. Without after-trade inputs, profiles are unavailable with
`risk_profile_after_trade_context_unavailable`. The existing portfolio
projection contract cannot currently score the fund distribution itself. A
`ValueError` rejecting supplied context records that profile unavailable with
`risk_profile_fund_context_unavailable`; unexpected projection exceptions
propagate. The shared risk-profile contract is unchanged. Execution remains
disabled. Top-*N* selection and all user interface work are outside this slice.
