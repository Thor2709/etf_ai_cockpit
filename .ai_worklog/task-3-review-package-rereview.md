# Review package: d48bbbe..902b21c (fix pass)

## Commits
902b21c docs: record Task 3 fix verification
4d02c80 fix: harden atomic transaction recovery

## Files changed
 .ai_worklog/task-3-brief.md                        |   1 -
 .ai_worklog/task-3-report.md                       |  74 ++--
 .../wave0/task3/artefacts/artefact-manifest.json   |  46 +++
 .../9eb3d7d8a764_canonical-sample.txt              |   1 +
 .../backups/20260711T081411.470664Z/manifest.json  |  12 +
 .../artefacts/backup-drill/canonical-sample.txt    |   1 +
 .../artefacts/backup-drill/restore-result.json     |  11 +
 .../recovery-drill/data/clean/canonical-sample.txt |   1 +
 .../recovery-drill/interrupted-journal.json        |  39 +++
 .../artefacts/recovery-drill/recovery-result.json  |  14 +
 .../task3/artefacts/recovery-drill/session.jsonl   |   1 +
 evidence/wave0/task3/fault-matrix.json             |  25 +-
 src/etf_cockpit/core/atomic_io.py                  |  43 ++-
 src/etf_cockpit/core/migrations.py                 |   5 +-
 src/etf_cockpit/operations/models.py               |  34 +-
 src/etf_cockpit/operations/recovery.py             | 386 ++++++++++++++++++---
 tests/operations/test_recovery.py                  | 178 +++++++++-
 tests/operations/test_transactions.py              | 119 ++++++-
 18 files changed, 880 insertions(+), 111 deletions(-)

## Diff
diff --git a/.ai_worklog/task-3-brief.md b/.ai_worklog/task-3-brief.md
index 86a256c..2638aa2 100644
--- a/.ai_worklog/task-3-brief.md
+++ b/.ai_worklog/task-3-brief.md
@@ -50,13 +50,12 @@ Write the fault matrix, backup manifest checksums and recovery-state screenshots
 
 - Work only in `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task3-atomic-recovery` on branch `wave0/task3-atomic-recovery`; do not edit `main`.
 - Correct task base is commit `445dd44b5382160d4e93e4cada018beb4ab0f5b5` plus the committed read-only issue-reconciliation preflight `791aede`. Do not reset, discard or overwrite existing Task 1/2 work.
 - Primary local issue seam is `ISSUE-0040` (atomic data commits and failed-workflow non-corruption). `ISSUE-0038` and `ISSUE-0044` are related later-task seams; do not close them from this task. The local issue ledger and approved specification are authoritative; GitHub Issues are only a synchronised representation.
 - Preserve `execution_allowed = false`, evidence/provider/model boundaries, current revision-protected stores, Task 2 operational-event authority, session tracing, Data Health, audit manifests, schemas and compatibility paths. Do not add execution, provider, model, portfolio, scoring, data-coverage or UI scope.
 - Use the existing `src/etf_cockpit/core/atomic_io.py` grouped write, lock, journal, checksum, backup and restore primitives. Do not create a competing lock, journal or transaction engine. If the existing primitive lacks an observable seam, extend it narrowly and keep legacy callers compatible.
 - Add the required RED tests before production behaviour. Run the exact plan RED command with the absolute existing interpreter `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe` because the ignored `.venv` is not materialised in the worktree. Record a genuine behavioural failure, not an import/syntax error.
 - `WriteTransaction` must follow the approved shape: transaction ID, workflow run ID, type, affected datasets, base generations, staging/final paths, expected checksums, approved status literals, timestamps and recovery instructions. Recovery results must expose deterministic state and evidence without promoting ambiguous staging.
 - Observable invariants: readers see either the previous complete valid state or the new complete valid state; validation/checksums precede activation; lock contention is safe; repeated recovery is idempotent; corrupt/incomplete journals and payloads become explicit recovery-required/read-only/manual-review outcomes; operational events and audit/manifest evidence remain visible.
 - Tests must exercise failure outcomes and invariants, not private call counts. Cover staging, validating, committing and manifest publication interruption, locks/concurrency, checksum/payload/journal corruption, missing files, permission/replace failures, startup recovery, clean restart, migration compatibility and backup/restore checksum validation where applicable.
 - No user-visible surface is added unless current code requires it for recovery status; if no UI changes are made, document UI/browser/package visual gates as `pending_later_task` for `ISSUE-0040`.
 - Update `.ai_worklog/task-3-report.md` with exact RED/GREEN/refactor commands, exit status, failure excerpts, checksums, test totals, fault/recovery matrix, migration compatibility and residual closure gates. Commit implementation and tests only after review-ready self-review; do not close `ISSUE-0040` unless every applicable issue gate passes.
-
diff --git a/.ai_worklog/task-3-report.md b/.ai_worklog/task-3-report.md
index bbd6630..5e7a920 100644
--- a/.ai_worklog/task-3-report.md
+++ b/.ai_worklog/task-3-report.md
@@ -1,71 +1,87 @@
 # Wave 0 Task 3 - Atomic transaction and deterministic recovery
 
-Date opened: 2026-07-11  
-Branch: `wave0/task3-atomic-recovery`  
-Task base: `445dd44b5382160d4e93e4cada018beb4ab0f5b5` (`origin/main`)  
-Owning local issue: `ISSUE-0040` - Error handling and recovery centre.  
+Date opened: 2026-07-11
+Branch: `wave0/task3-atomic-recovery`
+Task base: `445dd44b5382160d4e93e4cada018beb4ab0f5b5` (`origin/main`)
+Owning local issue: `ISSUE-0040` - Error handling and recovery centre.
 Related later-task issue seams: `ISSUE-0038` (storage migration plan) and `ISSUE-0044` (backup/restore UI and release metadata). These remain open unless their own closure gates pass.
 
 ## Closure decision before implementation
 
 Task 3 is an infrastructure increment for the atomic-commit and recovery portion of `ISSUE-0040`; it cannot close that issue by itself because the local issue requires a user-visible Error/Recovery panel, retry workflow, package rebuild and browser failure smoke. Those are later dependency-valid tasks. The issue therefore remains open with an implementation-complete, closure-pending state until those gates have fresh evidence.
 
 ## Task 3 closure checklist
 
 Each row is updated only after fresh evidence exists.
 
 | Gate | State before implementation | Evidence / reason |
 |---|---|---|
-| Transaction records and lifecycle | pending | Task 3 implementation |
-| Staging before activation | pending | Task 3 implementation and tests |
-| All-or-nothing old/new complete visibility | pending | Fault matrix tests |
-| Durable journal/evidence and transaction identity | pending | Task 3 implementation and audit evidence |
-| Checksums and validation before activation | pending | Recovery/integrity tests |
-| Writer locking and concurrent writers | pending | Lock contention tests |
-| Interrupted writes, migrations and activation | pending | Fault injection and startup recovery tests |
-| Stale/orphaned staging classification | pending | Recovery tests |
-| Deterministic idempotent recovery | pending | Repeated recovery tests |
-| Corrupt journal/payload/checksum/missing-file handling | pending | Recovery failure-path tests |
-| Permission/locked-file/write-failure handling | pending | Failure injection tests |
-| Startup recovery and clean-start behaviour | pending | Recovery integration tests |
-| Operational-event emission and audit/manifest visibility | pending | Existing Task 2 contracts plus Task 3 evidence |
+| Transaction records and lifecycle | verified_task_scope | Typed contract and real journal lifecycle tests |
+| Staging before activation | verified_task_scope | Real writer and staged tamper tests |
+| All-or-nothing old/new complete visibility | verified_task_scope | Fault matrix and concurrent real-writer recovery |
+| Durable journal/evidence and transaction identity | verified_task_scope | Strict identity validation and durable artefact manifest |
+| Checksums and validation before activation | verified_task_scope | Post-hook checksum recomputation regression |
+| Writer locking and concurrent writers | verified_task_scope | Canonical locks precede snapshots; real two-writer regression |
+| Interrupted writes, migrations and activation | verified_task_scope | Real interruption and nested migration preflight tests |
+| Stale/orphaned staging classification | verified_task_scope | Recovery classification tests |
+| Deterministic idempotent recovery | verified_task_scope | Repeated recovery test |
+| Corrupt journal/payload/checksum/missing-file handling | verified_task_scope | Schema, state, cardinality, containment and payload tests |
+| Permission/locked-file/write-failure handling | verified_task_scope | Failure injection tests |
+| Startup recovery and clean-start behaviour | verified_task_scope | Startup recovery and clean restart tests |
+| Operational-event emission and audit/manifest visibility | verified_task_scope | Default Task 2 session trace and durable event evidence |
 | Data Health visibility | pending_later_task | No user-facing Data Health change is owned by Task 3 |
-| Backward compatibility / migration behaviour | pending | Migration and compatibility tests |
-| Read-only or unavailable state when recovery is unproven | pending | Recovery classification tests |
+| Backward compatibility / migration behaviour | verified_task_scope | Legacy schema-1 and migration regression tests |
+| Read-only or unavailable state when recovery is unproven | verified_task_scope | Invalid journals remain preserved and read-only |
 | ISSUE-0040 readable errors, panel, retry and Activity Log UI | pending_later_task | Required by issue but not this infrastructure task |
 | ISSUE-0040 package/build/browser gates | pending_later_task | Required by issue but not this infrastructure task |
