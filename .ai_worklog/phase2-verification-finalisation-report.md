# Phase 2 verification-finalisation workflow report

## Scope

This bounded workflow refactor separates implementation verification from release certification and makes passing evidence reusable across issues without weakening authority or safety boundaries. `execution_allowed=false` remains unchanged.

## RED evidence

- Command: `python -m pytest -q tests/release/test_verification_finalisation_policy.py --disable-warnings --maxfail=1`
- Result: exit 1 before implementation; all ten focused behaviours failed at collection with `ModuleNotFoundError: No module named 'etf_cockpit.release'`.
- Raw output: `C:\Users\thor2\AppData\Local\Temp\phase2-policy-red-20260716.txt`.

## GREEN and regression evidence

- Focused policy tests: `python -m pytest -q tests/release/test_verification_finalisation_policy.py --disable-warnings --maxfail=1` - 10 passed.
- Affected release and operations tests: `python -m pytest tests/release/test_verification_finalisation_policy.py tests/release/test_verification_automation.py tests/operations/test_verification_records.py -q --disable-warnings --maxfail=1` - 33 passed.
- Implementer release/operations regression: `python -m pytest tests/release tests/operations -q` - 117 passed.
- Scoped Ruff: `python -m ruff check src/etf_cockpit/release scripts/verify_issue.py tests/release/test_verification_finalisation_policy.py` - passed after removing two test-only lint findings.
- Compile check: `python -m compileall -q src/etf_cockpit/release scripts/verify_issue.py` - passed.

## Implementation

- `src/etf_cockpit/release/verification_records.py` provides deterministic executable-byte and domain-separated evidence hashes, exact release-record keys, atomic JSON persistence, exactly-once runner reuse, issue/reviewer references and committed-checkpoint resume loading.
- `scripts/verify_issue.py` rejects explicit staged evidence and exposes evidence state and shared record identifiers without mutating tracker state.
- Policy, AGENTS.md, programme index, active closure plan and closure matrix now bind evidence isolation, immutable promotion, shared release records, invalidation, bounded review and committed resume rules.

## Task 15 integration

Task 15 PR #204 merged at `4379132092b8f037bd6227eb4562c2bfbcaa6748`. Local issues `UPDATEV2-0017` and `UPDATEV2-0019` are closed; GitHub Issues #157 and #159 were read back and closed. No Task 16 implementation has started on this branch.

## Correction pass - 2026-07-16

- Independent review identified five blocking gaps: checkpoint redispatch wording, closure-matrix state reconciliation, immutable generation discovery, shared issue/reviewer association checks and manifest-level per-run record mapping.
- The corrections were implemented without changing the committed Windows lock implementation. Six new verifier regressions first failed, then passed after the correction: canonical generation discovery and validation, per-run shared-record mapping, rejection of ambiguous one-run plural IDs, rejection of conflicting manifest/run IDs and durable issue/reviewer association enforcement.
- The invalidated verifier/issue/operations bundle passed with 41 tests; scoped Ruff, `py_compile`, JSON/YAML parsing and `git diff --check` passed. The already-passing 17-test focused release record remains valid and was not rerun because its source and test files were unchanged.
- The corrected Phase 2 change set received final independent approval with no Critical, Important, Blocking or material findings. No Task 16 dispatch or worktree is part of this run; commit, push, pull-request integration and `origin/main` verification remain.

## Review and next gate

No full-suite, build or browser gate is repeated here because the Task 15 executable/source inputs are unchanged and the Phase 2 deliverable is a bounded verification-record workflow; any source-sensitive release certification will use a new key after this branch is integrated.
