# Future-only / no-authority

This document is a design record for a possible broker boundary. It is not an
integration, does not contain credentials or endpoints, and provides no
runnable order example. The current cockpit remains local-first and
advisory-only: `execution_allowed=false` and `executable_authority=false`.

## Current boundary and paper mode first

The only current execution-like workflow is local backtest and paper evidence.
Paper mode is deliberately first: it can replay a sealed proposal against local
prices and persist a result, but it cannot contact an account or mutate an
external position. A future broker abstraction must remain behind a separately
approved capability boundary and must not be reachable from scores, forecasts,
LLM commentary, news text, or an ordinary UI action.

The current package has no broker adapter, credential store, transport, order
submission path, or execution authority. The strategy matrix therefore keeps
`paper`, `draft_order`, `canary`, and `bounded_automatic` cells unavailable or
research-only as applicable. See [execution scope and approval](execution_scope_and_approval.md)
and the [source-of-truth and reconciliation record](source_of_truth_and_reconciliation.md).

## Future staged contract

Any future implementation would progress in this order, with a separately
reviewed release gate between stages:

`research` -> `shadow_proposal` -> `paper` -> `broker_read_only` ->
`draft_order` -> `capped_automatic` (or `disabled` on any failed gate).

1. **`paper`**: exercise the complete intent, preview, explicit-confirmation,
   controls, lifecycle, and audit flow against a local paper ledger only.
2. **`broker_read_only`**: obtain account observations such as settled
   positions and cash, never create or submit an order.
3. **`draft_order`**: render an order preview from a versioned, immutable intent
   for a human to inspect and explicitly confirm. Confirmation records intent
   and evidence; it does not transmit anything.
4. **`capped_automatic`**: a contingent, separately authorised capability only
   after independent security, recovery, packaging, and governance approval.

The future interface would accept only a canonical instrument, explicit account
scope, side, bounded quantity, mandatory limit price, decision timestamp,
immutable intent ID, and recorded human confirmation. Missing approval, stale
evidence, unknown identity, duplicate intent ID, or an out-of-scope account
would fail closed. A model or forecast could never supply or alter these
fields.

## Mandatory future pre-trade controls

Before any future draft or transmission could be considered, an independent
control layer would enforce all of the following. These are requirements for a
future design, not controls that enable a current stage.

| Control | Required behaviour |
| --- | --- |
| Maximum order value | Reject an intent above the versioned per-order monetary ceiling. |
| Position size | Reject a resulting position above the instrument/account size limit. |
| Daily turnover | Reject when cumulative notional would exceed the daily turnover limit. |
| Daily loss | Block when realised and mark-to-market loss reaches the daily loss limit. |
| Drawdown kill switch | Fail closed when account drawdown reaches the approved threshold. |
| Cooldowns | Pause after volatility, anomaly, rejection, or rapid-sequence events; re-enable only by explicit review. |
| Market-hours checks | Reject outside the instrument's verified session, calendar, and auction rules. |
| Stale-data block | Reject when decision-time prices, identity, or risk evidence are outside their freshness window. |
| News/event block | Block on an unresolved critical event, contradiction, or severe retraction; context cannot silently approve an order. |
| Audit log | Append immutable intent, preview, gate, confirmation, rejection, cancellation, and observation records with lineage. |
| Emergency disable | Provide an independent fail-closed disable that prevents new intents and requires an auditable administrative review to clear. |

The adapter would use exact idempotency: the same intent ID with the identical
immutable payload and checksum returns its prior status; the same ID with any
payload or checksum difference rejects and quarantines the intent. It would
reconcile a timeout before any retry and treat partial, unknown, cancelled, or
conflicting provider states as manual-review conditions, never as implicit success. Market orders,
unbounded quantities, credential leakage, and retry loops are outside the
future contract.

## Authority prohibition and release gates

LLM, generative-AI, and model-only authority is prohibited. Models may provide
clearly labelled research context, but may not generate, approve, modify, or
submit a draft or order. Only deterministic policy checks plus an explicit
human approval record could satisfy a future stage gate.

Progression would require a new authority decision, threat model, independent
security review, credential and transport isolation review, deterministic tests,
Windows and Linux package evidence, recovery drills, and an immutable audit
manifest. Until then, `execution_allowed=false` remains the controlling
invariant and ISSUE-0066 remains the linked future source-of-truth/reconciliation
work.
