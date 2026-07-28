# ETF economics, structure, exposure and context

Phase `phase-04-etf-research` covers `ISSUE-0103–ISSUE-0107, ISSUE-0172`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded etf economics, structure, exposure and context work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-3b790ea/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0103` | `P0/P1` | `planned` | `etf-research` | `ISSUE-0084`, `UPDATEV2-0015` | - | - | - |
| `ISSUE-0104` | `P0/P1` | `planned` | `etf-research` | `UPDATEV2-0015`, `UPDATEV2-0018` | - | `ISSUE-0107` | - |
| `ISSUE-0105` | `P0` | `planned` | `etf-research` | `ISSUE-0082`, `UPDATEV2-0016` | - | `ISSUE-0108`, `ISSUE-0162`, `ISSUE-0172` | - |
| `ISSUE-0106` | `P0/P1` | `implemented_initially` | `etf-research` | `ISSUE-0128` | - | - | - |
| `ISSUE-0107` | `P1/P2` | `planned` | `etf-research` | `ISSUE-0088`, `ISSUE-0104` | - | - | - |
| `ISSUE-0172` | `P0` | `planned` | `etf-and-fund-research` | `ISSUE-0074`, `ISSUE-0098`, `ISSUE-0105`, `ISSUE-0108`, `ISSUE-0109`, `ISSUE-0112`, `ISSUE-0120`, `ISSUE-0123`, `ISSUE-0128`, `ISSUE-0170`, `ISSUE-0171`, `ISSUE-0173`, `ISSUE-0174`, `ISSUE-0175` | - | - | - |
