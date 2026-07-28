# Audit, reproducibility, documentation and governance

Phase `phase-10-audit-documentation-governance` covers `ISSUE-0147–ISSUE-0151`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded audit, reproducibility, documentation and governance work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-92dbc82/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0147` | `P0` | `planned` | `audit-and-reproducibility` | `ISSUE-0075`, `UPDATEV2-0028` | - | - | - |
| `ISSUE-0148` | `P0/P1` | `planned` | `documentation` | `ISSUE-0043` | - | - | - |
| `ISSUE-0149` | `P0` | `hardening_required` | `programme-governance` | `ISSUE-0080` | - | `ISSUE-0079`, `ISSUE-0155`, `ISSUE-0170`, `ISSUE-0171`, `ISSUE-0173`, `ISSUE-0176` | `ISSUE-0079` |
| `ISSUE-0150` | `P0/P1` | `implemented_initially` | `model-governance` | `ISSUE-0090`, `ISSUE-0120` | - | - | - |
| `ISSUE-0151` | `P1` | `hardening_required` | `quality-and-release` | `ISSUE-0078` | - | `ISSUE-0175` | - |
