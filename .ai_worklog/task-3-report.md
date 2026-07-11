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
| Transaction records and lifecycle | verified_task_scope | Typed contract and real journal lifecycle tests |
| Staging before activation | verified_task_scope | Real writer and staged tamper tests |
| All-or-nothing old/new complete visibility | verified_task_scope | Fault matrix and concurrent real-writer recovery |
| Durable journal/evidence and transaction identity | verified_task_scope | Strict identity validation and durable artefact manifest |
| Checksums and validation before activation | verified_task_scope | Post-hook checksum recomputation regression |
| Writer locking and concurrent writers | verified_task_scope | Canonical locks precede snapshots; real two-writer regression |
| Interrupted writes, migrations and activation | verified_task_scope | Real interruption and nested migration preflight tests |
| Stale/orphaned staging classification | verified_task_scope | Recovery classification tests |
| Deterministic idempotent recovery | verified_task_scope | Repeated recovery test |
| Corrupt journal/payload/checksum/missing-file handling | verified_task_scope | Schema, state, cardinality, containment and payload tests |
| Permission/locked-file/write-failure handling | verified_task_scope | Failure injection tests |
| Startup recovery and clean-start behaviour | verified_task_scope | Startup recovery and clean restart tests |
| Operational-event emission and audit/manifest visibility | verified_task_scope | Default Task 2 session trace and durable event evidence |
| Data Health visibility | pending_later_task | No user-facing Data Health change is owned by Task 3 |
| Backward compatibility / migration behaviour | verified_task_scope | Legacy schema-1 and migration regression tests |
| Read-only or unavailable state when recovery is unproven | verified_task_scope | Invalid journals remain preserved and read-only |
| ISSUE-0040 readable errors, panel, retry and Activity Log UI | pending_later_task | Required by issue but not this infrastructure task |
| ISSUE-0040 package/build/browser gates | pending_later_task | Required by issue but not this infrastructure task |
| Independent task review | rejected_fix_pending_rereview | Review 1 rejected; all findings received a fix pass; fresh rereview required |
| Closure evaluator | pending_later_task | Issue and REL-02 remain open until all later UI/package/browser gates pass |
| `execution_allowed` remains `false` | verified_unchanged | No execution-authority source or configuration changed |

## RED-GREEN-REFACTOR evidence

To be recorded by the implementer and independently checked by the reviewer:

- RED command and non-syntax failure: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q` exited 1 on 2026-07-11 with 11 behavioural failures and 7 passes. Representative failures: the grouped journal exposed only `prepared`/`committed` rather than the required lifecycle; `WriteTransaction` was absent; recovery returned no classification for interrupted and corrupt journals. Collection completed successfully, so this was not an import or syntax failure.
- Review-fix RED cycle: the exact model test exited 1 because `base_generation_ids` was absent. The adversarial command covering staged tampering and corrupt journals exited 1: tampering did not raise, and unknown-state, missing-field, cardinality, transaction-identity and outside-root journals all returned `rolled_back` instead of `recovery_required`. The first nested-layout attempt had a test-fixture `NameError`; that fixture error was corrected before its behavioural result was counted. The initial combined concurrency run terminated its Windows test process because the existing POSIX-style `os.kill(pid, 0)` probe is destructive on Windows; the root cause was replaced with a read-only process-handle query, after which the real concurrency test could run normally.
- Partial-staging RED cycle: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py::test_real_group_interruption_recovers_the_previous_complete_generation -q` exited 1 with the real `staging` interruption classified `recovery_required` because zero entries contradicted pre-populated top-level path/checksum fields. The writer now publishes those fields with each entry; the same command exited 0 with four passes.
- GREEN plan command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py -q` exited 0 with 29 passed after the lifecycle/fault-injection increment.
- Review-fix GREEN/refactor command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py -q` exited 0 with 54 passed.
- Static checks: scoped Ruff exited 0 (`All checks passed!`); `python -m compileall -q src\etf_cockpit` exited 0; both `git diff --check HEAD` and `git diff --check 445dd44b5382160d4e93e4cada018beb4ab0f5b5` exited 0.
- Full applicable verification: `python -m pytest tests -q` collected 322 tests and exited 1 with 315 passed and seven failures. These are exactly the unchanged clean-worktree baseline failures: six `tests/test_simple_scores.py` failures and `tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity`, caused by ignored trade-candidate/catalogue artefacts absent from the isolated worktree. No Task 3 test failed.

## Implementation and compatibility record

