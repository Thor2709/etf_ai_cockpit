# Future-only / no-authority

This document is future-only and has no authority. It is a reconciliation
design note, not an implemented execution workflow and not permission to
connect to or control an external account. The current cockpit remains
local-first with `execution_allowed=false` and `executable_authority=false`.

## Exact split authority (future)

The immutable local ledger owns local intents, approvals, policy decisions, and
audit history. The official broker API owns external account, order, fill,
position, and cash state. A separately governed broker record can be stored only
as an external observation with its provider reference, status, timestamp, and
checksum; it cannot overwrite local intent, human approval, source snapshot,
policy, or audit history.

The immutable local intent would include a unique idempotency identifier,
canonical instrument identity, explicit account scope, side, decimal-safe
quantity, limit price, decision time, evidence checksum, and human confirmation
record. A preview is evidence of what a person reviewed; it is not a submission.

Idempotency is exact: the same ID with an identical immutable payload and
checksum returns the previously recorded status. The same ID with any payload
or checksum difference is rejected and quarantined as an intent conflict.

## Reconciliation contract (future)

A future read-only or separately approved adapter would compare intent ID,
instrument identity, quantity, monetary value, position size, timestamps,
session, status transitions, provider reference, and audit checksum. Decimal
money and quantity handling would be exact and deterministic. Duplicate intent
IDs would return the already recorded status rather than create a duplicate.

Any divergence between local intent/approval history and official broker
account/order/fill/position/cash state, or any unknown or stale state, would
block new submission and automated retries until reconciled by an authorised
human process. Conflicting, partially filled, cancelled, or out-of-order states
would be quarantined for manual review. A timeout would require reconciliation
before retry and could never justify a retry storm or inferred success.
Market-hours, stale-data, news/event, daily turnover, daily loss, drawdown kill
switch, cooldown, and emergency-disable gates would block the future transition
before reconciliation could be treated as approval.

## Audit and release evidence

Every future run would publish an immutable manifest linking local proposal,
policy and evidence checksums, preview, explicit human confirmation, broker
observation, rejection or cancellation reason, and reviewer disposition. The
manifest would preserve the distinction between local source-of-truth state
and an external observation; it would not create execution authority.

Progression would require a new approved authority record, independent
security and recovery review, deterministic tests, package parity evidence,
and an auditable emergency-disable drill. Until that separately approved design
exists, the cockpit records advisory evidence only and keeps
`execution_allowed=false` and `executable_authority=false`.
