# Wave 0 Task 3 - independent review 1

Date: 2026-07-11
Reviewer role: fresh independent reviewer; no implementation authorship
Range reviewed: `445dd44b5382160d4e93e4cada018beb4ab0f5b5..d48bbbec5d1833eb5fc627d351f32cbe6d6b53c2`
Owning plan: Wave 0 foundation/operations/boundary plan, Task 3
Acceptance authority: approved Group M / `REL-02`, Task 3 binding brief and `ISSUE-0040-R05/R06`

## Verdict

**REJECTED - not ready for a fix-free hand-off.** Two independently reproduced Critical data-integrity failures and six Important contract/evidence gaps remain. The focused suite passes, but it does not exercise the concurrency, post-validation tampering, real nested-journal migration or forged/corrupt-path outcomes that fail below. Stop after this report and send the change through a fresh implementation/fix pass.

## Review 1 - specification and acceptance compliance

### Critical

#### C1 - Locking occurs after the rollback snapshot, so recovery can erase a different writer's successful commit

Evidence: `atomic_write_group()` reads each previous value and creates its rollback backup at `src/etf_cockpit/core/atomic_io.py:295-305`, but does not acquire the group locks until `src/etf_cockpit/core/atomic_io.py:321-326`. Recovery later treats that stale backup as authoritative at `src/etf_cockpit/core/atomic_io.py:156-175`.

Fresh two-thread reproduction:

- Writer 1 and writer 2 both snapshot `old` before either owns the lock.
- Writer 1 commits `new-1` successfully.
- Writer 2 then commits `new-2` and is interrupted at `manifest_publish`.
- Startup recovery reports `rolled_back` but restores `old`, erasing writer 1's already committed generation.
- Observed JSON: `{"errors": [], "before_recovery": "new-2", "after_recovery": "old", "recovery_state": "rolled_back"}`.

This violates lock-contention safety, old/new complete-state authority and the requirement that failed work cannot corrupt a previous clean committed state. The new concurrency test at `tests/operations/test_transactions.py:115-128` only writes a synthetic same-process lock and calls the reader wait helper; it never runs two writers.

#### C2 - A syntactically valid but corrupt v2 journal can delete a file outside the recovery root and is reported as a normal rollback

Evidence: `_validate_v2_payload()` at `src/etf_cockpit/operations/recovery.py:127-152` does not validate required fields, approved states, transaction identity, path containment or the relationship between entries and top-level checksum/path maps. `_recover_journal()` then trusts `destination` and, when `backup_path` is false, deletes it at `src/etf_cockpit/core/atomic_io.py:156-175`.

Fresh forged-journal reproduction placed the transaction under `data/.atomic-transactions` but set its destination to a sibling `outside.txt`. Recovery returned `{"state": "rolled_back", "mode": "normal", "outside_file_exists": false}`. The corrupt journal therefore mutated unrelated state instead of being preserved as `recovery_required`/`read_only` for manual review.

This directly fails the corrupt/incomplete-journal and manual-review acceptance criteria.

### Important

#### I1 - Validation/checksums do not immediately precede activation, and tampered staged bytes are committed under the wrong checksum

Evidence: expected hashes are calculated from the original in-memory payload at `src/etf_cockpit/core/atomic_io.py:268-270` and `src/etf_cockpit/core/atomic_io.py:306-313`; validators run at `src/etf_cockpit/core/atomic_io.py:318-320`; then the lifecycle hook and lock wait occur before unchecked `Path.replace()` activation at `src/etf_cockpit/core/atomic_io.py:321-327`. No checksum is recomputed after validation or immediately before replacement.

A fresh hook changed the staged file at `committing`. The call succeeded, removed its journal, activated `TAMPERED`, and returned the SHA-256 for `new`: `{"destination": "TAMPERED", "reported_sha256": "11507a0e...", "journal_dirs": 0}`.

The test at `tests/operations/test_transactions.py:16-43` observes private `_write_journal` calls and checks only that an expected-checksum map was written; it does not prove that activated bytes match it.

#### I2 - Migration preflight misses transaction journals produced in nested canonical folders

Evidence: recovery scans only `data_root/.atomic-transactions` and one level of child directories at `src/etf_cockpit/operations/recovery.py:184-195`. `run_migrations()` passes the project root at `src/etf_cockpit/core/migrations.py:92-99`. A real single-parent grouped write under `root/data/clean` creates `root/data/clean/.atomic-transactions/...`, which is two levels below the project root and is not found.

