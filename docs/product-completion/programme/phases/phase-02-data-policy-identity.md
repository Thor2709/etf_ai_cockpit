# Local-first data policy, identity and data platform

Phase `phase-02-data-policy-identity` covers `ISSUE-0007, ISSUE-0022–ISSUE-0023, ISSUE-0025, ISSUE-0038, ISSUE-0048, ISSUE-0054–ISSUE-0056, ISSUE-0068, ISSUE-0080–ISSUE-0090, ISSUE-0153, ISSUE-0155, ISSUE-0170–ISSUE-0171, UPDATEV2-0011, UPDATEV2-0015–UPDATEV2-0016, UPDATEV2-0018, UPDATEV2-0021, UPDATEV2-0023, UPDATEV2-0030`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded local-first data policy, identity and data platform work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-6596055/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0007` | `P2` | `implemented_initially` | `data-and-evidence` | - | - | - | `ISSUE-0024`, `ISSUE-0026`, `ISSUE-0054`, `ISSUE-0073`, `ISSUE-0115` |
| `ISSUE-0022` | `P1` | `implemented_initially` | `data-and-evidence` | - | - | `ISSUE-0162` | `ISSUE-0082`, `ISSUE-0105`, `UPDATEV2-0016` |
| `ISSUE-0023` | `P1` | `implemented_initially` | `data-and-evidence` | - | - | - | `ISSUE-0091`, `ISSUE-0102` |
| `ISSUE-0025` | `P1` | `implemented_initially` | `data-and-evidence` | - | - | - | `ISSUE-0007`, `ISSUE-0054`, `ISSUE-0087`, `ISSUE-0149` |
| `ISSUE-0038` | `P2` | `integrated` | `data-and-evidence` | - | - | `ISSUE-0072` | `ISSUE-0072`, `ISSUE-0073`, `ISSUE-0090` |
| `ISSUE-0048` | `P1` | `integrated` | `data-and-evidence` | - | - | - | `ISSUE-0120`, `ISSUE-0122`, `ISSUE-0147` |
| `ISSUE-0054` | `P1/P2` | `implemented_initially` | `data-and-evidence` | - | - | - | `ISSUE-0025`, `ISSUE-0073`, `ISSUE-0149` |
| `ISSUE-0055` | `P2` | `implemented_initially` | `data-and-evidence` | - | - | - | `ISSUE-0080`, `ISSUE-0081`, `ISSUE-0087`, `ISSUE-0088` |
| `ISSUE-0056` | `P2` | `implemented_initially` | `data-and-evidence` | - | - | - | `ISSUE-0076`, `ISSUE-0085`, `ISSUE-0130` |
| `ISSUE-0068` | `P0/P1` | `implemented_initially` | `data-and-evidence` | - | - | - | `ISSUE-0076`, `ISSUE-0080`, `ISSUE-0082`, `ISSUE-0083` |
| `ISSUE-0080` | `P0` | `integrated` | `data-platform` | `ISSUE-0070`, `ISSUE-0076` | - | `ISSUE-0081`, `ISSUE-0088`, `ISSUE-0149`, `ISSUE-0171`, `ISSUE-0176` | - |
| `ISSUE-0081` | `P0` | `integrated` | `data-platform` | `ISSUE-0072`, `ISSUE-0077`, `ISSUE-0080` | - | `ISSUE-0087`, `ISSUE-0088`, `ISSUE-0155`, `ISSUE-0165`, `ISSUE-0171` | - |
| `ISSUE-0082` | `P0` | `integrated` | `data-platform` | `ISSUE-0073`, `UPDATEV2-0011` | - | `ISSUE-0083`, `ISSUE-0084`, `ISSUE-0085`, `ISSUE-0086`, `ISSUE-0105`, `ISSUE-0126`, `ISSUE-0153`, `ISSUE-0170` | - |
| `ISSUE-0083` | `P0/P1` | `in_progress` | `data-platform` | `ISSUE-0082` | - | `ISSUE-0098`, `ISSUE-0153`, `ISSUE-0162`, `ISSUE-0170` | - |
| `ISSUE-0084` | `P0` | `planned` | `data-platform` | `ISSUE-0073`, `ISSUE-0082` | - | `ISSUE-0094`, `ISSUE-0103`, `ISSUE-0127`, `ISSUE-0159`, `ISSUE-0163`, `ISSUE-0173` | - |
| `ISSUE-0085` | `P0/P1` | `planned` | `data-platform` | `ISSUE-0079`, `ISSUE-0082` | - | `ISSUE-0153`, `ISSUE-0154`, `ISSUE-0159`, `ISSUE-0167`, `ISSUE-0170` | - |
| `ISSUE-0086` | `P0` | `planned` | `data-platform` | `ISSUE-0036`, `ISSUE-0082` | - | - | - |
| `ISSUE-0087` | `P0/P1` | `integrated` | `data-platform` | `ISSUE-0081`, `UPDATEV2-0012`, `UPDATEV2-0014` | - | - | - |
| `ISSUE-0088` | `P0/P1` | `implemented_initially` | `data-platform` | `ISSUE-0073`, `ISSUE-0080`, `ISSUE-0081` | - | `ISSUE-0096`, `ISSUE-0107`, `ISSUE-0154`, `ISSUE-0155`, `ISSUE-0173` | - |
| `ISSUE-0089` | `P0` | `planned` | `data-platform` | `ISSUE-0073`, `UPDATEV2-0021` | - | `ISSUE-0173` | - |
| `ISSUE-0090` | `P0/P1` | `implemented_initially` | `data-platform` | `ISSUE-0072`, `ISSUE-0075` | - | `ISSUE-0150` | - |
| `ISSUE-0153` | `P0` | `planned` | `data-platform` | `ISSUE-0082`, `ISSUE-0083`, `ISSUE-0085` | - | `ISSUE-0154`, `ISSUE-0155`, `ISSUE-0158`, `ISSUE-0162`, `ISSUE-0163` | - |
| `ISSUE-0155` | `P0/P1` | `planned` | `data-platform` | `ISSUE-0076`, `ISSUE-0081`, `ISSUE-0088`, `ISSUE-0149`, `ISSUE-0153` | - | `ISSUE-0156`, `ISSUE-0157`, `ISSUE-0158` | - |
| `ISSUE-0170` | `P0` | `planned` | `data-platform` | `ISSUE-0076`, `ISSUE-0082`, `ISSUE-0083`, `ISSUE-0085`, `ISSUE-0149` | - | `ISSUE-0171`, `ISSUE-0172` | - |
| `ISSUE-0171` | `P0` | `planned` | `data-platform` | `ISSUE-0076`, `ISSUE-0080`, `ISSUE-0081`, `ISSUE-0149`, `ISSUE-0170`, `ISSUE-0176` | - | `ISSUE-0172` | - |
| `UPDATEV2-0011` | `P0` | `integrated` | `data-and-evidence` | - | - | `ISSUE-0082` | `ISSUE-0082`, `ISSUE-0083` |
| `UPDATEV2-0015` | `P0` | `closed` | `data-and-evidence` | - | - | `ISSUE-0103`, `ISSUE-0104` | `ISSUE-0090`, `ISSUE-0103`, `ISSUE-0104` |
| `UPDATEV2-0016` | `P0` | `closed` | `data-and-evidence` | - | - | `ISSUE-0105` | `ISSUE-0082`, `ISSUE-0105` |
| `UPDATEV2-0018` | `P1` | `planned` | `data-and-evidence` | - | - | `ISSUE-0104` | `ISSUE-0104`, `UPDATEV2-0015` |
| `UPDATEV2-0021` | `P0` | `integrated` | `data-and-evidence` | - | - | `ISSUE-0089` | `ISSUE-0073`, `ISSUE-0089`, `ISSUE-0090` |
| `UPDATEV2-0023` | `P1` | `planned` | `data-and-evidence` | - | - | - | `ISSUE-0076`, `ISSUE-0080` |
| `UPDATEV2-0030` | `P2` | `planned` | `data-and-evidence` | - | - | - | `ISSUE-0080`, `ISSUE-0086`, `ISSUE-0089` |
