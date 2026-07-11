# Wave 0 Task 5 independent re-review

## Scope and basis

Fresh read-only re-review of commits `7089cd7..7a7adc7` in the
`wave0/task5-evidence-automation` worktree. The review compared the final
source and tests with `.ai_worklog/task-5-brief.md`, Task 5 in
`docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md`,
the closure-matrix policy, and the five Important findings in
`.ai_worklog/task-5-review.md`. No source or test files, issue ledgers,
closure status, credentials, or remote trackers were changed.

## SPECIFICATION verdict - APPROVED

All five prior Important findings are fixed in the final commits:

1. **Independent package and browser stages.**
   `Invoke-PackageStage` now independently validates the build output marker,
   contained package directory, and non-empty `ETF_AI_Cockpit.bat` launcher;
   it is no longer a copy of the build result. `Invoke-BrowserStage` separately
   resolves Chrome, runs a headless DOM smoke, requires HTML output, and blocks
   when Chrome is unavailable (`scripts/verify_clean_environment.ps1:174-284,
   348-362`).
2. **Deterministic command-plan binding.** `_make_run` compares every declared
   gate command with the fixed plan and blocks empty, unknown, or mismatched
   commands (`scripts/verify_issue.py:597-605,785-800`).
3. **Mandatory output captures/checksums.** `_validate_output_files` rejects
   absent, empty, mismatched, unsafe, or corrupt output path/checksum pairs and
   verifies SHA-256 content (`scripts/verify_issue.py:361-415,810-822`).
4. **Mandatory per-run environment hash.** A run with a missing, blank, or
   mismatched environment hash is invalid (`scripts/verify_issue.py:613-623`).
   The clean-environment stage builder records source and environment hashes on
   every stage (`scripts/verify_clean_environment.ps1:92-127`).
5. **Package/build/browser/UI screenshot authenticity.** Required package,
   build, browser, and UI runs all require screenshot metadata; the verifier
   checks path containment, suffix, SHA-256, positive integer dimensions, and
   image header dimensions rather than trusting declared metadata
   (`scripts/verify_issue.py:418-554,824-835`).

The verifier remains read-only and always returns `tracker_mutated=False`; no
issue or remote state mutation is present. `execution_allowed` and the
existing closure/operations contracts remain unchanged.

## CODE-QUALITY verdict - APPROVED WITH MINOR FOLLOW-UP

The implementation is deterministic, local-only, redacts captured output,
keeps evidence paths contained, converts missing fixed tools to typed blocked
runs, and retains compatible optional fields on `VerificationRun`. The tests
now cover each prior Important failure path and binary screenshot validation.

### Critical findings

None.

### Important findings

None. The prior five Important findings are closed by the evidence above.

### Minor findings

1. The clean-environment manifest's synthetic `venv` and some blocked
   dependency stages use `New-Stage` without stdout/stderr paths, while the
   Python verifier deliberately requires at least one captured output for each
   run. `CLEAN-ENVIRONMENT` is not a closure-matrix issue and therefore is not
   directly passed to `verify_issue`; this is a compatibility/documentation
   limitation, not an approval blocker.
2. Screenshot authenticity is a stdlib header/dimension check rather than a
   full pixel decoder (for example, PNG CRC/IDAT completeness is not checked).
   It rejects the prior text-file/fabricated-dimension bypass and is adequate
   for the current local evidence contract; a full decoder can be added if
   stronger forensic authenticity is later required.

## Fresh verification commands and results

All commands below were run in the worktree with `.venv\Scripts\python.exe`.

```text
pytest tests/release/test_verification_automation.py tests/release/test_clean_environment.py tests/release/test_package_matrix.py tests/operations/test_verification_records.py -q --tb=short
31 passed (exit 0)

pytest tests/release -q --tb=short
26 passed (exit 0)

pytest tests/operations -q --tb=short
1 flaky/pre-existing failure, 80 passed (exit 1):
  test_recovery_of_interrupted_second_real_writer_preserves_first_commit
  (expected ['rolled_back'], observed ['recovery_required', 'rolled_back'])
The failed test was rerun alone and passed (exit 0); Task 5 changes contain no
operations-source changes.

ruff check scripts/verify_issue.py tests/release/test_verification_automation.py tests/release/test_clean_environment.py tests/release/test_package_matrix.py scripts/dev_finish_check.py src/etf_cockpit/core/closure.py src/etf_cockpit/operations/models.py
All checks passed (exit 0)

python -m compileall -q scripts src tests/release tests/operations
exit 0

python -m pip check
No broken requirements found (exit 0)

PowerShell Parser.ParseFile(scripts/verify_clean_environment.ps1)
AST_OK (exit 0)
```

An additional temporary positive-manifest smoke assembled all DATA-05 fixed
commands, valid hashes/checksums, and 1x1 PNG evidence; `verify_issue` returned
`pass` with no limitations (exit 0). The focused negative tests also exercised
command mismatch, empty captures, missing run environment hash, package
screenshot omission, fake image bytes, and missing fixed-tool handling.

## Final recommendation

Approve the Task 5 implementation for integration. Keep the existing
operations-test flaky failure and the two minor follow-ups documented; do not
close any issue or alter closure-matrix/tracker state as part of this review.
