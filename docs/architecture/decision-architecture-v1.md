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
mean authority × freshness × explicit reliability evidence over available
inputs. Metric coverage is reported separately and is not multiplied into the
confidence factors; confidence never changes the rank. Gate
and context-only metrics are recorded outside the peer rank. Every assessment
has `execution_allowed=false`.

## ETF decision graph

ETFs have a separate Vehicle Rank and Exposure Opportunity Rank. Vehicle metrics
use `ETF_EXPOSURE_PEERS`; their output domains are Tracking,
Cost/Implementation, Diversification and Structural risk. Equity exposure uses
the point-in-time look-through summary through the shared DA-001 domain engine.
Bond, commodity and multi-asset exposure remains `UNAVAILABLE` until its adapter
exists. Tracking Difference uses the canonical compounded value from
`etf_economics` (fund return minus benchmark return, annualised); its provenance
records `td_definition: compounded (canonical etf_economics)`. Tracking Error
uses the canonical `sqrt(A) * sigma(a)` value. When the matched TD history is
reliable, expected ETF return is index return plus canonical TD minus trading
costs; otherwise it is index return minus TER, structural drag and trading
costs. The selected method is recorded with the expected return evidence.

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

## Rank validation and promotion record

DA-005 replays QV, QVM, the balanced Q/V/M challenger and the named
`score-engine-v3` comparator using a frozen `decision_cutover_v1.yaml` policy.
The default validation window is 21 sessions with at least 20 point-in-time
members, twelve development and holdout decision dates, Top/Bottom five
portfolios, three chronological subperiods, and the conservative `t >= 3`
haircut. Sector and size neutralization require three members per group. These
are v1 research defaults, not estimates from production outcomes.

Every replay cutoff requires a dated membership snapshot whose
`snapshot_complete` flag is true and whose rows include `instrument_id`,
`valid_from`, `valid_to` and `known_at`. Membership intervals are half-open;
missing, incomplete or not-yet-known snapshots make that date insufficient.
Evidence, price availability and issue-0128 round-trip costs are checked at
their knowledge times. Ranks are frozen before forward prices are read.
Delisted members remain in the decision-time universe and use an explicit
terminal price or delisting return; missing terminal outcomes fail validation.

Candidate selection uses only the expanding-window development folds returned
by the shared Forecast Lab walk-forward splitter. The owner supplies a fixed
holdout date set before inspection; `promotion_decision` evaluates that set
without using it to select the challenger. Promotion requires the challenger
to beat QV and QVM net of costs, meet the rank-IC or top-minus-bottom `t >= 3`
haircut, and outperform both baselines in all three holdout subperiods. QV is
the fallback champion when no challenger passes. If QV does not beat v3, the
record keeps v3 active with the reason.

Each promotion record binds its validation id, rationale, complete PIT
availability, incremental IC, selected rank and authority decision. The
pre-existing DA-001 domain-registry flags continue to govern shadow metric
normalization; a DA-005 canonical metric authority grant is emitted only
through `metric_rank_authority_record` with a complete promotion record. The
rank monitor reuses ISSUE-0124 drift and paired
net-performance assessments; a warning requests review and never retires a
rank automatically. The owner must run real-data validation and record its
result in `rank_cutover.promotion_record`. `rank_cutover.enabled` is false by
default, so the Screener, score history and Instrument Detail keep v3 as their
default until that record exists and the owner enables the flag. The v3
comparator remains available after cutover.
