# Leakage-safe validation protocol

`etf_cockpit.validation.protocol` owns temporal validation boundaries, not
model training. Callers provide per-observation trial scores and receive an
immutable, fingerprinted report containing the split definition, folds,
retained trial records, uncertainty, regime/subgroup summaries and promotion
decision.

Development folds are rolling or expanding walk-forward windows. Labels are
purged by the configured forecast horizon and a separate embargo keeps future
observations out of the training window. A final tail is reserved before any
trial is selected; `final_test_used_for_selection` is structurally false and
discarded trials remain in the report.

The local application facade exposes a read-only preview in Training Centre
and Backtests. It proves the protocol from adjusted-price returns without
training or promoting a model. Real trial scores, model registries and
champion/challenger promotion remain separate issues.
