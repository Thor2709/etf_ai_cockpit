# Wave 0 Task 2 - Authority seam fix

Date: 2026-07-11  
Status: in progress; no commit and no issue-status update.

## RED evidence

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workflow_runtime.py -q
```

Result: exit 1, `2 failed, 5 passed`.

Expected failures:

- `test_default_workflow_lifecycle_uses_session_trace_without_secondary_log` found the default-created `logs/workflow.jsonl` after start, step and finish, even though the three lifecycle events reached `logs/session.jsonl`.
- `test_activity_panel_names_the_session_trace` found no `logs/session.jsonl` text because the activity panel still named the retired `logs/activity_log.jsonl` path.

The next change is limited to suppressing the secondary append when `WorkflowController` is constructed without an explicit adapter path, and correcting the dashboard trace label.

## GREEN evidence

Implementation:

- `WorkflowController(log_path=None)` now omits the secondary append entirely and sends lifecycle events only through its existing session-event logger.
- An explicitly supplied `log_path` still enables the narrow append adapter used by the existing workflow runtime tests.
- The dashboard activity panel now calls `logs/session.jsonl` the session trace.

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workflow_runtime.py -q
```

Result: exit 0, `7 passed`.

## Focused regression and static verification

Focused regression command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workflow_runtime.py tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_trust_critical_artifacts.py -q
```

Result: exit 0, `28 passed`. Existing warnings only: GluonTS JSON performance and pandas mixed-dtype loading in trust-artifact tests.

Scoped Ruff command:

```powershell
.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\core\workflow.py src\etf_cockpit\app\pages\dashboard.py tests\test_workflow_runtime.py
```

Result: exit 0, `All checks passed!`.

Compilation command:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit\core\workflow.py src\etf_cockpit\app\pages\dashboard.py tests\test_workflow_runtime.py
```

Result: exit 0.

## Changed files and residual limitation

- `src/etf_cockpit/core/workflow.py`: default controller construction has no secondary log path; `_append` is also defensive if reached without an explicit path.
- `src/etf_cockpit/app/pages/dashboard.py`: activity-panel copy names `logs/session.jsonl` as the session trace.
- `tests/test_workflow_runtime.py`: regressions cover default lifecycle events in the session trace, absence of the secondary log, and the rendered activity-panel path.
- `.ai_worklog/task-2-authority-fix-report.md`: this RED-GREEN-verification record.

Residual limitation: a caller that explicitly injects `log_path` still receives the legacy append adapter for compatibility with existing tests. Default production construction does not use it, and the session event logger remains the default lifecycle persistence path. No commit, issue-status update or Task 3 work was performed.
