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

- RED command and non-syntax failure: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q` exited 1 on 2026-07-11 with 11 behavioural failures and 7 passes. Representative failures: the grouped journal exposed only `prepared`/`committed` rather than the required lifecycle; `WriteTransaction` was absent; recovery returned no classification for interrupted and corrupt journals. Collection completed successfully, so this was not an import or syntax failure.
- GREEN plan command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py -q` exited 0 with 29 passed after the lifecycle/fault-injection increment.
- Refactor regression command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py -q` exited 0 with 38 passed. A subsequent affected-release run including three audit/release regressions exited 0 with 41 passed.
- Static checks: Ruff on all changed Python files, `python -m compileall -q src\etf_cockpit`, and `git diff --check` each exited 0.
- Full applicable verification: `python -m pytest tests -q` collected 306 tests and exited 1 with 299 passed and seven failures. These are exactly the seven clean-worktree baseline failures previously recorded by preflight: six `tests/test_simple_scores.py` failures and `tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity`, caused by ignored trade-candidate/catalogue artefacts absent from the isolated worktree. The first full attempt additionally exposed three migration-startup failures caused by scanning pytest artefacts under `logs/pytest_system_tmp`; discovery was narrowed to the supplied root and its immediate dataset directories, and all three affected release/audit regressions then passed.

## Implementation and compatibility record

- The existing `.atomic-transactions` directory, `.atomic-write-group.lock`, journal writer, rollback backups, checksum functions and atomic replace functions remain the only transaction engine. No second lock or journal format was introduced.
- Journal schema 2 adds durable transaction identity, approved dataset/timestamp fields, expected payload checksums, recovery instructions and observable `staging`, `validating`, `committing`, `manifest_publish` and `committed` phases. Legacy schema-1 prepared journals remain recoverable.
- `WriteTransaction` uses the approved `affected_dataset_ids`, `started_at`, `committed_at` and `ready_to_commit`/rollback/recovery status names. Read-only compatibility properties accept the earlier draft names `affected_datasets` and `created_at`. `begin_write_transaction` and `mark_transaction_ready` keep the plan call shapes by defaulting their optional data root to the project data directory.
- Recovery is deterministic and conservative: verified incomplete work rolls back to the old complete state; a verified lingering commit retains the new complete state; corrupt, missing, checksum-invalid or permission-blocked evidence stays in place and returns `recovery_required` plus `read_only` startup mode for manual review. Repeated recovery after a successful rollback is an empty no-op.
- `run_migrations` performs recovery before schema changes and refuses to migrate if recovery cannot be proved. Existing migration and backup/restore compatibility tests pass.
- Recovery outcomes can be emitted through Task 2's authoritative hash-chained session trace via the optional `event_path`; no parallel operational logger exists. The regression asserts event type, status, transaction ID and event hash.
- Writer inventory found existing atomic/grouped canonical seams in backup/restore, import/export, FX, manual notes, import pipeline, trust artefacts, universe store, reference data and simple scores. Direct writers in model/feature/report/export paths were not bulk-rewritten because their ownership belongs to later storage/workflow tasks and doing so would exceed Task 3. No mutable writer required a compatibility-breaking edit for this foundation.

## Evidence and boundary state

- Fault matrix and source checksums: `evidence/wave0/task3/fault-matrix.json`.
- Backup checksum evidence is exercised by `tests/operations/test_backups.py`, `tests/test_atomic_io.py` and `tests/test_backup_restore.py`; tampering blocks restore.
- No UI was changed. Recovery screenshots, Error/Recovery panel, package rebuild and browser smoke remain `pending_later_task` for `ISSUE-0040`; the issue and `REL-02` remain open.
- No issue files were moved or closed, no remote state was changed, and Task 4 was not started. The implementation adds no execution path and does not change the documented `execution_allowed=false` boundary.
- Independent task review and closure evaluation remain pending.

## Remote issue reconciliation preflight

`issues/github_issue_map.json` is a read-only inventory manifest at this boundary. The local ledger parser found 98 canonical stable IDs (77 open, 21 closed), no remote GitHub Issues, and five documented historical/placement contradictions. No remote issue mutation has been performed. The local ledger and approved specification remain authoritative.
