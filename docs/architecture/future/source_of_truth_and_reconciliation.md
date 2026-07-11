# Future-only / no-authority

This document is future-only and has no authority. It is a reconciliation
design note, not an implemented execution workflow and not permission to
connect to or control an external account.

## Proposed source hierarchy (future)

The local evidence ledger would remain the source of truth for observations,
proposals, approvals and policy decisions. A separately governed provider
record could be stored as an external observation with its own timestamp,
provider reference, status and checksum. It would not overwrite the local
intent or approval record.

## Reconciliation questions (future)

Reconciliation would compare immutable intent identifiers, instrument identity,
quantities, status transitions, timestamps and provider references. Unknown or
conflicting states would be quarantined for human review. A timeout, partial
response, stale approval or checksum mismatch would block reconciliation rather
than promote an inferred state.

Every future run would publish a manifest linking the local proposal, approval
decision, provider observation and reviewer disposition. Until that separately
approved design exists, the cockpit records only advisory evidence and keeps
`execution_allowed=false` and `executable_authority=false`.
