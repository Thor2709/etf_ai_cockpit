# Wave 0 Task 5 brief - evidence automation without automatic issue closure

## Owning scope

Implement the Task 5 section of
`docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md`
and the approved REL-03 contract. The deliverable is a deterministic,
source/environment-bound verification package that can be independently
approved or rejected. It must never move a local or remote issue between open
and closed states.

## Files owned

- Create `scripts/verify_issue.py`.
- Create `scripts/verify_clean_environment.ps1`.
- Create `tests/release/test_clean_environment.py` and
  `tests/release/test_package_matrix.py`.
- Modify `scripts/dev_finish_check.py`, `configs/closure_matrix.yaml` and
  `README_FIRST_RUN.md` only for the evidence-policy interfaces owned here.
- Add focused Task 5 worklog, RED/GREEN report and independent review report.

## Required observable behaviour

- `verify_issue(issue_id, ...)` reads the closure matrix and its verification
  policy, validates requirement version and source/environment hashes, checks
  output checksums and freshness, and returns a typed result with
  `status` (`pass`, `fail` or `blocked`), `limitations`, `tracker_mutated=False`
  and the captured verification runs.
- A stale or mismatched source hash is `blocked` and explicitly names the
  source-hash limitation. Missing required layers, skipped tests,
  live-informational-only results, missing package/browser evidence, fake or
  missing screenshot metadata, corrupted output checksums and incomplete
  independent review are never counted as pass.
- Fixed command selection is deterministic and injectable for tests. Captured
  stdout/stderr and output files are local, redacted where needed and
  SHA-256-addressed. The verifier never writes `issues/open.md`,
  `issues/closed.md`, closure status, GitHub Issues or credentials.
- The clean-environment script must fail closed with an explicit blocked
  result when required tools/dependencies are absent; it must not claim a
  package/browser pass from a skipped command.
- Preserve the existing `VerificationRun`, closure matrix, audit/recovery and
  static-boundary foundations. `execution_allowed` remains false.

## RED-GREEN-REFACTOR contract

Write behavioural tests first and record a genuine failing run. Implement the
smallest compatible evidence model/manifest and command runner. Refactor only
to keep policy and checksum validation deterministic and testable. Run the
focused Task 5 tests, existing verification-record tests, release/operations
regressions, scoped Ruff and compileall before review.

## Global constraints

No scope drift, no authority inflation, no issue closure, no external uploads,
no broker capability, no credentials, no destructive data changes, and no
invented evidence. Existing local issue files remain authoritative.
