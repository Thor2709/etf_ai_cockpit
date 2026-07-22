# Governance, scope and completion contract

Phase `phase-01-governance-scope` covers `ISSUE-0001–ISSUE-0006, ISSUE-0009–ISSUE-0010, ISSUE-0012–ISSUE-0015, ISSUE-0018–ISSUE-0019, ISSUE-0021, ISSUE-0024, ISSUE-0026–ISSUE-0027, ISSUE-0033–ISSUE-0036, ISSUE-0039–ISSUE-0040, ISSUE-0044, ISSUE-0047, ISSUE-0049–ISSUE-0050, ISSUE-0053, ISSUE-0058, ISSUE-0061–ISSUE-0063, ISSUE-0067, ISSUE-0069–ISSUE-0079, UPDATEV2-0010, UPDATEV2-0012–UPDATEV2-0014, UPDATEV2-0017, UPDATEV2-0019–UPDATEV2-0020, UPDATEV2-0022, UPDATEV2-0024–UPDATEV2-0025, UPDATEV2-0028–UPDATEV2-0029`. The issue registry remains the canonical source for titles, priorities, state and acceptance criteria; this document records phase-specific implementation guidance.

## Objective

Deliver the bounded governance, scope and completion contract work with local-first behaviour, explicit evidence and the safety gates defined by the canonical records.

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
- The registry's blocking graph is acyclic; dependency conversions are recorded in `docs/product-completion/reconciliation/2026-07-21-384c82d/dependency-reconciliation.csv`.

## Issue coverage

