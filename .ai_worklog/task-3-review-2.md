# Wave 0 Task 3 - post-fix review checkpoint

Date: 2026-07-11  
Review role: parent-side adversarial verification; **not an independent task re-review**  
Task base: `445dd44b5382160d4e93e4cada018beb4ab0f5b5`  
Current implementation: `4d02c8076cbdbc1da296d9b39962104a8a2a224f`  
Current documentation checkpoint: `902b21c4d2435109f07e9d5104d1823992fd09a0`

## Review status

The first fresh reviewer rejected the implementation with two Critical and six Important findings. The fix implementer addressed those findings, and the covering tests pass. The required fresh independent re-review has not been completed and this report must not be used as its substitute.

The permitted delegated-agent configuration cannot be verified in this repository or user configuration:

- `C:\Users\thor2\.codex\agents` is absent;
- `C:\Users\thor2\Desktop\Trading App\.codex\agents` is absent;
- `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.codex\agents` is absent;
- the available Superpowers `agents/openai.yaml` contains display metadata only and no GPT-5.6 Luna/Max pin.

A fresh re-review dispatch was attempted before this checkpoint but returned a usage-limit error and produced no review report. Under the current repository instructions, no unpinned or non-Luna-Max replacement may be dispatched. The implementation therefore remains **review-pending** and is not eligible for branch integration, issue closure or GitHub synchronisation.

## Parent-side adversarial checks

The following checks were run after the fix pass. They are evidence of implementation behaviour only, not an independent approval:

1. Focused Task 3 and adjacent regression suite:
   `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\operations\test_transactions.py tests\operations\test_recovery.py tests\operations\test_backups.py tests\test_atomic_io.py tests\test_backup_restore.py tests\test_schema_migrations.py tests\operations\test_operational_events.py -q`
   - exit 0; 55 tests passed, including the stale-lock containment regression.
2. Targeted adversarial suite for real concurrency, post-hook tampering, interruption states, corrupt journals, outside-root paths, nested migration recovery, default session tracing and the public model contract:
   - exit 0; 17 tests passed.
3. Full suite:
   `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests -q --tb=short`
   - exit 1; 323 collected, 316 passed, seven failures. The failures are the pre-existing isolated-worktree missing generated market/candidate artefacts and the recorded identity-artifact count mismatch; no Task 3 test failed.
4. Static checks:
   - scoped Ruff: exit 0 (`All checks passed!`);
   - `python -m compileall -q src\etf_cockpit`: exit 0;
   - `git diff --check HEAD`: exit 0.
5. Evidence integrity:
   - `evidence/wave0/task3/artefacts/artefact-manifest.json`: eight of eight artefacts present with matching byte counts and SHA-256 values;
   - `evidence/wave0/task3/fault-matrix.json`: four of four source SHA-256 values match the current files.

## Additional finding fixed during this checkpoint

The parent-side review identified one residual safety gap not covered by the first fix report: `_recover_lock()` could follow a stale lock to a syntactically valid legacy journal whose destination was outside that journal's recovery root. A direct RED test demonstrated that `wait_for_atomic_group()` restored an unrelated outside file. The test was added at `tests/operations/test_transactions.py::test_stale_lock_cannot_recover_a_journal_outside_its_recovery_root`; the RED run exited 1 with the outside file changed. The guard in `src/etf_cockpit/core/atomic_io.py` now validates canonical transaction identity and containment for journal entries, staging, final and lock paths before any recovery mutation. The focused regression then exited 0 and the outside file remained unchanged while the forged lock stayed present for timeout/manual handling.

This safety fix is uncommitted and must be included in the next reviewed task checkpoint. It does not change execution authority or product scope.

## Closure decision

- Implementation and fix evidence: present.
- Independent re-review: **blocked/pending**.
- Closure evaluator: not run.
- Local issue `ISSUE-0040`: remains open and closure-pending; no issue files were moved.
- GitHub Issue writes, pull request creation, merge, push and remote issue reconciliation: not performed because the mandatory independent-review gate is not satisfied.
- Wave 0 Task 4 and all later tasks: not started.
