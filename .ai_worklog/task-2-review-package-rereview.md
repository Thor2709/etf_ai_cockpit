# Wave 0 Task 2 re-review package - authority seam fix

## Review basis
- Original review package: `.ai_worklog/task-2-review-package.md` (Task 2 base snapshot to pre-fix head).
- Independent review: `.ai_worklog/task-2-review-1.md`.
- Fix report: `.ai_worklog/task-2-authority-fix-report.md`.
- Current head includes the narrow authority fix in `src/etf_cockpit/core/workflow.py`, the dashboard path correction in `src/etf_cockpit/app/pages/dashboard.py`, and observable regressions in `tests/test_workflow_runtime.py`.
- Scope remains Wave 0 Task 2 only. Task 3 and issue closure are out of scope.

## Review findings addressed
- Default `WorkflowController()` no longer creates a persistent `logs/workflow.jsonl`; lifecycle events use the existing session-event logger.
- Explicit injected `log_path` remains a compatibility/test adapter only.
- Dashboard activity-panel copy names `logs/session.jsonl`, not the retired `logs/activity_log.jsonl`.

## Current fix evidence
See `.ai_worklog/task-2-authority-fix-report.md` for RED/GREEN commands, exits, focused regression, Ruff, compilation and residual limitation. Re-run the current focused tests and inspect the current files directly.
