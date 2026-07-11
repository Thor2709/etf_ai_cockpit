# Wave 0 Task 3 - fix pass 4 report

Date: 2026-07-11
Worktree: `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task3-atomic-recovery`
Scope: residual I2 recovery-boundary finding only

## RED

Added `test_unreadable_v2_payload_hash_returns_read_only_unavailable_evidence` before changing production code. The test patches `atomic_io.sha256_file` to raise `PermissionError("locked backup")` for a schema-2 rollback backup, then requires recovery to return a read-only result while preserving the journal and backup.

Command:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_recovery.py::test_unreadable_v2_payload_hash_returns_read_only_unavailable_evidence -q
```

Exit status 1. The test failed behaviourally because `recover_incomplete_transactions()` let `PermissionError: locked backup` escape from `_validate_v2_payload()`.

## GREEN

The recovery boundary now catches `OSError`, `RuntimeError` and `ValueError` raised while schema-2 validation resolves, reads or hashes payload evidence. It returns `_required_result()` with `state="recovery_required"`, `startup_mode="read_only"`, and `payload_sha256="unavailable"` evidence, while retaining the journal and payload files. Existing best-effort journal hashing remains in place, so an unreadable journal is also marked `journal_sha256="unavailable"`.

Targeted regression:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_recovery.py::test_unreadable_v2_payload_hash_returns_read_only_unavailable_evidence -q
```

Exit status 0: 1 passed.

Full focused Task 3 bundle:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests/operations/test_transactions.py tests/operations/test_recovery.py tests/operations/test_backups.py tests/test_atomic_io.py tests/test_backup_restore.py tests/test_schema_migrations.py tests/operations/test_operational_events.py --tb=short
```

Exit status 0: **68 passed in 4.45s**.

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

Exit status 0; Git emitted only existing LF/CRLF conversion advisories.

## SHA-256 evidence

Hashes are captured after the final source and regression-test edits (the report is documentation of these values):

```text
src/etf_cockpit/operations/recovery.py       D8E30A4397528265072BE2B0F5DD2594F65B00471EAC6421F8DB035FE61A04E2
tests/operations/test_recovery.py           8E8DE71C3763B37AA0840199A5CC6D43275AEB3F4FEE234B62B18E11F7559061
```

No UI, execution authority, issue state, remote state or later-task files were changed.
