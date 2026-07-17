# Robust risk evidence

`etf_cockpit.portfolio.robust_risk` provides a local, evidence-only risk model for the Risk workspace. It does not authorise trading or broker activity and returns `execution_allowed=False` for every report.

The report keeps sample, EWMA, shrinkage, winsorised robust, diagonal and optional ISSUE-0110 factor-model covariance estimators side by side. Every matrix is symmetrised and PSD-repaired with the pre- and post-repair minimum eigenvalues recorded. Condition number, effective sample and positive-semidefinite diagnostics are retained for audit.

Estimator selection uses held-out covariance Frobenius error. When the history is too short, the report explicitly marks validation unavailable and falls back to the sample estimator. Component contributions are calculated from the selected covariance and reconcile to portfolio variance.

Tail evidence includes downside volatility, 95% VaR, expected shortfall, maximum drawdown, lower-tail dependence, a traded-value liquidity multiplier, deterministic block-bootstrap uncertainty and calm/stress regime comparisons. Inputs include adjusted prices and, when available, volume and current allocation weights. Missing or insufficient inputs produce readable partial or unavailable evidence rather than inferred values.

The Risk page surfaces the selected estimator, diagnostics, uncertainty interval, tail measures, estimator comparison and regime/liquidity evidence. All displayed results remain local and read-only.
