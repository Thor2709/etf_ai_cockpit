# Task 22 cmd-only Windows build fix

## Task completed

`scripts/build_windows.bat` and its generated native launcher are now
cmd.exe-only. PowerShell is no longer invoked for the broken-venv archive or
the native-launcher readiness wait.

## Files and symbols examined

- `scripts/build_windows.bat` - venv validation/archive block and
  `:write_native_launcher`.
- `tests/release/test_build_windows.py` - focused static contract tests.

## Findings or changes

- Replaced the PowerShell `Move-Item` archive path with a timestamped cmd
  `move`, preserving the broken venv when the archive operation fails and
  adding a random suffix on a same-stamp collision.
- Replaced generated `Start-Sleep` with `timeout /t 1 /nobreak`.
- Kept pip installation, Flet packaging and error-level gates unchanged.

## Evidence

RED (before the batch change, cached CPython 3.12):

```text
FF [100%]
FAILED test_windows_build_and_generated_native_launcher_use_cmd_only
  assert "powershell" not in lowered
FAILED test_broken_venv_backup_remains_timestamped_and_package_gates_are_intact
  assert "%date%" in lowered
exit_code=1
```

GREEN (after the batch change, cached CPython 3.12):

```text
.. [100%]
exit_code=0
```

## Commands or tests run

- Cached CPython focused pytest: `tests\\release\\test_build_windows.py -q` -
  2 passed, exit 0.
- Cached CPython compile check: `-m compileall -q scripts tests` - exit 0.
- `git diff --check` - exit 0; only existing LF/CRLF conversion warnings.

## Remaining uncertainty and risk

The Windows packaging command itself was not run in this environment; the
static contract verifies the generated launcher text and preserved build
gates. No PowerShell command was executed. The timestamp uses the host's cmd
`%date%` and `%time%` values, sanitised for a directory name.

## Recommended next action

Run the approved Windows packaging and native-launcher smoke gates on a host
with the required Python/Flet tooling, then record that result in the canonical
Task 22 evidence manifest. Commit SHA is provided in the implementation
hand-off.