Fresh reproduction interrupted a real write at `manifest_publish`, then ran migrations. Result: `{"journal_location": "data\\clean\\.atomic-transactions\\...\\journal.json", "migration_version": 4, "journal_still_exists": true, "destination": "new"}`. Migration proceeded to version 4 despite unresolved interrupted work. The migration test at `tests/operations/test_recovery.py:179-186` hand-builds its journal directly under the root, so it does not cover the layout generated by `atomic_write_group()`.

#### I3 - The public `WriteTransaction` path types do not match the approved contract

The approved shape requires `staging_paths: list[str]` and `final_paths: list[str]`. The implementation declares both as `dict[str, str]` at `src/etf_cockpit/operations/models.py:90-91`, and the public `begin_write_transaction()` parameters repeat those incompatible dict types at `src/etf_cockpit/operations/recovery.py:69-70`.

Fresh schema inspection reports both properties as JSON `type: object` with string-valued additional properties. The exact public function signatures otherwise preserve the plan's required leading arguments, but this field-type mismatch is a downstream compatibility break. The field-existence test at `tests/operations/test_transactions.py:46-64` checks names only, not types.

The real v2 grouped journal also stores `staged_paths` as a list at `src/etf_cockpit/core/atomic_io.py:266` and `src/etf_cockpit/core/atomic_io.py:315`, does not store `final_paths`, and emits `manifest_publish`, which is absent from `WriteTransactionStatus` at `src/etf_cockpit/operations/models.py:64-75`. Thus the claimed typed projection and the durable journal are not one coherent public contract.

#### I4 - Production startup recovery emits no Task 2 authoritative operational event

Evidence: event emission exits immediately when `event_path` is omitted at `src/etf_cockpit/operations/recovery.py:155-157`; the public API defaults it to `None` at `src/etf_cockpit/operations/recovery.py:179-183`; and the only production caller, migration preflight, supplies no event path at `src/etf_cockpit/core/migrations.py:93-95`. Repository call-site search found no other production recovery caller.

The test at `tests/operations/test_recovery.py:165-176` proves only the explicit test-only path. Consequently real startup recovery is not visible in Task 2's authoritative session trace, contrary to the operational-event/audit visibility requirement and the report's implication that this integration is complete.

#### I5 - Structurally invalid v2 journals are silently accepted and destroyed

As a separate non-path corruption case, fresh recovery of a v2 journal with `state="nonsense"` and no entries returned `rolled_back`, `normal` and deleted the journal. A `committed` journal with no entries and a contradictory top-level expected-checksum map returned `committed`, `normal` and was also deleted. `_validate_v2_payload()` at `src/etf_cockpit/operations/recovery.py:127-152` validates only files present in entries; it never validates the journal schema as a whole.

The only corrupt-journal test at `tests/operations/test_recovery.py:81-90` uses invalid JSON. It does not cover syntactically valid corruption, unknown status, missing required fields, entry/checksum cardinality or transaction-directory identity.

#### I6 - Required durable backup/audit evidence is absent from the evidence artefact

The Task 3 evidence file `evidence/wave0/task3/fault-matrix.json:17-22` contains source-file checksums only. It records no concrete backup manifest path/checksum or restore output, despite the plan requiring backup manifest checksums in wave evidence. `tests/operations/test_backups.py:11-22` proves a temporary test fixture is checked, but that fixture disappears and is not durable review evidence. Recovery evidence itself is only retained in the session event when the optional path is explicitly supplied; otherwise successful cleanup deletes the journal and no audit record is written.

### Minor

#### M1 - Review-range whitespace validation is not clean

`git diff --check 445dd44..HEAD` exits 2 due to a blank line at EOF in `.ai_worklog/task-3-brief.md:62` and trailing Markdown whitespace at `.ai_worklog/task-3-report.md:3-6`. This is not a runtime defect but contradicts the report's statement that `git diff --check` exited 0 for the reviewed range.

#### M2 - The task report's closure table was never reconciled with its own claimed evidence

