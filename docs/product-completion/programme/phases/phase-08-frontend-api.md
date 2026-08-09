# Typed local API and task-oriented frontend

Phase `phase-08-frontend-api` covers `ISSUE-0011, ISSUE-0016–ISSUE-0017, ISSUE-0020, ISSUE-0030, ISSUE-0037, ISSUE-0041–ISSUE-0043, ISSUE-0045, ISSUE-0136–ISSUE-0140, ISSUE-0158, ISSUE-0160–ISSUE-0161, ISSUE-0163, ISSUE-0165, ISSUE-0175, UPDATEV2-0027`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded typed local api and task-oriented frontend work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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

- Resolve only `blocking_dependencies` as prerequisites; `required_inputs` are policy/evidence inputs and do not block readiness. `downstream_issues` are generated reverse links and `related_issues` are context only.
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-2337f69/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0011` | `P0` | `integrated` | `frontend-and-api` | - | - | - | `ISSUE-0014`, `ISSUE-0045`, `ISSUE-0136`, `ISSUE-0143` |
| `ISSUE-0016` | `P1` | `implemented_initially` | `frontend-and-api` | - | - | - | `ISSUE-0137`, `ISSUE-0138`, `ISSUE-0139`, `ISSUE-0140` |
| `ISSUE-0017` | `P1` | `implemented_initially` | `frontend-and-api` | - | - | - | `ISSUE-0080`, `ISSUE-0146`, `ISSUE-0151` |
| `ISSUE-0020` | `P1` | `implemented_initially` | `frontend-and-api` | - | - | `ISSUE-0165`, `ISSUE-0166` | `ISSUE-0073`, `ISSUE-0074`, `ISSUE-0098`, `ISSUE-0138` |
| `ISSUE-0030` | `P0/P1` | `implemented_initially` | `frontend-and-api` | - | - | - | `ISSUE-0010`, `ISSUE-0057`, `ISSUE-0129`, `ISSUE-0147` |
| `ISSUE-0037` | `P1/P2` | `integrated` | `frontend-and-api` | - | - | `ISSUE-0176` | `ISSUE-0075`, `ISSUE-0076`, `ISSUE-0144` |
| `ISSUE-0041` | `P1/P2` | `implemented_initially` | `frontend-and-api` | - | - | - | `ISSUE-0137`, `ISSUE-0140`, `ISSUE-0143` |
| `ISSUE-0042` | `P1/P2` | `implemented_initially` | `frontend-and-api` | - | - | - | `ISSUE-0090`, `ISSUE-0138`, `ISSUE-0147` |
| `ISSUE-0043` | `P2` | `planned` | `frontend-and-api` | - | - | `ISSUE-0148` | `ISSUE-0148`, `ISSUE-0149` |
| `ISSUE-0045` | `P1` | `in_progress` | `frontend-and-api` | - | - | - | `ISSUE-0136`, `ISSUE-0143` |
| `ISSUE-0136` | `P0` | `integrated` | `frontend-and-api` | `ISSUE-0071` | - | `ISSUE-0137`, `ISSUE-0139`, `ISSUE-0158`, `ISSUE-0169` | - |
| `ISSUE-0137` | `P0/P1` | `implemented_initially` | `frontend-and-api` | `ISSUE-0136` | - | `ISSUE-0138`, `ISSUE-0139`, `ISSUE-0140`, `ISSUE-0158` | - |
| `ISSUE-0138` | `P0/P1` | `implemented_initially` | `frontend-and-api` | `ISSUE-0137` | - | `ISSUE-0158`, `ISSUE-0161` | - |
| `ISSUE-0139` | `P0/P1` | `implemented_initially` | `frontend-and-api` | `ISSUE-0136`, `ISSUE-0137` | - | `ISSUE-0158`, `ISSUE-0160`, `ISSUE-0161` | - |
| `ISSUE-0140` | `P1` | `implemented_initially` | `frontend-and-api` | `ISSUE-0137` | - | `ISSUE-0158` | - |
| `ISSUE-0158` | `P1` | `planned` | `frontend-and-api` | `ISSUE-0136`, `ISSUE-0137`, `ISSUE-0138`, `ISSUE-0139`, `ISSUE-0140`, `ISSUE-0153`, `ISSUE-0154`, `ISSUE-0155`, `ISSUE-0156`, `ISSUE-0157`, `ISSUE-0161`, `ISSUE-0162` | - | `ISSUE-0163` | - |
| `ISSUE-0160` | `P0/P1` | `planned` | `frontend-and-api` | `ISSUE-0139`, `ISSUE-0159` | - | - | - |
| `ISSUE-0161` | `P0/P1` | `planned` | `frontend-and-api` | `ISSUE-0074`, `ISSUE-0127`, `ISSUE-0138`, `ISSUE-0139`, `ISSUE-0159` | - | `ISSUE-0158`, `ISSUE-0163`, `ISSUE-0164`, `ISSUE-0168`, `ISSUE-0169` | - |
| `ISSUE-0163` | `P1` | `planned` | `frontend-and-api` | `ISSUE-0024`, `ISSUE-0084`, `ISSUE-0127`, `ISSUE-0153`, `ISSUE-0158`, `ISSUE-0161` | - | `ISSUE-0164` | - |
| `ISSUE-0165` | `P0` | `planned` | `application-platform` | `ISSUE-0018`, `ISSUE-0020`, `ISSUE-0074`, `ISSUE-0077`, `ISSUE-0081`, `ISSUE-0126` | - | `ISSUE-0166`, `ISSUE-0169`, `ISSUE-0175` | - |
| `ISSUE-0175` | `P0` | `planned` | `application-platform` | `ISSUE-0039`, `ISSUE-0077`, `ISSUE-0078`, `ISSUE-0121`, `ISSUE-0151`, `ISSUE-0165` | - | `ISSUE-0172` | - |
| `UPDATEV2-0027` | `P0` | `in_progress` | `frontend-and-api` | - | - | - | `ISSUE-0011`, `ISSUE-0012`, `ISSUE-0077`, `ISSUE-0136` |
