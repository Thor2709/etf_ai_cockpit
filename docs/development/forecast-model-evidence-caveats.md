# Forecast model evidence caveats

Boundaries and evidence limits for the optional forecast models (TimesFM 2.5, TimesFM 3.0, Toto 2.0). Execution stays disabled (`execution_allowed=false`).

## 1. Pretraining cutoffs and prospective evidence
- TimesFM 3.0's declared cutoff 2023-11-30 (Wikipedia to Nov 2023, Google Trends to end 2022) covers only some corpora. The model card also lists GiftEvalPretrain, synthetic and augmented data without a dated cutoff, so it does not prove 2024-2026 market data were absent.
- Prospective evidence for every optional model starts after its first verified local run (recorded `created_at`).
- Rows without a verifiable `created_at` or `model_version` are "unverifiable" and never promotion evidence.

## 2. Promotion thresholds are policy, not proof
- The thresholds (>=100 matured instrument/origin pairs, >=5 origin dates, 60-session horizon, lower MASE, no worse direction accuracy, non-weak calibration) are guardrails.
- Pairs on the same date and overlapping 60-session windows are correlated; no confidence interval or significance test is computed yet.
- Eligibility applies only to the evidence horizon.

## 3. Quantile approximations
- q05/q95 are derived from q10/q90 by a normal approximation.
- Coverage widening by `1/sqrt(coverage)` is a heuristic.
- Toto horizon quantiles aggregate daily half-widths in quadrature, ignoring serial covariance.
- Every row carries `quantile_method` provenance; none of these are validated 80%/90% intervals.

## 4. Point forecasts and units
- Point forecasts are medians (`point_statistic`) in log-return units; the UI converts with `expm1`.

## 5. Weights and licences
- Weights should be pinned by SHA256 with licence flags.
- TimesFM 3.0 weights are non-commercial; the owner approved personal use on 2026-10-11.

## 6. Runtime
- The model extras need Python >=3.12 (toto-2) and `timesfm==3.0.2`.
- The owner machine uses a CUDA torch build; CPU torch is the fallback.
