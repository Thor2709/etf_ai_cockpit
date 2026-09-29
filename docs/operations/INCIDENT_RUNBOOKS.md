# Paper operational incident runbooks

These runbooks apply to the local paper ledger only. They do not grant broker,
provider, network or live-order authority; `execution_allowed` remains false.
When order state is unknown, freeze first and reconcile before allowing another
paper order action. Do not retry an uncertain action speculatively.

## Disconnect or unknown order state

1. Stop paper order acceptance, fills and cancellations. Recording an incident
   with code `disconnect` or `unknown_state` freezes those operations.
2. Record the observed failure with `PaperLedger.record_operational_error`,
   including a concise reason and related paper order ID when known. Preserve
   the resulting incident journal entry and the paper ledger event.
3. Review the read-only paper state with `PaperLedger.reconciliation_state()`.
   Obtain the independently observed paper-side state from the local simulation
   and compare account, cash, order IDs and statuses, fills, and positions.
4. Submit that complete observed state to
   `PaperLedger.reconcile_operational_state(observed_state)`. A mismatch keeps
   the order pipeline frozen. Only a clean match clears the freeze.
5. Retry an intended proposal only after recovery. Acceptance is idempotent by
   proposal, so a previously accepted proposal returns its existing order
   instead of creating a second one.
6. Append a post-mortem with `IncidentJournal.append_postmortem`. The journal is
   append-only; corrections require a new entry and never overwrite prior
   evidence.

## Order break or contradictory ledger event

1. Freeze the paper order pipeline by recording `order_break` with the related
   order ID and the contradictory observation.
2. Preserve the paper ledger and incident journal files. Do not edit, truncate,
   replay around or resubmit the disputed order.
3. Compare the observed state with `PaperLedger.reconciliation_state()` and use
   `reconcile_operational_state` as above. Keep the freeze active while any
   order, fill, cash or position value differs.
4. If either hash chain or the incident journal's durable head/count anchor
   fails verification, leave the pipeline frozen, retain the files for
   investigation and do not rewrite stored evidence. A clean reconciliation
   cannot clear an integrity failure. The anchor detects removed rows and an
   empty or missing journal file.

## Ledger or journal integrity failure

1. Stop paper mutations. Ledger replay and incident journal verification fail
   closed when event identity, ordering or hashes do not match.
2. Preserve the affected local files and their associated lock files. Capture
   the visible error and current file hashes in a new incident record if the
   journal remains writable and verifiable.
3. Re-enable paper order activity only after an intact ledger can be replayed
   and the incident journal records a clean state reconciliation.

## Deterministic drills

Run the synthetic disconnect and order-break drills with
`run_operational_drill("disconnect")` and
`run_operational_drill("order_break")`. Each returns a deterministic `passed`
or `failed` result for persisted freeze, mismatch retention, clean recovery,
incident and recovery retry idempotency, order retry idempotency, and persisted
ledger event identity/count preservation. Each drill uses a temporary local
journal and paper ledger and does not change a user's paper account.

The regression checks are `test_unknown_state_causes_immediate_freeze`,
`test_unfreezing_requires_clean_reconciliation`,
`test_incident_journal_hash_chain_integrity`,
`test_incident_journal_rejects_truncation_against_durable_head` and the
parametrized operational drill test in `tests/test_operational_incidents.py`.
