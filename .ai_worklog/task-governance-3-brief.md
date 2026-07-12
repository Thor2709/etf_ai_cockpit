# Wave 1 Governance Task 3 brief

Read this brief first. Implement only the dependency-ordered Governance Task 3
scope on branch `wave1/governance-task3`, based on `origin/main` at
`2a26619bdbf26f11e8a77dbdefc3ab22d93d213b`.

## Required outcome

Centralise severity-aware authority resolution and permanently neutralise the
deprecated `trading_allowed` compatibility property. Produce a deterministic
typed `AuthorityDecision` and ordered `GateResult` table consumed by release
paths. Preserve the approved v2 research-state and portfolio-review-state
contracts from Tasks 1-2.

## Exact task interfaces

Create:

- `src/etf_cockpit/governance/gate_policy.py`
- `tests/test_authority_resolution.py`
- `evidence/governance/gate_resolution_samples/` representative typed gate
  table and policy checksum evidence.

Modify only the required seams in:

- `src/etf_cockpit/signals/gates.py`
- `src/etf_cockpit/core/types.py`
- `src/etf_cockpit/services.py`
- `src/etf_cockpit/portfolio/proposals.py`
- release/export callers that consume the authority decision.

Expose a deterministic function with this contract:

```python
def resolve_authority(
    base_state: ResearchState,
    gates: Sequence[GateResult],
    portfolio_context: PortfolioContext | None,
) -> AuthorityDecision: ...
```

Use the existing Task 2 `ResearchState`, `PortfolioReviewState`, `GateSeverity`,
`GateResult` and `AuthorityDecision` types where compatible; extend them
narrowly rather than replacing them. Every result must carry policy version and
checksum metadata and `execution_allowed` must be the literal `False`.

## Binding gate semantics

Process gates in this order: identity, data, evidence, model validity, risk,
valuation, signal, portfolio fit and cost. A failed blocker is monotonic: it
cannot be erased by a later passing gate and forces `not_scoreable` plus both
promotion dimensions false. An `authority_warning` may downgrade a positive
state and must remain visible; it cannot increase authority. Notices remain
visible and cannot increase authority. Missing, malformed, unsupported or
unavailable policy input fails closed to a diagnostic state with explicit
unavailable metadata. Portfolio review remains separate from research state
and requires validated portfolio context; it never grants execution.

The deprecated `trading_allowed` property must warn and always return `False`.
No resolver or compatibility adapter may return `True` for it or for
`execution_allowed`.

## TDD and review contract

Write meaningful RED tests before production behaviour. The required initial
command is:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py -q
```

Expected RED: failure because no typed resolver exists and the deprecated
`trading_allowed` seam remains permissive. Record the exact command, exit code,
failure output and timestamp in `.ai_worklog/task-governance-3-report.md`.

GREEN command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_authority_resolution.py tests\test_signal_gates.py tests\test_release_hardening.py -q
```

Also run the affected governance, Task 2 migration, proposal and export
regressions, compileall, scoped Ruff and the authoritative full suite. Record
the seven known generated-data/identity baseline failures separately and do
not attribute them to this task.

## Invariants and forbidden scope

- `execution_allowed` remains `False` everywhere.
- Do not change score weights, model authority, portfolio targets, research
  thresholds, data coverage, DATA-05 membership or product scope.
- Do not implement Task 4's journal/review-report replacement or Task 5 UI.
- Do not add broker execution, credentials, order routing or autonomous action.
- Do not close or reopen issues; update only the Task 3 worklog/evidence until
  the controller performs integration bookkeeping.
- Preserve provider/evidence contracts, atomic I/O, session tracing, audit
  manifests and existing Flet architecture.

## Required report

Append to `.ai_worklog/task-governance-3-report.md`: changed files and symbols,
RED/GREEN/REFACTOR commands/results, migration/compatibility behaviour,
failure-path and monotonicity evidence, policy/checksum evidence, full-suite
classification, compile/lint results, concerns and self-review status. Do not
claim issue closure. Commit only the implementation and focused evidence after
the controller dispatches the independent reviewer.
