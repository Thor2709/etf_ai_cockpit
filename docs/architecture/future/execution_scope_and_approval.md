# Future-only / no-authority

This document records a possible future governance shape. It is not an
implemented execution capability, does not grant authority, and is not
permission to send an order or change a risk gate. The current contract is
`execution_allowed=false` and `executable_authority=false`.

## Authority ladder and current stage

The accepted staged-authority vocabulary is `research`, `shadow_proposal`,
`paper`, `broker_read_only`, `draft_order`, `capped_automatic`, and `disabled`.
The current release enables research and local evidence only. Paper records
are simulated and user-owned; broker read-only, draft-order, and capped
automatic capabilities are future-only and unavailable. The ladder describes
policy states, not a hidden switch.

The future sequence is intentionally paper mode first:

`research` -> `shadow_proposal` -> `paper` -> `broker_read_only` ->
`draft_order` -> `capped_automatic` (or `disabled` on any failed gate).

| Stage | Future intent | Current status |
| --- | --- | --- |
| Research / paper | Replay local evidence and record a paper outcome. | Research or local simulation only; no account mutation. |
| `broker_read_only` | Read settled positions and cash from official broker APIs for reconciliation. | Not installed and not connected. |
| Draft order | Produce a human-readable order preview after deterministic checks. | No transmission path exists. |
| `capped_automatic` | Route only after an entirely new authority decision and release. | Disabled and rejected by policy. |

No stage may be promoted by a YAML edit, a UI click, forecast output, LLM
response, or model-only decision. A new ADR, policy checksum, threat model,
independent review, and release evidence would be required.

## Future approval sequence

1. Governance records a bounded authority statement and approved instrument and
   account scope.
2. Deterministic data, identity, market-hours, liquidity, cost, risk, and
   news/event gates evaluate a versioned proposal.
3. A human reviews an order preview containing side, quantity, limit price,
   maximum order value, resulting position size, daily turnover and daily loss
   impact, and evidence timestamps.
4. The human explicitly confirms the immutable intent; absence, expiry, or
   mismatch of confirmation rejects the intent.
5. Independent reviewers verify idempotency, audit logging, emergency disable,
   recovery, package contents, and the `execution_allowed` boundary.
6. A release decision records policy, source, and evidence checksums before any
   future stage can be considered.

## Future safety gates

The control layer must fail closed on a maximum order value or position-size
breach, daily turnover or daily loss breach, drawdown kill switch, cooldown,
outside-market-hours request, stale data, unresolved news or event
contradiction, unknown instrument, duplicate intent, or account-scope error.
An emergency disable must block new intents independently of the UI and leave
an auditable reason. Every preview, confirmation, rejection, cancellation,
timeout, and provider observation belongs in an immutable audit log.

An LLM, generative model, forecast, narrative sentiment, or model-only policy
can never authorize, modify, or submit an intent. They remain untrusted,
context-only inputs. A timeout requires status reconciliation before retry;
partial or unknown status remains manual review.

Until every future gate is separately accepted, the proposal remains a
non-executable note for manual review. The static boundary and rejection
registry are the controlling Wave 0 records.
