# Wave 0 Task 3 - fix pass 3 report

Date: 2026-07-11
Worktree: `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task3-atomic-recovery`
Scope: review-final findings C1, C2 and I1 only

## RED

The new regressions were added before the implementation and failed behaviourally after collection completed.

1. C1 and C2:

   ```text
   C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_transactions.py::test_stale_lock_does_not_recover_unrelated_transaction_under_sibling_root tests/operations/test_transactions.py::test_activation_rollback_failure_preserves_recovery_evidence -q
   ```

   Exit status 1 (`FF`). The stale-lock test observed the forged backup change `victim.bin` from `new` to `old`; the rollback-failure test found zero durable journals after the first activation succeeded and rollback was denied.

2. I1:

   ```text
   C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_recovery.py::test_legacy_journal_does_not_cleanup_unowned_lock_path tests/operations/test_recovery.py::test_legacy_journal_does_not_cleanup_unowned_staged_path tests/operations/test_recovery.py::test_v2_journal_does_not_cleanup_unowned_staged_path -q
   ```

   Exit status 1 (`FFF`). Each invalid in-root artefact was accepted as a normal rollback (`rolled_back`) and the journal/important file was eligible for cleanup instead of producing `recovery_required` / `read_only`.

## GREEN

Implementation changes are limited to the atomic I/O and recovery primitives:

- `_recover_lock()` now requires canonical lock identity, matching transaction ID/owner, the journal recovery root to contain the resolved lock parent, and the lock to be listed by that journal before recovery is attempted.
- Writer rollback exceptions or an unprovable rollback persist `state/status = recovery_required` when possible and set a recovery-pending guard that skips all normal staged/lock/journal cleanup. Existing exception propagation is preserved.
- Legacy and schema-2 validation now requires writer-generated stage naming/entry relationships, canonical group locks in destination/common-root parents, and matching lock ownership evidence before any mutation or cleanup.
- Invalid recovery evidence remains in place and startup recovery reports `recovery_required` / `read_only`.

Focused Task 3 regression suite:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_transactions.py tests/operations/test_recovery.py tests/operations/test_backups.py tests/test_atomic_io.py tests/test_backup_restore.py tests/test_schema_migrations.py tests/operations/test_operational_events.py --tb=short
```

Exit status 0: **67 passed in 3.11s**.

The C2 regression also runs startup recovery after the writer failure and verifies `recovery_required` / `read_only` while the journal, lock evidence and surviving staged evidence remain present. The additional schema-2 canonical-lock-parent regression passes in the same suite.

## Refactor and validation

Scoped Ruff:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m ruff check src/etf_cockpit/core/atomic_io.py src/etf_cockpit/operations/recovery.py tests/operations/test_transactions.py tests/operations/test_recovery.py
```

Exit status 0: `All checks passed!`

Compile check:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m compileall -q src/etf_cockpit
```

Exit status 0.

Whitespace/diff check:

```text
git diff --check
```

Exit status 0 (only Git's existing LF/CRLF advisories were emitted).

## SHA-256 evidence

Hashes were captured after the final source/test edits and before this report was committed:

```text
src/etf_cockpit/core/atomic_io.py       EA9A84B3EFDC452980017E314C12C2201EFA39C49EF12090C2A2ED1CBE35DAF6
src/etf_cockpit/operations/recovery.py  A82D807CD9D806EC64DEC849FF78100CDF52439A199256414BC812D87F7C49F2
tests/operations/test_transactions.py   7EC8A4ED02E3C780F0FEF1E54325C905041CCED0218587A3988BA327DDA51720
tests/operations/test_recovery.py       D085560537A136219E53A6B414468AA517A93D6B5279DC65E0FF30415E3BC4ED
```

No UI, execution authority, issue status, remote state or later-task files were changed.
