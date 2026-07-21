# Completion programme progress

This file is generated from `issues/issue_registry.json`; it contains no wall-clock state.

## Status summary

| Programme status | Records |
|---|---:|
| `blocked` | 1 |
| `closed` | 17 |
| `hardening_required` | 4 |
| `implemented_initially` | 60 |
| `in_progress` | 7 |
| `integrated` | 34 |
| `planned` | 72 |
| `research_only` | 2 |

## Ready issues

`ISSUE-0011`, `ISSUE-0012`, `ISSUE-0013`, `ISSUE-0070`, `ISSUE-0145`, `ISSUE-0152`, `UPDATEV2-0011`, `UPDATEV2-0012`, `UPDATEV2-0021`, `UPDATEV2-0027`, `UPDATEV2-0029`, `ISSUE-0014`, `ISSUE-0018`, `ISSUE-0019`, `ISSUE-0028`, `ISSUE-0030`, `ISSUE-0067`, `ISSUE-0068`, `ISSUE-0015`, `ISSUE-0016`, `ISSUE-0017`, `ISSUE-0020`, `ISSUE-0021`, `ISSUE-0022`, `ISSUE-0023`, `ISSUE-0025`, `ISSUE-0027`, `ISSUE-0031`, `ISSUE-0034`, `ISSUE-0040`, `ISSUE-0045`, `ISSUE-0047`, `ISSUE-0048`, `ISSUE-0049`, `ISSUE-0050`, `ISSUE-0052`, `ISSUE-0057`, `ISSUE-0060`, `ISSUE-0063`, `ISSUE-0064`, `UPDATEV2-0014`, `UPDATEV2-0018`, `UPDATEV2-0020`, `UPDATEV2-0023`, `UPDATEV2-0026`, `ISSUE-0024`, `ISSUE-0026`, `ISSUE-0029`, `ISSUE-0036`, `ISSUE-0037`, `ISSUE-0039`, `ISSUE-0041`, `ISSUE-0042`, `ISSUE-0044`, `ISSUE-0046`, `ISSUE-0051`, `ISSUE-0053`, `ISSUE-0054`, `ISSUE-0059`, `ISSUE-0007`, `ISSUE-0008`, `ISSUE-0010`, `ISSUE-0032`, `ISSUE-0033`, `ISSUE-0038`, `ISSUE-0043`, `ISSUE-0055`, `ISSUE-0056`, `ISSUE-0058`, `ISSUE-0065`, `ISSUE-0066`, `UPDATEV2-0024`, `UPDATEV2-0025`, `UPDATEV2-0030`, `ISSUE-0061`, `ISSUE-0062`

## Readiness reason summary

- `BLOCKED_UNRESOLVED_DEPENDENCY`: 104
- `CLOSED_LEDGER_NOT_IMPLEMENTATION_CANDIDATE`: 17
- `READY_NO_BLOCKING_DEPENDENCIES`: 76

Activation readiness is projected separately from implementation readiness. It never grants execution authority; `execution_allowed=false` remains mandatory.

## Phase coverage

| Phase | Records |
|---|---:|
| `phase-01-governance-scope` | 57 |
| `phase-02-data-policy-identity` | 32 |
| `phase-03-stock-research` | 12 |
| `phase-04-etf-research` | 6 |
| `phase-05-returns-risk-portfolio` | 30 |
| `phase-06-model-research` | 8 |
| `phase-07-backtest-paper-execution` | 16 |
| `phase-08-frontend-api` | 22 |
| `phase-09-quality-release-security` | 8 |
| `phase-10-audit-documentation-governance` | 5 |
| `phase-11-certification` | 1 |

## Safety boundaries

- `execution_allowed=false` remains the controlling product boundary.
- Optional providers and model integrations remain non-blocking.
- GitHub synchronisation remains dry-run by default and requires a reviewed plan checksum.
