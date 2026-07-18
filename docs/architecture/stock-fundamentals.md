# Stock fundamentals evidence

`ISSUE-0023` retains the existing five-section fundamentals contract as a compatibility surface while hardening its evidence boundary. Valuation, profitability, leverage, growth and shareholder return remain measurements, not actions or universally comparable recommendations.

Canonical rows require a valid, non-future as-of date and all five finite, non-boolean values to be score-eligible. Stale, malformed, future or incomplete rows remain visible with warnings but fail closed for screening ranks. Missing values are never converted to zero or negative evidence.

Source merging is deterministic only for matching canonical instrument and reporting period. Official evidence may outrank vendor evidence within that boundary; mismatched source rows are excluded and force manual review. Persisted rows retain compact per-section provenance alongside source authority, as-of date, missing fields, stale fields, limitations and sector-relative availability.

Screener and Instrument Detail expose the same five-section values and lineage. Instrument Detail also carries available canonical statement history, coverage and reconciliation evidence. All outputs set `execution_allowed=false` and `executable_authority=false`.

Sector-specific adapters, new remote provider integrations, universal scoring thresholds, forecast conversion and broker/execution authority remain outside this initial hardening slice.
