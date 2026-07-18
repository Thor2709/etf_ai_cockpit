# Leakage-safe feature store

`etf_cockpit.features.feature_store.LocalFeatureStore` is the local research
contract for ISSUE-0119. Feature definitions record their source column,
version, lookback, availability delay, dependencies, units and missing-value
policy in the existing transactional store. Built-in baseline definitions are
visible even before a local catalogue has been populated.

Materialisation takes explicit decision timestamps. It selects the latest row
whose feature timestamp and, when present, `available_at` timestamp are both
known to be usable by that decision. Each row carries the definition hash and
a deterministic vintage hash. Missing values are visible or rejected by the
declared policy; they are never silently forward-filled.

Targets are registered separately and materialised from adjusted prices. They
carry maturity and embargo timestamps, so validation can reject overlapping
outcomes before fitting. Forward return, excess return, drawdown, tail and
threshold event labels are bounded local diagnostics. No target column is
copied into an inference matrix, and no target or model result grants order or
live-execution authority.

Offline, paper and disabled live-inference calls use the same definitions and
selection code. Coverage and bounded mean/missing-rate drift diagnostics are
reported for review; fitting, promotion and real-money execution remain out of
scope for this slice.
