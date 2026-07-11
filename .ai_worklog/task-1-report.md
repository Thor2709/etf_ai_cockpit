# Wave 0 Task 1 Implementer Report

## Status

`FIXED_LOCALLY_REVIEW_PENDING` - the Round-1 Important independent-review finding is fixed and locally verified; the required fresh independent re-review remains pending. No issue was closed.

## Scope delivered

- Added typed Pydantic `VerificationRun` and `ClosureEvidenceRecord` records.
- Enforced that approved closure evidence uses non-empty, normalised actor IDs and cannot use the builder as the required independent reviewer.
- Replaced the closure parser's bare list return with an honestly iterable `ClosureMatrix` carrying `programme_schema_version`, `historic_baseline_count` and `record_for()`.
- Migrated `configs/closure_matrix.yaml` to programme schema 2, preserved the historic baseline count of 41, and added DATA-05 as the forty-second active record with `still_open` status.
- Added the exact DATA-05 gate set: source, schema, tests, UI, audit, package and browser.
- Preserved all historic issue identities and statuses. No execution, broker, credential, upload or unrelated product functionality was added.

## Repository-grounded plan seam

The original Task 1 file list omitted `tests/test_closure_matrix.py`, although that regression asserted exactly 41 iterable records. Returning 41 while hiding DATA-05 would have contradicted the requirement for 42 explicitly represented active records. The controller confirmed and updated the brief to authorise a narrow migration of this test: it now proves 42 active records, the unchanged historic 41-ID subset, and separately open DATA-05.

## Changed files

### Product/configuration

- `src/etf_cockpit/operations/__init__.py` - new public exports.
- `src/etf_cockpit/operations/models.py` - new typed verification and closure-evidence records.
- `src/etf_cockpit/core/closure.py` - new `ClosureMatrix`, schema metadata parsing, lookup and expanded gate vocabulary.
- `configs/closure_matrix.yaml` - schema 2 metadata and separate open DATA-05 record.

### Tests

- `tests/operations/test_verification_records.py` - valid record, invalid result and independent-review behaviour.
- `tests/release/test_issue_evidence.py` - schema/baseline/count/status and exact DATA-05 gates.
- `tests/test_closure_matrix.py` - migrated historic-baseline regression.

### Authorised durable checkpoints

- `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-progress-ledger.md`
- `RUN_STATE.json`
- `.ai_worklog/PLAN.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/task-1-report.md`

## TDD evidence

### RED

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py -q
```

Exit code: `1`.

Observed output:

```text
ERROR collecting tests/operations/test_verification_records.py
ModuleNotFoundError: No module named 'etf_cockpit.operations'
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

This was the expected missing-feature cause named by the task brief and occurred before any production implementation.

### GREEN

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q
```

Exit code: `0`.

Observed output:

```text
...............                                                          [100%]
```

Result: 15 focused and closure-matrix regression tests passed.

### Refactor/focused rerun

No behavioural expansion was needed after GREEN. The focused suite was rerun together with scoped lint and compilation:

```text
...............                                                          [100%]
All checks passed!
FOCUSED_EXIT=0 RUFF_EXIT=0 COMPILE_EXIT=0
```

## Other verification results

- Full regression: `.\.venv\Scripts\python.exe -m pytest tests -q` - exit `0`, reached `[100%]` with no failures.
- Scoped Ruff: `.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\operations src\etf_cockpit\core\closure.py tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py` - exit `0`, `All checks passed!`.
- Compilation: `.\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit\operations src\etf_cockpit\core\closure.py` - exit `0`.
- Direct matrix probe - exit `0`: `programme_schema_version=2`, `historic_baseline_count=41`, `active_record_count=42`, DATA-05 `still_open`, exact gates `audit/browser/package/schema/source/tests/ui`.
- `scripts/closure_status.py --matrix configs/closure_matrix.yaml` parsed and emitted all 42 records, including DATA-05 with all seven gates missing. It exited `1` as designed because open issues are not closure-ready; this was a consumer smoke, not a passing closure assertion.
- Two earlier combined full-suite capture attempts returned partial progress only and were discarded as evidence. The definitive independently polled full-suite run above exited `0` at `[100%]`.

Full-suite warnings were pre-existing warnings from GluonTS JSON handling, pandas mixed CSV dtypes and pandas empty/all-NA concatenation deprecation. No new warning originated in Task 1 files.

## SHA-256 checkpoint

| File | SHA-256 |
|---|---|
| `src/etf_cockpit/operations/__init__.py` | `8c8ee081d0a4fdc3e72a543702ccca1d863413fdf79ba51ff8f7f29681740e48` |
| `src/etf_cockpit/operations/models.py` | `e648ff729aa29beb2754a44911d8293ec0fcd142941fbb4c52e466f8487275f8` |
| `src/etf_cockpit/core/closure.py` | `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e` |
| `configs/closure_matrix.yaml` | `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595` |

## Self-review

- `ClosureMatrix.__iter__` and `__len__` expose all 42 records; DATA-05 is not hidden behind compatibility behaviour.
- The old 41 IDs are asserted unchanged as a subset, and the YAML metadata records `historic_baseline_count: 41`.
- DATA-05 is explicitly `still_open`, has empty evidence paths and cannot become ready without every named gate.
- Historic evidence gate names (`export`, `build`) remain valid, while new (`schema`, `audit`, `package`) gates are added without rewriting historic criteria.
- Existing closure-status iteration remains compatible and was smoke-tested.
- The approved-review validator applies only to `review_result="approved"`, matching the supplied minimal contract; rejected evidence may record the same actor.
- No existing issue status, evidence path or identity was intentionally changed.
- `RUN_STATE.json` remains parseable and records independent review as pending.

## Concerns and handoff

- Fresh independent review is still required before Task 1 may be marked complete in the programme plan or used as closure evidence.
- The RED state is an import-time collection error because the required package did not yet exist. This exactly matches the task brief's expected missing-model failure, but it is less granular than a collected assertion failure.
- Full-suite warnings are pre-existing and outside this task's scope.
- No Git repository exists, so no branch, worktree, commit or remote action was performed.

## Important Independent-Review Finding Fix - 2026-07-11

Round 1 of the independent review found an Important bypass in approved `ClosureEvidenceRecord` actor validation: blank actor identifiers and whitespace-equivalent builder/reviewer identities were accepted. This fix is deliberately limited to that finding.

### TDD evidence

RED command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py -q
```

