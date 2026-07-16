# Implementation order

Follow the phase order below. Within a phase, resolve `blocking_dependencies` before implementation; treat `related_issues` as context only.

1. **phase-01-governance-scope** - Governance, scope and completion contract (ISSUE-0070–ISSUE-0079; 43 records).
2. **phase-02-data-policy-identity** - Local-first data policy, identity and data platform (ISSUE-0080–ISSUE-0090; 28 records).
3. **phase-03-stock-research** - Stock statements, fundamentals, valuation and sectors (ISSUE-0091–ISSUE-0102; 12 records).
4. **phase-04-etf-research** - ETF economics, structure, exposure and context (ISSUE-0103–ISSUE-0107; 5 records).
5. **phase-05-returns-risk-portfolio** - Expected return, risk and portfolio construction (ISSUE-0108–ISSUE-0116; 20 records).
6. **phase-06-model-research** - Training, validation and model governance (ISSUE-0117–ISSUE-0124; 8 records).
7. **phase-07-backtest-paper-execution** - Backtest, paper trading and staged execution (ISSUE-0125–ISSUE-0135; 15 records).
8. **phase-08-frontend-api** - Typed local API and task-oriented frontend (ISSUE-0136–ISSUE-0140; 16 records).
9. **phase-09-quality-release-security** - Quality, release, security and resilience (ISSUE-0141–ISSUE-0146; 6 records).
10. **phase-10-audit-documentation-governance** - Audit, reproducibility, documentation and governance (ISSUE-0147–ISSUE-0151; 5 records).
11. **phase-11-certification** - Final certification and programme closure (ISSUE-0152; 1 records).

The canonical blocking graph is available as `docs/product-completion/reconciliation/2026-07-17-3321ebd/canonical-dag.json`. Cyclic raw candidates were converted to related references with reasons rather than silently dropped.
