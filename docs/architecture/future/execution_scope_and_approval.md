# Future-only / no-authority

This document records a possible future governance shape. It is not an
implemented execution capability, does not grant authority, and must not be
read as permission to send an order or change a risk gate.

## Scope

The current cockpit remains local-first decision support. It may produce dated
signals, manual-review proposals, evidence packages and audit records. Those
records are advisory and retain `execution_allowed=false` and
`executable_authority=false`.

Any future execution work would be a separately approved programme with an
explicit threat model, independent review, migration plan and release gate. A
future design would first define the allowed instrument universe, account
scope, human approval step, idempotency rules, failure handling and immutable
audit evidence. None of those controls exists in the current application.

## Approval sequence (future)

1. Governance records a change request and a bounded authority statement.
2. A human reviews the proposed action and the applicable risk and data gates.
3. Independent reviewers verify the implementation, package contents and
   recovery behaviour.
4. A release decision records the exact policy, source and evidence checksums.

Until every future gate is separately accepted, the proposal remains a
non-executable note for manual review. The static boundary and rejection
registry are the controlling Wave 0 records.