Exit code: `1`.

Observed failures were the expected real-Pydantic validation gaps: blank `independent_reviewer` and whitespace-equivalent reviewer tests did not raise `ValidationError`; a valid approved-record test also proved whitespace was not stripped before storage.

GREEN and focused regression command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q
```

Exit code: `0` - `18 passed`.

Additional scoped checks:

```powershell
.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\operations\models.py tests\operations\test_verification_records.py
.\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit\operations
```

Both exited `0`; Ruff reported `All checks passed!`.

### Delivered change

- For approved evidence only, both actor IDs are stripped before storage and comparison.
- Approved evidence now rejects empty normalised builder or independent-reviewer IDs and rejects normalised same-actor identities.
- New tests exercise real Pydantic validation for a blank reviewer, a whitespace-equivalent reviewer and successful normalised storage.

### Current checkpoint

- The Round-1 Important finding is fixed locally, but fresh independent re-review remains pending.
- The recorded Minor closure-metadata observation was not changed.
- Matrix schema 2, the historic baseline of 41, the 42 active records, all issue statuses and `execution_allowed: false` remain unchanged.
- Current SHA-256: operations init `8c8ee081d0a4fdc3e72a543702ccca1d863413fdf79ba51ff8f7f29681740e48`; operations models `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`; closure parser `59a16b3e6b24f70dcb2619f3834d8a55ca095f85c741b691f75b42b1f9cc484e`; matrix `c8de2825d7e5ac0be47a752eb6f3c420390f019ebd0f2345e7e995dea936f595`.

## Round-2 Important Checkpoint-Evidence Correction - 2026-07-11

Deterministic pre-fix verification intentionally failed (exit 1): the current `operations/models.py` hash was `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`, while `.ai_worklog/PLAN.md` still contained stale `e648ff729aa29beb2754a44911d8293ec0fcd142941fbb4c52e466f8487275f8`; the reviewer-finding-fix TESTING block also contained ambiguous command prefixes.

After the documentation-only correction, the same deterministic check passed (exit 0): the latest checkpoint has no stale hash, and the current model hash matched the checkpoint. Matrix schema 2, historic baseline 41, 42 active records and DATA-05 `still_open` remain unchanged. Fresh independent re-review remains pending; no issue was closed.

## Round-3 Important Checkpoint-Evidence Correction - 2026-07-11

The durable PLAN checkpoint now records the required slash-form commands verbatim, with individual exit codes, current model checksum, schema/count/status state, no-closure state and fresh independent re-review pending. No source, tests, matrix, issue status or authority changed.

## Final Independent Task Review Approval - 2026-07-11

- Fresh independent reviewer approved Task 1 after confirming the actor-validation and checkpoint-evidence findings were resolved.
- Post-review controller verification passed 18 focused tests, scoped Ruff, compilation and source snapshot smoke.
- The retained metadata-validation Minor is recorded for broad final triage. This approval is task-level only; no issue was closed.
