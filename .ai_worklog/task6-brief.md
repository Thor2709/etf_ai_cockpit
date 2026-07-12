# Wave 3 Task 6 brief - Structured Workflow Runtime and Session Trace

## Scope

Verify and extend the existing `WorkflowController`/`logs/session.jsonl`
authority seam for `ISSUE-0069`, `UPDATEV2-0027` and `ISSUE-0012`. The baseline
already contains the typed workflow state machine, redaction, failure
fingerprints, session-event projection, dashboard background workers and
progress panel. This task owns the remaining keyboard-operable primary
workflow-button contract and fresh runtime evidence.

## Binding requirements

- Preserve `execution_allowed=false`; no broker, credentials, order routing or
  autonomous portfolio management.
- Keep `logs/session.jsonl` as the authoritative current-session trace; do not
  reintroduce a second default workflow log.
- Preserve action IDs across button click, workflow start/step/finish/failure,
  output paths and visible Activity Log state.
- Preserve redaction and logging-failure tolerance.
- Do not close any issue unless its complete closure matrix evidence passes.

## Owned files

- Modify `src/etf_cockpit/app/pages/dashboard.py`.
- Test `tests/test_workflow_runtime.py` and affected Flet/startup tests.
- Record RED/GREEN/review/package/smoke evidence in the Task 6 report.

## Stop boundary

Do not begin Task 7. After independent review and safe integration, update the
local ledger, run state and GitHub mirror, then select the next dependency-valid
task.
