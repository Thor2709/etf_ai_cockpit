# Decision Architecture v1

Decision Architecture v1 adds a read-only scoring language alongside the frozen
v3 score engine. It consumes existing canonical calculation results and keeps
their source values, timing and quality separate from peer-relative scores.

## Pipeline

1. Existing producers calculate canonical metrics. `ScoredMetric` records the
   calculation ID, value and unit, effective and known times, source, normalized
   authority and freshness factors, comparison scope, shape, requirement class
   and quality. It does not calculate accounting or valuation formulas.
2. `decision_domains_v1.yaml` binds calculation IDs to domains and subfamilies,
   weights, comparison scopes, requirement classes and rank authority. Its
   SHA-256 is computed over the complete LF-normalized YAML registry.
3. `peer_cohorts` selects the point-in-time cohort and retains its existing
   MAD clipping, weighted mid-rank, effective sample size and parent shrinkage
   (`k=5`). Orientation is applied after ranking. The normalized z value is the
   inverse normal CDF of the shrunk percentile clipped to `[0.01, 0.99]`.
   Target-band metrics rank distance from the configured band; threshold metrics
   cap values at their configured plateau.
4. The domain engine takes a weighted mean within each subfamily, then gives
   each subfamily its configured domain weight. A displayed 0–100 value is
   emitted only when a point-in-time domain reference cohort is supplied.
   Coverage and confidence stay separate from the domain score.

## Contracts and invariants

`InstrumentDecisionAssessment` carries eligibility and gate results, explicit
domain and opportunity slots, formula and evidence hashes, drivers and warnings.
Empty evidence stays `UNAVAILABLE`; an inapplicable conditional metric is `N/A`.
A missing critical input makes its domain `INSUFFICIENT_EVIDENCE`, while missing
optional evidence lowers coverage. Confidence is domain coverage multiplied by
mean authority × freshness × reliability over available inputs. Reliability is
source coverage × (`1 − uncertainty`); confidence never changes the rank. Gate
and context-only metrics are recorded outside the peer rank. Every assessment
has `execution_allowed=false`.

Nothing with `known_at` or `effective_at` after decision time can contribute.
Peer scopes are explicit: `UNIVERSE`, `SECTOR`, `INDUSTRY`, `BUSINESS_MODEL`,
`ETF_CATEGORY` and `ETF_EXPOSURE_PEERS`. ETF category and exposure groups must
be supplied by their later mapping work; missing groups cannot silently become
rank evidence. No network, LLM-set values or additional dependency is used.

## Migration policy

The v3 formula file, output fields and default remain frozen. This layer writes
no v3 field and does not replace the replay comparator. Stock and ETF domain
mapping, opportunity ranking and weight optimization remain later issues. Any
cutover requires a separately versioned policy, point-in-time replay comparison
and explicit acceptance; until then v3 remains the default.