- The existing `.atomic-transactions` directory, `.atomic-write-group.lock`, journal writer, rollback backups, checksum functions and atomic replace functions remain the only transaction engine. No second lock or journal format was introduced.
- Journal schema 2 adds durable transaction identity, approved dataset/timestamp fields, expected payload checksums, recovery instructions and observable `staging`, `validating`, `committing`, internal `manifest_publish` and `committed` phases. Legacy schema-1 prepared journals remain recoverable.
- `WriteTransaction` exposes the exact approved public list fields, `base_generation_ids`, list-valued recovery instructions and approved statuses beginning with `planned`; internal `manifest_publish` projects to public `committing`. Read-only compatibility aliases preserve `affected_datasets`, `created_at` and `base_generations`, and legacy mapping inputs are normalised without changing the public list schema.
- Recovery is deterministic and conservative: verified incomplete work rolls back to the old complete state; a verified lingering commit retains the new complete state; corrupt, missing, checksum-invalid or permission-blocked evidence stays in place and returns `recovery_required` plus `read_only` startup mode for manual review. Repeated recovery after a successful rollback is an empty no-op.
- `run_migrations` performs recovery before schema changes and refuses to migrate if recovery cannot be proved. Existing migration and backup/restore compatibility tests pass.
- Recovery outcomes use Task 2's authoritative hash-chained session trace by default; migration preflight passes its project-root trace explicitly. No parallel operational logger exists. Regressions assert the default production path, event type, status, transaction ID and event hash.
- Writer inventory found existing atomic/grouped canonical seams in backup/restore, import/export, FX, manual notes, import pipeline, trust artefacts, universe store, reference data and simple scores. Direct writers in model/feature/report/export paths were not bulk-rewritten because their ownership belongs to later storage/workflow tasks and doing so would exceed Task 3. No mutable writer required a compatibility-breaking edit for this foundation.

## Evidence and boundary state

- Fault matrix and source checksums: `evidence/wave0/task3/fault-matrix.json`.
- Durable synthetic evidence inventory: `evidence/wave0/task3/artefacts/artefact-manifest.json`. It records the concrete backup manifest (`f04e498f217da4546620c003cd7b311d4ed9597b1bf045260e022640b3492631`), verified restore result, preserved interrupted journal, recovery result (`70711c6110c72ae5e6fda384a28d0bad1b7c2fa2aee7d8a199ca5ee73e6fe6b9`) and authoritative event artefact (`5810a49942e0beaa7186adf4855a271a27e43a4ef505168fc15fa5b43b86d017`). The drill contains synthetic text only, with no secrets or generated market data.
- No UI was changed. Recovery screenshots, Error/Recovery panel, package rebuild and browser smoke remain `pending_later_task` for `ISSUE-0040`; the issue and `REL-02` remain open.
- No issue files were moved or closed, no remote state was changed, and Task 4 was not started. The implementation adds no execution path and does not change the documented `execution_allowed=false` boundary.
- Independent task review and closure evaluation remain pending.

## Independent review 1 disposition

- C1 fixed: canonical locks are acquired before old-generation reads/backups and held through activation and manifest publication. A real two-writer interruption proves recovery preserves writer 1's commit.
- C2 and I5 fixed: complete schema-2 validation covers required fields, approved states, identity, cardinality, contradictory maps, checksums and strict containment before mutation. Invalid journals remain auditable, read-only and untouched; legacy schema-1 paths also cannot escape the supplied root.
- I1 fixed: validators and staged SHA-256 checks run again after the commit hook and lock acquisition, immediately before activation.
- I2 fixed: recovery discovers direct and canonical nested transaction roots, including `data/clean`, while excluding `logs` and `pytest_*` artefacts. Migration preflight uses a real nested writer regression.
- I3 fixed: the public model now uses `base_generation_ids: dict[str, str]`, list-valued staging/final paths and recovery instructions, and exact approved status literals including `planned`; compatibility aliases remain read-only.
- I4 fixed: default recovery emission and migration preflight both use the authoritative Task 2 session trace and produce hash-chained events.
- I6 fixed: concrete backup, restore, interrupted-journal, recovery-result and event artefacts plus checksums are durable under `evidence/wave0/task3/artefacts`.
- M1 fixed: both current-diff and full review-range whitespace checks exit 0.
- M2 fixed: completed infrastructure gates are `verified_task_scope`; later UI/package/browser gates remain `pending_later_task`, review remains `rejected_fix_pending_rereview`, and `ISSUE-0040`/`REL-02` remain open.

Fix implementation commit: `4d02c8076cbdbc1da296d9b39962104a8a2a224f` (`fix: harden atomic transaction recovery`).

## Remote issue reconciliation preflight

`issues/github_issue_map.json` is a read-only inventory manifest at this boundary. The local ledger parser found 98 canonical stable IDs (77 open, 21 closed), no remote GitHub Issues, and five documented historical/placement contradictions. No remote issue mutation has been performed. The local ledger and approved specification remain authoritative.
