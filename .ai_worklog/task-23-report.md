# Wave 5 Task 23 bounded verification-fix and release-candidate report

Date: 2026-07-15
Branch: `wave5/task23-working`
Worktree: `etf_ai_cockpit/.worktrees/TASK22-RECONCILIATION`
Base: `ff75414` (local Task 22 reconciliation checkpoint)

## Scope

This checkpoint addresses verified defects exposed while completing the Task 22
full-suite and Task 23 closure preparation: detached Flet controls in headless
table filtering, nullable identity values in contradictory-identifier checks,
pandas Arrow-backed fixture assignment for malformed metadata cases, and the
reproducible Windows RC packaging path. No product scope, authority, scoring,
execution or DATA-05 coverage was changed.

## RED evidence

The focused behavioural bundle was run before the fixes and exited `1`: the
detached Flet update raised `Control must be added to the page first`, nullable
identity rows were incorrectly filtered, and malformed scenario/freshness cases
either produced an available/high result or failed during Arrow string
assignment.

The independent-review regression was then run before its implementation fix:

```text
cached-python -m pytest tests/test_accessible_tables.py::test_accessible_table_does_not_mask_unrelated_runtime_errors -q --tb=short
```

Observed exit code: `1` with `Failed: DID NOT RAISE RuntimeError`, proving that
the broad detached-control substring suppressed an unrelated persistence error.

## GREEN evidence

Applied the smallest changes:

- suppress only the exact Flet detached-control phrase `control must be added
  to the page first` in table and status updates;
- treat pandas missing scalars as absent when evaluating contradictory
  instrument identifiers;
- keep malformed scenario and freshness fixture columns as object dtype before
  injecting list/array/non-string values;
- make the canonical PyInstaller spec and Windows batch path reproducible for
  the `0.1.0rc1` release candidate, including runtime DLLs, hidden imports and
  application version metadata.

Focused verification:

```text
cached-python -m pytest tests/test_accessible_tables.py tests/test_task19_instrument_detail.py tests/test_instrument_detail.py tests/test_instrument_identity.py -q --tb=short
```

Result: exit code `0` (all collected tests passed).

Additional checks:

```text
cached-python -m pytest tests -q --tb=short
cached-python -m compileall -q src tests
ruff check src/etf_cockpit/app/components/tables.py src/etf_cockpit/app/selectors/instrument_detail.py tests/test_accessible_tables.py tests/test_task19_instrument_detail.py
system-git diff --check
```

The final authoritative suite exited `0` (`build/full-task23-final2.log`,
`build/full-task23-final2.exit`), compileall, scoped Ruff and diff checks also
exited `0`. Only the repository's existing Pandas/deprecation warnings were
reported.

## Release-candidate evidence

- `ETF_AI_Cockpit.spec` discovers package paths at build time, carries
  NumPy/SciPy/Pandas/PyArrow runtime DLLs, includes the required Pandas hidden
  import, excludes optional model and desktop-only modules, and uses
  `packaging/windows_version_info.txt` for application metadata.
- `scripts/build_windows.bat` targets `0.1.0rc1`, invokes the repository
  PyInstaller spec and applies the version resource. It could not be executed
  in this environment because the repository `.venv` is inaccessible
  (`ensurepip`/ACL failure); this is recorded as unverified, not as a pass.
- Reviewed onedir native build:
  `build/flet_dist_release_final/ETF_AI_Cockpit`, approximately 578 MB,
  executable SHA-256
  `339B20194C2AE0FF0238A2437B0504081005F328E7F725ABCC0F940571B08BF1`,
  Windows ProductVersion `0.1.0rc1`.
- Complete documented portable archive:
  `build/ETF_AI_Cockpit_Portable_v0.1.0rc1.zip`, 254,392,741 bytes, SHA-256
  `A282F48A53844848E7FD42A3712F1F405B6A189A11EB8CE7FA547F9BDBD35ABD`.
  Extracted outside the repository into
  `release_test_task23_rc1_final_20260714`; extraction produced 3,271 files
  and the packaged launcher returned HTTP 200 on port 8649 without the repo
  virtual environment.
- Optional model and credential-dependent functions remain explicitly
  unavailable/setup-required; `execution_allowed` remains `false`.

## Review state and closure boundary

The first fresh independent reviewers rejected the broad RuntimeError filter and
the unreproducible release boundary. Those findings were reproduced by RED
tests and fixed. Fresh reviewer Planck re-reviewed the stable current tree and
approved specification compliance and code quality with no Critical,
Important or Minor findings. The review noted only non-blocking mixed-line-ending
noise.

Task 23 remains implementation-complete but closure-pending: the full 41-issue
dossier/evaluator, rendered browser/computer-use matrix, clean first-run package
matrix, remote integration and issue transitions are not yet complete. No issue
is moved to `issues/closed.md` by this bounded checkpoint.

`execution_allowed` remains `false`.

## Post-merge lint correction - 2026-07-15

The fresh post-merge scoped Ruff run identified one unused fixture variable in
`tests/test_trust_critical_artifacts.py`. The variable was removed without
changing the test contract. The trust-artifact focused suite passed after the
correction, as did the scoped Ruff check, compileall and diff check. This is a
test-quality correction only; no product authority or issue state changed.
