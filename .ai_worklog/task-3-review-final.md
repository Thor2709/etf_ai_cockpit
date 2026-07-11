# Wave 0 Task 3 - independent final review

Date: 2026-07-11
Reviewer role: fresh independent approval review; no implementation authorship
Requested code range: 445dd44b5382160d4e93e4cada018beb4ab0f5b5..ae21717
Acceptance authority: foundation/operations/boundary Task 3 plan and brief, .ai_worklog/task-3-fix-pass-2-report.md, .ai_worklog/task-3-review-3.md, and the recorded Task 3 report

## Verdicts

### Specification compliance: CHANGES_REQUIRED

The reported C1/I1/I2/M2 scenarios are fixed in their direct regressions: terminal manual-review journals remain untouched/read-only; grouped readers block during publication; journal/trace evidence failures are best-effort; and out-of-root transaction IDs are rejected. However, the current primitive still permits unrelated stale-lock recovery, loses the durable journal after an unprovable rollback, and permits forged in-root cleanup paths to delete user files. A locked rollback backup can also abort startup before a read-only result is returned.

### Code quality: CHANGES_REQUIRED

The focused suite and static checks are clean, but the failure paths below are material data-integrity and recovery-boundary defects not covered by the current tests. They require another fix pass and fresh independent review.

## Findings

### Critical C1 - stale-lock recovery is not scoped to the requesting lock

Evidence: _recover_lock() accepts journal_path from the lock payload and calls _recover_journal() without requiring the journal’s resolved recovery root to contain the lock parent (src/etf_cockpit/core/atomic_io.py:251-261). _recover_journal() then restores entries and deletes the referenced transaction (src/etf_cockpit/core/atomic_io.py:213-248).

Fresh bounded harness: a stale lock at root/data/.atomic-write-group.lock pointed at a valid schema-1 journal under sibling root/other/.atomic-transactions/forged, with a destination under root/other. wait_for_atomic_group(root/data/store.bin) changed the victim from new to the forged backup old, deleted the forged journal, left the unrelated lock in place, and finally raised TimeoutError.

Required fix: bind a recovered journal to the lock’s resolved parent/group (and validate the lock/journal identity) before invoking rollback. Unrelated or malformed stale locks must remain present and return a safe timeout/read-only outcome without mutating their referenced transaction.

### Critical C2 - failed rollback removes the journal and leaves a mixed generation

Evidence: the writer exception handler invokes _recover_journal(..., force=True) and then re-enters finally; whenever the journal still exists, finally unconditionally calls _cleanup_transaction() (src/etf_cockpit/core/atomic_io.py:469-486). If rollback raises or cannot be proved, the transaction record and lock/staging evidence are still deleted.

Fresh bounded harness: a two-file group started at old-a/old-b; the first replacement succeeded, the second replacement raised PermissionError, and rollback of the first file was also denied. The writer raised the rollback error but left first.bin = new-a, second.bin = old-b and no journal/transaction directory. This violates the old-or-new complete-generation invariant and removes the only manual-recovery evidence.

Required fix: preserve the journal, staged payloads and lock evidence whenever rollback fails or cannot be proved; classify/surface recovery_required/read-only state and never run normal cleanup over an unresolved transaction. Add a real activation-plus-rollback permission-failure regression.

### Important I1 - cleanup trusts forged in-root staged/lock paths

Evidence: _cleanup_transaction() unlinks every staged_paths and lock_paths entry (src/etf_cockpit/core/atomic_io.py:149-154). The legacy validator checks only recovery-root containment (src/etf_cockpit/operations/recovery.py:394-417), and the lower-level path guard used by stale-lock recovery likewise checks containment but not transaction ownership or canonical lock identity (src/etf_cockpit/core/atomic_io.py:180-210). V2 top-level paths are checked for containment, while only entry staged paths are constrained to the destination parent (src/etf_cockpit/operations/recovery.py:296-323); stale-lock recovery bypasses the full v2 validator.

Fresh bounded harnesses placed an existing data/important.bin in staged_paths of a valid legacy journal, and as the staged entry/top-level path of a structurally valid v2 journal with a matching checksum. Recovery returned normal rolled_back, restored the target and unlinked important.bin in both cases.

Required fix: require staged files to be writer-created transaction artefacts (including destination-parent/name relationship) and require lock paths to be canonical .atomic-write-group.lock files whose ownership evidence names this journal. Preserve journals as recovery_required when these relationships cannot be proven, including through stale-lock recovery.

### Important I2 - locked payload evidence can escape before read-only classification

Evidence: _validate_v2_payload() hashes rollback backups, staged payloads and committed destinations directly (src/etf_cockpit/operations/recovery.py:345-359). recover_incomplete_transactions() calls that validator without a surrounding exception boundary (src/etf_cockpit/operations/recovery.py:499-507), so a PermissionError/OSError while hashing a readable journal’s backup or staged file escapes startup instead of producing RecoveryResult(state="recovery_required", startup_mode="read_only").

Fresh bounded harness: a structurally valid committing v2 journal with a locked/denied rollback-backup hash raised PermissionError("locked backup") directly from recover_incomplete_transactions().

Required fix: catch validation evidence I/O failures, preserve the journal and payloads, and return an explicit unavailable checksum/read-only recovery result. Keep event emission non-throwing as in the current fix.

## Positive and boundary checks

- Explicit schema-2 recovery_required and quarantined journals remain byte-for-byte untouched and return read-only results.
- The group-reader regression blocks while a writer is paused between destination replacements and returns one complete generation.
- The interrupted real-writer, two-writer ordering, staged post-hook checksum, nested migration and default authoritative session-trace regressions pass.
- mark_transaction_ready() rejects absolute, nested and otherwise out-of-root transaction IDs before opening a journal.
- No broker/order/credential/upload/execution capability or UI scope was added. The reviewed source diff does not alter the existing execution_allowed/executable_authority boundary; no issue, remote, branch or package mutation was performed.

## Verification evidence

Commands run from C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task3-atomic-recovery with the existing Python 3.13 interpreter:

C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py --tb=short -q

Exit 0; 61 focused tests passed (the supplied fix report’s result is trusted).

C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\core\atomic_io.py src\etf_cockpit\operations\recovery.py tests\operations\test_transactions.py tests\operations\test_recovery.py
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit
git diff --check 445dd44b5382160d4e93e4cada018beb4ab0f5b5

Ruff exit 0, compileall exit 0 and review-range whitespace check exit 0. No long-running suite was run.

## Final decision

CHANGES_REQUIRED - do not integrate or close the Task 3 gate until C1/C2 and the Important recovery-boundary findings are fixed and independently re-reviewed.
