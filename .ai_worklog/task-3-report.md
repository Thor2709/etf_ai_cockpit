# Wave 0 Task 3 - Atomic transaction and deterministic recovery

Date opened: 2026-07-11  
Branch: `wave0/task3-atomic-recovery`  
Task base: `445dd44b5382160d4e93e4cada018beb4ab0f5b5` (`origin/main`)  
Owning local issue: `ISSUE-0040` - Error handling and recovery centre.  
Related later-task issue seams: `ISSUE-0038` (storage migration plan) and `ISSUE-0044` (backup/restore UI and release metadata). These remain open unless their own closure gates pass.

## Closure decision before implementation

Task 3 is an infrastructure increment for the atomic-commit and recovery portion of `ISSUE-0040`; it cannot close that issue by itself because the local issue requires a user-visible Error/Recovery panel, retry workflow, package rebuild and browser failure smoke. Those are later dependency-valid tasks. The issue therefore remains open with an implementation-complete, closure-pending state until those gates have fresh evidence.

## Task 3 closure checklist

Each row is updated only after fresh evidence exists.

| Gate | State before implementation | Evidence / reason |
|---|---|---|
| Transaction records and lifecycle | pending | Task 3 implementation |
| Staging before activation | pending | Task 3 implementation and tests |
| All-or-nothing old/new complete visibility | pending | Fault matrix tests |
| Durable journal/evidence and transaction identity | pending | Task 3 implementation and audit evidence |
| Checksums and validation before activation | pending | Recovery/integrity tests |
| Writer locking and concurrent writers | pending | Lock contention tests |
| Interrupted writes, migrations and activation | pending | Fault injection and startup recovery tests |
| Stale/orphaned staging classification | pending | Recovery tests |
| Deterministic idempotent recovery | pending | Repeated recovery tests |
| Corrupt journal/payload/checksum/missing-file handling | pending | Recovery failure-path tests |
| Permission/locked-file/write-failure handling | pending | Failure injection tests |
| Startup recovery and clean-start behaviour | pending | Recovery integration tests |
| Operational-event emission and audit/manifest visibility | pending | Existing Task 2 contracts plus Task 3 evidence |
| Data Health visibility | pending_later_task | No user-facing Data Health change is owned by Task 3 |
| Backward compatibility / migration behaviour | pending | Migration and compatibility tests |
| Read-only or unavailable state when recovery is unproven | pending | Recovery classification tests |
| ISSUE-0040 readable errors, panel, retry and Activity Log UI | pending_later_task | Required by issue but not this infrastructure task |
| ISSUE-0040 package/build/browser gates | pending_later_task | Required by issue but not this infrastructure task |
| Independent task review | pending | Fresh reviewer required |
| Closure evaluator | pending | Issue remains closure-pending unless all gates pass |
| `execution_allowed` remains `false` | pending | Boundary regression |

## RED-GREEN-REFACTOR evidence

To be recorded by the implementer and independently checked by the reviewer:

- RED command and non-syntax failure: pending.
- GREEN focused transaction/recovery command: pending.
- Refactor regression command: pending.
- Full applicable verification: pending.

## Remote issue reconciliation preflight

`issues/github_issue_map.json` is a read-only inventory manifest at this boundary. The local ledger parser found 98 canonical stable IDs (77 open, 21 closed), no remote GitHub Issues, and five documented historical/placement contradictions. No remote issue mutation has been performed. The local ledger and approved specification remain authoritative.

