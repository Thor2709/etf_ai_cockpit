# Completion programme progress

This file is generated from `issues/issue_registry.json`; it contains no wall-clock state.

## Status summary

| Programme status | Records |
|---|---:|
| `blocked` | 1 |
| `closed` | 4 |
| `hardening_required` | 3 |
| `implemented_initially` | 58 |
| `in_progress` | 9 |
| `integrated` | 28 |
| `planned` | 54 |
| `research_only` | 2 |

## Ready issues

`ISSUE-0150`, `ISSUE-0095`, `ISSUE-0097`, `ISSUE-0151`, `UPDATEV2-0014`, `UPDATEV2-0018`, `UPDATEV2-0020`, `UPDATEV2-0023`, `UPDATEV2-0026`, `ISSUE-0029`, `ISSUE-0037`, `ISSUE-0046`, `ISSUE-0051`, `ISSUE-0053`, `ISSUE-0010`, `ISSUE-0032`, `ISSUE-0033`, `ISSUE-0043`, `ISSUE-0058`, `ISSUE-0066`, `UPDATEV2-0024`, `UPDATEV2-0025`, `UPDATEV2-0030`

## Phase coverage

| Phase | Records |
|---|---:|
| `phase-01-governance-scope` | 43 |
| `phase-02-data-policy-identity` | 28 |
| `phase-03-stock-research` | 12 |
| `phase-04-etf-research` | 5 |
| `phase-05-returns-risk-portfolio` | 20 |
| `phase-06-model-research` | 8 |
| `phase-07-backtest-paper-execution` | 15 |
| `phase-08-frontend-api` | 16 |
| `phase-09-quality-release-security` | 6 |
| `phase-10-audit-documentation-governance` | 5 |
| `phase-11-certification` | 1 |

## Safety boundaries

- `execution_allowed=false` remains the controlling product boundary.
- Optional providers and model integrations remain non-blocking.
- GitHub synchronisation remains dry-run by default and requires a reviewed plan checksum.
