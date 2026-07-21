# ADR-0070: Product scope and staged authority

- Status: accepted for the Step 2 completion programme
- Version: `ADR-0070-v1`
- Policy: `configs/authority_matrix.yaml`
- Execution authority: permanently disabled in this release

## Decision

ETF AI Cockpit is a local-first investment evidence and portfolio-research
cockpit for a human decision owner. Its mandatory core runs from local data,
user-owned imports and cached/public evidence without a paid plan, API key or
per-call vendor quota. Optional providers, TimesFM, Toto and local LLM
commentary enrich evidence only; they are never required for baseline launch,
scoring or release validation.

The finite authority ladder is: research, shadow proposal, paper,
broker read-only, draft order, capped automatic and disabled. The current
release enables only research. Shadow proposals and paper work are local,
non-executable evidence. Broker read-only is reserved for a future approved
adapter and does not permit credentials or orders. Draft-order and capped
automatic stages remain disabled and cannot be enabled by YAML, UI actions or
model output.

## Boundaries

Every route, dataset dependency, model, strategy and broker capability is
declared in `configs/authority_matrix.yaml`. The matrix is immutable after
load, checksum-bearing in audit exports and fails closed if the required
stage set or capability coverage is incomplete. Risk and evidence gates remain
authoritative over scores, forecasts, audit commentary and UI actions.

`configs/strategy_scope.yaml` is the instrument-and-strategy refinement of
that authority ladder. Every strategy resolves through an explicit profile
for analyse, portfolio, backtest, paper, draft-order, canary and bounded-
automatic stages. Every supported instrument family declares classification
aliases, horizons, long-only actions and data, model, liquidity, broker and
legal prerequisites. Unknown or conflicting classifications and excluded
OTC, microcap, illiquid, leveraged, inverse, derivative, crypto, short and
complex-structured products fail closed with deterministic reason codes.
Risk profiles cannot override those exclusions.

The matrix can describe a later stage without activating it. Draft-order,
canary and bounded-automatic cells are unavailable or rejected in the current
policy, and every resolved row and audit export states
`execution_allowed=false`.

Historical rejection records are preserved. This ADR supersedes ambiguous
scope wording for the current completion programme; it does not grant live
execution authority or promise returns, alpha or equivalence with a
proprietary institutional platform.

## Change control

Any future authority change must add a new ADR version and matrix policy,
retain this record and its checksum, pass the static execution boundary scan,
and include the resulting policy checksum in the audit packet before review.
