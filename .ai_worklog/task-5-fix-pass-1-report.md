# Wave 0 Task 5 fix pass 1

## Scope

Resolved every Important finding from `.ai_worklog/task-5-review.md` and the
practical Minor findings without changing issue ledgers, closure plans,
`execution_allowed=false`, or tracker state.

## RED evidence

Added focused behavioural tests first in:

- `tests/release/test_verification_automation.py`
- `tests/release/test_clean_environment.py`

The pre-fix run was:

```text
.venv\\Scripts\\python.exe -m pytest tests/release/test_verification_automation.py tests/release/test_clean_environment.py -q --tb=short
8 failed, 13 passed
```

The failures reproduced command-plan bypass/empty and unknown commands,
missing output captures, missing run environment hashes, package screenshot
omission, missing-tool `OSError`, synthetic package/no browser stages, and
uppercase/no per-run hash clean-environment output.

## GREEN implementation

### `scripts/verify_issue.py`

- Normalises manifest command text and binds every declared gate to the fixed
  deterministic command plan; empty, unknown, and mismatched commands block.
- Requires non-empty output path/checksum pairs and verifies each SHA-256.
- Requires a run-level environment hash; no expected-hash substitution occurs.
- Requires screenshot metadata for browser, UI, package, and build gates.
- Adds stdlib-only PNG/JPEG/WebP/BMP header and dimension checks so text or
  fabricated screenshot metadata cannot pass.
- Converts missing fixed-command tools (`OSError`/`FileNotFoundError`) into a
  blocked captured run with exit code 127 and a limitation.

### `scripts/verify_clean_environment.ps1`

- Package is now an independent stage that verifies the build output marker,
  contained portable package directory, and non-empty `ETF_AI_Cockpit.bat`
  launcher. It no longer copies the build result.
- Missing package tooling/output/launcher is blocked.
- Adds an independent Chrome headless stage; missing Chrome is blocked and a
  successful stage requires HTML output.
- Lowercases run/overall statuses and records source/environment hashes on
  every stage.

## GREEN evidence

```text
.venv\\Scripts\\python.exe -m pytest tests/release/test_verification_automation.py tests/release/test_clean_environment.py -q --tb=short
21 passed

.venv\\Scripts\\python.exe -m pytest tests/release -q --tb=short
26 passed

.venv\\Scripts\\python.exe -m pytest tests/operations -q --tb=short -k "not group_reader_cannot_observe_mixed_generation_during_activation"
72 passed

.venv\\Scripts\\python.exe -m ruff check scripts/verify_issue.py tests/release/test_verification_automation.py tests/release/test_clean_environment.py tests/release/test_package_matrix.py scripts/dev_finish_check.py src/etf_cockpit/core/closure.py src/etf_cockpit/operations/models.py
All checks passed!

.venv\\Scripts\\python.exe -m compileall -q scripts src tests/release tests/operations
COMPILEALL_OK

.venv\\Scripts\\python.exe -m pip check
No broken requirements found.

PowerShell Parser.ParseFile(scripts/verify_clean_environment.ps1)
AST_OK
```

The combined release/operations command was also run. Release passed; one
pre-existing Windows concurrency test,
`test_group_reader_cannot_observe_mixed_generation_during_activation`,
reported `PermissionError(13, 'Toegang geweigerd')` while its writer thread
was activating files. The remaining operations tests pass as shown above;
the failure is unrelated to the Task 5 evidence changes.

## Limitations

- The clean-environment script was syntax-validated but not executed against a
  fresh package/Chrome installation: doing so would create a venv, run the
  package build, and modify local build/evidence artefacts. Its fail-closed
  missing-tool paths are covered by the static behavioural tests.
- No issue ledger, closure status, remote tracker, credentials, or plan file
  was modified.
