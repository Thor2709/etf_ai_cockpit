# Task 22 matrix-status fix report

## Scope

Normalise five closure-matrix records that used the unsupported status
`implementation_complete_closure_pending`. The repository closure loader
accepts `still_open`, `closed`, `blocked` and `deferred`; these records retain
their implementation checkpoints and pending gates and therefore remain open.

## RED evidence

The authoritative Task 22 full-suite run failed while loading
`configs/closure_matrix.yaml` with `ValueError: Unsupported closure status
implementation_complete_closure_pending` from
`src/etf_cockpit/core/closure.py`. The invalid records were
`UPDATEV2-0028`, `ISSUE-0036`, `ISSUE-0041`, `ISSUE-0042` and `ISSUE-0044`.

Command:

```text
set PYTHONPATH=C:\Users\thor2\AppData\Local\uv\cache\archive-v0\zb0f3XbD0hKukXUk\Lib\site-packages&& C:\Users\thor2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q
```

Result: non-zero exit during release/closure verification. This pre-fix
failure was captured in the original Task 22 run output; the refreshed
canonical manifest records the post-fix verification below and does not
restate the obsolete failure as current evidence.

## GREEN evidence

The five statuses now use `still_open`; no implementation checkpoint or
pending-gate content was removed. The pre-fix unsupported-status failure was
observed during the earlier full-suite run and is now superseded by the
post-fix manifest entry `closure-status-post-fix`; the canonical manifest does
not claim that the old failure remains current. The following verification was
run at the combined Task 22 review boundary:

```text
set PYTHONPATH=C:\Users\thor2\AppData\Local\uv\cache\archive-v0\zb0f3XbD0hKukXUk\Lib\site-packages&& C:\Users\thor2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/release/test_issue_evidence.py tests/release/test_verification_automation.py tests/test_closure_matrix.py -q
```

Result: 27 passed, exit 0. Artefact checksum and command are recorded in
`evidence/final/verification-manifest.json`.

Additional checks:

```text
set PYTHONPATH=C:\Users\thor2\AppData\Local\uv\cache\archive-v0\zb0f3XbD0hKukXUk\Lib\site-packages&& C:\Users\thor2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m compileall -q src tests
git -c safe.directory=* diff --check
```

## Files changed

- `configs/closure_matrix.yaml`
- `.ai_worklog/task-22-matrix-status-fix-report.md`

## Closure impact

This is a release-verification defect correction. It does not close any issue,
change product authority or alter `execution_allowed=false`; the five records
remain open pending their existing gates.
