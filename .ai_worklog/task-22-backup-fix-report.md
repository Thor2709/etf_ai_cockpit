# Task 22 backup manifest fix

## Root cause

`create_backup` delegates transient filtering to `_transient_path`. That helper
treated any path with a `logs` (or other transient) ancestor as transient,
without considering the archive name selected by the caller. Pytest's temporary
root for this regression test is under `logs/pytest_system_tmp`, so explicitly
selected `pyproject.toml` and `.ai_worklog/CHANGES.md` were both excluded and
the manifest checksum map was empty.

## RED

Command (cached CPython 3.12 runtime):

```text
set PYTHONPATH=C:\Users\thor2\AppData\Local\uv\cache\archive-v0\zb0f3XbD0hKukXUk\Lib\site-packages
C:\Users\thor2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_backup_restore.py::test_backup_manifest_keeps_actual_version_and_changelog_metadata_paths -q
```

Result: one expected assertion failure. `manifest.checksums` was `set()`
instead of `{"pyproject.toml", ".ai_worklog/CHANGES.md"}`.

## Implementation

`_transient_path` now derives the normalised archive name and exempts the
existing allow-listed release metadata names (`pyproject.toml`, version files,
`changelog.md`, `changes.md`, and `.ai_worklog/changes.md`) from transient
classification. Secret path/content checks and ordinary transient artefacts
remain unchanged.

## GREEN and regression checks

- `python -m pytest tests/test_backup_restore.py -q` - 10 passed.
- `python -m compileall -q src tests` - passed.
- `git diff --check` - passed; Git emitted only existing LF/CRLF conversion
  warnings.
- Ruff check of the changed source and focused test - passed (`All checks
  passed!`).

## Remaining concerns

Focused behaviour is correct for the approved metadata paths and all existing
tests pass. A minor bounded risk remains: the metadata exception is keyed by
archive basename, so callers must select canonical metadata roots to avoid an
unrelated transient file with the same basename being retained. This is
recorded in the canonical Task 22 manifest for later hardening.
The worktree contains unrelated pre-existing edits under
`data/.schema_versions/`; those were not modified or included in this task's
commit.
