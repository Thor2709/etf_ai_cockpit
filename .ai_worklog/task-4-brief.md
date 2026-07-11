# Wave 0 Task 4 - no-execution and rejection boundary

## Owning programme work

- Owning plan: `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md`, Task 4.
- Specification epics: `FUTURE-01`, `FUTURE-03` and the Wave 0 static execution/rejection interface. This task supplies the boundary consumed by Wave 1 governance and release work; it does not close the later UI-facing tracker records `ISSUE-0008`, `ISSUE-0032`, `ISSUE-0060` or `ISSUE-0066`.
- Base: `origin/main` at `c5fd053425376508e141f3cef3cc09f72d2fe791`; branch `wave0/task4-execution-boundary`.

## Binding constraints

- `execution_allowed` and `executable_authority` remain `false`.
- Preserve current local-first architecture, safety gates, evidence contracts, session trace, audit manifests, router and Flet shell.
- No broker SDK, order endpoint, credential handling, external upload, autonomous execution, score-weight change, model-authority change or adjacent product capability.
- Use RED-GREEN-REFACTOR and observable invariant/failure-path tests. Do not hard-code tests to private control flow.
- Future architecture documents must be explicitly future-only/no-authority, contain no credentials or runnable order examples, and must not be presented as implemented execution capability.

## Required deliverable

Create:

- `src/etf_cockpit/governance/static_checks.py` with `ExecutionBoundaryReport`, `BoundaryViolation` and `run_static_execution_boundary_check(root: Path) -> ExecutionBoundaryReport`.
- `configs/rejection_registry.yaml` with versioned, auditable permanent rejection records.
- `docs/architecture/future/execution_scope_and_approval.md`.
- `docs/architecture/future/broker_adapter_contract.md`.
- `docs/architecture/future/source_of_truth_and_reconciliation.md`.
- `tests/scope_boundary/test_execution_boundary.py`.
- `tests/scope_boundary/test_rejection_registry.py`.
- `tests/scope_boundary/test_package_inventory.py`.

Modify only the approved `src/etf_cockpit/core/types.py` boundary fields and release/audit scripts when the new report interface requires it.

## Observable acceptance criteria

1. A production-like tree containing `def place_order(): pass` fails with `PROHIBITED_ORDER_SYMBOL`.
2. A benign identifier such as `sort_order = 'asc'` passes without a false positive.
3. Context-aware AST/config/dependency/resource scans reject broker SDKs, order-routing symbols, credential/order endpoints, current UI order controls and any schema value with `execution_allowed=True`.
4. Explicit future-only documentation and test fixtures are allow-listed without weakening production scans.
5. The report is machine-readable, schema-versioned, deterministic for the same tree/policy and carries a policy checksum and generation timestamp.
6. Rejection-registry records are validated, duplicate-free, auditable and preserve `execution_allowed=false`.
7. Production source and package inventory pass; injected violations fail; no credentials or runnable order examples occur in future docs.
8. Existing authority boundaries remain unchanged and all relevant tests/regressions pass.

## Required RED/GREEN commands

RED:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\scope_boundary\test_execution_boundary.py tests\scope_boundary\test_rejection_registry.py -q
```

Expected RED: behavioural failures because checker/registry/tests are absent or incomplete, not import/syntax-only failure.

GREEN/regression:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\scope_boundary tests\test_release_hardening.py -q
```

Also run scoped Ruff, compileall, package inventory checks and the relevant full regression suite. Record exact results in `.ai_worklog/task-4-report.md` and leave review/closure status accurate; do not close an unrelated issue in this task.
