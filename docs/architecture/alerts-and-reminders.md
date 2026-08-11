# Local alerts and review reminders

ISSUE-0033 adds a local-only alert record family for review evidence. Alerts
are persisted as `local_alert` records through the existing
`TransactionalStore`; the record family does not add a storage migration or a
second event store. SQLite WAL transactions and the existing per-record CAS
revision protect snooze and dismissal updates from stale writers.

## Contract

The accepted alert types are material score change, rank change, news
conflict, stale data, model forecast failure, review date arrived, risk limit
breached and target drift exceeded. Every record carries typed severity
(`info`, `warning`, `critical`) and confidence (`low`, `medium`, `high`). Its
ID is the SHA-256 of the alert type, subject ID and caller-supplied dedupe key,
so repeated observations of the same identity are deterministic and do not
create duplicate records.

Alert state is durable: active alerts may be snoozed until a future UTC time,
dismissed, or expired by their optional UTC expiry. Expiry and completed
snoozes are materialised with the same CAS revision guard. Malformed or
unknown fields, naive timestamps, invalid domains and `execution_allowed=true`
are rejected.

The default is informational and non-blocking. `AlertBlockPolicy` is an
explicit caller-owned policy; only a supplied policy can classify a record as
blocking, and only while the alert is active. Portfolio incidents are limited
to risk-limit breach and target drift; model incidents are limited to forecast
failure. An order preview may record the same typed risk-limit breach under
the explicit `order` incident domain, but the alert remains informational and
cannot submit, amend or cancel an order. Execution remains `false`.

The application seam accepts strict `AlertTriggerObservation` values. It uses
fixed per-type thresholds and evidence fields to generate the eight accepted
alert records, then persists them through `AlertStore`; false or below-
threshold observations produce no record. This is a bounded generation seam,
not a general rules engine.

Historical evaluation accepts an `as_of` timestamp and includes only records
whose `available_at` is no later than that timestamp. It also evaluates
snooze using its persisted `snoozed_at` transition, plus dismissal and expiry
as they existed at the cutoff, preventing future evidence or current state from
leaking into bounded backtests.

## Readback

The Dashboard shows the active alert digest and local alert history under the
existing Activity Log. Instrument Detail shows alerts scoped to the selected
instrument. Snooze and dismiss operations are exposed through the local
Dashboard controls using expected revisions and only update the local store;
Instrument Detail remains read-only. Unavailable/corrupt local storage is
shown as an explicit manual-review state, distinct from a healthy empty
digest. There is no email, push, webhook, provider notification, broker write
or execution authority.
