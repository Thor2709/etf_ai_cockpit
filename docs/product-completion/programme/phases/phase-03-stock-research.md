# Stock statements, fundamentals, valuation and sectors

Phase `phase-03-stock-research` covers `ISSUE-0091–ISSUE-0102, ISSUE-0183, ISSUE-0186–ISSUE-0189, ISSUE-0191`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded stock statements, fundamentals, valuation and sectors work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

## Current delivery mechanics

Follow [`DELIVERY_WORKFLOW.md`](../../DELIVERY_WORKFLOW.md) for current E/O/H/C validation, exact-tree evidence reuse, ownership, review and automatic convergence. This phase document is implementation guidance only.

## Affected modules, schemas and UI

- Confirm the existing module boundary before implementation; keep UI orchestration separate from feature, signal, model, backtest and ChatGPT bridge logic.
- Keep persisted user data under `data/`, configuration under `configs/`, logs under `logs/` and optional model files under `models/`.
- Extend existing schemas and reusable components only where the acceptance criteria require it; document compatibility for every schema change.

## Tests and evidence

- Add deterministic tests for calculations, parsing and safety gates before claiming the phase is implemented.
- Cover empty, partial, stale, conflicting, provider-unavailable and permission-denied states where the phase handles those inputs.
- Preserve source evidence, provenance and point-in-time boundaries in outputs and audit records.

## Performance

- Measure the affected local operation with representative data before and after the change.
- Avoid network calls or model loading on the baseline launch path; optional Toto and TimesFM integrations must remain optional.

## Security and authority

- Keep the app advisory and local-first. Risk gates override forecasts, audits and UI actions.
- Automatic trading remains staged, disabled and non-default. No broker automation or external upload is part of this phase.
- Treat imported files, provider responses and model output as untrusted evidence; validate before use.

## Migration and compatibility

- Prefer additive, versioned changes with an explicit migration or compatibility path.
- Do not silently mix adjusted and raw prices for returns, signals or backtests.

## Blockers, dependencies and related links

- Resolve `blocking_dependencies` through issue evidence. A named `external:...` entry in `required_inputs` blocks implementation and activation while pending. Issue references in `required_inputs` are policy or evidence inputs. `downstream_issues` are generated reverse links and `related_issues` provide context.
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-2337f69/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0091` | `P0` | `integrated` | `stock-research` | `ISSUE-0073`, `UPDATEV2-0012` | - | `ISSUE-0092`, `ISSUE-0093`, `ISSUE-0094`, `ISSUE-0095`, `ISSUE-0096`, `ISSUE-0097`, `ISSUE-0156` | - |
| `ISSUE-0092` | `P0/P1` | `integrated` | `stock-research` | `ISSUE-0074`, `ISSUE-0091` | - | `ISSUE-0097` | - |
| `ISSUE-0093` | `P0/P1` | `integrated` | `stock-research` | `ISSUE-0091` | - | - | - |
| `ISSUE-0094` | `P0/P1` | `integrated` | `stock-research` | `ISSUE-0084`, `ISSUE-0091` | - | - | - |
| `ISSUE-0095` | `P1` | `integrated` | `stock-research` | `ISSUE-0091` | - | - | - |
| `ISSUE-0096` | `P0/P1` | `integrated` | `stock-research` | `ISSUE-0088`, `ISSUE-0091` | - | `ISSUE-0108` | - |
| `ISSUE-0097` | `P1` | `integrated` | `stock-research` | `ISSUE-0091`, `ISSUE-0092` | - | - | - |
| `ISSUE-0098` | `P0` | `integrated` | `stock-research` | `ISSUE-0074`, `ISSUE-0083` | - | `ISSUE-0099`, `ISSUE-0100`, `ISSUE-0101`, `ISSUE-0102`, `ISSUE-0157`, `ISSUE-0172` | - |
| `ISSUE-0099` | `P0/P1` | `integrated` | `stock-research` | `ISSUE-0098` | - | - | - |
| `ISSUE-0100` | `P1` | `integrated` | `stock-research` | `ISSUE-0098` | - | - | - |
| `ISSUE-0101` | `P1` | `integrated` | `stock-research` | `ISSUE-0098` | - | - | - |
| `ISSUE-0102` | `P1` | `integrated` | `stock-research` | `ISSUE-0098` | - | - | - |
| `ISSUE-0183` | `P1` | `planned` | `stock-research` | - | - | `ISSUE-0187`, `ISSUE-0191`, `ISSUE-0202`, `ISSUE-0203` | `ISSUE-0087`, `ISSUE-0091` |
| `ISSUE-0186` | `P1` | `planned` | `stock-research` | `ISSUE-0182` | - | `ISSUE-0189`, `ISSUE-0200` | `ISSUE-0024`, `ISSUE-0087`, `ISSUE-0095`, `ISSUE-0126` |
| `ISSUE-0187` | `P1` | `planned` | `stock-research` | `ISSUE-0183` | - | `ISSUE-0188`, `ISSUE-0203` | `ISSUE-0092`, `ISSUE-0093`, `ISSUE-0094` |
| `ISSUE-0188` | `P1` | `planned` | `stock-research` | `ISSUE-0182`, `ISSUE-0187` | - | - | `ISSUE-0075`, `ISSUE-0092`, `ISSUE-0096`, `ISSUE-0120` |
| `ISSUE-0189` | `P1` | `planned` | `stock-research` | `ISSUE-0186` | `external:entitled-estimates-source` | - | `ISSUE-0080`, `ISSUE-0095` |
| `ISSUE-0191` | `P2` | `planned` | `stock-research` | `ISSUE-0183` | - | - | `ISSUE-0096`, `ISSUE-0097` |
