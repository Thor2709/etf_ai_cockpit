# ETF AI Cockpit completion roadmap

This roadmap is the lightweight programme view. `issues/issue_registry.json` owns issue identity, title, priority, state, acceptance criteria and dependencies; phase documents own implementation guidance.

## Guardrails

- Local-first and advisory by default; no broker automation, external upload or cloud service is introduced.
- Risk gates override model forecasts, audits and UI actions.
- Adjusted prices are required for returns, signals and backtests.
- Toto and TimesFM are optional; baseline signals must work without their packages or weights.
- GitHub synchronisation is dry-run by default and apply requires a reviewed plan checksum.
- Current delivery mechanics are defined in [`DELIVERY_WORKFLOW.md`](../DELIVERY_WORKFLOW.md); phase grouping does not authorise multi-issue PRs or multiple writers.

## Phase order

| Phase | Coverage | Records | State summary | Owners |
|---|---|---:|---|---|
| `phase-01-governance-scope` | `ISSUE-0001–ISSUE-0006, ISSUE-0009–ISSUE-0010, ISSUE-0012–ISSUE-0015, ISSUE-0018–ISSUE-0019, ISSUE-0021, ISSUE-0024, ISSUE-0026–ISSUE-0027, ISSUE-0033–ISSUE-0036, ISSUE-0039–ISSUE-0040, ISSUE-0044, ISSUE-0047, ISSUE-0049–ISSUE-0050, ISSUE-0053, ISSUE-0058, ISSUE-0061–ISSUE-0063, ISSUE-0067, ISSUE-0069–ISSUE-0079, ISSUE-0179, UPDATEV2-0010, UPDATEV2-0012–UPDATEV2-0014, UPDATEV2-0017, UPDATEV2-0019–UPDATEV2-0020, UPDATEV2-0022, UPDATEV2-0024–UPDATEV2-0025, UPDATEV2-0028–UPDATEV2-0029` - Governance, scope and completion contract | 58 | closed=15, hardening_required=1, implemented_initially=14, in_progress=2, integrated=17, planned=7, research_only=2 | analysis-and-validation, data-and-evidence, data-platform, frontend-and-api, platform-and-operations, programme-control, programme-governance, reproducibility, scoring-and-evidence, security-and-release |
| `phase-02-data-policy-identity` | `ISSUE-0007, ISSUE-0022–ISSUE-0023, ISSUE-0025, ISSUE-0038, ISSUE-0048, ISSUE-0054–ISSUE-0056, ISSUE-0068, ISSUE-0080–ISSUE-0090, ISSUE-0153, ISSUE-0155, ISSUE-0170–ISSUE-0171, ISSUE-0181, UPDATEV2-0011, UPDATEV2-0015–UPDATEV2-0016, UPDATEV2-0018, UPDATEV2-0021, UPDATEV2-0023, UPDATEV2-0030` - Local-first data policy, identity and data platform | 33 | closed=2, implemented_initially=8, integrated=18, planned=5 | data-and-evidence, data-platform |
| `phase-03-stock-research` | `ISSUE-0091–ISSUE-0102` - Stock statements, fundamentals, valuation and sectors | 12 | implemented_initially=4, integrated=7, planned=1 | stock-research |
| `phase-04-etf-research` | `ISSUE-0103–ISSUE-0107, ISSUE-0172` - ETF economics, structure, exposure and context | 6 | implemented_initially=1, integrated=2, planned=3 | etf-and-fund-research, etf-research |
| `phase-05-returns-risk-portfolio` | `ISSUE-0008, ISSUE-0028–ISSUE-0029, ISSUE-0046, ISSUE-0051–ISSUE-0052, ISSUE-0059–ISSUE-0060, ISSUE-0064–ISSUE-0065, ISSUE-0108–ISSUE-0116, ISSUE-0154, ISSUE-0156–ISSUE-0157, ISSUE-0159, ISSUE-0162, ISSUE-0164, ISSUE-0166, ISSUE-0168, ISSUE-0173–ISSUE-0174, UPDATEV2-0026` - Expected return, risk and portfolio construction | 30 | implemented_initially=9, integrated=7, planned=14 | analysis-and-validation, portfolio-construction, programme-governance, returns-and-risk |
| `phase-06-model-research` | `ISSUE-0117–ISSUE-0124` - Training, validation and model governance | 8 | implemented_initially=6, planned=2 | model-governance |
| `phase-07-backtest-paper-execution` | `ISSUE-0031–ISSUE-0032, ISSUE-0057, ISSUE-0066, ISSUE-0125–ISSUE-0135, ISSUE-0167` - Backtest, paper trading and staged execution | 16 | implemented_initially=2, integrated=4, planned=10 | backtest-and-paper, trading-safety |
| `phase-08-frontend-api` | `ISSUE-0011, ISSUE-0016–ISSUE-0017, ISSUE-0020, ISSUE-0030, ISSUE-0037, ISSUE-0041–ISSUE-0043, ISSUE-0045, ISSUE-0136–ISSUE-0140, ISSUE-0158, ISSUE-0160–ISSUE-0161, ISSUE-0163, ISSUE-0165, ISSUE-0175, UPDATEV2-0027` - Typed local API and task-oriented frontend | 22 | implemented_initially=9, in_progress=2, integrated=4, planned=7 | application-platform, frontend-and-api |
| `phase-09-quality-release-security` | `ISSUE-0141–ISSUE-0146, ISSUE-0169, ISSUE-0176–ISSUE-0178, ISSUE-0180` - Quality, release, security and resilience | 11 | hardening_required=1, integrated=7, planned=3 | programme-governance, quality-and-release, quality-release, security-and-release |
| `phase-10-audit-documentation-governance` | `ISSUE-0147–ISSUE-0151` - Audit, reproducibility, documentation and governance | 5 | hardening_required=2, implemented_initially=1, planned=2 | audit-and-reproducibility, documentation, model-governance, programme-governance, quality-and-release |
| `phase-11-certification` | `ISSUE-0152` - Final certification and programme closure | 1 | blocked=1 | programme-governance |

## Phase mapping

1. Scope and governance - `phase-01-governance-scope`.
2. Architecture and storage - `phase-01-governance-scope` / `phase-02-data-policy-identity`.
3. Local data and identity - `phase-02-data-policy-identity`.
4. Stock research - `phase-03-stock-research`.
5. ETF research - `phase-04-etf-research`.
6. Returns and risk - `phase-05-returns-risk-portfolio`.
7. Model governance - `phase-06-model-research`.
8. Event and backtest evidence - `phase-07-backtest-paper-execution`.
9. Paper trading and execution safety - `phase-07-backtest-paper-execution`.
10. Frontend and local API - `phase-08-frontend-api`.
11. Quality and release - `phase-09-quality-release-security`.
12. Security, resilience, audit, documentation and bias controls - `phase-09-quality-release-security` / `phase-10-audit-documentation-governance`.
13. Certification - `phase-11-certification`.

## Completion evidence

A phase is complete only when its deterministic tests, safety gates, evidence/provenance checks, compatibility path and reviewable diff are present. Product implementation is intentionally outside this reconciliation task.
