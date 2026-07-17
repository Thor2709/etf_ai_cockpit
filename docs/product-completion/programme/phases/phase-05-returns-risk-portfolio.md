# Expected return, risk and portfolio construction

Phase `phase-05-returns-risk-portfolio` covers `ISSUE-0108–ISSUE-0116`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded expected return, risk and portfolio construction work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-17-3321ebd/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0008` | `P2` | `planned` | `analysis-and-validation` | - | - | `ISSUE-0070` | `ISSUE-0060`, `ISSUE-0070`, `ISSUE-0130`, `ISSUE-0133` |
| `ISSUE-0028` | `P0/P1` | `planned` | `analysis-and-validation` | - | - | `ISSUE-0125` | `ISSUE-0120`, `ISSUE-0125`, `ISSUE-0128` |
| `ISSUE-0029` | `P1/P2` | `planned` | `analysis-and-validation` | - | - | - | `ISSUE-0074`, `ISSUE-0075`, `ISSUE-0130` |
| `ISSUE-0046` | `P1/P2` | `planned` | `analysis-and-validation` | - | - | - | `ISSUE-0108`, `ISSUE-0112`, `ISSUE-0115`, `ISSUE-0130` |
| `ISSUE-0051` | `P1/P2` | `planned` | `analysis-and-validation` | - | - | `ISSUE-0112` | `ISSUE-0088`, `ISSUE-0112` |
| `ISSUE-0052` | `P1` | `implemented_initially` | `analysis-and-validation` | - | - | `ISSUE-0110` | `ISSUE-0105`, `ISSUE-0110`, `ISSUE-0113`, `ISSUE-0115` |
| `ISSUE-0059` | `P1/P2` | `implemented_initially` | `analysis-and-validation` | - | - | `ISSUE-0110`, `ISSUE-0112`, `ISSUE-0116` | `ISSUE-0105`, `ISSUE-0110`, `ISSUE-0116` |
| `ISSUE-0060` | `P1` | `planned` | `analysis-and-validation` | - | - | `ISSUE-0070` | `ISSUE-0008`, `ISSUE-0070`, `ISSUE-0132`, `ISSUE-0133` |
| `ISSUE-0064` | `P1` | `implemented_initially` | `analysis-and-validation` | - | - | `ISSUE-0128` | `ISSUE-0108`, `ISSUE-0128` |
| `ISSUE-0065` | `P2` | `planned` | `analysis-and-validation` | - | - | - | `ISSUE-0049`, `ISSUE-0111`, `ISSUE-0125` |
| `ISSUE-0108` | `P0` | `planned` | `returns-and-risk` | `ISSUE-0074`, `ISSUE-0096`, `ISSUE-0105` | - | `ISSUE-0109`, `ISSUE-0123` | - |
| `ISSUE-0109` | `P0/P1` | `planned` | `returns-and-risk` | `ISSUE-0108` | - | `ISSUE-0115` | - |
| `ISSUE-0110` | `P0` | `integrated` | `returns-and-risk` | `ISSUE-0052`, `ISSUE-0059` | - | `ISSUE-0111`, `ISSUE-0113`, `ISSUE-0115` | - |
| `ISSUE-0111` | `P0` | `planned` | `returns-and-risk` | `ISSUE-0110` | - | `ISSUE-0113` | - |
| `ISSUE-0112` | `P0/P1` | `planned` | `returns-and-risk` | `ISSUE-0051`, `ISSUE-0059` | - | - | - |
| `ISSUE-0113` | `P0` | `planned` | `portfolio-construction` | `ISSUE-0021`, `ISSUE-0110`, `ISSUE-0111` | - | `ISSUE-0114` | - |
| `ISSUE-0114` | `P0/P1` | `planned` | `portfolio-construction` | `ISSUE-0113` | - | `ISSUE-0130` | - |
| `ISSUE-0115` | `P0/P1` | `planned` | `returns-and-risk` | `ISSUE-0109`, `ISSUE-0110` | - | - | - |
| `ISSUE-0116` | `P0/P1` | `planned` | `returns-and-risk` | `ISSUE-0021`, `ISSUE-0059` | - | `ISSUE-0134` | - |
| `UPDATEV2-0026` | `P1` | `planned` | `analysis-and-validation` | - | - | - | `ISSUE-0084`, `ISSUE-0125`, `ISSUE-0128` |
