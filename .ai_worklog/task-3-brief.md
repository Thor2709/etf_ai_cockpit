### Task 3: Route mutable canonical writes through the existing atomic transaction primitive

**Files:**

- Create: `src/etf_cockpit/operations/recovery.py`, `tests/operations/test_transactions.py`, `tests/operations/test_recovery.py`, `tests/operations/test_backups.py`
- Modify: `src/etf_cockpit/core/atomic_io.py:1-366`, `src/etf_cockpit/core/migrations.py:1-145`, selected mutable writer modules only after a writer inventory is generated

**Consumes:** Tasks 1-2 evidence/event contracts and existing grouped atomic write/journal APIs.

**Produces:** `WriteTransaction` lifecycle and startup recovery result reused by registry, catalogue, portfolio and workflow tasks.

- [ ] **Step 1: Write parameterised fault-injection RED tests**

```python
@pytest.mark.parametrize("crash_point", ["staging", "validating", "committing", "manifest_publish"])
def test_recovery_exposes_old_or_new_complete_generation_only(tmp_path: Path, crash_point: str) -> None:
    simulate_grouped_write_crash(tmp_path, crash_point=crash_point)
    outcome = recover_incomplete_transactions(tmp_path)
    assert outcome[0].state in {"rolled_back", "recovery_required"}
    assert read_current_pointer(tmp_path) in {"generation-old", "generation-new"}
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\test_atomic_io.py -q`

Expected: FAIL because transaction records and recovery classification are absent.

- [ ] **Step 3: Implement transaction records around, not beside, `atomic_io`**

```python
def begin_write_transaction(*, transaction_type: str, base_generations: dict[str, str]) -> WriteTransaction: ...
def mark_transaction_ready(transaction_id: str, checksums: dict[str, str]) -> WriteTransaction: ...
def recover_incomplete_transactions(data_root: Path) -> list[RecoveryResult]: ...
```

Each function delegates actual byte/group commit, lock, journal, verification and backup work to `core.atomic_io`; it never introduces a second lock or journal format. Startup recovery must select normal, read-only diagnostic or recovery-required mode without promoting ambiguous staging data.

- [ ] **Step 4: Run GREEN and restore drill**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py -q`

Expected: PASS, including locked-file, checksum-mismatch and restore fixtures.

- [ ] **Step 5: Log recovery evidence**

Write the fault matrix, backup manifest checksums and recovery-state screenshots to the wave evidence directory; update the ledger but do not close `REL-02` until package recovery has also passed.

## Binding execution brief

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
