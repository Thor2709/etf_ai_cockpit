# Wave 0 Task 3 - independent review 3 fix pass

Date: 2026-07-11
Worktree: `wave0/task3-atomic-recovery`
Scope: C1, I1, I2 and M2 from `task-3-review-3.md`; review-range Markdown whitespace

## RED

Command:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q
```

Exit status: 1. Collection completed and the failures were behavioural (six new tests failed; the pre-existing tests passed). Representative failures:

- Explicit schema-2 `recovery_required` and `quarantined` journals were classified as `rolled_back` and deleted instead of remaining manual-review/read-only.
- The mixed-generation reader regression reported `group reader protocol is missing`.
- Out-of-root `mark_transaction_ready` raised `FileNotFoundError` while trying to read the forged path instead of rejecting the transaction ID first.
- Unreadable journal evidence hashing raised `PermissionError` while constructing `_required_result`.
- Unreadable session-trace sequence calculation raised `PermissionError` from `_emit_recovery_event`.

## GREEN

The minimal fixes are:

- Terminal schema-2 manual-review states are classified before `_recover_journal`; the journal and payload remain untouched and the result is `recovery_required` / `read_only`. `_recover_journal` also refuses those terminal states when reached through lock recovery.
- `atomic_write_group` now holds the common-root group lock in addition to destination-parent locks. `read_atomic_group` acquires the same complete lock set and reads all payload bytes inside one boundary, preventing mixed generations.
- Recovery evidence hashing is best-effort with an explicit `journal_sha256: unavailable` marker, and event emission is non-throwing when the session trace cannot be read.
- `mark_transaction_ready` rejects non-string, nested, absolute or otherwise out-of-root transaction IDs before opening a journal.

Focused command (RED target plus the new regressions):

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q
```

Exit status: 0.

Expanded Task 3 regression command:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py --tb=short
```

Result: exit status 0, **61 passed in 4.55s**.

The end-to-end reader regression pauses the first destination replacement, starts a group reader while publication is paused, verifies the reader remains blocked, then releases publication and asserts it receives `(new-a, new-b)` rather than a mixed generation.

## Refactor and static checks

Scoped Ruff:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\core\atomic_io.py src\etf_cockpit\operations\recovery.py tests\operations\test_transactions.py tests\operations\test_recovery.py
```

Result: exit status 0, `All checks passed!`.

Compile check:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit
```

Result: exit status 0.

Whitespace checks after trimming the review artefacts (`task-3-review-1.md`, `task-3-review-2.md`, `task-3-review-package.md` and `task-3-review-package-rereview.md`):

```text
git diff --check HEAD
git diff --check 445dd44b5382160d4e93e4cada018beb4ab0f5b5
```

Both exit status 0 against the current worktree. After committing this fix pass, `git diff --check 445dd44b5382160d4e93e4cada018beb4ab0f5b5..HEAD` also exits 0, so the reviewed range has no trailing whitespace.

SHA-256 evidence for the implementation and focused regressions:

```text
src/etf_cockpit/core/atomic_io.py       7A264AEC23B2F26EA6B1B07A07CBAEEB4D9BD4C9E2C19C4FF5BB5CEDF9D3DA05
src/etf_cockpit/operations/recovery.py  442091055A9C876298B2F7E1A4C9034746A3F975096D0817965C59BEDA192747
tests/operations/test_transactions.py   CA243582BAC4476277EF9FA4FC4F3E63F66E6EAEFEC78663B05AA0061450EBCC
tests/operations/test_recovery.py       013F4893FA19E4176185CC212B2F605D381277753403789F0ECAC5E080DF01AD
```

## Changed files

- `src/etf_cockpit/core/atomic_io.py`
- `src/etf_cockpit/operations/recovery.py`
- `tests/operations/test_transactions.py`
- `tests/operations/test_recovery.py`
- `.ai_worklog/task-3-review-1.md`
- `.ai_worklog/task-3-review-2.md`
- `.ai_worklog/task-3-review-package.md`
- `.ai_worklog/task-3-review-package-rereview.md`
- `.ai_worklog/task-3-fix-pass-2-report.md`

No UI, execution authority, issue status or later-task files were changed.