`.ai_worklog/task-3-report.md:15-40` leaves every implementation gate as `pending`, including transaction lifecycle, checksum order, concurrency, recovery, migration compatibility, event visibility and authority boundary, while later prose calls the infrastructure increment implementation-complete. Keeping UI/package/browser gates `pending_later_task` and `ISSUE-0040`/`REL-02` open is correct, but the internal report state is ambiguous.

## Review 2 - correctness, quality and maintainability

The dominant quality problem is that the tests verify journal vocabulary and handcrafted single-file fixtures, rather than the coupled behaviour of the real writer and recovery engine. In particular:

- Real writer interruptions are asserted only to leave a journal (`tests/operations/test_transactions.py:95-112`); real journals are not then recovered and checked across multi-file and concurrent cases.
- Recovery fault tests construct journals independently (`tests/operations/test_recovery.py:21-64`), allowing their layout to drift from `atomic_write_group()`.
- Lock testing does not create concurrent writers (`tests/operations/test_transactions.py:115-128`).
- Checksum testing inspects a private journal function rather than activated bytes (`tests/operations/test_transactions.py:16-43`).
- Migration preflight uses a journal location the real same-folder writer does not generate (`tests/operations/test_recovery.py:179-186`).
- Corruption coverage tests JSON syntax, missing files and payload hashes, but not schema/state/path authority (`tests/operations/test_recovery.py:81-109`).

The implementation also couples public recovery code to private `atomic_io._write_journal()` and `atomic_io._recover_journal()` at `src/etf_cockpit/operations/recovery.py:103`, `src/etf_cockpit/operations/recovery.py:119` and `src/etf_cockpit/operations/recovery.py:223`. That makes the claimed public transaction wrapper fragile and contributes to the mismatch between `WriteTransaction` and the actual journal.

Positive, verified boundaries:

- No Task 4 governance implementation, broker/order capability or authority inflation appears in the reviewed source diff. The documented `execution_allowed=false` / `executable_authority=false` boundary is unchanged.
- No UI change was claimed. The report correctly keeps Error/Recovery UI, package rebuild and browser gates as `pending_later_task`; `ISSUE-0040` and `REL-02` remain open.
- Legacy schema-1 prepared recovery and backup tamper rejection pass in the fresh focused suite.
- Fault-matrix source SHA-256 values match all four reviewed source files.

## Fresh commands and results

1. Focused covering suite:
   `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py -q`
   - Exit 0: **38 passed**.

2. Full suite:
   `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests -q`
   - Exit 1: **299 passed, 7 failed** in 45.3 s.
   - Failures are the six known isolated-worktree `tests/test_simple_scores.py` artefact/configuration failures plus `tests/test_trust_critical_artifacts.py::test_static_trust_artifacts_cover_providers_and_identity`. No additional Task 3 failure appeared, but this does not supersede the direct adversarial reproductions above.

3. Static checks:
   - Scoped Ruff on all changed Python files: exit 0, `All checks passed!`.
   - `python -m compileall -q src\etf_cockpit`: exit 0.
   - `git diff --check 445dd44..HEAD`: exit 2 with the whitespace findings in M1.

4. Evidence hashes:
   - All four `source_sha256` entries in `evidence/wave0/task3/fault-matrix.json` match fresh `Get-FileHash -Algorithm SHA256` results.

5. Adversarial direct executions using the absolute interpreter:
   - Post-validation staged-file mutation: activated `TAMPERED` while reporting the hash of `new`.
   - Two concurrent writers plus writer-2 interruption: recovery changed `new-2` to `old`, losing committed `new-1`.
   - Real nested journal plus migration: migration reached version 4 and left the interrupted journal unresolved.
   - Syntactically valid corrupt journals: unknown/contradictory states were accepted as normal and deleted.
   - Forged destination outside recovery root: recovery deleted the outside file and reported normal rollback.

## Required fix-pass focus

Acquire all writer locks before reading/snapshotting the old generation and retain them through activation/manifest publication; revalidate exact staged hashes immediately before replace; validate the complete v2 schema, approved states, transaction identity, cardinality and path containment before any mutation; discover the exact journal roots that the writer can produce; align `WriteTransaction` list field types and status model with the approved contract; make startup recovery events use the Task 2 authority by default; and add end-to-end, real-journal tests for concurrency, nested migration, multi-file visibility and structurally corrupt journals. Then regenerate durable backup/recovery evidence and request a fresh independent review.