-| Independent task review | pending | Fresh reviewer required |
-| Closure evaluator | pending | Issue remains closure-pending unless all gates pass |
-| `execution_allowed` remains `false` | pending | Boundary regression |
+| Independent task review | rejected_fix_pending_rereview | Review 1 rejected; all findings received a fix pass; fresh rereview required |
+| Closure evaluator | pending_later_task | Issue and REL-02 remain open until all later UI/package/browser gates pass |
+| `execution_allowed` remains `false` | verified_unchanged | No execution-authority source or configuration changed |
 
 ## RED-GREEN-REFACTOR evidence
 
 To be recorded by the implementer and independently checked by the reviewer:
 
 - RED command and non-syntax failure: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q` exited 1 on 2026-07-11 with 11 behavioural failures and 7 passes. Representative failures: the grouped journal exposed only `prepared`/`committed` rather than the required lifecycle; `WriteTransaction` was absent; recovery returned no classification for interrupted and corrupt journals. Collection completed successfully, so this was not an import or syntax failure.
+- Review-fix RED cycle: the exact model test exited 1 because `base_generation_ids` was absent. The adversarial command covering staged tampering and corrupt journals exited 1: tampering did not raise, and unknown-state, missing-field, cardinality, transaction-identity and outside-root journals all returned `rolled_back` instead of `recovery_required`. The first nested-layout attempt had a test-fixture `NameError`; that fixture error was corrected before its behavioural result was counted. The initial combined concurrency run terminated its Windows test process because the existing POSIX-style `os.kill(pid, 0)` probe is destructive on Windows; the root cause was replaced with a read-only process-handle query, after which the real concurrency test could run normally.
+- Partial-staging RED cycle: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py::test_real_group_interruption_recovers_the_previous_complete_generation -q` exited 1 with the real `staging` interruption classified `recovery_required` because zero entries contradicted pre-populated top-level path/checksum fields. The writer now publishes those fields with each entry; the same command exited 0 with four passes.
 - GREEN plan command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py -q` exited 0 with 29 passed after the lifecycle/fault-injection increment.
-- Refactor regression command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py -q` exited 0 with 38 passed. A subsequent affected-release run including three audit/release regressions exited 0 with 41 passed.
-- Static checks: Ruff on all changed Python files, `python -m compileall -q src\etf_cockpit`, and `git diff --check` each exited 0.
-- Full applicable verification: `python -m pytest tests -q` collected 306 tests and exited 1 with 299 passed and seven failures. These are exactly the seven clean-worktree baseline failures previously recorded by preflight: six `tests/test_simple_scores.py` failures and `tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity`, caused by ignored trade-candidate/catalogue artefacts absent from the isolated worktree. The first full attempt additionally exposed three migration-startup failures caused by scanning pytest artefacts under `logs/pytest_system_tmp`; discovery was narrowed to the supplied root and its immediate dataset directories, and all three affected release/audit regressions then passed.
+- Review-fix GREEN/refactor command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py -q` exited 0 with 54 passed.
+- Static checks: scoped Ruff exited 0 (`All checks passed!`); `python -m compileall -q src\etf_cockpit` exited 0; both `git diff --check HEAD` and `git diff --check 445dd44b5382160d4e93e4cada018beb4ab0f5b5` exited 0.
+- Full applicable verification: `python -m pytest tests -q` collected 322 tests and exited 1 with 315 passed and seven failures. These are exactly the unchanged clean-worktree baseline failures: six `tests/test_simple_scores.py` failures and `tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity`, caused by ignored trade-candidate/catalogue artefacts absent from the isolated worktree. No Task 3 test failed.
 
 ## Implementation and compatibility record
 
 - The existing `.atomic-transactions` directory, `.atomic-write-group.lock`, journal writer, rollback backups, checksum functions and atomic replace functions remain the only transaction engine. No second lock or journal format was introduced.
-- Journal schema 2 adds durable transaction identity, approved dataset/timestamp fields, expected payload checksums, recovery instructions and observable `staging`, `validating`, `committing`, `manifest_publish` and `committed` phases. Legacy schema-1 prepared journals remain recoverable.
-- `WriteTransaction` uses the approved `affected_dataset_ids`, `started_at`, `committed_at` and `ready_to_commit`/rollback/recovery status names. Read-only compatibility properties accept the earlier draft names `affected_datasets` and `created_at`. `begin_write_transaction` and `mark_transaction_ready` keep the plan call shapes by defaulting their optional data root to the project data directory.
+- Journal schema 2 adds durable transaction identity, approved dataset/timestamp fields, expected payload checksums, recovery instructions and observable `staging`, `validating`, `committing`, internal `manifest_publish` and `committed` phases. Legacy schema-1 prepared journals remain recoverable.
+- `WriteTransaction` exposes the exact approved public list fields, `base_generation_ids`, list-valued recovery instructions and approved statuses beginning with `planned`; internal `manifest_publish` projects to public `committing`. Read-only compatibility aliases preserve `affected_datasets`, `created_at` and `base_generations`, and legacy mapping inputs are normalised without changing the public list schema.
 - Recovery is deterministic and conservative: verified incomplete work rolls back to the old complete state; a verified lingering commit retains the new complete state; corrupt, missing, checksum-invalid or permission-blocked evidence stays in place and returns `recovery_required` plus `read_only` startup mode for manual review. Repeated recovery after a successful rollback is an empty no-op.
 - `run_migrations` performs recovery before schema changes and refuses to migrate if recovery cannot be proved. Existing migration and backup/restore compatibility tests pass.
-- Recovery outcomes can be emitted through Task 2's authoritative hash-chained session trace via the optional `event_path`; no parallel operational logger exists. The regression asserts event type, status, transaction ID and event hash.
+- Recovery outcomes use Task 2's authoritative hash-chained session trace by default; migration preflight passes its project-root trace explicitly. No parallel operational logger exists. Regressions assert the default production path, event type, status, transaction ID and event hash.
 - Writer inventory found existing atomic/grouped canonical seams in backup/restore, import/export, FX, manual notes, import pipeline, trust artefacts, universe store, reference data and simple scores. Direct writers in model/feature/report/export paths were not bulk-rewritten because their ownership belongs to later storage/workflow tasks and doing so would exceed Task 3. No mutable writer required a compatibility-breaking edit for this foundation.
 
 ## Evidence and boundary state
 
 - Fault matrix and source checksums: `evidence/wave0/task3/fault-matrix.json`.
-- Backup checksum evidence is exercised by `tests/operations/test_backups.py`, `tests/test_atomic_io.py` and `tests/test_backup_restore.py`; tampering blocks restore.
+- Durable synthetic evidence inventory: `evidence/wave0/task3/artefacts/artefact-manifest.json`. It records the concrete backup manifest (`f04e498f217da4546620c003cd7b311d4ed9597b1bf045260e022640b3492631`), verified restore result, preserved interrupted journal, recovery result (`70711c6110c72ae5e6fda384a28d0bad1b7c2fa2aee7d8a199ca5ee73e6fe6b9`) and authoritative event artefact (`5810a49942e0beaa7186adf4855a271a27e43a4ef505168fc15fa5b43b86d017`). The drill contains synthetic text only, with no secrets or generated market data.
 - No UI was changed. Recovery screenshots, Error/Recovery panel, package rebuild and browser smoke remain `pending_later_task` for `ISSUE-0040`; the issue and `REL-02` remain open.
 - No issue files were moved or closed, no remote state was changed, and Task 4 was not started. The implementation adds no execution path and does not change the documented `execution_allowed=false` boundary.
 - Independent task review and closure evaluation remain pending.
 
+## Independent review 1 disposition
+
+- C1 fixed: canonical locks are acquired before old-generation reads/backups and held through activation and manifest publication. A real two-writer interruption proves recovery preserves writer 1's commit.
+- C2 and I5 fixed: complete schema-2 validation covers required fields, approved states, identity, cardinality, contradictory maps, checksums and strict containment before mutation. Invalid journals remain auditable, read-only and untouched; legacy schema-1 paths also cannot escape the supplied root.
+- I1 fixed: validators and staged SHA-256 checks run again after the commit hook and lock acquisition, immediately before activation.
+- I2 fixed: recovery discovers direct and canonical nested transaction roots, including `data/clean`, while excluding `logs` and `pytest_*` artefacts. Migration preflight uses a real nested writer regression.
+- I3 fixed: the public model now uses `base_generation_ids: dict[str, str]`, list-valued staging/final paths and recovery instructions, and exact approved status literals including `planned`; compatibility aliases remain read-only.
+- I4 fixed: default recovery emission and migration preflight both use the authoritative Task 2 session trace and produce hash-chained events.
+- I6 fixed: concrete backup, restore, interrupted-journal, recovery-result and event artefacts plus checksums are durable under `evidence/wave0/task3/artefacts`.
+- M1 fixed: both current-diff and full review-range whitespace checks exit 0.
+- M2 fixed: completed infrastructure gates are `verified_task_scope`; later UI/package/browser gates remain `pending_later_task`, review remains `rejected_fix_pending_rereview`, and `ISSUE-0040`/`REL-02` remain open.
+
+Fix implementation commit: `4d02c8076cbdbc1da296d9b39962104a8a2a224f` (`fix: harden atomic transaction recovery`).
+
 ## Remote issue reconciliation preflight
 
 `issues/github_issue_map.json` is a read-only inventory manifest at this boundary. The local ledger parser found 98 canonical stable IDs (77 open, 21 closed), no remote GitHub Issues, and five documented historical/placement contradictions. No remote issue mutation has been performed. The local ledger and approved specification remain authoritative.
diff --git a/evidence/wave0/task3/artefacts/artefact-manifest.json b/evidence/wave0/task3/artefacts/artefact-manifest.json
new file mode 100644
index 0000000..8cdfe93
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/artefact-manifest.json
@@ -0,0 +1,46 @@
+{
+  "schema_version": 1,
+  "purpose": "Synthetic Task 3 backup and recovery evidence; no market data or secrets.",
+  "artefacts": [
+    {
+      "path": "backup-drill/backups/20260711T081411.470664Z/9eb3d7d8a764_canonical-sample.txt",
+      "sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+      "bytes": 37
+    },
+    {
+      "path": "backup-drill/backups/20260711T081411.470664Z/manifest.json",
+      "sha256": "f04e498f217da4546620c003cd7b311d4ed9597b1bf045260e022640b3492631",
+      "bytes": 616
+    },
+    {
+      "path": "backup-drill/canonical-sample.txt",
+      "sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+      "bytes": 37
+    },
+    {
+      "path": "backup-drill/restore-result.json",
+      "sha256": "1e03b7d066b4758fac3137785122fb597c303d5132a32534ca0515f04294f19c",
+      "bytes": 663
+    },
+    {
+      "path": "recovery-drill/data/clean/canonical-sample.txt",
+      "sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+      "bytes": 37
+    },
+    {
+      "path": "recovery-drill/interrupted-journal.json",
+      "sha256": "a2dbe15a4c87e6de70adb986b29e738cba0ee5b8bdce02128e04359b36abd634",
+      "bytes": 2491
+    },
+    {
+      "path": "recovery-drill/recovery-result.json",
+      "sha256": "70711c6110c72ae5e6fda384a28d0bad1b7c2fa2aee7d8a199ca5ee73e6fe6b9",
+      "bytes": 747
+    },
+    {
+      "path": "recovery-drill/session.jsonl",
+      "sha256": "5810a49942e0beaa7186adf4855a271a27e43a4ef505168fc15fa5b43b86d017",
+      "bytes": 662
+    }
+  ]
+}
diff --git a/evidence/wave0/task3/artefacts/backup-drill/backups/20260711T081411.470664Z/9eb3d7d8a764_canonical-sample.txt b/evidence/wave0/task3/artefacts/backup-drill/backups/20260711T081411.470664Z/9eb3d7d8a764_canonical-sample.txt
new file mode 100644
index 0000000..91355e4
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/backup-drill/backups/20260711T081411.470664Z/9eb3d7d8a764_canonical-sample.txt
@@ -0,0 +1 @@
+synthetic canonical generation: old
diff --git a/evidence/wave0/task3/artefacts/backup-drill/backups/20260711T081411.470664Z/manifest.json b/evidence/wave0/task3/artefacts/backup-drill/backups/20260711T081411.470664Z/manifest.json
new file mode 100644
index 0000000..2e48bab
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/backup-drill/backups/20260711T081411.470664Z/manifest.json
@@ -0,0 +1,12 @@
+{
+  "schema_version": 1,
+  "created_at": "2026-07-11T08:14:11.470664+00:00",
+  "entries": [
+    {
+      "source_path": "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\backup-drill\\canonical-sample.txt",
+      "backup_path": "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\backup-drill\\backups\\20260711T081411.470664Z\\9eb3d7d8a764_canonical-sample.txt",
+      "sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+      "bytes_copied": 37
+    }
+  ]
+}
diff --git a/evidence/wave0/task3/artefacts/backup-drill/canonical-sample.txt b/evidence/wave0/task3/artefacts/backup-drill/canonical-sample.txt
new file mode 100644
index 0000000..91355e4
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/backup-drill/canonical-sample.txt
@@ -0,0 +1 @@
+synthetic canonical generation: old
diff --git a/evidence/wave0/task3/artefacts/backup-drill/restore-result.json b/evidence/wave0/task3/artefacts/backup-drill/restore-result.json
new file mode 100644
index 0000000..2bc6c8c
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/backup-drill/restore-result.json
@@ -0,0 +1,11 @@
+{
+  "schema_version": 1,
+  "source_path": "backup-drill/canonical-sample.txt",
+  "backup_manifest_path": "backup-drill/backups/20260711T081411.470664Z/manifest.json",
+  "backup_manifest_sha256": "f04e498f217da4546620c003cd7b311d4ed9597b1bf045260e022640b3492631",
+  "backup_payload_path": "backup-drill/backups/20260711T081411.470664Z/9eb3d7d8a764_canonical-sample.txt",
+  "backup_payload_sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+  "restored_source_sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+  "manifest_verified": true,
+  "restored_bytes": "synthetic canonical generation: old\n"
+}
diff --git a/evidence/wave0/task3/artefacts/recovery-drill/data/clean/canonical-sample.txt b/evidence/wave0/task3/artefacts/recovery-drill/data/clean/canonical-sample.txt
new file mode 100644
index 0000000..91355e4
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/recovery-drill/data/clean/canonical-sample.txt
@@ -0,0 +1 @@
+synthetic canonical generation: old
diff --git a/evidence/wave0/task3/artefacts/recovery-drill/interrupted-journal.json b/evidence/wave0/task3/artefacts/recovery-drill/interrupted-journal.json
new file mode 100644
index 0000000..819c4c1
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/recovery-drill/interrupted-journal.json
@@ -0,0 +1,39 @@
+{
+  "schema_version": 2,
+  "transaction_id": "890374783f6946ed970e825ebfbe4594",
+  "workflow_run_id": "",
+  "transaction_type": "atomic_write_group",
+  "owner_pid": 29704,
+  "state": "manifest_publish",
+  "affected_dataset_ids": [
+    "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\canonical-sample.txt"
+  ],
+  "base_generation_ids": {},
+  "entries": [
+    {
+      "destination": "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\canonical-sample.txt",
+      "backup_path": "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\.atomic-transactions\\890374783f6946ed970e825ebfbe4594\\backup-0.bin",
+      "previous_sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+      "staged_path": "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\.canonical-sample.txt._afej4l7.group.tmp",
+      "expected_sha256": "1182704556f8ada3316240ec0786c2657e8f6763b409157b41e29f5e4640a862"
+    }
+  ],
+  "staged_paths": [
+    "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\.canonical-sample.txt._afej4l7.group.tmp"
+  ],
+  "final_paths": [
+    "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\canonical-sample.txt"
+  ],
+  "lock_paths": [
+    "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\.atomic-write-group.lock"
+  ],
+  "expected_checksums": {
+    "C:\\Users\\thor2\\Desktop\\Trading App\\.worktrees\\wave0-task3-atomic-recovery\\evidence\\wave0\\task3\\artefacts\\recovery-drill\\data\\clean\\canonical-sample.txt": "1182704556f8ada3316240ec0786c2657e8f6763b409157b41e29f5e4640a862"
+  },
+  "started_at": "2026-07-11T08:14:11.508961+00:00",
+  "updated_at": "2026-07-11T08:14:11.555549+00:00",
+  "committed_at": null,
+  "recovery_instructions": [
+    "On interrupted startup, verify journal and payload checksums, then restore the previous complete generation. Never promote ambiguous staging data."
+  ]
+}
diff --git a/evidence/wave0/task3/artefacts/recovery-drill/recovery-result.json b/evidence/wave0/task3/artefacts/recovery-drill/recovery-result.json
new file mode 100644
index 0000000..c79d277
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/recovery-drill/recovery-result.json
@@ -0,0 +1,14 @@
+{
+  "schema_version": 1,
+  "transaction_id": "890374783f6946ed970e825ebfbe4594",
+  "state": "rolled_back",
+  "startup_mode": "normal",
+  "reason": "previous complete generation restored",
+  "journal_snapshot_path": "recovery-drill/interrupted-journal.json",
+  "journal_snapshot_sha256": "a2dbe15a4c87e6de70adb986b29e738cba0ee5b8bdce02128e04359b36abd634",
+  "event_path": "recovery-drill/session.jsonl",
+  "event_sha256": "5810a49942e0beaa7186adf4855a271a27e43a4ef505168fc15fa5b43b86d017",
+  "restored_destination_path": "recovery-drill/data/clean/canonical-sample.txt",
+  "restored_destination_sha256": "4cc3b522f5488c1e82a06ba9988ea02c1dbc2b6acc064331c7ffe6ae06ae91aa",
+  "restored_bytes": "synthetic canonical generation: old\n"
+}
diff --git a/evidence/wave0/task3/artefacts/recovery-drill/session.jsonl b/evidence/wave0/task3/artefacts/recovery-drill/session.jsonl
new file mode 100644
index 0000000..0432d10
--- /dev/null
+++ b/evidence/wave0/task3/artefacts/recovery-drill/session.jsonl
@@ -0,0 +1 @@
+{"action_id": "890374783f6946ed970e825ebfbe4594", "component": "operations.recovery", "event_hash": "556253e4cf558ab442e814c2a9c4572452152f450b5d1df8978402deb494a086", "event_id": "eb007081ea0a465fa0aa43e03cda5718", "event_type": "write_transaction_recovery", "evidence_checksums": {"journal_sha256": "a2dbe15a4c87e6de70adb986b29e738cba0ee5b8bdce02128e04359b36abd634"}, "prior_event_hash": null, "reason": "previous complete generation restored", "sequence_number": 1, "session_id": "startup-recovery", "startup_mode": "normal", "status": "rolled_back", "timestamp_utc": "2026-07-11T08:14:11.577121+00:00", "transaction_id": "890374783f6946ed970e825ebfbe4594"}
diff --git a/evidence/wave0/task3/fault-matrix.json b/evidence/wave0/task3/fault-matrix.json
index 965fb5a..3b584f7 100644
--- a/evidence/wave0/task3/fault-matrix.json
+++ b/evidence/wave0/task3/fault-matrix.json
@@ -1,26 +1,41 @@
 {
   "schema_version": 1,
   "task": "wave0-task3-atomic-recovery",
-  "captured_at": "2026-07-11",
+  "captured_at": "2026-07-11T08:14:11Z",
   "fault_matrix": [
     {"fault": "staging interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
     {"fault": "validation interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
     {"fault": "commit interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
     {"fault": "manifest publication interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
     {"fault": "corrupt journal", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
     {"fault": "staged checksum mismatch", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
     {"fault": "missing staged payload", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
     {"fault": "missing rollback backup", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
     {"fault": "locked destination during rollback", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
     {"fault": "lingering verified committed journal", "result": "committed", "startup_mode": "normal", "visible_generation": "new complete"},
     {"fault": "legacy schema-1 prepared journal", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
+    {"fault": "second concurrent writer interrupted after first writer commits", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "first writer complete"},
+    {"fault": "post-hook staged payload tampering", "result": "write rejected", "startup_mode": "normal", "visible_generation": "old complete"},
+    {"fault": "forged destination outside recovery root", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "outside path untouched"},
+    {"fault": "unknown or structurally invalid schema-2 journal", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "journal preserved for manual review"},
+    {"fault": "real nested data/clean transaction before migration", "result": "rolled_back before migration", "startup_mode": "normal", "visible_generation": "old complete"},
     {"fault": "clean restart", "result": "no recovery records", "startup_mode": "normal", "visible_generation": "unchanged"}
   ],
   "source_sha256": {
-    "src/etf_cockpit/core/atomic_io.py": "48a159c9cfbc1f53a67e89ec8f41a5eb5cc34c4c68bd2ad6bafb5f2258673bf0",
-    "src/etf_cockpit/core/migrations.py": "07b727bcca93cbb1bd854a7af7e1eaa1bd54982c203a3e5f09832f670fb51357",
-    "src/etf_cockpit/operations/models.py": "f16fb8acbdfbcf0968f46b625cc9f74b3a86ad94509407a698d1d2b964f3d6f9",
-    "src/etf_cockpit/operations/recovery.py": "0aacc2503be8f1875a41db56bbb7abde31bb57f7d9d9a854ff8eac2fad53a865"
+    "src/etf_cockpit/core/atomic_io.py": "c5ad5ab577719de680df0902eb227709a8170bdacfc65d9e9737d73d85154434",
+    "src/etf_cockpit/core/migrations.py": "653c09426d6535b8fabaeb6de03c31fe4e3343369e5d442f9d9e19de9f22496b",
+    "src/etf_cockpit/operations/models.py": "4c3c01bd15993132c614dffaa49e22189493d5148a791c5aad1dd135d8163392",
+    "src/etf_cockpit/operations/recovery.py": "f5cdc8711afa1e4f16571e670a5e6d187b2c145754a517631851459a94e37585"
+  },
+  "durable_artefact_manifest": {
+    "path": "evidence/wave0/task3/artefacts/artefact-manifest.json",
+    "sha256": "b45d6f25f97084f3262fe723b4d2667df7d1cd0a0b9aa107c23a7286dec71c92",
+    "backup_manifest_path": "evidence/wave0/task3/artefacts/backup-drill/backups/20260711T081411.470664Z/manifest.json",
+    "backup_manifest_sha256": "f04e498f217da4546620c003cd7b311d4ed9597b1bf045260e022640b3492631",
+    "recovery_result_path": "evidence/wave0/task3/artefacts/recovery-drill/recovery-result.json",
+    "recovery_result_sha256": "70711c6110c72ae5e6fda384a28d0bad1b7c2fa2aee7d8a199ca5ee73e6fe6b9",
+    "authoritative_event_path": "evidence/wave0/task3/artefacts/recovery-drill/session.jsonl",
+    "authoritative_event_sha256": "5810a49942e0beaa7186adf4855a271a27e43a4ef505168fc15fa5b43b86d017"
   },
   "visual_evidence": "pending_later_task: Task 3 adds no user-visible surface; ISSUE-0040 UI/browser/package gates remain open"
 }
diff --git a/src/etf_cockpit/core/atomic_io.py b/src/etf_cockpit/core/atomic_io.py
index f502262..98fd05d 100644
--- a/src/etf_cockpit/core/atomic_io.py
+++ b/src/etf_cockpit/core/atomic_io.py
@@ -106,24 +106,33 @@ def _stage_request(request: AtomicWriteRequest, *, validate: bool = True) -> Pat
     if validate:
         try:
             request.validator(path)
         except Exception:
             path.unlink(missing_ok=True)
             raise
     return path
 
 
 def _pid_alive(pid: int) -> bool:
     if pid <= 0:
         return False
+    if os.name == "nt":
+        import ctypes
+
+        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
+        handle = kernel32.OpenProcess(0x1000, False, pid)
+        if handle:
+            kernel32.CloseHandle(handle)
+            return True
+        return ctypes.get_last_error() == 5
     try:
         os.kill(pid, 0)
         return True
     except OSError:
         return False
 
 
 def _retry_unlink(path: Path) -> None:
     for attempt in range(3):
         try:
             path.unlink(missing_ok=True)
             return
@@ -252,85 +261,99 @@ def atomic_write_group(
     previous: dict[Path, bytes | None] = {}
     entries: list[dict[str, object]] = []
     locks: tuple[Path, ...] = ()
     now = datetime.now(timezone.utc).isoformat()
     journal_payload: dict[str, object] = {
         "schema_version": 2,
         "transaction_id": transaction_root.name,
         "workflow_run_id": "",
         "transaction_type": "atomic_write_group",
         "owner_pid": os.getpid(),
         "state": "staging",
         "affected_dataset_ids": [str(path) for path in destinations],
-        "base_generations": {},
+        "base_generation_ids": {},
         "entries": entries,
         "staged_paths": [],
+        "final_paths": [],
         "lock_paths": [],
-        "expected_checksums": {
-            str(request.destination.resolve()): hashlib.sha256(request.payload).hexdigest()
-            for request in request_tuple
-        },
+        "expected_checksums": {},
         "started_at": now,
         "updated_at": now,
         "committed_at": None,
-        "recovery_instructions": (
+        "recovery_instructions": [
             "On interrupted startup, verify journal and payload checksums, then restore the "
             "previous complete generation. Never promote ambiguous staging data."
-        ),
+        ],
     }
     interrupted = False
 
     def publish_state(state: str) -> None:
         journal_payload["state"] = state
         journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
         if state == "committed":
             journal_payload["committed_at"] = journal_payload["updated_at"]
         _write_journal(journal_path, journal_payload)
         if lifecycle_hook is not None:
             lifecycle_hook(state, journal_path)
 
     try:
         _write_journal(journal_path, journal_payload)
         if lifecycle_hook is not None:
             lifecycle_hook("staging", journal_path)
+        locks = _acquire_group_locks(parents, journal_path)
+        journal_payload["lock_paths"] = [str(path.resolve()) for path in locks]
+        _write_journal(journal_path, journal_payload)
         for index, request in enumerate(request_tuple):
             original = request.destination.read_bytes() if request.destination.is_file() else None
             previous[request.destination] = original
             backup_path: Path | None = None
             if original is not None:
                 backup_path = transaction_root / f"backup-{index}.bin"
                 with backup_path.open("wb") as handle:
                     handle.write(original)
                     handle.flush()
                     os.fsync(handle.fileno())
             staged[request.destination] = _stage_request(request, validate=False)
             entries.append(
                 {
                     "destination": str(request.destination.resolve()),
                     "backup_path": str(backup_path.resolve()) if backup_path else None,
                     "previous_sha256": hashlib.sha256(original).hexdigest() if original is not None else None,
                     "staged_path": str(staged[request.destination].resolve()),
                     "expected_sha256": hashlib.sha256(request.payload).hexdigest(),
                 }
             )
             journal_payload["staged_paths"] = [str(path.resolve()) for path in staged.values()]
+            journal_payload["final_paths"] = [str(entry["destination"]) for entry in entries]
+            expected_checksums = journal_payload["expected_checksums"]
+            assert isinstance(expected_checksums, dict)
+            expected_checksums[str(request.destination.resolve())] = hashlib.sha256(
+                request.payload
+            ).hexdigest()
             journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
             _write_journal(journal_path, journal_payload)
         publish_state("validating")
         for request in request_tuple:
             request.validator(staged[request.destination])
-        lock_paths = [str((parent / ".atomic-write-group.lock").resolve()) for parent in parents]
-        journal_payload["lock_paths"] = lock_paths
         publish_state("committing")
-        locks = _acquire_group_locks(parents, journal_path)
+        for request in request_tuple:
+            staged_path = staged[request.destination]
+            request.validator(staged_path)
+            expected = str(journal_payload["expected_checksums"][str(request.destination.resolve())])
+            actual = sha256_file(staged_path)
+            if actual != expected:
+                raise OSError(
+                    f"staged payload checksum mismatch: {staged_path} "
+                    f"(expected {expected}, found {actual})"
+                )
         for request in request_tuple:
             staged[request.destination].replace(request.destination)
         publish_state("manifest_publish")
         publish_state("committed")
         return tuple(
             AtomicWriteResult(
                 destination=request.destination,
                 sha256=hashlib.sha256(request.payload).hexdigest(),
                 bytes_written=len(request.payload),
                 replaced_existing=previous[request.destination] is not None,
             )
             for request in request_tuple
diff --git a/src/etf_cockpit/core/migrations.py b/src/etf_cockpit/core/migrations.py
index 7d537d3..e72bdff 100644
--- a/src/etf_cockpit/core/migrations.py
+++ b/src/etf_cockpit/core/migrations.py
@@ -83,25 +83,28 @@ MIGRATIONS = (
 def _load_state(path: Path) -> dict[str, object]:
     if not path.is_file():
         return {"schema_version": 0, "applied": []}
     payload = json.loads(path.read_text(encoding="utf-8"))
     if not isinstance(payload.get("applied"), list):
         raise ValueError("migration state applied field must be a list")
     return payload
 
 
 def run_migrations(context: MigrationContext) -> MigrationReport:
     from etf_cockpit.operations.recovery import recover_incomplete_transactions
 
-    recovery_results = recover_incomplete_transactions(context.root)
+    recovery_results = recover_incomplete_transactions(
+        context.root,
+        event_path=context.root / "logs" / "session.jsonl",
+    )
     blocked = [result for result in recovery_results if result.state == "recovery_required"]
     if blocked:
         reasons = "; ".join(result.reason for result in blocked)
         raise OSError(f"migration blocked by incomplete atomic transaction: {reasons}")
     state = _load_state(context.state_path)
     current_version = int(state.get("schema_version", 0))
     pending = tuple(migration for migration in MIGRATIONS if migration.version > current_version)
     if not pending:
         return MigrationReport((), current_version, None, context.state_path)
 
     migration_paths = tuple(context.metadata_root / f"{migration.name}.json" for migration in pending)
     protected_paths = tuple(dict.fromkeys((*context.managed_paths, context.state_path, *migration_paths)))
diff --git a/src/etf_cockpit/operations/models.py b/src/etf_cockpit/operations/models.py
index bd35ac4..9a5a658 100644
--- a/src/etf_cockpit/operations/models.py
+++ b/src/etf_cockpit/operations/models.py
@@ -1,18 +1,18 @@
 from __future__ import annotations
 
 from datetime import datetime
 from typing import Literal, Self
 
-from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
+from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
 
 
 class OperationalEvent(BaseModel):
     """Typed projection of one row in the authoritative session trace."""
 
     model_config = ConfigDict(extra="allow")
 
     event_id: str = ""
     session_id: str
     sequence_number: int
     timestamp_utc: datetime
     event_type: str
@@ -53,55 +53,77 @@ class ClosureEvidenceRecord(BaseModel):
             if not self.builder:
                 raise ValueError("builder must be non-empty for approved closure evidence")
             if not self.independent_reviewer:
                 raise ValueError(
                     "independent_reviewer must be non-empty for approved closure evidence"
                 )
             if self.builder == self.independent_reviewer:
                 raise ValueError("independent_reviewer must differ from builder")
         return self
 
 
 WriteTransactionStatus = Literal[
-    "started",
+    "planned",
     "staging",
     "validating",
     "ready_to_commit",
     "committing",
     "committed",
     "rolling_back",
     "rolled_back",
     "recovery_required",
     "quarantined",
 ]
 
 
 class WriteTransaction(BaseModel):
     """Durable projection of the existing atomic grouped-write journal."""
 
     transaction_id: str
     workflow_run_id: str
     transaction_type: str
     model_config = ConfigDict(populate_by_name=True)
 
     affected_dataset_ids: list[str] = Field(
         validation_alias=AliasChoices("affected_dataset_ids", "affected_datasets")
     )
-    base_generations: dict[str, str]
-    staging_paths: dict[str, str]
-    final_paths: dict[str, str]
+    base_generation_ids: dict[str, str] = Field(
+        validation_alias=AliasChoices("base_generation_ids", "base_generations")
+    )
+    staging_paths: list[str]
+    final_paths: list[str]
     expected_checksums: dict[str, str]
     status: WriteTransactionStatus
     started_at: datetime = Field(validation_alias=AliasChoices("started_at", "created_at"))
     updated_at: datetime
     committed_at: datetime | None = None
-    recovery_instructions: str
+    recovery_instructions: list[str]
+
+    @field_validator("staging_paths", "final_paths", mode="before")
+    @classmethod
+    def accept_legacy_path_maps(cls, value: object) -> object:
+        """Accept the pre-approval mapping shape while exposing only list fields."""
+        if isinstance(value, dict):
+            return list(value.values())
+        return value
+
+    @field_validator("recovery_instructions", mode="before")
+    @classmethod
+    def accept_legacy_recovery_instruction(cls, value: object) -> object:
+        if isinstance(value, str):
+            return [value]
+        return value
 
     @property
     def affected_datasets(self) -> list[str]:
         """Compatibility alias for the pre-approval Task 3 draft name."""
         return self.affected_dataset_ids
 
     @property
     def created_at(self) -> datetime:
         """Compatibility alias for the pre-approval Task 3 draft name."""
         return self.started_at
+
+    @property
+    def base_generations(self) -> dict[str, str]:
+        """Compatibility alias for the pre-approval Task 3 draft name."""
+        return self.base_generation_ids
diff --git a/src/etf_cockpit/operations/recovery.py b/src/etf_cockpit/operations/recovery.py
index 2926115..bb7c3c3 100644
--- a/src/etf_cockpit/operations/recovery.py
+++ b/src/etf_cockpit/operations/recovery.py
@@ -2,25 +2,25 @@ from __future__ import annotations
 
 from dataclasses import dataclass
 from datetime import datetime, timezone
 import hashlib
 import json
 from pathlib import Path
 import uuid
 
 from pydantic import ValidationError
 
 from etf_cockpit.core import atomic_io
 from etf_cockpit.core.paths import ROOT
-from etf_cockpit.core.session_log import append_event
+from etf_cockpit.core.session_log import SESSION_LOG_PATH, append_event
 from etf_cockpit.operations.models import WriteTransaction
 
 
 @dataclass(frozen=True)
 class RecoveryResult:
     transaction_id: str
     state: str
     startup_mode: str
     reason: str
     journal_path: Path
     evidence_checksums: dict[str, str]
 
@@ -32,132 +32,381 @@ def _transaction_root(data_root: Path, transaction_id: str) -> Path:
 def _journal_path(data_root: Path, transaction_id: str) -> Path:
     return _transaction_root(data_root, transaction_id) / "journal.json"
 
 
 def _resolved_data_root(data_root: Path | None) -> Path:
     return data_root if data_root is not None else ROOT / "data"
 
 
 def _now() -> datetime:
     return datetime.now(timezone.utc)
 
 
+def _path_list(value: object) -> list[str]:
+    if isinstance(value, dict):
+        return [str(item) for item in value.values()]
+    if isinstance(value, list):
+        return [str(item) for item in value]
+    return []
+
+
 def _record_from_payload(payload: dict[str, object]) -> WriteTransaction:
+    journal_state = str(payload.get("state", "recovery_required"))
     return WriteTransaction(
         transaction_id=str(payload["transaction_id"]),
         workflow_run_id=str(payload.get("workflow_run_id", "")),
         transaction_type=str(payload.get("transaction_type", "atomic_write_group")),
         affected_dataset_ids=[str(item) for item in payload.get("affected_dataset_ids", payload.get("affected_datasets", []))],
-        base_generations={str(key): str(value) for key, value in dict(payload.get("base_generations", {})).items()},
-        staging_paths={str(key): str(value) for key, value in dict(payload.get("staging_paths_by_dataset", {})).items()},
-        final_paths={str(key): str(value) for key, value in dict(payload.get("final_paths", {})).items()},
+        base_generation_ids={
+            str(key): str(value)
+            for key, value in dict(
+                payload.get("base_generation_ids", payload.get("base_generations", {}))
+            ).items()
+        },
+        staging_paths=_path_list(
+            payload.get("staged_paths", payload.get("staging_paths_by_dataset", []))
+        ),
+        final_paths=_path_list(payload.get("final_paths", [])),
         expected_checksums={str(key): str(value) for key, value in dict(payload.get("expected_checksums", {})).items()},
-        status=str(payload.get("state", "recovery_required")),
+        status="committing" if journal_state == "manifest_publish" else journal_state,
         started_at=payload.get("started_at", payload.get("created_at", _now())),
         updated_at=payload.get("updated_at", _now()),
         committed_at=payload.get("committed_at"),
-        recovery_instructions=str(payload.get("recovery_instructions", "Manual review required.")),
+        recovery_instructions=payload.get(
+            "recovery_instructions", ["Manual review required."]
+        ),
     )
 
 
 def begin_write_transaction(
     *,
     transaction_type: str,
     base_generations: dict[str, str],
     data_root: Path | None = None,
     workflow_run_id: str = "",
     affected_datasets: list[str] | None = None,
-    staging_paths: dict[str, str] | None = None,
-    final_paths: dict[str, str] | None = None,
+    staging_paths: list[str] | None = None,
+    final_paths: list[str] | None = None,
 ) -> WriteTransaction:
     transaction_id = uuid.uuid4().hex
     now = _now()
     record = WriteTransaction(
         transaction_id=transaction_id,
         workflow_run_id=workflow_run_id,
         transaction_type=transaction_type,
         affected_dataset_ids=list(affected_datasets or base_generations),
-        base_generations=base_generations,
-        staging_paths=staging_paths or {},
-        final_paths=final_paths or {},
+        base_generation_ids=base_generations,
+        staging_paths=_path_list(staging_paths or []),
+        final_paths=_path_list(final_paths or []),
         expected_checksums={},
-        status="started",
+        status="planned",
         started_at=now,
         updated_at=now,
-        recovery_instructions=(
+        recovery_instructions=[
             "Verify all expected checksums before activation; on ambiguity remain read-only "
             "and request manual recovery."
-        ),
+        ],
     )
     path = _journal_path(_resolved_data_root(data_root), transaction_id)
     path.parent.mkdir(parents=True, exist_ok=False)
     payload = record.model_dump(mode="json")
     payload.update(
         schema_version=2,
         state=record.status,
         owner_pid=__import__("os").getpid(),
         entries=[],
-        staged_paths=list(record.staging_paths.values()),
-        staging_paths_by_dataset=record.staging_paths,
+        staged_paths=record.staging_paths,
         lock_paths=[],
     )
     atomic_io._write_journal(path, payload)
     return record
 
 
 def mark_transaction_ready(
     transaction_id: str,
     checksums: dict[str, str],
     *,
     data_root: Path | None = None,
 ) -> WriteTransaction:
     path = _journal_path(_resolved_data_root(data_root), transaction_id)
     payload = json.loads(path.read_text(encoding="utf-8"))
     payload["state"] = "ready_to_commit"
     payload["status"] = "ready_to_commit"
     payload["expected_checksums"] = dict(checksums)
     payload["updated_at"] = _now().isoformat()
     atomic_io._write_journal(path, payload)
     return _record_from_payload(payload)
 
 
 def _required_result(journal: Path, transaction_id: str, reason: str) -> RecoveryResult:
-    return RecoveryResult(transaction_id, "recovery_required", "read_only", reason, journal, {})
+    checksums = {"journal_sha256": atomic_io.sha256_file(journal)} if journal.is_file() else {}
+    return RecoveryResult(
+        transaction_id,
+        "recovery_required",
+        "read_only",
+        reason,
+        journal,
+        checksums,
+    )
+
+
+_V2_STATES = {
+    "planned",
+    "staging",
+    "validating",
+    "ready_to_commit",
+    "committing",
+    "manifest_publish",
+    "committed",
+    "rolling_back",
+    "rolled_back",
+    "recovery_required",
+    "quarantined",
+}
+_V2_REQUIRED_FIELDS = {
+    "schema_version",
+    "transaction_id",
+    "workflow_run_id",
+    "transaction_type",
+    "owner_pid",
+    "state",
+    "affected_dataset_ids",
+    "base_generation_ids",
+    "entries",
+    "staged_paths",
+    "final_paths",
+    "lock_paths",
+    "expected_checksums",
+    "started_at",
+    "updated_at",
+    "committed_at",
+    "recovery_instructions",
+}
+
 
+def _is_contained(path: Path, root: Path) -> bool:
+    try:
+        path.resolve().relative_to(root.resolve())
+    except ValueError:
+        return False
+    return True
 
-def _validate_v2_payload(payload: dict[str, object]) -> str | None:
-    state = str(payload.get("state", ""))
-    for entry_value in payload.get("entries", []):
-        entry = dict(entry_value)
+
+def _validated_path(value: object, root: Path, label: str) -> tuple[Path | None, str | None]:
+    if not isinstance(value, str) or not value:
+        return None, f"{label} must be a non-empty path string"
+    path = Path(value)
+    if not path.is_absolute():
+        return None, f"{label} must be absolute"
+    path = path.resolve()
+    if not _is_contained(path, root):
+        return None, f"{label} is outside recovery root: {path}"
+    return path, None
+
+
+def _valid_checksum(value: object) -> bool:
+    return (
+        isinstance(value, str)
+        and len(value) == 64
+        and all(character in "0123456789abcdef" for character in value)
+    )
+
+
+def _validate_v2_payload(
+    payload: dict[str, object],
+    journal: Path,
+    recovery_root: Path,
+) -> str | None:
+    missing = sorted(_V2_REQUIRED_FIELDS - payload.keys())
+    if missing:
+        return f"required journal fields missing: {', '.join(missing)}"
+    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 2:
+        return "schema_version must equal 2"
+    if journal.name != "journal.json" or journal.parent.parent.name != ".atomic-transactions":
+        return "transaction journal path has invalid identity"
+    if not _is_contained(journal, recovery_root):
+        return f"journal is outside recovery root: {journal}"
+    transaction_id = payload.get("transaction_id")
+    if not isinstance(transaction_id, str) or transaction_id != journal.parent.name:
+        return "transaction identity does not match transaction directory"
+    state = payload.get("state")
+    if state not in _V2_STATES:
+        return f"state is not approved: {state!r}"
+    if not isinstance(payload.get("workflow_run_id"), str):
+        return "workflow_run_id must be a string"
+    if not isinstance(payload.get("transaction_type"), str) or not payload["transaction_type"]:
+        return "transaction_type must be a non-empty string"
+    if type(payload.get("owner_pid")) is not int:
+        return "owner_pid must be an integer"
+    for field in ("affected_dataset_ids", "staged_paths", "final_paths", "lock_paths"):
+        value = payload.get(field)
+        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
+            return f"{field} must be a list of strings"
+    if not isinstance(payload.get("recovery_instructions"), list) or not payload[
+        "recovery_instructions"
+    ] or not all(
+        isinstance(item, str) and item for item in payload["recovery_instructions"]
+    ):
+        return "recovery_instructions must be a list of non-empty strings"
+    for field in ("base_generation_ids", "expected_checksums"):
+        value = payload.get(field)
+        if not isinstance(value, dict) or not all(
+            isinstance(key, str)
+            and bool(key)
+            and isinstance(item, str)
+            and bool(item)
+            for key, item in value.items()
+        ):
+            return f"{field} must be a string map"
+    entries_value = payload.get("entries")
+    if not isinstance(entries_value, list) or not all(isinstance(item, dict) for item in entries_value):
+        return "entries must be a list of objects"
+    entries = [dict(item) for item in entries_value]
+    staged_paths = list(payload["staged_paths"])
+    final_paths = list(payload["final_paths"])
+    checksums = dict(payload["expected_checksums"])
+    if entries and not (
+        len(entries) == len(staged_paths) == len(final_paths) == len(checksums)
+    ):
+        return "entry/top-level path and checksum cardinality mismatch"
+    if not entries and (staged_paths or checksums):
+        return "entry/top-level path and checksum cardinality mismatch"
+    if len(set(staged_paths)) != len(staged_paths) or len(set(final_paths)) != len(final_paths):
+        return "staged_paths and final_paths must not contain duplicates"
+    if "status" in payload and payload["status"] != state:
+        return "status contradicts journal state"
+    entry_destinations: list[str] = []
+    entry_staged_paths: list[str] = []
+    transaction_root = journal.parent.resolve()
+    for index, value in enumerate(staged_paths):
+        _, error = _validated_path(value, recovery_root, f"staged_paths[{index}]")
+        if error:
+            return error
+    for index, value in enumerate(final_paths):
+        _, error = _validated_path(value, recovery_root, f"final_paths[{index}]")
+        if error:
+            return error
+    for index, entry in enumerate(entries):
+        required_entry_fields = {
+            "destination", "backup_path", "previous_sha256", "staged_path", "expected_sha256"
+        }
+        missing_entry = sorted(required_entry_fields - entry.keys())
+        if missing_entry:
+            return f"required entry fields missing at index {index}: {', '.join(missing_entry)}"
+        destination, error = _validated_path(
+            entry.get("destination"), recovery_root, f"entries[{index}].destination"
+        )
+        if error:
+            return error
+        staged, error = _validated_path(
+            entry.get("staged_path"), recovery_root, f"entries[{index}].staged_path"
+        )
+        if error:
+            return error
+        assert destination is not None and staged is not None
+        if staged.parent != destination.parent:
+            return f"entries[{index}].staged_path must share the destination parent"
+        expected_checksum = entry.get("expected_sha256")
+        if not _valid_checksum(expected_checksum):
+            return f"entries[{index}].expected_sha256 is invalid"
         backup_value = entry.get("backup_path")
         previous_checksum = entry.get("previous_sha256")
-        if backup_value:
-            backup = Path(str(backup_value))
+        backup: Path | None = None
+        if backup_value is not None:
+            backup, error = _validated_path(
+                backup_value, recovery_root, f"entries[{index}].backup_path"
+            )
+            if error:
+                return error
+            assert backup is not None
+            if not _is_contained(backup, transaction_root):
+                return f"entries[{index}].backup_path is outside transaction directory"
+            if not _valid_checksum(previous_checksum):
+                return f"entries[{index}].previous_sha256 is invalid"
+        elif previous_checksum is not None:
+            return f"entries[{index}] has previous checksum without rollback backup"
+        entry_destinations.append(str(destination))
+        entry_staged_paths.append(str(staged))
+        if backup is not None:
             if not backup.is_file():
                 return f"missing rollback backup: {backup}"
-            if previous_checksum and atomic_io.sha256_file(backup) != str(previous_checksum):
+            if atomic_io.sha256_file(backup) != previous_checksum:
                 return f"rollback backup checksum mismatch: {backup}"
-        staged_value = entry.get("staged_path")
-        expected_checksum = entry.get("expected_sha256")
-        if staged_value and Path(str(staged_value)).is_file():
-            if expected_checksum and atomic_io.sha256_file(Path(str(staged_value))) != str(expected_checksum):
-                return f"staged payload checksum mismatch: {staged_value}"
-        elif state in {"staging", "validating", "ready", "ready_to_commit"} and staged_value:
-            return f"missing staged payload: {staged_value}"
+        if staged.is_file():
+            if atomic_io.sha256_file(staged) != expected_checksum:
+                return f"staged payload checksum mismatch: {staged}"
+        elif state in {"staging", "validating", "ready_to_commit"}:
+            return f"missing staged payload: {staged}"
         if state == "committed":
-            destination = Path(str(entry.get("destination", "")))
             if not destination.is_file():
                 return f"missing committed payload: {destination}"
-            if expected_checksum and atomic_io.sha256_file(destination) != str(expected_checksum):
+            if atomic_io.sha256_file(destination) != expected_checksum:
                 return f"committed payload checksum mismatch: {destination}"
+    if entries and final_paths != entry_destinations:
+        return "final_paths contradict journal entries"
+    if entries and staged_paths != entry_staged_paths:
+        return "staged_paths contradict journal entries"
+    if entries and checksums != {
+        destination: entry["expected_sha256"]
+        for destination, entry in zip(entry_destinations, entries, strict=True)
+    }:
+        return "expected_checksums contradict journal entries"
+    for index, value in enumerate(payload["lock_paths"]):
+        lock, error = _validated_path(value, recovery_root, f"lock_paths[{index}]")
+        if error:
+            return error
+        if lock is None or lock.name != ".atomic-write-group.lock":
+            return f"lock_paths[{index}] is not a canonical group lock"
+        if lock.is_file():
+            try:
+                lock_payload = json.loads(lock.read_text(encoding="utf-8"))
+                lock_journal = Path(str(lock_payload["journal_path"])).resolve()
+            except (OSError, json.JSONDecodeError, KeyError, TypeError):
+                return f"lock_paths[{index}] has corrupt ownership evidence"
+            if lock_journal != journal.resolve():
+                return f"lock_paths[{index}] belongs to another transaction"
+    committed_at = payload.get("committed_at")
+    if state == "committed" and not isinstance(committed_at, str):
+        return "committed journal requires committed_at"
+    if state != "committed" and committed_at is not None:
+        return "non-committed journal cannot have committed_at"
+    for field in ("started_at", "updated_at"):
+        if not isinstance(payload.get(field), str) or not payload[field]:
+            return f"{field} must be a non-empty timestamp string"
+    return None
+
+
+def _validate_legacy_paths(
+    payload: dict[str, object], journal: Path, recovery_root: Path
+) -> str | None:
+    if not _is_contained(journal, recovery_root):
+        return f"journal is outside recovery root: {journal}"
+    for index, entry_value in enumerate(payload.get("entries", [])):
+        if not isinstance(entry_value, dict):
+            return f"legacy entry {index} is not an object"
+        for field in ("destination", "backup_path", "staged_path"):
+            value = entry_value.get(field)
+            if value is None:
+                continue
+            _, error = _validated_path(value, recovery_root, f"entries[{index}].{field}")
+            if error:
+                return error
+    for field in ("staged_paths", "lock_paths"):
+        values = payload.get(field, [])
+        if not isinstance(values, list):
+            return f"legacy {field} must be a list"
+        for index, value in enumerate(values):
+            _, error = _validated_path(value, recovery_root, f"{field}[{index}]")
+            if error:
+                return error
     return None
 
 
 def _emit_recovery_event(result: RecoveryResult, event_path: Path | None) -> None:
     if event_path is None:
         return
     sequence = 1
     if event_path.is_file():
         sequence += len(event_path.read_text(encoding="utf-8", errors="replace").splitlines())
     append_event(
         {
             "session_id": "startup-recovery",
@@ -172,79 +421,110 @@ def _emit_recovery_event(result: RecoveryResult, event_path: Path | None) -> Non
             "reason": result.reason,
             "evidence_checksums": result.evidence_checksums,
         },
         path=event_path,
     )
 
 
 def recover_incomplete_transactions(
     data_root: Path,
     *,
     event_path: Path | None = None,
 ) -> list[RecoveryResult]:
+    data_root = data_root.resolve()
+    resolved_event_path = SESSION_LOG_PATH if event_path is None else event_path
+    roots: set[Path] = set()
     direct_root = data_root / ".atomic-transactions"
-    roots = [direct_root] if direct_root.is_dir() else []
-    if data_root.is_dir():
-        roots.extend(
-            sorted(
-                (
-                    item / ".atomic-transactions"
-                    for item in data_root.iterdir()
-                    if item.is_dir() and (item / ".atomic-transactions").is_dir()
-                ),
-                key=str,
-            )
-        )
+    if direct_root.is_dir():
+        roots.add(direct_root)
+    canonical_bases = [
+        child for child in (data_root / "data", data_root / "configs") if child.is_dir()
+    ]
+    if data_root.name in {"data", "configs"} or not canonical_bases:
+        canonical_bases.append(data_root)
+    for base in canonical_bases:
+        for path in base.rglob(".atomic-transactions"):
+            relative_parts = path.relative_to(data_root).parts
+            if (
+                path.is_dir()
+                and "logs" not in relative_parts
+                and not any(part.startswith("pytest_") for part in relative_parts)
+            ):
+                roots.add(path)
     if not roots:
         return []
     results: list[RecoveryResult] = []
     transaction_roots = sorted(
-        (item for root in roots for item in root.iterdir() if item.is_dir()), key=str
+        (item for root in sorted(roots, key=str) for item in root.iterdir() if item.is_dir()), key=str
     )
     for transaction_root in transaction_roots:
         journal = transaction_root / "journal.json"
         try:
             raw = journal.read_bytes()
             payload = json.loads(raw.decode("utf-8"))
         except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
             result = _required_result(journal, transaction_root.name, f"corrupt journal: {exc}")
             results.append(result)
-            _emit_recovery_event(result, event_path)
+            _emit_recovery_event(result, resolved_event_path)
+            continue
+        if not isinstance(payload, dict):
+            result = _required_result(
+                journal, transaction_root.name, "corrupt journal: top-level value must be an object"
+            )
+            results.append(result)
+            _emit_recovery_event(result, resolved_event_path)
             continue
         transaction_id = str(payload.get("transaction_id", transaction_root.name))
         journal_state = str(payload.get("state", ""))
-        if int(payload.get("schema_version", 1)) >= 2:
-            error = _validate_v2_payload(payload)
+        schema_version = payload.get("schema_version", 1)
+        if type(schema_version) is int and schema_version == 2:
+            error = _validate_v2_payload(payload, journal, data_root)
+            if error:
+                result = _required_result(journal, transaction_id, error)
+                results.append(result)
+                _emit_recovery_event(result, resolved_event_path)
+                continue
+        elif type(schema_version) is int and schema_version == 1:
+            error = _validate_legacy_paths(payload, journal, data_root)
             if error:
                 result = _required_result(journal, transaction_id, error)
                 results.append(result)
-                _emit_recovery_event(result, event_path)
+                _emit_recovery_event(result, resolved_event_path)
                 continue
+        else:
+            result = _required_result(
+                journal,
+                transaction_id,
+                f"unsupported or invalid journal schema_version: {schema_version!r}",
+            )
+            results.append(result)
+            _emit_recovery_event(result, resolved_event_path)
+            continue
         try:
             recovered = atomic_io._recover_journal(journal, force=True)
         except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
             result = _required_result(journal, transaction_id, f"rollback failed: {exc}")
             results.append(result)
-            _emit_recovery_event(result, event_path)
+            _emit_recovery_event(result, resolved_event_path)
             continue
         if not recovered:
             result = _required_result(journal, transaction_id, "journal could not be recovered")
             results.append(result)
-            _emit_recovery_event(result, event_path)
+            _emit_recovery_event(result, resolved_event_path)
             continue
         result_state = "committed" if journal_state == "committed" else "rolled_back"
         reason = (
             "verified committed generation retained"
             if result_state == "committed"
             else "previous complete generation restored"
         )
         result = RecoveryResult(
             transaction_id,
             result_state,
             "normal",
             reason,
             journal,
             {"journal_sha256": hashlib.sha256(raw).hexdigest()},
         )
         results.append(result)
-        _emit_recovery_event(result, event_path)
+        _emit_recovery_event(result, resolved_event_path)
     return results
diff --git a/tests/operations/test_recovery.py b/tests/operations/test_recovery.py
index 53d8c86..585a19c 100644
--- a/tests/operations/test_recovery.py
+++ b/tests/operations/test_recovery.py
@@ -1,71 +1,82 @@
 from __future__ import annotations
 
 import hashlib
 import json
 from pathlib import Path
 
 import pytest
 
 from etf_cockpit.core import atomic_io
 from etf_cockpit.core.migrations import MigrationContext, run_migrations
 
 
+def _request(path: Path, payload: bytes) -> atomic_io.AtomicWriteRequest:
+    return atomic_io.AtomicWriteRequest(path, payload, lambda staged: staged.read_bytes())
+
+
 def _recover(data_root: Path):
     try:
         recovery = __import__("etf_cockpit.operations.recovery", fromlist=["recover_incomplete_transactions"])
     except ModuleNotFoundError:
         return []
-    return recovery.recover_incomplete_transactions(data_root)
+    return recovery.recover_incomplete_transactions(
+        data_root,
+        event_path=data_root / "logs" / "session.jsonl",
+    )
 
 
 def _interrupted_transaction(tmp_path: Path, state: str, *, corrupt_payload: bool = False) -> Path:
     destination = tmp_path / "data" / "current.bin"
     destination.parent.mkdir(parents=True)
     destination.write_bytes(b"old")
     transaction_root = tmp_path / ".atomic-transactions" / f"tx-{state}"
     transaction_root.mkdir(parents=True)
     backup = transaction_root / "backup-0.bin"
     backup.write_bytes(b"old")
     staged = destination.parent / ".current.bin.interrupted.group.tmp"
     staged.write_bytes(b"corrupt" if corrupt_payload else b"new")
     if state in {"committing", "manifest_publish"}:
         destination.write_bytes(b"new")
     journal = transaction_root / "journal.json"
     journal.write_text(
         json.dumps(
             {
                 "schema_version": 2,
                 "transaction_id": f"tx-{state}",
                 "workflow_run_id": "workflow-1",
                 "transaction_type": "canonical_refresh",
                 "owner_pid": 999999,
                 "state": state,
-                "affected_datasets": ["canonical"],
-                "base_generations": {"canonical": "generation-old"},
+                "affected_dataset_ids": ["canonical"],
+                "base_generation_ids": {"canonical": "generation-old"},
                 "entries": [
                     {
                         "destination": str(destination.resolve()),
                         "backup_path": str(backup.resolve()),
                         "previous_sha256": hashlib.sha256(b"old").hexdigest(),
                         "staged_path": str(staged.resolve()),
                         "expected_sha256": hashlib.sha256(b"new").hexdigest(),
                     }
                 ],
                 "staged_paths": [str(staged.resolve())],
+                "final_paths": [str(destination.resolve())],
                 "lock_paths": [],
                 "expected_checksums": {
                     str(destination.resolve()): hashlib.sha256(b"new").hexdigest()
                 },
-                "recovery_instructions": "Restore the previous complete generation.",
+                "started_at": "2026-07-11T00:00:00+00:00",
+                "updated_at": "2026-07-11T00:00:01+00:00",
+                "committed_at": None,
+                "recovery_instructions": ["Restore the previous complete generation."],
             }
         ),
         encoding="utf-8",
     )
     return destination
 
 
 @pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
 def test_recovery_exposes_old_complete_generation_after_every_interruption(
     tmp_path: Path, crash_point: str
 ) -> None:
     destination = _interrupted_transaction(tmp_path, crash_point)
@@ -167,37 +178,196 @@ def test_recovery_outcome_is_visible_in_the_authoritative_operational_trace(tmp_
     event_path = tmp_path / "logs" / "session.jsonl"
     recovery = __import__("etf_cockpit.operations.recovery", fromlist=["recover_incomplete_transactions"])
 
     recovery.recover_incomplete_transactions(tmp_path, event_path=event_path)
 
     event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
     assert event["event_type"] == "write_transaction_recovery"
     assert event["status"] == "rolled_back"
     assert event["transaction_id"] == "tx-validating"
     assert event["event_hash"]
 
 
+def test_recovery_uses_authoritative_session_trace_by_default(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    _interrupted_transaction(tmp_path, "validating")
+    recovery = __import__("etf_cockpit.operations.recovery", fromlist=["SESSION_LOG_PATH"])
+    event_path = tmp_path / "logs" / "session.jsonl"
+    monkeypatch.setattr(recovery, "SESSION_LOG_PATH", event_path)
+
+    recovery.recover_incomplete_transactions(tmp_path)
+
+    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
+    assert event["event_type"] == "write_transaction_recovery"
+    assert event["event_hash"]
+
+
 def test_migration_recovers_interrupted_atomic_write_before_schema_changes(tmp_path: Path) -> None:
     destination = _interrupted_transaction(tmp_path, "committing")
     context = MigrationContext(tmp_path, tmp_path / "backups")
 
     report = run_migrations(context)
 
     assert report.current_version == 4
     assert destination.read_bytes() == b"old"
 
 
+def test_migration_recovers_real_nested_writer_and_emits_authoritative_event(tmp_path: Path) -> None:
+    destination = tmp_path / "data" / "clean" / "canonical.bin"
+    destination.parent.mkdir(parents=True)
+    destination.write_bytes(b"old")
+
+    def interrupt(state: str, _journal: Path) -> None:
+        if state == "manifest_publish":
+            raise atomic_io.AtomicWriteInterrupted(state)
+
+    with pytest.raises(atomic_io.AtomicWriteInterrupted):
+        atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=interrupt)
+    journal = next((tmp_path / "data" / "clean").glob(".atomic-transactions/*/journal.json"))
+
+    report = run_migrations(MigrationContext(tmp_path, tmp_path / "backups"))
+
+    assert report.current_version == 4
+    assert destination.read_bytes() == b"old"
+    assert not journal.exists()
+    event_path = tmp_path / "logs" / "session.jsonl"
+    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
+    recovery_events = [item for item in events if item["event_type"] == "write_transaction_recovery"]
+    assert recovery_events[-1]["status"] == "rolled_back"
+    assert recovery_events[-1]["event_hash"]
+
+
+def _valid_v2_payload(root: Path, transaction_id: str = "valid") -> tuple[Path, dict[str, object]]:
+    destination = root / "data" / "current.bin"
+    destination.parent.mkdir(parents=True, exist_ok=True)
+    destination.write_bytes(b"new")
+    transaction_root = root / ".atomic-transactions" / transaction_id
+    transaction_root.mkdir(parents=True)
+    backup = transaction_root / "backup-0.bin"
+    backup.write_bytes(b"old")
+    staged = destination.parent / ".current.bin.valid.group.tmp"
+    staged.write_bytes(b"new")
+    expected = hashlib.sha256(b"new").hexdigest()
+    payload: dict[str, object] = {
+        "schema_version": 2,
+        "transaction_id": transaction_id,
+        "workflow_run_id": "workflow-1",
+        "transaction_type": "canonical_refresh",
+        "owner_pid": 999999,
+        "state": "committing",
+        "affected_dataset_ids": ["canonical"],
+        "base_generation_ids": {"canonical": "generation-old"},
+        "entries": [{
+            "destination": str(destination.resolve()),
+            "backup_path": str(backup.resolve()),
+            "previous_sha256": hashlib.sha256(b"old").hexdigest(),
+            "staged_path": str(staged.resolve()),
+            "expected_sha256": expected,
+        }],
+        "staged_paths": [str(staged.resolve())],
+        "final_paths": [str(destination.resolve())],
+        "lock_paths": [],
+        "expected_checksums": {str(destination.resolve()): expected},
+        "started_at": "2026-07-11T00:00:00+00:00",
+        "updated_at": "2026-07-11T00:00:01+00:00",
+        "committed_at": None,
+        "recovery_instructions": ["Restore the previous complete generation."],
+    }
+    journal = transaction_root / "journal.json"
+    journal.write_text(json.dumps(payload), encoding="utf-8")
+    return journal, payload
+
+
+@pytest.mark.parametrize(
+    ("damage", "expected_reason"),
+    [
+        ("unknown_state", "state"),
+        ("missing_required", "required"),
+        ("contradictory_maps", "cardinality"),
+        ("contradictory_checksums", "contradict"),
+        ("identity", "transaction"),
+    ],
+)
+def test_structurally_invalid_v2_journal_is_preserved_for_manual_review(
+    tmp_path: Path, damage: str, expected_reason: str
+) -> None:
+    journal, payload = _valid_v2_payload(tmp_path)
+    if damage == "unknown_state":
+        payload["state"] = "nonsense"
+    elif damage == "missing_required":
+        payload.pop("recovery_instructions")
+    elif damage == "contradictory_maps":
+        payload["final_paths"] = []
+    elif damage == "contradictory_checksums":
+        checksums = payload["expected_checksums"]
+        assert isinstance(checksums, dict)
+        destination = str(payload["final_paths"][0])
+        checksums[destination] = "f" * 64
+    else:
+        payload["transaction_id"] = "forged-id"
+    journal.write_text(json.dumps(payload), encoding="utf-8")
+
+    result = _recover(tmp_path)[0]
+
+    assert result.state == "recovery_required"
+    assert result.startup_mode == "read_only"
+    assert expected_reason in result.reason.lower()
+    assert journal.exists()
+
+
+@pytest.mark.parametrize("payload", [["not", "an", "object"], {"schema_version": "two"}])
+def test_malformed_top_level_journal_is_preserved_without_startup_exception(
+    tmp_path: Path, payload: object
+) -> None:
+    transaction_root = tmp_path / ".atomic-transactions" / "malformed"
+    transaction_root.mkdir(parents=True)
+    journal = transaction_root / "journal.json"
+    journal.write_text(json.dumps(payload), encoding="utf-8")
+
+    result = _recover(tmp_path)[0]
+
+    assert result.state == "recovery_required"
+    assert result.startup_mode == "read_only"
+    assert journal.exists()
+
+
+def test_v2_journal_cannot_mutate_a_path_outside_supplied_recovery_root(tmp_path: Path) -> None:
+    root = tmp_path / "recovery-root"
+    outside = tmp_path / "outside.bin"
+    outside.write_bytes(b"do-not-touch")
+    journal, payload = _valid_v2_payload(root)
+    entry = payload["entries"][0]
+    assert isinstance(entry, dict)
+    original_destination = entry["destination"]
+    entry["destination"] = str(outside.resolve())
+    payload["final_paths"] = [str(outside.resolve())]
+    checksums = payload["expected_checksums"]
+    assert isinstance(checksums, dict)
+    checksums[str(outside.resolve())] = checksums.pop(original_destination)
+    journal.write_text(json.dumps(payload), encoding="utf-8")
+
+    result = _recover(root)[0]
+
+    assert result.state == "recovery_required"
+    assert result.startup_mode == "read_only"
+    assert "outside recovery root" in result.reason.lower()
+    assert outside.read_bytes() == b"do-not-touch"
+    assert journal.exists()
+
+
 def test_lingering_committed_journal_keeps_verified_new_generation(tmp_path: Path) -> None:
     destination = _interrupted_transaction(tmp_path, "manifest_publish")
     root = tmp_path / ".atomic-transactions" / "tx-manifest_publish"
     journal = root / "journal.json"
     payload = json.loads(journal.read_text(encoding="utf-8"))
     payload["state"] = "committed"
+    payload["committed_at"] = "2026-07-11T00:00:02+00:00"
     Path(payload["entries"][0]["staged_path"]).unlink()
     journal.write_text(json.dumps(payload), encoding="utf-8")
 
     outcome = _recover(tmp_path)
 
     assert outcome[0].state == "committed"
     assert outcome[0].startup_mode == "normal"
     assert destination.read_bytes() == b"new"
     assert not root.exists()
diff --git a/tests/operations/test_transactions.py b/tests/operations/test_transactions.py
index 421b9ef..fd429f4 100644
--- a/tests/operations/test_transactions.py
+++ b/tests/operations/test_transactions.py
@@ -1,17 +1,19 @@
 from __future__ import annotations
 
 import hashlib
 import json
 from pathlib import Path
+import threading
+from typing import get_args, get_origin
 
 import pytest
 
 from etf_cockpit.core import atomic_io
 
 
 def _request(path: Path, payload: bytes) -> atomic_io.AtomicWriteRequest:
     return atomic_io.AtomicWriteRequest(path, payload, lambda staged: staged.read_bytes())
 
 
 def test_grouped_write_journal_exposes_durable_transaction_identity_and_lifecycle(
     tmp_path: Path, monkeypatch: pytest.MonkeyPatch
@@ -43,86 +45,199 @@ def test_grouped_write_journal_exposes_durable_transaction_identity_and_lifecycl
     assert committed["recovery_instructions"]
 
 
 def test_transaction_model_carries_the_approved_recovery_fields() -> None:
     model = getattr(__import__("etf_cockpit.operations.models", fromlist=["WriteTransaction"]), "WriteTransaction", None)
     assert model is not None
     fields = set(model.model_fields)
     assert {
         "transaction_id",
         "workflow_run_id",
         "transaction_type",
         "affected_dataset_ids",
-        "base_generations",
+        "base_generation_ids",
         "staging_paths",
         "final_paths",
         "expected_checksums",
         "status",
         "started_at",
         "updated_at",
         "committed_at",
         "recovery_instructions",
     } <= fields
+    assert get_origin(model.model_fields["staging_paths"].annotation) is list
+    assert get_args(model.model_fields["staging_paths"].annotation) == (str,)
+    assert get_origin(model.model_fields["final_paths"].annotation) is list
+    assert get_args(model.model_fields["final_paths"].annotation) == (str,)
+    assert get_origin(model.model_fields["recovery_instructions"].annotation) is list
+    assert get_args(model.model_fields["recovery_instructions"].annotation) == (str,)
+    assert "planned" in get_args(model.model_fields["status"].annotation)
+    assert "manifest_publish" not in get_args(model.model_fields["status"].annotation)
 
 
 def test_begin_and_ready_lifecycle_is_durable_in_the_atomic_journal(tmp_path: Path) -> None:
     try:
         recovery = __import__("etf_cockpit.operations.recovery", fromlist=["begin_write_transaction"])
     except ModuleNotFoundError:
         pytest.fail("transaction lifecycle API is absent")
 
     transaction = recovery.begin_write_transaction(
         data_root=tmp_path,
         transaction_type="canonical_refresh",
         workflow_run_id="workflow-1",
         affected_datasets=["canonical"],
         base_generations={"canonical": "generation-old"},
-        final_paths={"canonical": str(tmp_path / "data" / "canonical.bin")},
+        final_paths=[str(tmp_path / "data" / "canonical.bin")],
     )
     ready = recovery.mark_transaction_ready(
         transaction.transaction_id,
         {"canonical": hashlib.sha256(b"new").hexdigest()},
         data_root=tmp_path,
     )
     journal = tmp_path / ".atomic-transactions" / transaction.transaction_id / "journal.json"
     durable = json.loads(journal.read_text(encoding="utf-8"))
 
     assert ready.status == "ready_to_commit"
     assert durable["transaction_id"] == transaction.transaction_id
     assert durable["state"] == "ready_to_commit"
     assert durable["expected_checksums"] == ready.expected_checksums
+    assert transaction.base_generation_ids == {"canonical": "generation-old"}
+    assert transaction.base_generations == transaction.base_generation_ids
+    assert transaction.status == "planned"
+    assert isinstance(durable["final_paths"], list)
+    assert isinstance(durable["recovery_instructions"], list)
 
 
 @pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
 def test_real_group_interruption_leaves_one_existing_journal_for_startup_recovery(
     tmp_path: Path, crash_point: str
 ) -> None:
     destination = tmp_path / "data" / "canonical.bin"
     destination.parent.mkdir(parents=True)
     destination.write_bytes(b"old")
 
     def interrupt(state: str, _journal: Path) -> None:
         if state == crash_point:
             raise atomic_io.AtomicWriteInterrupted(state)
 
     with pytest.raises(atomic_io.AtomicWriteInterrupted):
         atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=interrupt)
 
     journals = list(tmp_path.rglob(".atomic-transactions/*/journal.json"))
     assert len(journals) == 1
     assert json.loads(journals[0].read_text(encoding="utf-8"))["state"] == crash_point
 
 
+@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
+def test_real_group_interruption_recovers_the_previous_complete_generation(
+    tmp_path: Path, crash_point: str
+) -> None:
+    from etf_cockpit.operations.recovery import recover_incomplete_transactions
+
+    destination = tmp_path / "data" / "canonical.bin"
+    destination.parent.mkdir(parents=True)
+    destination.write_bytes(b"old")
+
+    def interrupt(state: str, _journal: Path) -> None:
+        if state == crash_point:
+            raise atomic_io.AtomicWriteInterrupted(state)
+
+    with pytest.raises(atomic_io.AtomicWriteInterrupted):
+        atomic_io.atomic_write_group((_request(destination, b"new"),), lifecycle_hook=interrupt)
+
+    result = recover_incomplete_transactions(
+        tmp_path,
+        event_path=tmp_path / "logs" / "session.jsonl",
+    )[0]
+
+    assert result.state == "rolled_back"
+    assert result.startup_mode == "normal"
+    assert destination.read_bytes() == b"old"
+
+
 def test_concurrent_writer_times_out_without_changing_previous_value(tmp_path: Path) -> None:
     destination = tmp_path / "data" / "canonical.bin"
     destination.parent.mkdir(parents=True)
     destination.write_bytes(b"old")
     lock = destination.parent / ".atomic-write-group.lock"
     lock.write_text(
         json.dumps({"owner_pid": __import__("os").getpid(), "journal_path": "active"}),
         encoding="utf-8",
     )
 
     with pytest.raises(TimeoutError):
         atomic_io.wait_for_atomic_group(destination, timeout_seconds=0.01)
 
     assert destination.read_bytes() == b"old"
+
+
+def test_recovery_of_interrupted_second_real_writer_preserves_first_commit(tmp_path: Path) -> None:
+    from etf_cockpit.operations.recovery import recover_incomplete_transactions
+
+    destination = tmp_path / "data" / "canonical.bin"
+    destination.parent.mkdir(parents=True)
+    destination.write_bytes(b"old")
+    first_at_commit = threading.Event()
+    release_first = threading.Event()
+    second_at_commit = threading.Event()
+    errors: list[BaseException] = []
+
+    def first_hook(state: str, _journal: Path) -> None:
+        if state == "committing":
+            first_at_commit.set()
+            assert release_first.wait(timeout=5)
+
+    def second_hook(state: str, _journal: Path) -> None:
+        if state == "committing":
+            second_at_commit.set()
+        if state == "manifest_publish":
+            raise atomic_io.AtomicWriteInterrupted(state)
+
+    def write(payload: bytes, hook) -> None:
+        try:
+            atomic_io.atomic_write_group((_request(destination, payload),), lifecycle_hook=hook)
+        except atomic_io.AtomicWriteInterrupted:
+            pass
+        except BaseException as exc:  # pragma: no cover - asserted below
+            errors.append(exc)
+
+    first = threading.Thread(target=write, args=(b"new-1", first_hook))
+    second = threading.Thread(target=write, args=(b"new-2", second_hook))
+    first.start()
+    assert first_at_commit.wait(timeout=5)
+    second.start()
+    second_at_commit.wait(timeout=0.25)
+    release_first.set()
+    first.join(timeout=5)
+    second.join(timeout=5)
+
+    assert not first.is_alive() and not second.is_alive()
+    assert errors == []
+    assert destination.read_bytes() == b"new-2"
+
+    results = recover_incomplete_transactions(
+        tmp_path,
+        event_path=tmp_path / "logs" / "session.jsonl",
+    )
+
+    assert [result.state for result in results] == ["rolled_back"]
+    assert destination.read_bytes() == b"new-1"
+
+
+def test_staged_checksum_is_recomputed_after_commit_hook_before_activation(tmp_path: Path) -> None:
+    destination = tmp_path / "data" / "canonical.bin"
+    destination.parent.mkdir(parents=True)
+    destination.write_bytes(b"old")
+
+    def tamper(state: str, journal: Path) -> None:
+        if state == "committing":
+            payload = json.loads(journal.read_text(encoding="utf-8"))
+            Path(payload["entries"][0]["staged_path"]).write_bytes(b"TAMPERED")
+
+    with pytest.raises(OSError, match="staged payload checksum mismatch"):
+        atomic_io.atomic_write_group(
+            (_request(destination, b"new"),),
+            lifecycle_hook=tamper,
+        )
+
+    assert destination.read_bytes() == b"old"
+    assert list(tmp_path.rglob(".atomic-transactions/*/journal.json")) == []
