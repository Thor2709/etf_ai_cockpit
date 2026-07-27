# Stock statements, fundamentals, valuation and sectors

Phase `phase-03-stock-research` covers `ISSUE-0091–ISSUE-0102`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded stock statements, fundamentals, valuation and sectors work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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

- Resolve only `blocking_dependencies` as prerequisites; `required_inputs` are policy/evidence inputs and do not block readiness. `downstream_issues` are generated reverse links and `related_issues` are context only.
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-5cdf8de/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0091` | `P0` | `integrated` | `stock-research` | `ISSUE-0073`, `UPDATEV2-0012` | - | `ISSUE-0092`, `ISSUE-0093`, `ISSUE-0094`, `ISSUE-0095`, `ISSUE-0096`, `ISSUE-0097`, `ISSUE-0156` | - |
| `ISSUE-0092` | `P0/P1` | `implemented_initially` | `stock-research` | `ISSUE-0074`, `ISSUE-0091` | - | `ISSUE-0097` | - |
| `ISSUE-0093` | `P0/P1` | `implemented_initially` | `stock-research` | `ISSUE-0091` | - | - | - |
| `ISSUE-0094` | `P0/P1` | `planned` | `stock-research` | `ISSUE-0084`, `ISSUE-0091` | - | - | - |
| `ISSUE-0095` | `P1` | `integrated` | `stock-research` | `ISSUE-0091` | - | - | - |
| `ISSUE-0096` | `P0/P1` | `implemented_initially` | `stock-research` | `ISSUE-0088`, `ISSUE-0091` | - | `ISSUE-0108` | - |
| `ISSUE-0097` | `P1` | `implemented_initially` | `stock-research` | `ISSUE-0091`, `ISSUE-0092` | - | - | - |
| `ISSUE-0098` | `P0` | `planned` | `stock-research` | `ISSUE-0074`, `ISSUE-0083` | - | `ISSUE-0099`, `ISSUE-0100`, `ISSUE-0101`, `ISSUE-0102`, `ISSUE-0157`, `ISSUE-0172` | - |
| `ISSUE-0099` | `P0/P1` | `planned` | `stock-research` | `ISSUE-0098` | - | - | - |
| `ISSUE-0100` | `P1` | `planned` | `stock-research` | `ISSUE-0098` | - | - | - |
| `ISSUE-0101` | `P1` | `planned` | `stock-research` | `ISSUE-0098` | - | - | - |
| `ISSUE-0102` | `P1` | `planned` | `stock-research` | `ISSUE-0098` | - | - | - |
