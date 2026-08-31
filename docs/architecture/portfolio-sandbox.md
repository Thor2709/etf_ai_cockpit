# Portfolio sandbox boundary

ISSUE-0021 is a local, deterministic, non-executable what-if boundary. The
domain module validates target intent and derives allocation evidence; the
application module binds it to a selected account/portfolio/as-of snapshot,
calls existing optimiser/risk/cost services, and owns local persistence and
the sandbox-specific export. `/portfolio` consumes this boundary and does not
call providers, storage or broker code directly.

## Snapshot and holdings contract

`portfolio_snapshot_binding()` records account, portfolio, one canonical
snapshot/as-of, universe revision, the checksum of the selected `direct`,
`look_through` or `combined` rows, the adjusted-price revision and checksum,
and the selected view. The same canonical as-of is the cutoff for overlap
evidence. Invalid view names or malformed lineage fail closed. A missing
account or snapshot identity uses an explicit deterministic local fallback;
it is never inferred from a broker write.
Identity selectors cannot relabel the supplied snapshot: a requested account,
portfolio or snapshot must exactly match its immutable identity or analysis
fails closed. Supporting multiple identities requires supplying the matching
resolved snapshot rather than a list of labels on one data object.
Holding rows retain direct versus look-through lineage, asset type, market
value, source id and capability state.

The source checksum is line-level and order-independent. Each selected line
binds its own weight and value to its lineage/source identifiers and every raw
classifier or resolver input used by capability policy; duplicate lines are
not collapsed before hashing. Duplicate instrument capability outcomes use a
deterministic fail-closed precedence, so any rejected line prevents that
instrument from becoming actionable regardless of row order.

The sandbox submits actionable rows to `resolve_instrument_capability()` using
complete raw classifiers or descriptors derived from the canonical config
rule. It never trusts a parallel allowlist. Missing or contradictory
classifiers are explicit unavailable/unsupported outcomes, including when the
canonical matrix itself marks a family unavailable. Full
ETF resolution, nested-fund exposure and unresolved-weight propagation remain
the ISSUE-0022 engine; the sandbox displays available direct/look-through
evidence and does not invent or redistribute missing holdings.
Configured target-only instruments are resolved from canonical config-derived
descriptors through the same policy; absence from current holdings is not a
capability bypass.

## What-if evidence

Each result contains current/target weights, signed marginal weight effect,
applicable constraint outcomes, explicit no-trade/inapplicable/blocked
`why_not` reasons, before/after rows, direct/look-through holdings and source
binding. The application attaches the selected holdings/reference binding
before service composition. Target-based risk, factor, attribution and stress
producers receive an adapter containing the candidate target weights; actual
current weights remain separate for baselines and optimiser turnover limits.
The existing optimiser comparison, factor-risk, robust-risk, rebalance,
attribution and scenario producers retain their calculation authority. Prices
and dated features use the resolved reference window and decision cutoff,
and producers share the governed candidate universe. Missing positive-target
prices, optional scenario inputs and unsupported mixed-asset rebalance cases
remain explicit limitations, not invented zero exposure or available trades.
No optimiser, covariance, risk or cost calculation is duplicated in the UI.

Usable adjusted returns, not the presence of a price row, determine input
coverage. Positive current exits remain part of optimiser turnover coverage;
an unpriced exit cannot disappear from the constraint. A cash-only target does
not invoke an equal-weight invested fallback. Benchmark prices remain available
to attribution separately from the investable universe, and scenario coverage
retains unsupported positive candidate exposure as an explicit limitation.
The reference window is intersected with the snapshot cutoff (date-only
snapshots include that complete day); dated optional features, costs, cashflows
and decisions are also bounded by their effective and knowledge times.

The result is stored separately as `portfolio_sandbox_result` so the saved
`portfolio_sandbox.v1` candidate remains intent-only and backward compatible.
Candidate and result publication uses one local CAS transaction with
independent expected revisions; a missing legacy result has expected revision
zero. The result payload is `portfolio_sandbox_result.v1`, has an exact field
set and checksum, cross-binds the exact candidate record revision and payload
checksum, is bound to the selected holdings and adjusted-price source
snapshot, and is also the
exact sandbox-specific JSON export contract. Derived values are always
recomputed when a saved candidate is loaded against a changed snapshot; stale
result evidence is not surfaced as current. A saved mixed-asset intent remains
readable when an unconfigured instrument later leaves current holdings; its
derived result becomes stale and is recomputed under current capability rules.
Candidate and result records are read in one SQLite read snapshot, preventing
a mixed-revision pair.

Service evidence identity additionally binds the consumed feature, tax-lot,
cost, cashflow, decision and scenario inputs, reference identity and holdings
view. Changed inputs invalidate derived evidence rather than being confused
with tampering of an unchanged saved result. DataFrame projections retain
columns, row indexes and values so dates and covariance/exposure axes survive
the existing result/export serialization boundary. No general persistence or
publication mechanism is introduced.

## Proposal and execution boundary

The only downstream hand-off is a non-executable, pre-`ISSUE-0130` draft
envelope. It is checksum-bound to candidate, result, snapshot and service
evidence; unsupported, partial, unavailable, constraint-violating and
no-trade rows are listed as rejected and cannot enter `changes`. It does not
claim proposal-policy acceptance.
Any applicable aggregate portfolio-constraint violation rejects every proposed
change. The hand-off checksum covers the complete immutable envelope,
including changes, rejected rows and why-not evidence.
The sandbox does not call proposal submission, paper acceptance, order
creation, broker code or the live ledger. Every candidate, result, export and
draft envelope carries `execution_allowed=false`; selecting, saving, loading,
analysing or exporting a sandbox candidate cannot mutate live portfolio state.

Optimiser internals (ISSUE-0113), full ETF overlap/look-through (ISSUE-0022),
order submission and the broader generic export registry are outside this
boundary.