| ID | Priority | Programme state | Owner | Blocking dependencies | Required inputs | Downstream issues | Related issues |
|---|---|---|---|---|---|---|---|
| `ISSUE-0001` | `P3` | `closed` | `programme-governance` | - | - | - | - |
| `ISSUE-0002` | `P3` | `closed` | `programme-governance` | - | - | - | - |
| `ISSUE-0003` | `P3` | `closed` | `analysis-and-validation` | - | - | - | - |
| `ISSUE-0004` | `P3` | `closed` | `programme-governance` | - | - | - | - |
| `ISSUE-0005` | `P3` | `closed` | `programme-governance` | - | - | - | - |
| `ISSUE-0006` | `P3` | `closed` | `analysis-and-validation` | - | - | - | - |
| `ISSUE-0009` | `P3` | `closed` | `programme-governance` | - | - | - | - |
| `ISSUE-0010` | `P2` | `planned` | `programme-governance` | - | - | - | `ISSUE-0030`, `ISSUE-0057`, `ISSUE-0147` |
| `ISSUE-0012` | `P0` | `in_progress` | `programme-governance` | - | - | - | `ISSUE-0077`, `ISSUE-0117`, `ISSUE-0139` |
| `ISSUE-0013` | `P0` | `integrated` | `platform-and-operations` | - | - | - | `ISSUE-0141`, `ISSUE-0145`, `ISSUE-0152`, `UPDATEV2-0029` |
| `ISSUE-0014` | `P0/P1` | `in_progress` | `programme-governance` | - | - | - | `ISSUE-0045`, `ISSUE-0143`, `ISSUE-0152` |
| `ISSUE-0015` | `P1` | `implemented_initially` | `programme-governance` | - | - | - | `ISSUE-0070`, `ISSUE-0075`, `ISSUE-0152` |
| `ISSUE-0018` | `P0/P1` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0165` | `ISSUE-0082`, `ISSUE-0083`, `ISSUE-0126`, `UPDATEV2-0011` |
| `ISSUE-0019` | `P0/P1` | `implemented_initially` | `programme-governance` | - | - | - | `ISSUE-0091`, `ISSUE-0116`, `ISSUE-0138` |
| `ISSUE-0021` | `P1` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0113`, `ISSUE-0116` | `ISSUE-0110`, `ISSUE-0116`, `ISSUE-0130` |
| `ISSUE-0024` | `P1/P2` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0163` | `ISSUE-0073`, `ISSUE-0084`, `ISSUE-0085`, `ISSUE-0130` |
| `ISSUE-0026` | `P1/P2` | `implemented_initially` | `programme-governance` | - | - | - | `ISSUE-0073`, `ISSUE-0088`, `ISSUE-0115` |
| `ISSUE-0027` | `P1` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0117` | `ISSUE-0117`, `ISSUE-0124`, `ISSUE-0139` |
| `ISSUE-0033` | `P2` | `planned` | `programme-governance` | - | - | - | `ISSUE-0024`, `ISSUE-0077`, `ISSUE-0132`, `ISSUE-0135` |
| `ISSUE-0034` | `P1` | `implemented_initially` | `programme-governance` | - | - | - | `ISSUE-0075`, `ISSUE-0090`, `ISSUE-0116`, `ISSUE-0134` |
| `ISSUE-0035` | `P3` | `closed` | `data-and-evidence` | - | - | - | - |
| `ISSUE-0036` | `P1/P2` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0086` | `ISSUE-0081`, `ISSUE-0086`, `ISSUE-0127`, `ISSUE-0146` |
| `ISSUE-0039` | `P1/P2` | `in_progress` | `platform-and-operations` | - | - | `ISSUE-0175` | `ISSUE-0077`, `ISSUE-0078`, `ISSUE-0151` |
| `ISSUE-0040` | `P1` | `in_progress` | `platform-and-operations` | - | - | - | `ISSUE-0077`, `ISSUE-0089`, `ISSUE-0135`, `ISSUE-0146` |
| `ISSUE-0044` | `P1/P2` | `implemented_initially` | `platform-and-operations` | - | - | `ISSUE-0146` | `ISSUE-0145`, `ISSUE-0146` |
| `ISSUE-0047` | `P1` | `implemented_initially` | `programme-governance` | - | - | - | `ISSUE-0074`, `ISSUE-0098`, `ISSUE-0138` |
| `ISSUE-0049` | `P1` | `implemented_initially` | `programme-governance` | - | - | - | `ISSUE-0111`, `ISSUE-0115`, `ISSUE-0128` |
| `ISSUE-0050` | `P1` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0125` | `ISSUE-0085`, `ISSUE-0125`, `ISSUE-0128`, `ISSUE-0134` |
| `ISSUE-0053` | `P1/P2` | `planned` | `programme-governance` | - | - | - | `ISSUE-0033`, `ISSUE-0034`, `ISSUE-0139` |
| `ISSUE-0058` | `P2` | `planned` | `programme-governance` | - | - | - | `ISSUE-0010`, `ISSUE-0149` |
| `ISSUE-0061` | `P3` | `research_only` | `programme-governance` | - | - | - | `ISSUE-0120`, `ISSUE-0128` |
| `ISSUE-0062` | `P3` | `research_only` | `programme-governance` | - | - | - | `ISSUE-0119`, `ISSUE-0120` |
| `ISSUE-0063` | `P1` | `integrated` | `programme-governance` | - | - | - | `ISSUE-0092`, `ISSUE-0098`, `ISSUE-0125`, `ISSUE-0129` |
| `ISSUE-0067` | `P0/P1` | `planned` | `frontend-and-api` | - | - | - | `ISSUE-0034`, `ISSUE-0047`, `UPDATEV2-0022` |
| `ISSUE-0069` | `P3` | `closed` | `programme-governance` | - | - | - | - |
| `ISSUE-0070` | `P0` | `integrated` | `programme-governance` | - | `ISSUE-0008`, `ISSUE-0032`, `ISSUE-0060`, `ISSUE-0066` | `ISSUE-0071`, `ISSUE-0076`, `ISSUE-0080`, `ISSUE-0130` | - |
| `ISSUE-0071` | `P0` | `integrated` | `programme-governance` | `ISSUE-0070` | - | `ISSUE-0072`, `ISSUE-0074`, `ISSUE-0076`, `ISSUE-0136` | - |
| `ISSUE-0072` | `P0` | `integrated` | `data-platform` | `ISSUE-0038`, `ISSUE-0071` | - | `ISSUE-0073`, `ISSUE-0075`, `ISSUE-0077`, `ISSUE-0081`, `ISSUE-0090`, `ISSUE-0127` | - |
| `ISSUE-0073` | `P0` | `integrated` | `data-platform` | `ISSUE-0072` | - | `ISSUE-0074`, `ISSUE-0082`, `ISSUE-0084`, `ISSUE-0088`, `ISSUE-0089`, `ISSUE-0091`, `ISSUE-0119`, `ISSUE-0126` | - |
| `ISSUE-0074` | `P0` | `integrated` | `scoring-and-evidence` | `ISSUE-0071`, `ISSUE-0073` | - | `ISSUE-0075`, `ISSUE-0092`, `ISSUE-0098`, `ISSUE-0108`, `ISSUE-0142`, `ISSUE-0161`, `ISSUE-0165`, `ISSUE-0169`, `ISSUE-0172`, `ISSUE-0174` | - |
| `ISSUE-0075` | `P0` | `integrated` | `reproducibility` | `ISSUE-0072`, `ISSUE-0074` | - | `ISSUE-0077`, `ISSUE-0090`, `ISSUE-0117`, `ISSUE-0141`, `ISSUE-0147` | - |
| `ISSUE-0076` | `P0/P1` | `integrated` | `platform-and-operations` | `ISSUE-0070`, `ISSUE-0071` | - | `ISSUE-0080`, `ISSUE-0144`, `ISSUE-0155`, `ISSUE-0170`, `ISSUE-0171`, `ISSUE-0173`, `ISSUE-0176` | - |
| `ISSUE-0077` | `P0` | `integrated` | `platform-and-operations` | `ISSUE-0072`, `ISSUE-0075` | - | `ISSUE-0078`, `ISSUE-0081`, `ISSUE-0165`, `ISSUE-0175` | - |
| `ISSUE-0078` | `P0/P1` | `integrated` | `platform-and-operations` | `ISSUE-0077` | - | `ISSUE-0151`, `ISSUE-0175` | - |
| `ISSUE-0079` | `P0` | `hardening_required` | `security-and-release` | `ISSUE-0145`, `ISSUE-0149` | - | `ISSUE-0085` | - |
| `UPDATEV2-0010` | `P3` | `closed` | `data-and-evidence` | - | - | - | - |
| `UPDATEV2-0012` | `P0` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0087`, `ISSUE-0091` | `ISSUE-0073`, `ISSUE-0081`, `ISSUE-0091` |
| `UPDATEV2-0013` | `P3` | `closed` | `data-and-evidence` | - | - | - | - |
| `UPDATEV2-0014` | `P1` | `implemented_initially` | `programme-governance` | - | - | `ISSUE-0087` | `ISSUE-0076`, `ISSUE-0087` |
| `UPDATEV2-0017` | `P1` | `closed` | `programme-governance` | - | - | - | `ISSUE-0103`, `ISSUE-0104` |
| `UPDATEV2-0019` | `P1` | `closed` | `programme-governance` | - | - | - | `ISSUE-0105`, `ISSUE-0112` |
| `UPDATEV2-0020` | `P1` | `planned` | `programme-governance` | - | - | - | `ISSUE-0104`, `ISSUE-0149`, `UPDATEV2-0015` |
| `UPDATEV2-0022` | `P3` | `closed` | `analysis-and-validation` | - | - | - | - |
| `UPDATEV2-0024` | `P2` | `planned` | `programme-governance` | - | - | - | `ISSUE-0076`, `ISSUE-0080` |
| `UPDATEV2-0025` | `P2` | `planned` | `programme-governance` | - | - | - | `ISSUE-0076`, `ISSUE-0080` |
| `UPDATEV2-0028` | `P3` | `closed` | `data-and-evidence` | - | - | `ISSUE-0147` | - |
| `UPDATEV2-0029` | `P0` | `integrated` | `platform-and-operations` | - | - | - | `ISSUE-0141`, `ISSUE-0145`, `ISSUE-0152` |
