# Wave 0 Task 3 - fix pass 5 report

Date: 2026-07-11
Worktree: `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task3-atomic-recovery`
Scope: residual recovery validation boundary findings only

## RED

Added behavioural regressions before the corresponding production guards:

- `test_non_hashable_v2_state_is_preserved_for_manual_review` writes a schema-2
  journal with JSON `state=[]` and requires an explicit read-only/manual-review
  result while preserving the journal.
- `test_v2_existing_destination_without_backup_requires_manual_review` writes a
  schema-2 journal with `backup_path=null` and `previous_sha256=null` while an
  existing destination contains bytes that do not match the staged payload; it
  requires recovery evidence to remain in place rather than deleting that
  destination.
- `test_stale_lock_with_unhashable_journal_state_is_left_in_place` exercises the
  lower-level stale-lock path with `state=[]` and requires timeout without
  mutating the destination, journal or lock.

Targeted RED command:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_recovery.py::test_non_hashable_v2_state_is_preserved_for_manual_review tests/operations/test_recovery.py::test_v2_existing_destination_without_backup_requires_manual_review tests/operations/test_transactions.py::test_stale_lock_with_unhashable_journal_state_is_left_in_place -q --tb=short
```

Exit status 1 with the expected behavioural failures: `TypeError: unhashable
type: 'list'` escaped v2 validation/stale-lock recovery, and the null-backup
case returned `rolled_back` after deleting the existing destination.

## GREEN

- `_validate_v2_payload()` now checks that `state` is a string before membership
  testing, classifying non-hashable or invalid JSON states as
  `recovery_required`/`read_only` instead of raising.
- `_recover_journal()` rejects non-string states before terminal-state set
  membership, so stale locks cannot escape on unhashable state values.
- Schema-2 recovery rejects an existing destination with no rollback backup when
  its checksum cannot be proved to be the writer-created staged payload. A
  matching checksum remains recoverable for the legitimate new-file rollback
  path; mismatched or unavailable evidence stays manual-review/read-only.

Focused Task 3 bundle:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_transactions.py tests/operations/test_recovery.py tests/operations/test_backups.py tests/test_atomic_io.py tests/test_backup_restore.py tests/test_schema_migrations.py tests/operations/test_operational_events.py --tb=short
```

Exit status 0: **71 passed in 4.53s**.

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

Exit status 0; Git emitted only existing LF/CRLF conversion advisories.

No UI, execution authority, issue state, remote state or later-task files were
changed.
