# Event calendar evidence

The event calendar is a local-first context ledger for dated earnings,
dividend/ex-dividend, split/corporate-action, filing, guidance, fund
rebalance, index-change, review-date and high-risk observations.
Each row retains an event identity, source authority, source URL, precision,
timezone and both availability and ingestion timestamps.

Rows are eligible for point-in-time replay only when both timestamps are at or
before the decision time. Date-only events are valid context; timed events and
availability metadata require explicit offsets, and `timezone_name` must name
a real IANA timezone (including `UTC`). A date-only snapshot cutoff is
normalised to explicit UTC end-of-day; a datetime cutoff without an offset is
ambiguous and fails closed. Conflicting observations from the same source are
rejected rather than resolved by last-write-wins.

For timed events, the timestamp's calendar date in the declared timezone must
match `event_date`. Minute precision permits zero seconds but rejects nonzero
seconds and fractional components; second precision rejects fractions. Imports
preserve missing timezone and precision metadata for explicit validation failure
instead of supplying UTC or date precision. Existing inconsistent ledgers fail
closed without automatic rewriting; historical defaults cannot retrospectively
be distinguished from source-supplied metadata.

The canonical append transaction holds one persistent store guard across the
existing-ledger read, merge and atomic publication, so concurrent local writers
cannot both succeed while dropping one event. Canonical readback independently
requires the complete schema, provenance, validation result, non-executable
authority flags and content checksum. An incomplete or inconsistent ledger is
not displayed and cannot be republished by a later append.
Each clean row is also bound to its exact contained raw JSON path and payload,
and the audit row count, frame checksum and complete per-row validation entries
must match. Missing, extra, nested, escaped, symlinked or altered raw evidence,
an inconsistent audit, duplicate rows or conflicting observations invalidate
the whole bundle. Event dates are lexical `YYYY-MM-DD`; datetime suffixes are
never discarded during validation.

The calendar is visible on Instrument Detail and News & Context. It is
filtered through the same availability/ingestion cutoff before either surface
renders rows. News & Context discloses event time, precision, source identity and
authority, timezone, availability and ingestion timestamps. Each rendered row states the decision time and
`available_at_decision_time=true`; if the snapshot cutoff is absent or invalid,
no event row is disclosed as decision-time evidence. The mandatory path remains
local cache, official bulk/public data or user-owned import. Optional remote
quota failure stays visible and non-blocking under the source-policy contract.
The calendar is descriptive evidence only: `context_only=true`,
`execution_allowed=false` and
`executable_authority=false` are forced at persistence and presentation
boundaries. Remote provider refresh, broker actions, score changes and order
creation remain outside this slice.

Explicit preview blackout policies are the sole exception to non-blocking
context. `EventBlockPolicy` is immutable and checksummed and selects only
`proposal_preview` and/or `order_preview`, event types, risk levels and elapsed
pre/post minutes. Both type and risk selections must match. No policy means
`context_only`; missing or corrupt calendar evidence is non-blocking in that
case. An applicable explicit policy requires the complete canonical local
bundle; unavailable evidence blocks that preview with `evidence_unavailable`.

Evaluation filters availability and ingestion at the aware decision timestamp
before matching. Date-only observations cover the complete local IANA calendar
day (including DST), with an exclusive next-midnight boundary. Timed events use
their explicit instant and inclusive blackout endpoints. Extra minutes extend
these boundaries as elapsed UTC time. The decision binds target, instrument,
timestamp, complete policy and policy checksum, visible calendar-frame checksum,
matched event identities/checksums, status and reason in a decision checksum.
Future observations cannot enter the visible-frame checksum. Persisted replay
verifies these bindings without querying today's calendar.

Operations exposes an opt-in local earnings/high-risk, high/critical policy with
a 24-hour pre/post window. It defaults off. A blocked preview retains its audit
evidence but cannot be confirmed or submitted as a local preview workflow. Live
execution remains independently disabled. Event controls never generate scores,
signals, targets, quantities, proposals, orders or execution authority.
