# ETF AI Cockpit completion roadmap

This roadmap is the lightweight programme view. `issues/issue_registry.json` owns issue identity, title, priority, state, acceptance criteria and dependencies; phase documents own implementation guidance.

## Guardrails

- Local-first and advisory by default; no broker automation, external upload or cloud service is introduced.
- Risk gates override model forecasts, audits and UI actions.
- Adjusted prices are required for returns, signals and backtests.
- Toto and TimesFM are optional; baseline signals must work without their packages or weights.
- GitHub synchronisation is dry-run by default and apply requires a reviewed plan checksum.

## Phase order

| Phase | Coverage | Records | State summary | Owners |
|---|---|---:|---|---|
| `phase-01-governance-scope` | `ISSUE-0070–ISSUE-0079` - Governance, scope and completion contract | 43 | closed=2, implemented_initially=7, in_progress=4, integrated=5, planned=23, research_only=2 | data-platform, platform-and-operations, programme-governance, reproducibility, scoring-and-evidence, security-and-release |
| `phase-02-data-policy-identity` | `ISSUE-0080–ISSUE-0090` - Local-first data policy, identity and data platform | 28 | closed=2, implemented_initially=6, in_progress=2, integrated=1, planned=17 | data-and-evidence, data-platform |
| `phase-03-stock-research` | `ISSUE-0091–ISSUE-0102` - Stock statements, fundamentals, valuation and sectors | 12 | planned=12 | stock-research |
| `phase-04-etf-research` | `ISSUE-0103–ISSUE-0107` - ETF economics, structure, exposure and context | 5 | planned=5 | etf-research |
| `phase-05-returns-risk-portfolio` | `ISSUE-0108–ISSUE-0116` - Expected return, risk and portfolio construction | 20 | implemented_initially=3, planned=17 | analysis-and-validation, portfolio-construction, returns-and-risk |
| `phase-06-model-research` | `ISSUE-0117–ISSUE-0124` - Training, validation and model governance | 8 | planned=8 | model-governance |
| `phase-07-backtest-paper-execution` | `ISSUE-0125–ISSUE-0135` - Backtest, paper trading and staged execution | 15 | planned=15 | backtest-and-paper, trading-safety |
| `phase-08-frontend-api` | `ISSUE-0136–ISSUE-0140` - Typed local API and task-oriented frontend | 16 | implemented_initially=3, in_progress=3, planned=10 | frontend-and-api |
| `phase-09-quality-release-security` | `ISSUE-0141–ISSUE-0146` - Quality, release, security and resilience | 6 | planned=6 | programme-governance, quality-and-release, security-and-release |
| `phase-10-audit-documentation-governance` | `ISSUE-0147–ISSUE-0151` - Audit, reproducibility, documentation and governance | 5 | planned=5 | audit-and-reproducibility, documentation, model-governance, programme-governance, quality-and-release |
| `phase-11-certification` | `ISSUE-0152` - Final certification and programme closure | 1 | planned=1 | programme-governance |

## Thirteen-stage mapping

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
