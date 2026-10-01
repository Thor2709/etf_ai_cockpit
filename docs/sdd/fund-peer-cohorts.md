# Ordinary-fund peer cohorts

## Scope and contracts

`fund_peers.py` builds advisory-only ordinary-fund cohorts from slice-A
`FundAnalysisRecord` values, `FundShareClass` identity, fund lifecycle events,
and `InstrumentContextV2` classification. Cohorts use the shared peer engine's
point-in-time filtering, fallback, support, deduplication, and peer statistics.
The fund scope is enabled only for `ordinary_fund` contexts; stock and ETF
scope rules remain on their existing paths. Every new contract has
`execution_allowed=False`.

The dimension order is vehicle, mandate, disclosure benchmark or classified
objective, geography and sector, asset class, currency hedge, distribution
policy, applicable duration and rating, fee tier, and dealing class. A known
prefix of that order defines the available leaf and its progressively broader
parents. Unknown or conflicted values stop target refinement; candidate funds
without a value cannot match a cohort level that needs it. Missing vehicle
classification leaves no safe fund parent and the engine abstains.

Fund classification leaves require the existing minimum leaf confidence.
Distribution policy and returns come from the fund share-class and slice-A
contracts. Fee tiers use configured upper-bound bands over slice-A total fees.
Each share class uses its linked `sub_fund_id`, or the record's `fund_id` when
that relationship is absent, as its economic strategy ID. The current
`FundShareClass` contract has no primary or representative flag, so a strategy
uses the class with the earliest known launch date; where launch evidence is
absent, the earliest available return-history start is used. Ties are broken by
`share_class_id`. This selection is independent of return values, and the rule
and collapsed class IDs are recorded on the cohort.

Peer values are the slice-A `return_decomposition.total_return` values. A
peer from a different requested horizon is inapplicable. Its return window
must also have the same calendar-day length as the target window and end within
the configured calendar-day tolerance; otherwise the peer is excluded with
`window_misaligned`. Cohorts below the configured minimum support abstain with
`INSUFFICIENT_PEER_SUPPORT` after the shared engine has completed parent
fallback.

## Lifecycle and point-in-time rules

Known `LAUNCHED` lifecycle events set `active_from`; the earliest known
`CLOSED`, `MERGED`, or `LIQUIDATED` event sets the exclusive `active_to`
boundary. Lifecycle events whose `available_at` is after the requested
decision time do not set a boundary. Target and peer return records must be
known by the requested decision time. The shared engine excludes observations
known after decision time and observations outside their active window. The
cohort carries each retained peer's slice-A lifecycle-risk evidence.

## Disclosure-benchmark metrics

Benchmark comparisons consume the existing trusted `TotalReturnEvidence`
contract. The window record and every periodic fund record must be known by the
requested decision time. Its instrument ID must equal the fund record's
disclosure benchmark, its currency must equal the selected fund-return
currency, and its `known_at` must be no later than decision time. Every periodic
fund record must also match the window record's fund, share class, and selected
currency. Benchmark index values must exist on the exact fund window and
periodic return dates. Missing evidence, identity or currency mismatch, date
mismatch, and too few periods produce unavailable metrics with a reason and no
zero fill.

Excess total return is slice-A fund total return minus the benchmark index
return over the same explicit window. Index and passive mandates also receive
tracking difference and tracking error when their aligned periodic series meet
the configured minimum. Tracking difference is the annualized compounded fund
return minus the annualized compounded benchmark return. Tracking error is the
sample standard deviation of periodic return differences multiplied by the
square root of the observed periods per year. Periods per year are inferred as
the number of aligned periods multiplied by 365.2425 and divided by elapsed
calendar days. No fixed trading-day count is assumed.

The API accepts only the disclosure benchmark identified by the fund record;
broad-market opportunity anchors remain a distinct comparison layer and are
not mixed into these metrics.

## Defaults

`configs/fund_analysis_v1.yaml` sets minimum peer support to 3, minimum
tracking history to 12 periodic observations, and peer window-end tolerance to
5 calendar days. Fee-tier upper bounds are 25, 50, 100, and 200 basis points;
the final tier is open-ended. These are conservative internal
cohort-stratification defaults, not fee-quality claims. The strict loader
rejects missing or malformed peer settings and missing, malformed, unordered,
or negative fee bands.
