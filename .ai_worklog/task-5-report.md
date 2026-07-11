# Wave 0 Task 5 implementation report

## Scope

Task 5 implements the REL-03 evidence-verification boundary: deterministic,
source- and environment-bound verification manifests, fixed command planning,
freshness/checksum/reviewer validation, a fail-closed clean-environment script,
package-mode declarations, and finish-check metadata. The verifier is
read-only and cannot mutate the local issue ledger or a remote tracker.

Implementation was performed on branch `wave0/task5-evidence-automation` from
base `d5ea661` (Task 4 integration checkpoint). The delegated implementer was
interrupted after the implementation and test evidence was present but before
it returned its report; this report records the independently reproduced
evidence without attributing review approval to the implementer.

## RED evidence

Command, run before behavioural implementation:

```powershell
& "C:\\Users\\thor2\\Desktop\\Trading App\\etf_ai_cockpit\\.venv\\Scripts\\python.exe" -m pytest tests\\release\\test_clean_environment.py tests\\release\\test_package_matrix.py tests\\operations\\test_verification_records.py -q --tb=short
```

The command exited `1`. The 11 existing verification-record tests passed and
three focused tests failed for the real missing behaviour: the clean-
environment script did not exist, `scripts.verify_issue` was unavailable, and
`PACKAGE_MODES` was unavailable. The failures were behavioural missing-artifact
failures, not syntax or import failures in the test itself.

## GREEN and refactor evidence

Fresh focused run after implementation:

```powershell
& "C:\\Users\\thor2\\Desktop\\Trading App\\etf_ai_cockpit\\.venv\\Scripts\\python.exe" -m pytest tests\\release\\test_verification_automation.py tests\\release\\test_clean_environment.py tests\\release\\test_package_matrix.py tests\\operations\\test_verification_records.py -q --tb=short
```

Result: `20 passed`.

Affected release and operations regression run:

```powershell
& "C:\\Users\\thor2\\Desktop\\Trading App\\etf_ai_cockpit\\.venv\\Scripts\\python.exe" -m pytest tests\\release tests\\operations -q --tb=short
```

Result: `81 passed`.

Quality checks:

```powershell
ruff check scripts/verify_issue.py scripts/dev_finish_check.py src/etf_cockpit/core/closure.py src/etf_cockpit/operations/models.py tests/release/test_verification_automation.py tests/release/test_clean_environment.py tests/release/test_package_matrix.py
& "C:\\Users\\thor2\\Desktop\\Trading App\\etf_ai_cockpit\\.venv\\Scripts\\python.exe" -m compileall -q scripts src tests/release
& "C:\\Users\\thor2\\Desktop\\Trading App\\etf_ai_cockpit\\.venv\\Scripts\\python.exe" -m pip check
```

Results: Ruff passed; compilation passed; `pip check` reported no broken
requirements.

The PowerShell parser reported `PS_PARSE=0`. A CLI smoke against an empty
temporary evidence root returned JSON status `blocked`, missing required gates,
`tracker_mutated=false`, and process exit `2`.

## Full-suite baseline

The full command collected 375 tests and reproduced seven unrelated existing
failures in `tests/test_simple_scores.py` and
`tests/test_trust_critical_artifacts.py` (generated market-candidate/identity
artefacts and the pre-existing trust-artifact count). The Task 5 focused,
release and operations suites introduce no new failures. The full-suite result
is recorded as a pre-existing baseline limitation, not as Task 5 closure
evidence.

## Files changed

- `scripts/verify_issue.py`
- `scripts/verify_clean_environment.ps1`
- `scripts/dev_finish_check.py`
- `src/etf_cockpit/core/closure.py`
- `src/etf_cockpit/operations/models.py`
- `configs/closure_matrix.yaml`
- `README_FIRST_RUN.md`
- `tests/release/test_verification_automation.py`
- `tests/release/test_clean_environment.py`
- `tests/release/test_package_matrix.py`

No issue state was changed. No GitHub Issue was written. `execution_allowed`
remains `false`; no execution authority, score weight, model authority,
portfolio target, research threshold or coverage scope changed.

## Closure checklist at implementation boundary

| Criterion | State | Evidence or reason |
|---|---|---|
| Deterministic read-only verifier | passed | Focused tests and CLI smoke |
| Source/environment hash binding | passed | Focused hash-mismatch tests |
| Freshness and checksum validation | passed | Stale/checksum tests |
| Missing/skipped/informational evidence blocked | passed | Focused failure-path tests |
| Independent reviewer distinct from builder | passed | Focused reviewer-identity test |
| Package/browser screenshot metadata | passed | Focused screenshot test |
| Clean-environment fail-closed script | passed | Script contract tests and parser |
| Finish-check metadata and deterministic package modes | passed | Release tests and Ruff |
| Migration/package/browser/source runtime evidence | pending | Later task-level and environment/package gates |
| Independent task review | pending | Fresh reviewer required after this report |
| Issue closure | pending | Owning issues require later UI/package/browser and full closure evidence |
