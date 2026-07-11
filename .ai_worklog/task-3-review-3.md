# Wave 0 Task 3 - independent review 3

Date: 2026-07-11
Reviewer role: fresh independent review of the implementation/fix range
Range reviewed: `445dd44b5382160d4e93e4cada018beb4ab0f5b5..cb6671016bad5bf6f1d5f372212e2e33553b6583`
Acceptance authority: foundation/operations/boundary plan, Task 3 brief, and the Task 3 report/reviews

## Verdicts

### Specification compliance: CHANGES_REQUIRED

The prior Critical/Important findings are substantially addressed, but the current recovery state machine still violates the manual-review/read-only invariant for journals that are already marked as requiring recovery.

### Code quality: CHANGES_REQUIRED

The focused evidence is useful, but the implementation still has an untested mixed-reader window and failure paths that can raise instead of returning a read-only result. The claimed review-range whitespace check is also not reproducible.

## Findings

### Critical

#### C1 - Explicit manual-review states are auto-recovered and destroyed

Evidence: `_V2_STATES` explicitly accepts `recovery_required` and `quarantined` in `src/etf_cockpit/operations/recovery.py:152-164`. After validation, `recover_incomplete_transactions()` calls `atomic_io._recover_journal(..., force=True)` for every accepted state at `src/etf_cockpit/operations/recovery.py:479-503`, and classifies every non-`committed` result as a normal rollback at `src/etf_cockpit/operations/recovery.py:514-524`. `_recover_journal()` restores/deletes entries and removes the journal for every state other than `committed` at `src/etf_cockpit/core/atomic_io.py:226-246`.

Fresh bounded harness: a structurally valid schema-2 journal with `state="recovery_required"` changed the destination from `new` to `old`, returned `RecoveryResult(state="rolled_back", startup_mode="normal")`, and deleted the journal. This directly defeats the required contract that an already ambiguous/blocked journal remain preserved as `recovery_required`/`read_only` for manual recovery. `quarantined` has the same path.

Required fix: classify `recovery_required` and `quarantined` as terminal manual-review states before calling `_recover_journal`; preserve the journal and return `recovery_required`/`read_only` without mutating payloads.

### Important

#### I1 - Group activation exposes mixed generations to readers

Evidence: `atomic_write_group()` replaces destinations one at a time at `src/etf_cockpit/core/atomic_io.py:409-410`. `wait_for_atomic_group()` only waits on the lock for one destination path at `src/etf_cockpit/core/atomic_io.py:294-302`; it does not provide a group snapshot/pointer or reader transaction boundary.

Fresh bounded harness paused the first destination replacement and read both destinations: it observed `new-a` alongside `old-b` before the second replacement completed. That violates Task 3's explicit “previous complete generation or new complete generation” invariant for multi-file groups. The concurrent-writer test only checks writer ordering/recovery and cannot prove reader visibility.

Required fix: publish/read a group generation pointer or add a group-level reader protocol so readers cannot observe the replacement loop midway; add an end-to-end mixed-reader regression.

#### I2 - Unreadable journals or session traces can abort recovery instead of yielding read-only state

Evidence: the journal read failure branch at `src/etf_cockpit/operations/recovery.py:460-467` immediately calls `_required_result()`, but `_required_result()` unconditionally hashes an existing journal at `src/etf_cockpit/operations/recovery.py:140-149`; a permission/locking failure can therefore escape while constructing the supposedly safe result. Likewise `_emit_recovery_event()` reads the existing trace without a guard at `src/etf_cockpit/operations/recovery.py:404-425`, so an unreadable event log can abort startup after a recovery result has been classified. This conflicts with the project's graceful logging/failure requirement and the Task 3 permission/locked-file acceptance gate.

Required fix: make evidence hashing best-effort (empty/explicit unavailable checksum on read failure) and make event emission non-throwing, preserving the recovery result and read-only mode even when journal or trace files cannot be read.

### Minor

#### M1 - Review-range whitespace evidence is stale

Fresh command `git diff --check 445dd44b5382160d4e93e4cada018beb4ab0f5b5..cb6671016bad5bf6f1d5f372212e2e33553b6583` exits non-zero with trailing Markdown whitespace in `.ai_worklog/task-3-review-1.md`, `.ai_worklog/task-3-review-2.md`, `.ai_worklog/task-3-review-package.md`, and `.ai_worklog/task-3-review-package-rereview.md`. The report claims this full-range check exited 0. `git diff --check HEAD` is clean, but that does not validate the requested review range.

#### M2 - `mark_transaction_ready()` does not constrain the transaction ID to the supplied root

Evidence: `src/etf_cockpit/operations/recovery.py:124-136` interpolates the caller-provided `transaction_id` directly into `_journal_path()` and reads/writes it without validating UUID/transaction-directory identity. A caller can supply an absolute path to an existing journal outside `data_root` and have it rewritten. `begin_write_transaction()` generates safe IDs, but the public ready-marking API does not enforce that contract.

## Positive checks

- The Task 3 plan, brief, report, review 1 and review 2 were read in full; the full requested commit range was inspected.
- Review 1's lock-order, strict v2 validation, nested discovery, model-shape, event-default and durable-evidence fixes are present in the current source.
- The documented execution boundary remains unchanged (`execution_allowed=false`), no broker/order capability was added, and UI/package/browser gates remain correctly open for later work.
- No long-running suite was rerun in this bounded review; the fresh harness checks above were run with the existing Python 3.13 environment.

## Final decision

**CHANGES_REQUIRED**
