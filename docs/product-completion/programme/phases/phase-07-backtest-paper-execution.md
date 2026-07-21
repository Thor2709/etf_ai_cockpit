# Backtest, paper trading and staged execution

Phase `phase-07-backtest-paper-execution` covers `ISSUE-0031–ISSUE-0032, ISSUE-0057, ISSUE-0066, ISSUE-0125–ISSUE-0135, ISSUE-0167`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded backtest, paper trading and staged execution work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-a5dee75/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0031` | `P1` | `integrated` | `trading-safety` | - | - | `ISSUE-0129` | `ISSUE-0125`, `ISSUE-0127`, `ISSUE-0130` |
| `ISSUE-0032` | `P2` | `planned` | `trading-safety` | - | - | `ISSUE-0070` | `ISSUE-0070`, `ISSUE-0131`, `ISSUE-0135` |
| `ISSUE-0057` | `P1` | `integrated` | `trading-safety` | - | - | `ISSUE-0129` | `ISSUE-0075`, `ISSUE-0129`, `ISSUE-0147` |
| `ISSUE-0066` | `P2` | `planned` | `trading-safety` | - | - | `ISSUE-0070`, `ISSUE-0131` | `ISSUE-0070`, `ISSUE-0127`, `ISSUE-0131`, `ISSUE-0135` |
| `ISSUE-0125` | `P0` | `implemented_initially` | `backtest-and-paper` | `ISSUE-0028`, `ISSUE-0050` | - | - | - |
| `ISSUE-0126` | `P0` | `planned` | `backtest-and-paper` | `ISSUE-0073`, `ISSUE-0082` | - | `ISSUE-0165` | - |
| `ISSUE-0127` | `P0` | `planned` | `trading-safety` | `ISSUE-0072`, `ISSUE-0084` | - | `ISSUE-0131`, `ISSUE-0142`, `ISSUE-0159`, `ISSUE-0161`, `ISSUE-0162`, `ISSUE-0163`, `ISSUE-0164`, `ISSUE-0167`, `ISSUE-0168` | - |
| `ISSUE-0128` | `P0/P1` | `implemented_initially` | `trading-safety` | `ISSUE-0064` | - | `ISSUE-0106`, `ISSUE-0166`, `ISSUE-0172`, `ISSUE-0174` | `ISSUE-0106` |
| `ISSUE-0129` | `P0` | `integrated` | `backtest-and-paper` | `ISSUE-0031`, `ISSUE-0057` | - | - | - |
| `ISSUE-0130` | `P0` | `integrated` | `trading-safety` | `ISSUE-0070`, `ISSUE-0114` | - | `ISSUE-0167` | - |
| `ISSUE-0131` | `P0/P1` | `planned` | `trading-safety` | `ISSUE-0066`, `ISSUE-0127` | - | `ISSUE-0132`, `ISSUE-0134`, `ISSUE-0135`, `ISSUE-0167` | - |
| `ISSUE-0132` | `P0` | `planned` | `trading-safety` | `ISSUE-0131` | - | `ISSUE-0133`, `ISSUE-0135`, `ISSUE-0142`, `ISSUE-0167` | - |
| `ISSUE-0133` | `P0` | `planned` | `trading-safety` | `ISSUE-0132` | - | `ISSUE-0167` | - |
| `ISSUE-0134` | `P1` | `planned` | `trading-safety` | `ISSUE-0116`, `ISSUE-0131` | - | `ISSUE-0167` | - |
| `ISSUE-0135` | `P0` | `planned` | `trading-safety` | `ISSUE-0131`, `ISSUE-0132` | - | `ISSUE-0167` | - |
| `ISSUE-0167` | `P0` | `planned` | `trading-safety` | `ISSUE-0085`, `ISSUE-0114`, `ISSUE-0127`, `ISSUE-0130`, `ISSUE-0131`, `ISSUE-0132`, `ISSUE-0133`, `ISSUE-0134`, `ISSUE-0135` | - | `ISSUE-0169` | - |
