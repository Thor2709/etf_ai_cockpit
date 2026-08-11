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

The canonical append transaction holds one persistent store guard across the
existing-ledger read, merge and atomic publication, so concurrent local writers
cannot both succeed while dropping one event. Canonical readback independently
requires the complete schema, provenance, validation result, non-executable
authority flags and content checksum. An incomplete or inconsistent ledger is
not displayed and cannot be republished by a later append.

The calendar is visible on Instrument Detail and News & Context. It is
filtered through the same availability/ingestion cutoff before either surface
renders rows. Each rendered row states the decision time and
`available_at_decision_time=true`; if the snapshot cutoff is absent or invalid,
no event row is disclosed as decision-time evidence. The mandatory path remains
local cache, official bulk/public data or user-owned import. Optional remote
quota failure stays visible and non-blocking under the source-policy contract.
The calendar is descriptive evidence only: `context_only=true`,
`execution_allowed=false` and
`executable_authority=false` are forced at persistence and presentation
boundaries. Remote provider refresh, broker actions, score changes and order
creation remain outside this slice.
