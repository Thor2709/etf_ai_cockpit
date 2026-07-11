# Wave 0 Task 3 - independent post-fix review

Date: 2026-07-11
Worktree: `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task3-atomic-recovery`
Reviewed range: `445dd44b5382160d4e93e4cada018beb4ab0f5b5..fcb5e04e6fa638d887beaee58ff69346ddb7c1b0`
Reviewer role: fresh independent post-fix review; no source or test authorship

## Evidence reviewed

- Task 3 plan/brief, `.ai_worklog/task-3-fix-pass-3-report.md`, `.ai_worklog/task-3-review-final.md`, and the recorded Task 3 report.
- Current `src/etf_cockpit/core/atomic_io.py`, `src/etf_cockpit/operations/recovery.py`, `src/etf_cockpit/operations/models.py`, migration integration, and the Task 3 recovery/transaction tests against the task base.
- Supplied fresh focused evidence: 67 Task 3/adjacent tests passed, scoped Ruff passed, compileall passed, and the fix report's source hashes are recorded. I did not rerun the long suite.

Targeted post-fix command run:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_transactions.py::test_stale_lock_does_not_recover_unrelated_transaction_under_sibling_root tests/operations/test_transactions.py::test_activation_rollback_failure_preserves_recovery_evidence tests/operations/test_recovery.py::test_legacy_journal_does_not_cleanup_unowned_lock_path tests/operations/test_recovery.py::test_legacy_journal_does_not_cleanup_unowned_staged_path tests/operations/test_recovery.py::test_v2_journal_does_not_cleanup_unowned_staged_path tests/operations/test_recovery.py::test_v2_journal_does_not_cleanup_canonical_lock_outside_writer_group -q --tb=short
```

Exit status 0; 6 passed. Earlier manual-review, unreadable-journal/session-trace, group-reader, and out-of-root transaction-ID regressions also passed when targeted (5 passed).

## Specification compliance verdict: CHANGES_REQUIRED

The requested C1 stale-lock scope, C2 rollback-failure durability, and I1 owned-artefact regressions pass. `_recover_lock()` now checks canonical lock identity, transaction identity, recovery-root scope, journal membership and matching ownership before delegating recovery. Unprovable writer rollback leaves `recovery_required` journal state and staged/lock evidence. Legacy and schema-2 staged paths require the writer's destination-parent temp-file relationship; lock paths require canonical group placement and ownership evidence. Earlier manual-review terminal states, group-reader boundary, unreadable journal/session trace handling, out-of-root `mark_transaction_ready()` rejection, migration recovery and the `execution_allowed = false` authority boundary remain intact.

One earlier recovery-boundary finding remains open:

### Important I2 - payload checksum I/O can still escape startup recovery

`recover_incomplete_transactions()` invokes `_validate_v2_payload()` directly at `src/etf_cockpit/operations/recovery.py:555-561`. That validator hashes rollback backups, staged payloads and (for committed journals) destinations at `src/etf_cockpit/operations/recovery.py:347-361` without an exception boundary. A locked/permission-denied payload therefore raises before a `RecoveryResult(state="recovery_required", startup_mode="read_only")` can be produced.

Fresh bounded harness (not a repository test edit): a structurally valid `committing` schema-2 journal was created using the existing fixture shape; `atomic_io.sha256_file` was patched to raise `PermissionError("locked backup")` for its rollback backup. `recover_incomplete_transactions()` raised `PermissionError: locked backup` directly. The required behaviour is an explicit read-only/recovery-required result with the journal and payload evidence preserved, as specified by the prior final-review I2 finding. The same gap applies to staged/committed payload checksum reads and path-resolution/read errors that escape the validator.

Required fix: catch evidence I/O/validation exceptions around `_validate_v2_payload()` (including `OSError`, `RuntimeError` and equivalent path/hash failures), preserve the transaction evidence, and return/emit an explicit `recovery_required`/`read_only` result with an unavailable checksum marker when hashing is not possible.

## Code-quality verdict: CHANGES_REQUIRED

The targeted C1/C2/I1 checks are clean and the current source diff is whitespace-clean for the reviewed implementation/test files. However, the startup recovery path still has a directly reproducible unhandled permission failure in the validator. This leaves the recovery API capable of aborting rather than entering its documented safe read-only mode under locked payload evidence, so the implementation is not ready for approval.

No source, test, issue, remote, UI, package, execution-authority or later-task files were changed by this review. The review result is **CHANGES_REQUIRED** pending the I2 boundary fix and another fresh independent review.
