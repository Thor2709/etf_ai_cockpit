# Review package: 445dd44..d48bbbe

## Commits
d48bbbe feat: add atomic transaction recovery contract
e533d30 docs: record Wave 0 Task 3 implementation brief
791aede chore: record Task 3 issue reconciliation preflight

## Files changed
 .ai_worklog/task-3-brief.md            |   62 ++
 .ai_worklog/task-3-report.md           |   71 ++
 evidence/wave0/task3/fault-matrix.json |   26 +
 issues/github_issue_map.json           | 1483 ++++++++++++++++++++++++++++++++
 src/etf_cockpit/core/atomic_io.py      |   96 ++-
 src/etf_cockpit/core/migrations.py     |    7 +
 src/etf_cockpit/operations/models.py   |   48 +-
 src/etf_cockpit/operations/recovery.py |  250 ++++++
 tests/operations/test_backups.py       |   22 +
 tests/operations/test_recovery.py      |  203 +++++
 tests/operations/test_transactions.py  |  128 +++
 11 files changed, 2373 insertions(+), 23 deletions(-)

## Diff
diff --git a/.ai_worklog/task-3-brief.md b/.ai_worklog/task-3-brief.md
new file mode 100644
index 0000000..86a256c
--- /dev/null
+++ b/.ai_worklog/task-3-brief.md
@@ -0,0 +1,62 @@
+### Task 3: Route mutable canonical writes through the existing atomic transaction primitive
+
+**Files:**
+
+- Create: `src/etf_cockpit/operations/recovery.py`, `tests/operations/test_transactions.py`, `tests/operations/test_recovery.py`, `tests/operations/test_backups.py`
+- Modify: `src/etf_cockpit/core/atomic_io.py:1-366`, `src/etf_cockpit/core/migrations.py:1-145`, selected mutable writer modules only after a writer inventory is generated
+
+**Consumes:** Tasks 1-2 evidence/event contracts and existing grouped atomic write/journal APIs.
+
+**Produces:** `WriteTransaction` lifecycle and startup recovery result reused by registry, catalogue, portfolio and workflow tasks.
+
+- [ ] **Step 1: Write parameterised fault-injection RED tests**
+
+```python
+@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
+def test_recovery_exposes_old_or_new_complete_generation_only(tmp_path: Path, crash_point: str) -> None:
+    simulate_grouped_write_crash(tmp_path, crash_point=crash_point)
+    outcome = recover_incomplete_transactions(tmp_path)
+    assert outcome[0].state in {"rolled_back", "recovery_required"}
+    assert read_current_pointer(tmp_path) in {"generation-old", "generation-new"}
+```
+
+- [ ] **Step 2: Run RED**
+
+Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q`
+
+Expected: FAIL because transaction records and recovery classification are absent.
+
+- [ ] **Step 3: Implement transaction records around, not beside, `atomic_io`**
+
+```python
+def begin_write_transaction(*, transaction_type: str, base_generations: dict[str, str]) -> WriteTransaction: ...
+def mark_transaction_ready(transaction_id: str, checksums: dict[str, str]) -> WriteTransaction: ...
+def recover_incomplete_transactions(data_root: Path) -> list[RecoveryResult]: ...
+```
+
+Each function delegates actual byte/group commit, lock, journal, verification and backup work to `core.atomic_io`; it never introduces a second lock or journal format. Startup recovery must select normal, read-only diagnostic or recovery-required mode without promoting ambiguous staging data.
+
+- [ ] **Step 4: Run GREEN and restore drill**
+
+Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py -q`
+
+Expected: PASS, including locked-file, checksum-mismatch and restore fixtures.
+
+- [ ] **Step 5: Log recovery evidence**
+
+Write the fault matrix, backup manifest checksums and recovery-state screenshots to the wave evidence directory; update the ledger but do not close `REL-02` until package recovery has also passed.
+
+## Binding execution brief
+
+- Work only in `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task3-atomic-recovery` on branch `wave0/task3-atomic-recovery`; do not edit `main`.
+- Correct task base is commit `445dd44b5382160d4e93e4cada018beb4ab0f5b5` plus the committed read-only issue-reconciliation preflight `791aede`. Do not reset, discard or overwrite existing Task 1/2 work.
+- Primary local issue seam is `ISSUE-0040` (atomic data commits and failed-workflow non-corruption). `ISSUE-0038` and `ISSUE-0044` are related later-task seams; do not close them from this task. The local issue ledger and approved specification are authoritative; GitHub Issues are only a synchronised representation.
+- Preserve `execution_allowed = false`, evidence/provider/model boundaries, current revision-protected stores, Task 2 operational-event authority, session tracing, Data Health, audit manifests, schemas and compatibility paths. Do not add execution, provider, model, portfolio, scoring, data-coverage or UI scope.
+- Use the existing `src/etf_cockpit/core/atomic_io.py` grouped write, lock, journal, checksum, backup and restore primitives. Do not create a competing lock, journal or transaction engine. If the existing primitive lacks an observable seam, extend it narrowly and keep legacy callers compatible.
+- Add the required RED tests before production behaviour. Run the exact plan RED command with the absolute existing interpreter `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe` because the ignored `.venv` is not materialised in the worktree. Record a genuine behavioural failure, not an import/syntax error.
+- `WriteTransaction` must follow the approved shape: transaction ID, workflow run ID, type, affected datasets, base generations, staging/final paths, expected checksums, approved status literals, timestamps and recovery instructions. Recovery results must expose deterministic state and evidence without promoting ambiguous staging.
+- Observable invariants: readers see either the previous complete valid state or the new complete valid state; validation/checksums precede activation; lock contention is safe; repeated recovery is idempotent; corrupt/incomplete journals and payloads become explicit recovery-required/read-only/manual-review outcomes; operational events and audit/manifest evidence remain visible.
+- Tests must exercise failure outcomes and invariants, not private call counts. Cover staging, validating, committing and manifest publication interruption, locks/concurrency, checksum/payload/journal corruption, missing files, permission/replace failures, startup recovery, clean restart, migration compatibility and backup/restore checksum validation where applicable.
+- No user-visible surface is added unless current code requires it for recovery status; if no UI changes are made, document UI/browser/package visual gates as `pending_later_task` for `ISSUE-0040`.
+- Update `.ai_worklog/task-3-report.md` with exact RED/GREEN/refactor commands, exit status, failure excerpts, checksums, test totals, fault/recovery matrix, migration compatibility and residual closure gates. Commit implementation and tests only after review-ready self-review; do not close `ISSUE-0040` unless every applicable issue gate passes.
+
diff --git a/.ai_worklog/task-3-report.md b/.ai_worklog/task-3-report.md
new file mode 100644
index 0000000..bbd6630
--- /dev/null
+++ b/.ai_worklog/task-3-report.md
@@ -0,0 +1,71 @@
+# Wave 0 Task 3 - Atomic transaction and deterministic recovery
+
+Date opened: 2026-07-11  
+Branch: `wave0/task3-atomic-recovery`  
+Task base: `445dd44b5382160d4e93e4cada018beb4ab0f5b5` (`origin/main`)  
+Owning local issue: `ISSUE-0040` - Error handling and recovery centre.  
+Related later-task issue seams: `ISSUE-0038` (storage migration plan) and `ISSUE-0044` (backup/restore UI and release metadata). These remain open unless their own closure gates pass.
+
+## Closure decision before implementation
+
+Task 3 is an infrastructure increment for the atomic-commit and recovery portion of `ISSUE-0040`; it cannot close that issue by itself because the local issue requires a user-visible Error/Recovery panel, retry workflow, package rebuild and browser failure smoke. Those are later dependency-valid tasks. The issue therefore remains open with an implementation-complete, closure-pending state until those gates have fresh evidence.
+
+## Task 3 closure checklist
+
+Each row is updated only after fresh evidence exists.
+
+| Gate | State before implementation | Evidence / reason |
+|---|---|---|
+| Transaction records and lifecycle | pending | Task 3 implementation |
+| Staging before activation | pending | Task 3 implementation and tests |
+| All-or-nothing old/new complete visibility | pending | Fault matrix tests |
+| Durable journal/evidence and transaction identity | pending | Task 3 implementation and audit evidence |
+| Checksums and validation before activation | pending | Recovery/integrity tests |
+| Writer locking and concurrent writers | pending | Lock contention tests |
+| Interrupted writes, migrations and activation | pending | Fault injection and startup recovery tests |
+| Stale/orphaned staging classification | pending | Recovery tests |
+| Deterministic idempotent recovery | pending | Repeated recovery tests |
+| Corrupt journal/payload/checksum/missing-file handling | pending | Recovery failure-path tests |
+| Permission/locked-file/write-failure handling | pending | Failure injection tests |
+| Startup recovery and clean-start behaviour | pending | Recovery integration tests |
+| Operational-event emission and audit/manifest visibility | pending | Existing Task 2 contracts plus Task 3 evidence |
+| Data Health visibility | pending_later_task | No user-facing Data Health change is owned by Task 3 |
+| Backward compatibility / migration behaviour | pending | Migration and compatibility tests |
+| Read-only or unavailable state when recovery is unproven | pending | Recovery classification tests |
+| ISSUE-0040 readable errors, panel, retry and Activity Log UI | pending_later_task | Required by issue but not this infrastructure task |
+| ISSUE-0040 package/build/browser gates | pending_later_task | Required by issue but not this infrastructure task |
+| Independent task review | pending | Fresh reviewer required |
+| Closure evaluator | pending | Issue remains closure-pending unless all gates pass |
+| `execution_allowed` remains `false` | pending | Boundary regression |
+
+## RED-GREEN-REFACTOR evidence
+
+To be recorded by the implementer and independently checked by the reviewer:
+
+- RED command and non-syntax failure: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q` exited 1 on 2026-07-11 with 11 behavioural failures and 7 passes. Representative failures: the grouped journal exposed only `prepared`/`committed` rather than the required lifecycle; `WriteTransaction` was absent; recovery returned no classification for interrupted and corrupt journals. Collection completed successfully, so this was not an import or syntax failure.
+- GREEN plan command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py -q` exited 0 with 29 passed after the lifecycle/fault-injection increment.
+- Refactor regression command: `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py -q` exited 0 with 38 passed. A subsequent affected-release run including three audit/release regressions exited 0 with 41 passed.
+- Static checks: Ruff on all changed Python files, `python -m compileall -q src\etf_cockpit`, and `git diff --check` each exited 0.
+- Full applicable verification: `python -m pytest tests -q` collected 306 tests and exited 1 with 299 passed and seven failures. These are exactly the seven clean-worktree baseline failures previously recorded by preflight: six `tests/test_simple_scores.py` failures and `tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity`, caused by ignored trade-candidate/catalogue artefacts absent from the isolated worktree. The first full attempt additionally exposed three migration-startup failures caused by scanning pytest artefacts under `logs/pytest_system_tmp`; discovery was narrowed to the supplied root and its immediate dataset directories, and all three affected release/audit regressions then passed.
+
+## Implementation and compatibility record
+
+- The existing `.atomic-transactions` directory, `.atomic-write-group.lock`, journal writer, rollback backups, checksum functions and atomic replace functions remain the only transaction engine. No second lock or journal format was introduced.
+- Journal schema 2 adds durable transaction identity, approved dataset/timestamp fields, expected payload checksums, recovery instructions and observable `staging`, `validating`, `committing`, `manifest_publish` and `committed` phases. Legacy schema-1 prepared journals remain recoverable.
+- `WriteTransaction` uses the approved `affected_dataset_ids`, `started_at`, `committed_at` and `ready_to_commit`/rollback/recovery status names. Read-only compatibility properties accept the earlier draft names `affected_datasets` and `created_at`. `begin_write_transaction` and `mark_transaction_ready` keep the plan call shapes by defaulting their optional data root to the project data directory.
+- Recovery is deterministic and conservative: verified incomplete work rolls back to the old complete state; a verified lingering commit retains the new complete state; corrupt, missing, checksum-invalid or permission-blocked evidence stays in place and returns `recovery_required` plus `read_only` startup mode for manual review. Repeated recovery after a successful rollback is an empty no-op.
+- `run_migrations` performs recovery before schema changes and refuses to migrate if recovery cannot be proved. Existing migration and backup/restore compatibility tests pass.
+- Recovery outcomes can be emitted through Task 2's authoritative hash-chained session trace via the optional `event_path`; no parallel operational logger exists. The regression asserts event type, status, transaction ID and event hash.
+- Writer inventory found existing atomic/grouped canonical seams in backup/restore, import/export, FX, manual notes, import pipeline, trust artefacts, universe store, reference data and simple scores. Direct writers in model/feature/report/export paths were not bulk-rewritten because their ownership belongs to later storage/workflow tasks and doing so would exceed Task 3. No mutable writer required a compatibility-breaking edit for this foundation.
+
+## Evidence and boundary state
+
+- Fault matrix and source checksums: `evidence/wave0/task3/fault-matrix.json`.
+- Backup checksum evidence is exercised by `tests/operations/test_backups.py`, `tests/test_atomic_io.py` and `tests/test_backup_restore.py`; tampering blocks restore.
+- No UI was changed. Recovery screenshots, Error/Recovery panel, package rebuild and browser smoke remain `pending_later_task` for `ISSUE-0040`; the issue and `REL-02` remain open.
+- No issue files were moved or closed, no remote state was changed, and Task 4 was not started. The implementation adds no execution path and does not change the documented `execution_allowed=false` boundary.
+- Independent task review and closure evaluation remain pending.
+
+## Remote issue reconciliation preflight
+
+`issues/github_issue_map.json` is a read-only inventory manifest at this boundary. The local ledger parser found 98 canonical stable IDs (77 open, 21 closed), no remote GitHub Issues, and five documented historical/placement contradictions. No remote issue mutation has been performed. The local ledger and approved specification remain authoritative.
diff --git a/evidence/wave0/task3/fault-matrix.json b/evidence/wave0/task3/fault-matrix.json
new file mode 100644
index 0000000..965fb5a
--- /dev/null
+++ b/evidence/wave0/task3/fault-matrix.json
@@ -0,0 +1,26 @@
+{
+  "schema_version": 1,
+  "task": "wave0-task3-atomic-recovery",
+  "captured_at": "2026-07-11",
+  "fault_matrix": [
+    {"fault": "staging interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
+    {"fault": "validation interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
+    {"fault": "commit interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
+    {"fault": "manifest publication interruption", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
+    {"fault": "corrupt journal", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
+    {"fault": "staged checksum mismatch", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
+    {"fault": "missing staged payload", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
+    {"fault": "missing rollback backup", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
+    {"fault": "locked destination during rollback", "result": "recovery_required", "startup_mode": "read_only", "visible_generation": "not promoted"},
+    {"fault": "lingering verified committed journal", "result": "committed", "startup_mode": "normal", "visible_generation": "new complete"},
+    {"fault": "legacy schema-1 prepared journal", "result": "rolled_back", "startup_mode": "normal", "visible_generation": "old complete"},
+    {"fault": "clean restart", "result": "no recovery records", "startup_mode": "normal", "visible_generation": "unchanged"}
+  ],
+  "source_sha256": {
+    "src/etf_cockpit/core/atomic_io.py": "48a159c9cfbc1f53a67e89ec8f41a5eb5cc34c4c68bd2ad6bafb5f2258673bf0",
+    "src/etf_cockpit/core/migrations.py": "07b727bcca93cbb1bd854a7af7e1eaa1bd54982c203a3e5f09832f670fb51357",
+    "src/etf_cockpit/operations/models.py": "f16fb8acbdfbcf0968f46b625cc9f74b3a86ad94509407a698d1d2b964f3d6f9",
+    "src/etf_cockpit/operations/recovery.py": "0aacc2503be8f1875a41db56bbb7abde31bb57f7d9d9a854ff8eac2fad53a865"
+  },
+  "visual_evidence": "pending_later_task: Task 3 adds no user-visible surface; ISSUE-0040 UI/browser/package gates remain open"
+}
diff --git a/issues/github_issue_map.json b/issues/github_issue_map.json
new file mode 100644
index 0000000..c84ba1e
--- /dev/null
+++ b/issues/github_issue_map.json
@@ -0,0 +1,1483 @@
+{
+  "schema_version": "1.0",
+  "repository": "Thor2709/etf_ai_cockpit",
+  "generated_at_utc": "2026-07-11T07:32:46Z",
+  "source_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+  "local_ledger_policy": "One canonical record per stable ID. Explicit current status wins; dated closure records take precedence over retained historical notes. Headings without an explicit status are not issue records.",
+  "github_inventory": {
+    "open_count": 0,
+    "closed_count": 0,
+    "issues": []
+  },
+  "local_counts": {
+    "open": 77,
+    "closed": 21,
+    "unresolved": 0,
+    "records": 98
+  },
+  "unresolved_contradictions": [
+    {
+      "local_issue_id": "ISSUE-0067",
+      "reason": "closed_record_resides_in_open_file",
+      "selected_state": "closed",
+      "source_file": "issues/open.md",
+      "source_line": 136
+    },
+    {
+      "local_issue_id": "ISSUE-0069",
+      "reason": "historical_state_disagreement_resolved_by_dated_latest_record",
+      "selected_state": "closed",
+      "records": [
+        {
+          "source_file": "issues/open.md",
+          "source_line": 218,
+          "state": "closed",
+          "status": "Closed 2026-07-11; final evidence is recorded in `evidence/final/*-wave4.md`."
+        },
+        {
+          "source_file": "issues/closed.md",
+          "source_line": 580,
+          "state": "open",
+          "status": "Reopened 2026-07-10 after independent review; retained as a rejected closure checkpoint."
+        },
+        {
+          "source_file": "issues/closed.md",
+          "source_line": 616,
+          "state": "closed",
+          "status": "Closed 2026-07-11"
+        }
+      ]
+    },
+    {
+      "local_issue_id": "UPDATEV2-0010",
+      "reason": "closed_record_resides_in_open_file",
+      "selected_state": "closed",
+      "source_file": "issues/open.md",
+      "source_line": 283
+    },
+    {
+      "local_issue_id": "UPDATEV2-0022",
+      "reason": "historical_state_disagreement_resolved_by_dated_latest_record",
+      "selected_state": "closed",
+      "records": [
+        {
+          "source_file": "issues/open.md",
+          "source_line": 487,
+          "state": "open",
+          "status": "Open"
+        },
+        {
+          "source_file": "issues/closed.md",
+          "source_line": 588,
+          "state": "open",
+          "status": "Reopened 2026-07-10 after independent review; retained as a rejected closure checkpoint."
+        },
+        {
+          "source_file": "issues/closed.md",
+          "source_line": 626,
+          "state": "closed",
+          "status": "Closed 2026-07-11"
+        }
+      ]
+    },
+    {
+      "local_issue_id": "UPDATEV2-0028",
+      "reason": "historical_state_disagreement_resolved_by_dated_latest_record",
+      "selected_state": "closed",
+      "records": [
+        {
+          "source_file": "issues/open.md",
+          "source_line": 589,
+          "state": "open",
+          "status": "Open"
+        },
+        {
+          "source_file": "issues/closed.md",
+          "source_line": 596,
+          "state": "open",
+          "status": "Reopened 2026-07-10 after independent review; retained as a rejected closure checkpoint."
+        },
+        {
+          "source_file": "issues/closed.md",
+          "source_line": 634,
+          "state": "closed",
+          "status": "Closed 2026-07-11"
+        }
+      ]
+    }
+  ],
+  "records": [
+    {
+      "local_issue_id": "ISSUE-0001",
+      "title": "Create durable issue tracker and plan synchronisation",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:74",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Completed",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0002",
+      "title": "Add young/noisy evidence and too-good-to-be-true warnings",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:103",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Completed",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0003",
+      "title": "Add benchmark alpha/beta/regime attribution",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:138",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Completed",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0004",
+      "title": "Add hit-rate, payoff-ratio and expected-value diagnostics",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:176",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Completed",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0005",
+      "title": "Add friction/cost/slippage stress engine",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:212",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Completed",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0006",
+      "title": "Add explicit model/backtest contamination validity status",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:249",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Completed",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0007",
+      "title": "Add non-executable news/macro contradiction panel",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:657",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0008",
+      "title": "Add strategy taxonomy and scope/rejection matrix",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:674",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0009",
+      "title": "Add source-credibility scoring for imported research notes",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:283",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Completed",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0010",
+      "title": "Add non-executable LLM thesis diary",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:691",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0011",
+      "title": "Full main-UI button reliability audit",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:708",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0012",
+      "title": "Add visible progress/status indicators for long-running actions",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:726",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0013",
+      "title": "Rebuild package after every completed feature",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:744",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0014",
+      "title": "Add end-to-end workflow test",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:761",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0015",
+      "title": "Add app-level feature map / roadmap page",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:779",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0016",
+      "title": "Full product navigation redesign",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:796",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0017",
+      "title": "First-run onboarding and setup wizard",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:813",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0018",
+      "title": "Watchlist and universe manager",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:830",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0019",
+      "title": "Proper instrument detail page",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:847",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0020",
+      "title": "Screener and filter system",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:864",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0021",
+      "title": "Portfolio construction and allocation sandbox",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:881",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0022",
+      "title": "ETF overlap and look-through exposure engine",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:898",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0023",
+      "title": "Stock fundamentals quality module hardening",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:915",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0024",
+      "title": "Earnings, dividends and event calendar",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:932",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0025",
+      "title": "Free news and filings dashboard",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:949",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0026",
+      "title": "Macro regime dashboard",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:966",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0027",
+      "title": "Forecast lab page",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:983",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0028",
+      "title": "Backtest lab upgrade",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1000",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0029",
+      "title": "Strategy template builder",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1017",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0030",
+      "title": "Decision journal",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1034",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0031",
+      "title": "Paper trading module",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1051",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0032",
+      "title": "Future broker-execution architecture document only",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1068",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0033",
+      "title": "Alerts and review reminders",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1085",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0034",
+      "title": "What changed since last run page",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1102",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0035",
+      "title": "Data health centre",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:604",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Closed 2026-07-10",
+      "historical_record_count": 2
+    },
+    {
+      "local_issue_id": "ISSUE-0036",
+      "title": "Import/export centre",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1136",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0037",
+      "title": "Config editor UI",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1153",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0038",
+      "title": "Local database / storage migration plan",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1170",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0039",
+      "title": "Performance and caching audit",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1187",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0040",
+      "title": "Error handling and recovery centre",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1204",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0041",
+      "title": "Accessibility, responsive layout and table usability",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1221",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0042",
+      "title": "Charts, tables and CSV export improvements",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1238",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0043",
+      "title": "User manual, glossary and in-app explanations",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1255",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0044",
+      "title": "Backup, restore, version and changelog",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1272",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0045",
+      "title": "UI semantic locators and visual smoke tests",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1289",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0046",
+      "title": "Monthly decision template: basket vs benchmark vs cash",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1307",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0047",
+      "title": "Feature-driver explanations for every evidence component",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1324",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0048",
+      "title": "Strategy complexity and overfitting penalty metadata",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1341",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0049",
+      "title": "Worst-day, loss-cluster and tail-event diagnostics",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1358",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0050",
+      "title": "Operational evidence panel for next-open/decision-price realism",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1375",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0051",
+      "title": "Cash proxy and risk-free/defensive comparison everywhere relevant",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1392",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0052",
+      "title": "Correlation clustering and factor-crowding warnings",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1409",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0053",
+      "title": "What matters today digest",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1426",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0054",
+      "title": "Point-in-time news/sentiment validation rules",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1443",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0055",
+      "title": "Optional free provider research/stubs: SEC EDGAR, FRED, Stooq, RSS",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1460",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0056",
+      "title": "Data-frequency suitability and unsupported-asset guardrails",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1477",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0057",
+      "title": "Paper/forward evidence diary",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1494",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0058",
+      "title": "Closed-source/promotional-claim detector for imported notes",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1511",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0059",
+      "title": "Benchmark-relative sector/theme attribution beyond single benchmark beta",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1528",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0060",
+      "title": "Strategy rejection tests",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1545",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0061",
+      "title": "Pair-trading/cointegration research-only module",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1562",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0062",
+      "title": "Triple-barrier and purged-CV research-only module",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1579",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0063",
+      "title": "Close-based quality-momentum next-open template hardening",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1596",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0064",
+      "title": "Friction-adjusted return estimate per evidence score",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1613",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0065",
+      "title": "Payoff-profile classification and risk/reward asymmetry display",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1630",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0066",
+      "title": "Source-of-truth and reconciliation architecture for future execution",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1647",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0067",
+      "title": "Local score history and per-instrument score evolution mini charts",
+      "local_state": "closed",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:136",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Closed 2026-07-11; final evidence is recorded in `evidence/final/*-wave4.md`.",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0068",
+      "title": "Two-tier universe manager and provider policy editor",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:1664",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "ISSUE-0069",
+      "title": "Single-file session action logging and diagnostics trace",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:616",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Closed 2026-07-11",
+      "historical_record_count": 3
+    },
+    {
+      "local_issue_id": "REJECTED-0001",
+      "title": "Autonomous broker execution",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:318",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Rejected",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "REJECTED-0002",
+      "title": "Direct LLM portfolio management",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:326",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Rejected",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "REJECTED-0003",
+      "title": "Reinforcement-learning trading agents",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:334",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Rejected for current scope",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "REJECTED-0004",
+      "title": "Martingale and grid systems",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:342",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Rejected for current scope",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "REJECTED-0005",
+      "title": "Futures or intraday implementation now",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:350",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Deferred / research only",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "REJECTED-0006",
+      "title": "News sentiment as direct score authority",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:358",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Rejected",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "REJECTED-0007",
+      "title": "Short-sample return screenshots as evidence",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:366",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Rejected",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "REJECTED-0008",
+      "title": "Options, scalping, 0DTE, binary and crypto bot experiments unless separately scoped",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:374",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Rejected for current scope",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0010",
+      "title": "Provider registry, capability probes and source authority model (original update ISSUE-0010)",
+      "local_state": "closed",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:283",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Closed 2026-07-11; final evidence is recorded in `evidence/final/*-wave4.md`.",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0011",
+      "title": "Symbol/ISIN/exchange identity resolver (original update ISSUE-0011)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:300",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0012",
+      "title": "SEC EDGAR official statement importer (original update ISSUE-0012)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:317",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0013",
+      "title": "European ESEF/iXBRL filing importer (original update ISSUE-0013)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:334",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0014",
+      "title": "France DILA and Netherlands AFM OAM discovery adapters (original update ISSUE-0014)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:351",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0015",
+      "title": "ETF disclosure registry (original update ISSUE-0015)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:368",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0016",
+      "title": "ETF holdings normaliser (original update ISSUE-0016)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:385",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0017",
+      "title": "PRIIPs KID parser (original update ISSUE-0017)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:402",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0018",
+      "title": "ETF prospectus, annual and half-year report parser (original update ISSUE-0018)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:419",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0019",
+      "title": "Index methodology importer (original update ISSUE-0019)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:436",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0020",
+      "title": "SFDR disclosure parser (original update ISSUE-0020)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:453",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0021",
+      "title": "Source conflict resolver and canonical metric selector (original update ISSUE-0021)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:470",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0022",
+      "title": "Evidence ledger and score component audit trail",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:626",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Closed 2026-07-11",
+      "historical_record_count": 3
+    },
+    {
+      "local_issue_id": "UPDATEV2-0023",
+      "title": "FMP optional provider adapter (original update ISSUE-0023)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:504",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0024",
+      "title": "Alpha Vantage verification/fallback adapter (original update ISSUE-0024)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:521",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0025",
+      "title": "Finnhub experimental adapter with entitlement probes (original update ISSUE-0025)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:538",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0026",
+      "title": "Candle feature/context/backtest module (original update ISSUE-0026)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:555",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0027",
+      "title": "UI workflow/button reliability and progress indicators (original update ISSUE-0027)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:572",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0028",
+      "title": "Report/audit packet expansion for providers, filings, ETF docs and candles",
+      "local_state": "closed",
+      "source_file": "issues/closed.md",
+      "source_location": "issues/closed.md:634",
+      "source_checksum": "a39bc5d29bfe7ad3eb5cc61cff877286571a952ae5c07c8a8a6e8756f1fa60b3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Closed 2026-07-11",
+      "historical_record_count": 3
+    },
+    {
+      "local_issue_id": "UPDATEV2-0029",
+      "title": "Rebuild/test/update discipline automation (original update ISSUE-0029)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:606",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    },
+    {
+      "local_issue_id": "UPDATEV2-0030",
+      "title": "Optional OHLCV fallback providers: Stooq, Twelve Data and Tiingo (original update ISSUE-0030)",
+      "local_state": "open",
+      "source_file": "issues/open.md",
+      "source_location": "issues/open.md:623",
+      "source_checksum": "767cbc1d9f9d16c29ac32eaacbd29b6a63f7179bd1f616e3f44a9ae41cbe68d3",
+      "github_issue_number": null,
+      "github_url": null,
+      "github_state": null,
+      "last_synchronised_commit": "445dd44b5382160d4e93e4cada018beb4ab0f5b5",
+      "local_status_text": "Open",
+      "historical_record_count": 1
+    }
+  ]
+}
diff --git a/src/etf_cockpit/core/atomic_io.py b/src/etf_cockpit/core/atomic_io.py
index 1e350da..f502262 100644
--- a/src/etf_cockpit/core/atomic_io.py
+++ b/src/etf_cockpit/core/atomic_io.py
@@ -38,20 +38,24 @@ class BackupManifest:
     manifest_path: Path
 
 
 @dataclass(frozen=True)
 class AtomicWriteRequest:
     destination: Path
     payload: bytes
     validator: Callable[[Path], None]
 
 
+class AtomicWriteInterrupted(RuntimeError):
+    """Fault-injection signal that preserves the durable journal for startup recovery."""
+
+
 def sha256_file(path: Path) -> str:
     digest = hashlib.sha256()
     with path.open("rb") as handle:
         for chunk in iter(lambda: handle.read(1024 * 1024), b""):
             digest.update(chunk)
     return digest.hexdigest()
 
 
 def atomic_write_bytes(
     destination: Path,
@@ -79,38 +83,39 @@ def atomic_write_bytes(
             destination=destination,
             sha256=hashlib.sha256(payload).hexdigest(),
             bytes_written=len(payload),
             replaced_existing=replaced_existing,
         )
     finally:
         if temp_path is not None:
             temp_path.unlink(missing_ok=True)
 
 
-def _stage_request(request: AtomicWriteRequest) -> Path:
+def _stage_request(request: AtomicWriteRequest, *, validate: bool = True) -> Path:
     request.destination.parent.mkdir(parents=True, exist_ok=True)
     with tempfile.NamedTemporaryFile(
         mode="wb",
         dir=request.destination.parent,
         prefix=f".{request.destination.name}.",
         suffix=".group.tmp",
         delete=False,
     ) as handle:
         path = Path(handle.name)
         handle.write(request.payload)
         handle.flush()
         os.fsync(handle.fileno())
-    try:
-        request.validator(path)
-    except Exception:
-        path.unlink(missing_ok=True)
-        raise
+    if validate:
+        try:
+            request.validator(path)
+        except Exception:
+            path.unlink(missing_ok=True)
+            raise
     return path
 
 
 def _pid_alive(pid: int) -> bool:
     if pid <= 0:
         return False
     try:
         os.kill(pid, 0)
         return True
     except OSError:
@@ -220,87 +225,134 @@ def wait_for_atomic_group(path: Path, timeout_seconds: float = 5.0) -> None:
     lock = path.parent / ".atomic-write-group.lock"
     deadline = time.monotonic() + timeout_seconds
     while lock.exists():
         if _recover_lock(lock):
             continue
         if time.monotonic() >= deadline:
             raise TimeoutError(f"timed out waiting for atomic write transaction: {lock}")
         time.sleep(0.025)
 
 
-def atomic_write_group(requests: Iterable[AtomicWriteRequest]) -> tuple[AtomicWriteResult, ...]:
+def atomic_write_group(
+    requests: Iterable[AtomicWriteRequest],
+    *,
+    lifecycle_hook: Callable[[str, Path], None] | None = None,
+) -> tuple[AtomicWriteResult, ...]:
     request_tuple = tuple(requests)
     if not request_tuple:
         return ()
     destinations = [request.destination.resolve() for request in request_tuple]
     if len(destinations) != len(set(destinations)):
         raise ValueError("atomic write group destinations must be unique")
     parents = tuple(sorted({request.destination.parent.resolve() for request in request_tuple}, key=str))
     common_root = Path(os.path.commonpath([str(parent) for parent in parents]))
     transaction_root = common_root / ".atomic-transactions" / uuid.uuid4().hex
     transaction_root.mkdir(parents=True, exist_ok=False)
     journal_path = transaction_root / "journal.json"
     staged: dict[Path, Path] = {}
     previous: dict[Path, bytes | None] = {}
     entries: list[dict[str, object]] = []
     locks: tuple[Path, ...] = ()
-    journal_payload: dict[str, object] = {}
+    now = datetime.now(timezone.utc).isoformat()
+    journal_payload: dict[str, object] = {
+        "schema_version": 2,
+        "transaction_id": transaction_root.name,
+        "workflow_run_id": "",
+        "transaction_type": "atomic_write_group",
+        "owner_pid": os.getpid(),
+        "state": "staging",
+        "affected_dataset_ids": [str(path) for path in destinations],
+        "base_generations": {},
+        "entries": entries,
+        "staged_paths": [],
+        "lock_paths": [],
+        "expected_checksums": {
+            str(request.destination.resolve()): hashlib.sha256(request.payload).hexdigest()
+            for request in request_tuple
+        },
+        "started_at": now,
+        "updated_at": now,
+        "committed_at": None,
+        "recovery_instructions": (
+            "On interrupted startup, verify journal and payload checksums, then restore the "
+            "previous complete generation. Never promote ambiguous staging data."
+        ),
+    }
+    interrupted = False
+
+    def publish_state(state: str) -> None:
+        journal_payload["state"] = state
+        journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
+        if state == "committed":
+            journal_payload["committed_at"] = journal_payload["updated_at"]
+        _write_journal(journal_path, journal_payload)
+        if lifecycle_hook is not None:
+            lifecycle_hook(state, journal_path)
+
     try:
+        _write_journal(journal_path, journal_payload)
+        if lifecycle_hook is not None:
+            lifecycle_hook("staging", journal_path)
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
-            staged[request.destination] = _stage_request(request)
+            staged[request.destination] = _stage_request(request, validate=False)
             entries.append(
                 {
                     "destination": str(request.destination.resolve()),
                     "backup_path": str(backup_path.resolve()) if backup_path else None,
                     "previous_sha256": hashlib.sha256(original).hexdigest() if original is not None else None,
+                    "staged_path": str(staged[request.destination].resolve()),
+                    "expected_sha256": hashlib.sha256(request.payload).hexdigest(),
                 }
             )
+            journal_payload["staged_paths"] = [str(path.resolve()) for path in staged.values()]
+            journal_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
+            _write_journal(journal_path, journal_payload)
+        publish_state("validating")
+        for request in request_tuple:
+            request.validator(staged[request.destination])
         lock_paths = [str((parent / ".atomic-write-group.lock").resolve()) for parent in parents]
-        journal_payload = {
-            "schema_version": 1,
-            "transaction_id": transaction_root.name,
-            "owner_pid": os.getpid(),
-            "state": "prepared",
-            "entries": entries,
-            "staged_paths": [str(path.resolve()) for path in staged.values()],
-            "lock_paths": lock_paths,
-        }
-        _write_journal(journal_path, journal_payload)
+        journal_payload["lock_paths"] = lock_paths
+        publish_state("committing")
         locks = _acquire_group_locks(parents, journal_path)
         for request in request_tuple:
             staged[request.destination].replace(request.destination)
-        journal_payload["state"] = "committed"
-        _write_journal(journal_path, journal_payload)
+        publish_state("manifest_publish")
+        publish_state("committed")
         return tuple(
             AtomicWriteResult(
                 destination=request.destination,
                 sha256=hashlib.sha256(request.payload).hexdigest(),
                 bytes_written=len(request.payload),
                 replaced_existing=previous[request.destination] is not None,
             )
             for request in request_tuple
         )
+    except AtomicWriteInterrupted:
+        interrupted = True
+        raise
     except Exception:
         if journal_path.is_file():
             _recover_journal(journal_path, force=True)
         raise
     finally:
-        if journal_path.is_file():
+        if interrupted:
+            pass
+        elif journal_path.is_file():
             _cleanup_transaction(journal_payload, journal_path)
         else:
             for path in staged.values():
                 path.unlink(missing_ok=True)
             for lock in locks:
                 lock.unlink(missing_ok=True)
             shutil.rmtree(transaction_root, ignore_errors=True)
 
 
 def atomic_write_json(destination: Path, payload: object) -> AtomicWriteResult:
diff --git a/src/etf_cockpit/core/migrations.py b/src/etf_cockpit/core/migrations.py
index c1b3227..7d537d3 100644
--- a/src/etf_cockpit/core/migrations.py
+++ b/src/etf_cockpit/core/migrations.py
@@ -83,20 +83,27 @@ MIGRATIONS = (
 def _load_state(path: Path) -> dict[str, object]:
     if not path.is_file():
         return {"schema_version": 0, "applied": []}
     payload = json.loads(path.read_text(encoding="utf-8"))
     if not isinstance(payload.get("applied"), list):
         raise ValueError("migration state applied field must be a list")
     return payload
 
 
 def run_migrations(context: MigrationContext) -> MigrationReport:
+    from etf_cockpit.operations.recovery import recover_incomplete_transactions
+
+    recovery_results = recover_incomplete_transactions(context.root)
+    blocked = [result for result in recovery_results if result.state == "recovery_required"]
+    if blocked:
+        reasons = "; ".join(result.reason for result in blocked)
+        raise OSError(f"migration blocked by incomplete atomic transaction: {reasons}")
     state = _load_state(context.state_path)
     current_version = int(state.get("schema_version", 0))
     pending = tuple(migration for migration in MIGRATIONS if migration.version > current_version)
     if not pending:
         return MigrationReport((), current_version, None, context.state_path)
 
     migration_paths = tuple(context.metadata_root / f"{migration.name}.json" for migration in pending)
     protected_paths = tuple(dict.fromkeys((*context.managed_paths, context.state_path, *migration_paths)))
     existing_paths = tuple(path for path in protected_paths if path.is_file())
     absent_paths = tuple(path for path in protected_paths if not path.exists())
diff --git a/src/etf_cockpit/operations/models.py b/src/etf_cockpit/operations/models.py
index 66a9b2c..bd35ac4 100644
--- a/src/etf_cockpit/operations/models.py
+++ b/src/etf_cockpit/operations/models.py
@@ -1,16 +1,16 @@
 from __future__ import annotations
 
 from datetime import datetime
 from typing import Literal, Self
 
-from pydantic import BaseModel, ConfigDict, model_validator
+from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
 
 
 class OperationalEvent(BaseModel):
     """Typed projection of one row in the authoritative session trace."""
 
     model_config = ConfigDict(extra="allow")
 
     event_id: str = ""
     session_id: str
     sequence_number: int
@@ -52,10 +52,56 @@ class ClosureEvidenceRecord(BaseModel):
             self.independent_reviewer = self.independent_reviewer.strip()
             if not self.builder:
                 raise ValueError("builder must be non-empty for approved closure evidence")
             if not self.independent_reviewer:
                 raise ValueError(
                     "independent_reviewer must be non-empty for approved closure evidence"
                 )
             if self.builder == self.independent_reviewer:
                 raise ValueError("independent_reviewer must differ from builder")
         return self
+
+
+WriteTransactionStatus = Literal[
+    "started",
+    "staging",
+    "validating",
+    "ready_to_commit",
+    "committing",
+    "committed",
+    "rolling_back",
+    "rolled_back",
+    "recovery_required",
+    "quarantined",
+]
+
+
+class WriteTransaction(BaseModel):
+    """Durable projection of the existing atomic grouped-write journal."""
+
+    transaction_id: str
+    workflow_run_id: str
+    transaction_type: str
+    model_config = ConfigDict(populate_by_name=True)
+
+    affected_dataset_ids: list[str] = Field(
+        validation_alias=AliasChoices("affected_dataset_ids", "affected_datasets")
+    )
+    base_generations: dict[str, str]
+    staging_paths: dict[str, str]
+    final_paths: dict[str, str]
+    expected_checksums: dict[str, str]
+    status: WriteTransactionStatus
+    started_at: datetime = Field(validation_alias=AliasChoices("started_at", "created_at"))
+    updated_at: datetime
+    committed_at: datetime | None = None
+    recovery_instructions: str
+
+    @property
+    def affected_datasets(self) -> list[str]:
+        """Compatibility alias for the pre-approval Task 3 draft name."""
+        return self.affected_dataset_ids
+
+    @property
+    def created_at(self) -> datetime:
+        """Compatibility alias for the pre-approval Task 3 draft name."""
+        return self.started_at
diff --git a/src/etf_cockpit/operations/recovery.py b/src/etf_cockpit/operations/recovery.py
new file mode 100644
index 0000000..2926115
--- /dev/null
+++ b/src/etf_cockpit/operations/recovery.py
@@ -0,0 +1,250 @@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from datetime import datetime, timezone
+import hashlib
+import json
+from pathlib import Path
+import uuid
+
+from pydantic import ValidationError
+
+from etf_cockpit.core import atomic_io
+from etf_cockpit.core.paths import ROOT
+from etf_cockpit.core.session_log import append_event
+from etf_cockpit.operations.models import WriteTransaction
+
+
+@dataclass(frozen=True)
+class RecoveryResult:
+    transaction_id: str
+    state: str
+    startup_mode: str
+    reason: str
+    journal_path: Path
+    evidence_checksums: dict[str, str]
+
+
+def _transaction_root(data_root: Path, transaction_id: str) -> Path:
+    return data_root / ".atomic-transactions" / transaction_id
+
+
+def _journal_path(data_root: Path, transaction_id: str) -> Path:
+    return _transaction_root(data_root, transaction_id) / "journal.json"
+
+
+def _resolved_data_root(data_root: Path | None) -> Path:
+    return data_root if data_root is not None else ROOT / "data"
+
+
+def _now() -> datetime:
+    return datetime.now(timezone.utc)
+
+
+def _record_from_payload(payload: dict[str, object]) -> WriteTransaction:
+    return WriteTransaction(
+        transaction_id=str(payload["transaction_id"]),
+        workflow_run_id=str(payload.get("workflow_run_id", "")),
+        transaction_type=str(payload.get("transaction_type", "atomic_write_group")),
+        affected_dataset_ids=[str(item) for item in payload.get("affected_dataset_ids", payload.get("affected_datasets", []))],
+        base_generations={str(key): str(value) for key, value in dict(payload.get("base_generations", {})).items()},
+        staging_paths={str(key): str(value) for key, value in dict(payload.get("staging_paths_by_dataset", {})).items()},
+        final_paths={str(key): str(value) for key, value in dict(payload.get("final_paths", {})).items()},
+        expected_checksums={str(key): str(value) for key, value in dict(payload.get("expected_checksums", {})).items()},
+        status=str(payload.get("state", "recovery_required")),
+        started_at=payload.get("started_at", payload.get("created_at", _now())),
+        updated_at=payload.get("updated_at", _now()),
+        committed_at=payload.get("committed_at"),
+        recovery_instructions=str(payload.get("recovery_instructions", "Manual review required.")),
+    )
+
+
+def begin_write_transaction(
+    *,
+    transaction_type: str,
+    base_generations: dict[str, str],
+    data_root: Path | None = None,
+    workflow_run_id: str = "",
+    affected_datasets: list[str] | None = None,
+    staging_paths: dict[str, str] | None = None,
+    final_paths: dict[str, str] | None = None,
+) -> WriteTransaction:
+    transaction_id = uuid.uuid4().hex
+    now = _now()
+    record = WriteTransaction(
+        transaction_id=transaction_id,
+        workflow_run_id=workflow_run_id,
+        transaction_type=transaction_type,
+        affected_dataset_ids=list(affected_datasets or base_generations),
+        base_generations=base_generations,
+        staging_paths=staging_paths or {},
+        final_paths=final_paths or {},
+        expected_checksums={},
+        status="started",
+        started_at=now,
+        updated_at=now,
+        recovery_instructions=(
+            "Verify all expected checksums before activation; on ambiguity remain read-only "
+            "and request manual recovery."
+        ),
+    )
+    path = _journal_path(_resolved_data_root(data_root), transaction_id)
+    path.parent.mkdir(parents=True, exist_ok=False)
+    payload = record.model_dump(mode="json")
+    payload.update(
+        schema_version=2,
+        state=record.status,
+        owner_pid=__import__("os").getpid(),
+        entries=[],
+        staged_paths=list(record.staging_paths.values()),
+        staging_paths_by_dataset=record.staging_paths,
+        lock_paths=[],
+    )
+    atomic_io._write_journal(path, payload)
+    return record
+
+
+def mark_transaction_ready(
+    transaction_id: str,
+    checksums: dict[str, str],
+    *,
+    data_root: Path | None = None,
+) -> WriteTransaction:
+    path = _journal_path(_resolved_data_root(data_root), transaction_id)
+    payload = json.loads(path.read_text(encoding="utf-8"))
+    payload["state"] = "ready_to_commit"
+    payload["status"] = "ready_to_commit"
+    payload["expected_checksums"] = dict(checksums)
+    payload["updated_at"] = _now().isoformat()
+    atomic_io._write_journal(path, payload)
+    return _record_from_payload(payload)
+
+
+def _required_result(journal: Path, transaction_id: str, reason: str) -> RecoveryResult:
+    return RecoveryResult(transaction_id, "recovery_required", "read_only", reason, journal, {})
+
+
+def _validate_v2_payload(payload: dict[str, object]) -> str | None:
+    state = str(payload.get("state", ""))
+    for entry_value in payload.get("entries", []):
+        entry = dict(entry_value)
+        backup_value = entry.get("backup_path")
+        previous_checksum = entry.get("previous_sha256")
+        if backup_value:
+            backup = Path(str(backup_value))
+            if not backup.is_file():
+                return f"missing rollback backup: {backup}"
+            if previous_checksum and atomic_io.sha256_file(backup) != str(previous_checksum):
+                return f"rollback backup checksum mismatch: {backup}"
+        staged_value = entry.get("staged_path")
+        expected_checksum = entry.get("expected_sha256")
+        if staged_value and Path(str(staged_value)).is_file():
+            if expected_checksum and atomic_io.sha256_file(Path(str(staged_value))) != str(expected_checksum):
+                return f"staged payload checksum mismatch: {staged_value}"
+        elif state in {"staging", "validating", "ready", "ready_to_commit"} and staged_value:
+            return f"missing staged payload: {staged_value}"
+        if state == "committed":
+            destination = Path(str(entry.get("destination", "")))
+            if not destination.is_file():
+                return f"missing committed payload: {destination}"
+            if expected_checksum and atomic_io.sha256_file(destination) != str(expected_checksum):
+                return f"committed payload checksum mismatch: {destination}"
+    return None
+
+
+def _emit_recovery_event(result: RecoveryResult, event_path: Path | None) -> None:
+    if event_path is None:
+        return
+    sequence = 1
+    if event_path.is_file():
+        sequence += len(event_path.read_text(encoding="utf-8", errors="replace").splitlines())
+    append_event(
+        {
+            "session_id": "startup-recovery",
+            "sequence_number": sequence,
+            "timestamp_utc": _now().isoformat(),
+            "event_type": "write_transaction_recovery",
+            "status": result.state,
+            "component": "operations.recovery",
+            "action_id": result.transaction_id,
+            "transaction_id": result.transaction_id,
+            "startup_mode": result.startup_mode,
+            "reason": result.reason,
+            "evidence_checksums": result.evidence_checksums,
+        },
+        path=event_path,
+    )
+
+
+def recover_incomplete_transactions(
+    data_root: Path,
+    *,
+    event_path: Path | None = None,
+) -> list[RecoveryResult]:
+    direct_root = data_root / ".atomic-transactions"
+    roots = [direct_root] if direct_root.is_dir() else []
+    if data_root.is_dir():
+        roots.extend(
+            sorted(
+                (
+                    item / ".atomic-transactions"
+                    for item in data_root.iterdir()
+                    if item.is_dir() and (item / ".atomic-transactions").is_dir()
+                ),
+                key=str,
+            )
+        )
+    if not roots:
+        return []
+    results: list[RecoveryResult] = []
+    transaction_roots = sorted(
+        (item for root in roots for item in root.iterdir() if item.is_dir()), key=str
+    )
+    for transaction_root in transaction_roots:
+        journal = transaction_root / "journal.json"
+        try:
+            raw = journal.read_bytes()
+            payload = json.loads(raw.decode("utf-8"))
+        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
+            result = _required_result(journal, transaction_root.name, f"corrupt journal: {exc}")
+            results.append(result)
+            _emit_recovery_event(result, event_path)
+            continue
+        transaction_id = str(payload.get("transaction_id", transaction_root.name))
+        journal_state = str(payload.get("state", ""))
+        if int(payload.get("schema_version", 1)) >= 2:
+            error = _validate_v2_payload(payload)
+            if error:
+                result = _required_result(journal, transaction_id, error)
+                results.append(result)
+                _emit_recovery_event(result, event_path)
+                continue
+        try:
+            recovered = atomic_io._recover_journal(journal, force=True)
+        except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
+            result = _required_result(journal, transaction_id, f"rollback failed: {exc}")
+            results.append(result)
+            _emit_recovery_event(result, event_path)
+            continue
+        if not recovered:
+            result = _required_result(journal, transaction_id, "journal could not be recovered")
+            results.append(result)
+            _emit_recovery_event(result, event_path)
+            continue
+        result_state = "committed" if journal_state == "committed" else "rolled_back"
+        reason = (
+            "verified committed generation retained"
+            if result_state == "committed"
+            else "previous complete generation restored"
+        )
+        result = RecoveryResult(
+            transaction_id,
+            result_state,
+            "normal",
+            reason,
+            journal,
+            {"journal_sha256": hashlib.sha256(raw).hexdigest()},
+        )
+        results.append(result)
+        _emit_recovery_event(result, event_path)
+    return results
diff --git a/tests/operations/test_backups.py b/tests/operations/test_backups.py
new file mode 100644
index 0000000..1c28f9b
--- /dev/null
+++ b/tests/operations/test_backups.py
@@ -0,0 +1,22 @@
+from __future__ import annotations
+
+import json
+from pathlib import Path
+
+import pytest
+
+from etf_cockpit.core.atomic_io import backup_paths, restore_backup_manifest, verify_backup_manifest
+
+
+def test_backup_manifest_is_checksum_evidence_and_tampering_blocks_restore(tmp_path: Path) -> None:
+    source = tmp_path / "data" / "canonical.json"
+    source.parent.mkdir(parents=True)
+    source.write_text('{"generation": "old"}', encoding="utf-8")
+    manifest = backup_paths((source,), tmp_path / "backups")
+    evidence = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
+
+    assert evidence["entries"][0]["sha256"] == manifest.entries[0].sha256
+    manifest.entries[0].backup_path.write_text("tampered", encoding="utf-8")
+    assert verify_backup_manifest(manifest) is False
+    with pytest.raises(OSError, match="invalid backup manifest"):
+        restore_backup_manifest(manifest)
diff --git a/tests/operations/test_recovery.py b/tests/operations/test_recovery.py
new file mode 100644
index 0000000..53d8c86
--- /dev/null
+++ b/tests/operations/test_recovery.py
@@ -0,0 +1,203 @@
+from __future__ import annotations
+
+import hashlib
+import json
+from pathlib import Path
+
+import pytest
+
+from etf_cockpit.core import atomic_io
+from etf_cockpit.core.migrations import MigrationContext, run_migrations
+
+
+def _recover(data_root: Path):
+    try:
+        recovery = __import__("etf_cockpit.operations.recovery", fromlist=["recover_incomplete_transactions"])
+    except ModuleNotFoundError:
+        return []
+    return recovery.recover_incomplete_transactions(data_root)
+
+
+def _interrupted_transaction(tmp_path: Path, state: str, *, corrupt_payload: bool = False) -> Path:
+    destination = tmp_path / "data" / "current.bin"
+    destination.parent.mkdir(parents=True)
+    destination.write_bytes(b"old")
+    transaction_root = tmp_path / ".atomic-transactions" / f"tx-{state}"
+    transaction_root.mkdir(parents=True)
+    backup = transaction_root / "backup-0.bin"
+    backup.write_bytes(b"old")
+    staged = destination.parent / ".current.bin.interrupted.group.tmp"
+    staged.write_bytes(b"corrupt" if corrupt_payload else b"new")
+    if state in {"committing", "manifest_publish"}:
+        destination.write_bytes(b"new")
+    journal = transaction_root / "journal.json"
+    journal.write_text(
+        json.dumps(
+            {
+                "schema_version": 2,
+                "transaction_id": f"tx-{state}",
+                "workflow_run_id": "workflow-1",
+                "transaction_type": "canonical_refresh",
+                "owner_pid": 999999,
+                "state": state,
+                "affected_datasets": ["canonical"],
+                "base_generations": {"canonical": "generation-old"},
+                "entries": [
+                    {
+                        "destination": str(destination.resolve()),
+                        "backup_path": str(backup.resolve()),
+                        "previous_sha256": hashlib.sha256(b"old").hexdigest(),
+                        "staged_path": str(staged.resolve()),
+                        "expected_sha256": hashlib.sha256(b"new").hexdigest(),
+                    }
+                ],
+                "staged_paths": [str(staged.resolve())],
+                "lock_paths": [],
+                "expected_checksums": {
+                    str(destination.resolve()): hashlib.sha256(b"new").hexdigest()
+                },
+                "recovery_instructions": "Restore the previous complete generation.",
+            }
+        ),
+        encoding="utf-8",
+    )
+    return destination
+
+
+@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
+def test_recovery_exposes_old_complete_generation_after_every_interruption(
+    tmp_path: Path, crash_point: str
+) -> None:
+    destination = _interrupted_transaction(tmp_path, crash_point)
+
+    outcome = _recover(tmp_path)
+
+    assert outcome[0].state == "rolled_back"
+    assert outcome[0].startup_mode == "normal"
+    assert destination.read_bytes() == b"old"
+    assert _recover(tmp_path) == []
+
+
+def test_corrupt_journal_requires_read_only_manual_recovery(tmp_path: Path) -> None:
+    transaction_root = tmp_path / ".atomic-transactions" / "broken"
+    transaction_root.mkdir(parents=True)
+    (transaction_root / "journal.json").write_text('{"transaction_id":', encoding="utf-8")
+
+    outcome = _recover(tmp_path)
+
+    assert outcome[0].state == "recovery_required"
+    assert outcome[0].startup_mode == "read_only"
+    assert "journal" in outcome[0].reason.lower()
+
+
+@pytest.mark.parametrize("damage", ["checksum", "missing_payload", "missing_backup"])
+def test_corrupt_or_incomplete_transaction_is_not_promoted(tmp_path: Path, damage: str) -> None:
+    state = "staging" if damage == "missing_payload" else "committing"
+    destination = _interrupted_transaction(tmp_path, state, corrupt_payload=damage == "checksum")
+    transaction_root = tmp_path / ".atomic-transactions" / f"tx-{state}"
+    payload = json.loads((transaction_root / "journal.json").read_text(encoding="utf-8"))
+    if damage == "missing_payload":
+        Path(payload["entries"][0]["staged_path"]).unlink()
+    elif damage == "missing_backup":
+        Path(payload["entries"][0]["backup_path"]).unlink()
+
+    outcome = _recover(tmp_path)
+
+    assert outcome[0].state == "recovery_required"
+    assert outcome[0].startup_mode == "read_only"
+    assert destination.read_bytes() in {b"old", b"new"}
+    assert transaction_root.exists()
+
+
+def test_legacy_v1_prepared_journal_remains_recoverable(tmp_path: Path) -> None:
+    destination = tmp_path / "data" / "legacy.bin"
+    destination.parent.mkdir(parents=True)
+    destination.write_bytes(b"new")
+    root = tmp_path / ".atomic-transactions" / "legacy"
+    root.mkdir(parents=True)
+    backup = root / "backup.bin"
+    backup.write_bytes(b"old")
+    (root / "journal.json").write_text(
+        json.dumps(
+            {
+                "schema_version": 1,
+                "transaction_id": "legacy",
+                "owner_pid": 999999,
+                "state": "prepared",
+                "entries": [{
+                    "destination": str(destination.resolve()),
+                    "backup_path": str(backup.resolve()),
+                    "previous_sha256": hashlib.sha256(b"old").hexdigest(),
+                }],
+                "staged_paths": [],
+                "lock_paths": [],
+            }
+        ),
+        encoding="utf-8",
+    )
+
+    outcome = _recover(tmp_path)
+
+    assert outcome[0].state == "rolled_back"
+    assert destination.read_bytes() == b"old"
+
+
+def test_permission_failure_during_rollback_requires_manual_read_only_recovery(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    _interrupted_transaction(tmp_path, "committing")
+
+    def denied(*_args, **_kwargs):
+        raise PermissionError("locked destination")
+
+    monkeypatch.setattr(atomic_io, "atomic_write_bytes", denied)
+    outcome = _recover(tmp_path)
+
+    assert outcome[0].state == "recovery_required"
+    assert outcome[0].startup_mode == "read_only"
+    assert "locked destination" in outcome[0].reason
+
+
+def test_clean_restart_has_no_recovery_results(tmp_path: Path) -> None:
+    assert _recover(tmp_path) == []
+
+
+def test_recovery_outcome_is_visible_in_the_authoritative_operational_trace(tmp_path: Path) -> None:
+    _interrupted_transaction(tmp_path, "validating")
+    event_path = tmp_path / "logs" / "session.jsonl"
+    recovery = __import__("etf_cockpit.operations.recovery", fromlist=["recover_incomplete_transactions"])
+
+    recovery.recover_incomplete_transactions(tmp_path, event_path=event_path)
+
+    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
+    assert event["event_type"] == "write_transaction_recovery"
+    assert event["status"] == "rolled_back"
+    assert event["transaction_id"] == "tx-validating"
+    assert event["event_hash"]
+
+
+def test_migration_recovers_interrupted_atomic_write_before_schema_changes(tmp_path: Path) -> None:
+    destination = _interrupted_transaction(tmp_path, "committing")
+    context = MigrationContext(tmp_path, tmp_path / "backups")
+
+    report = run_migrations(context)
+
+    assert report.current_version == 4
+    assert destination.read_bytes() == b"old"
+
+
+def test_lingering_committed_journal_keeps_verified_new_generation(tmp_path: Path) -> None:
+    destination = _interrupted_transaction(tmp_path, "manifest_publish")
+    root = tmp_path / ".atomic-transactions" / "tx-manifest_publish"
+    journal = root / "journal.json"
+    payload = json.loads(journal.read_text(encoding="utf-8"))
+    payload["state"] = "committed"
+    Path(payload["entries"][0]["staged_path"]).unlink()
+    journal.write_text(json.dumps(payload), encoding="utf-8")
+
+    outcome = _recover(tmp_path)
+
+    assert outcome[0].state == "committed"
+    assert outcome[0].startup_mode == "normal"
+    assert destination.read_bytes() == b"new"
+    assert not root.exists()
diff --git a/tests/operations/test_transactions.py b/tests/operations/test_transactions.py
new file mode 100644
index 0000000..421b9ef
--- /dev/null
+++ b/tests/operations/test_transactions.py
@@ -0,0 +1,128 @@
+from __future__ import annotations
+
+import hashlib
+import json
+from pathlib import Path
+
+import pytest
+
+from etf_cockpit.core import atomic_io
+
+
+def _request(path: Path, payload: bytes) -> atomic_io.AtomicWriteRequest:
+    return atomic_io.AtomicWriteRequest(path, payload, lambda staged: staged.read_bytes())
+
+
+def test_grouped_write_journal_exposes_durable_transaction_identity_and_lifecycle(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    observed: list[dict[str, object]] = []
+    real_write = atomic_io._write_journal
+
+    def capture(path: Path, payload: dict[str, object]) -> None:
+        observed.append(json.loads(json.dumps(payload)))
+        real_write(path, payload)
+
+    monkeypatch.setattr(atomic_io, "_write_journal", capture)
+    destination = tmp_path / "data" / "canonical.bin"
+
+    atomic_io.atomic_write_group((_request(destination, b"new"),))
+
+    assert {str(item["state"]) for item in observed} >= {
+        "staging",
+        "validating",
+        "committing",
+        "manifest_publish",
+        "committed",
+    }
+    assert len({str(item["transaction_id"]) for item in observed}) == 1
+    committed = observed[-1]
+    assert committed["expected_checksums"] == {
+        str(destination.resolve()): hashlib.sha256(b"new").hexdigest()
+    }
+    assert committed["recovery_instructions"]
+
+
+def test_transaction_model_carries_the_approved_recovery_fields() -> None:
+    model = getattr(__import__("etf_cockpit.operations.models", fromlist=["WriteTransaction"]), "WriteTransaction", None)
+    assert model is not None
+    fields = set(model.model_fields)
+    assert {
+        "transaction_id",
+        "workflow_run_id",
+        "transaction_type",
+        "affected_dataset_ids",
+        "base_generations",
+        "staging_paths",
+        "final_paths",
+        "expected_checksums",
+        "status",
+        "started_at",
+        "updated_at",
+        "committed_at",
+        "recovery_instructions",
+    } <= fields
+
+
+def test_begin_and_ready_lifecycle_is_durable_in_the_atomic_journal(tmp_path: Path) -> None:
+    try:
+        recovery = __import__("etf_cockpit.operations.recovery", fromlist=["begin_write_transaction"])
+    except ModuleNotFoundError:
+        pytest.fail("transaction lifecycle API is absent")
+
+    transaction = recovery.begin_write_transaction(
+        data_root=tmp_path,
+        transaction_type="canonical_refresh",
+        workflow_run_id="workflow-1",
+        affected_datasets=["canonical"],
+        base_generations={"canonical": "generation-old"},
+        final_paths={"canonical": str(tmp_path / "data" / "canonical.bin")},
+    )
+    ready = recovery.mark_transaction_ready(
+        transaction.transaction_id,
+        {"canonical": hashlib.sha256(b"new").hexdigest()},
+        data_root=tmp_path,
+    )
+    journal = tmp_path / ".atomic-transactions" / transaction.transaction_id / "journal.json"
+    durable = json.loads(journal.read_text(encoding="utf-8"))
+
+    assert ready.status == "ready_to_commit"
+    assert durable["transaction_id"] == transaction.transaction_id
+    assert durable["state"] == "ready_to_commit"
+    assert durable["expected_checksums"] == ready.expected_checksums
+
+
+@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
+def test_real_group_interruption_leaves_one_existing_journal_for_startup_recovery(
+    tmp_path: Path, crash_point: str
+) -> None:
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
+    journals = list(tmp_path.rglob(".atomic-transactions/*/journal.json"))
+    assert len(journals) == 1
+    assert json.loads(journals[0].read_text(encoding="utf-8"))["state"] == crash_point
+
+
+def test_concurrent_writer_times_out_without_changing_previous_value(tmp_path: Path) -> None:
+    destination = tmp_path / "data" / "canonical.bin"
+    destination.parent.mkdir(parents=True)
+    destination.write_bytes(b"old")
+    lock = destination.parent / ".atomic-write-group.lock"
+    lock.write_text(
+        json.dumps({"owner_pid": __import__("os").getpid(), "journal_path": "active"}),
+        encoding="utf-8",
+    )
+
+    with pytest.raises(TimeoutError):
+        atomic_io.wait_for_atomic_group(destination, timeout_seconds=0.01)
+
+    assert destination.read_bytes() == b"old"
