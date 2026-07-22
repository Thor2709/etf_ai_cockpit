# Training, validation and model governance

Phase `phase-06-model-research` covers `ISSUE-0117–ISSUE-0124`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded training, validation and model governance work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-1d9838a/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0117` | `P0` | `implemented_initially` | `model-governance` | `ISSUE-0027`, `ISSUE-0075` | - | `ISSUE-0118`, `ISSUE-0119`, `ISSUE-0121`, `ISSUE-0124` | - |
| `ISSUE-0118` | `P1` | `implemented_initially` | `model-governance` | `ISSUE-0117` | - | - | - |
| `ISSUE-0119` | `P0` | `implemented_initially` | `model-governance` | `ISSUE-0073`, `ISSUE-0117` | - | `ISSUE-0120` | - |
| `ISSUE-0120` | `P0` | `implemented_initially` | `model-governance` | `ISSUE-0119` | - | `ISSUE-0121`, `ISSUE-0122`, `ISSUE-0123`, `ISSUE-0150`, `ISSUE-0157`, `ISSUE-0172` | - |
| `ISSUE-0121` | `P0/P1` | `implemented_initially` | `model-governance` | `ISSUE-0117`, `ISSUE-0120` | - | `ISSUE-0175` | - |
| `ISSUE-0122` | `P1` | `implemented_initially` | `model-governance` | `ISSUE-0120` | - | - | - |
| `ISSUE-0123` | `P0/P1` | `planned` | `model-governance` | `ISSUE-0108`, `ISSUE-0120` | - | `ISSUE-0124`, `ISSUE-0157`, `ISSUE-0172`, `ISSUE-0174` | - |
| `ISSUE-0124` | `P0/P1` | `planned` | `model-governance` | `ISSUE-0117`, `ISSUE-0123` | - | - | - |
