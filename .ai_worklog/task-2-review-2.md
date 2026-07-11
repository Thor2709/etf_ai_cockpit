# Wave 0 Task 2 independent re-review 2

Date: 2026-07-11  
Reviewer: fresh independent Task 2 reviewer  
Scope: Wave 0 Task 2 only. This approval does not close any issue and does not approve Task 3 or later work.

## Verdict

**APPROVED**

Both prior Important findings are resolved. The default workflow lifecycle now has one persistent event authority, `logs/session.jsonl`; the explicitly injected workflow log path is a documented non-default compatibility seam; and the dashboard names the session trace correctly. The original Task 2 event-store, redaction, recovery, integrity-error and activity-projection requirements remain satisfied.

## Prior Important findings - re-verification

1. **No default secondary workflow log** - resolved.

   - `WorkflowController.__init__` defaults `log_path` to `None` in `src/etf_cockpit/core/workflow.py:76`; its class documentation says default lifecycle events persist through the session trace and calls an injected `log_path` an explicit adapter/test seam (`:67-74`).
   - `_emit` calls `_append` only when `self.log_path is not None` (`:180-181`), while every lifecycle emission invokes the existing `event_logger` (`:182-186`). The default logger maps start, step and finish to `log_event` session-trace events (`:198-211`). `_append` is also defensive for a missing path (`:187-189`).
   - The focused regression `test_default_workflow_lifecycle_uses_session_trace_without_secondary_log` exercised default construction and a full start/step/finish lifecycle. It verified exactly `workflow_start`, `workflow_step`, and `workflow_finish` in the patched `session.jsonl`, all with the same action ID, and verified the secondary `workflow.jsonl` was absent (`tests/test_workflow_runtime.py:49-64`).
   - The physical `logs/workflow.jsonl` and `logs/activity_log.jsonl` files pre-exist in the shared workspace, but current production-source search found no default writer to either path. They are legacy artefacts, not a current authority.

2. **Dashboard path** - resolved.

   - The dashboard activity-panel description now states that actions are saved to the session trace at `logs/session.jsonl` (`src/etf_cockpit/app/pages/dashboard.py:206`).
   - Its focused UI-tree regression requires `logs/session.jsonl` and rejects `logs/activity_log.jsonl` (`tests/test_workflow_runtime.py:66-72`).

## Original Task 2 requirement re-check

- **Typed event authority and projection:** `OperationalEvent` remains exported from `etf_cockpit.operations`; `AppState.current_activity_view()` reloads `ACTIVITY_LOG_PATH` and projects it with `current_activity_view(events)` (`src/etf_cockpit/app/state.py:269-275`). The compatibility alias is explicitly `SESSION_LOG_PATH`, not an independent activity store (`:22-25`).
- **Redaction and integrity:** session writes redact recursively before assigning IDs and hash-chain values (`src/etf_cockpit/core/session_log.py:265-277`). The redaction regression confirms nested and bearer-form secrets do not reach the persisted row (`tests/operations/test_redaction.py:10-37`).
- **Tail recovery:** only an invalid, unterminated final physical JSONL row is quarantined; malformed complete JSON or schema-invalid complete rows raise contextual `ValueError` rather than being skipped (`src/etf_cockpit/operations/event_store.py:36-64`; `tests/operations/test_event_store.py:48-76`).
- **Diagnostics:** the panel handles both tail quarantine and contextual integrity errors without abandoning the panel (`src/etf_cockpit/app/pages/diagnostics.py:91-103`), while continuing to identify `logs/session.jsonl` as the trace (`:151`).
- **Boundary and scope:** review of the Task 2 and authority-fix paths found no broker/order execution, credential transmission, remote upload, execution-authority change, issue closure, or Task 3 implementation. The local file-import and provider-settings code in `AppState` is pre-existing application functionality outside this narrow event-authority change.

## Findings

### Critical

None.

### Important

None.

### Minor

None.

## Verification performed

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workflow_runtime.py tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_trust_critical_artifacts.py -q
```

Result: exit 0, `28 passed`. Existing warnings only: GluonTS JSON performance and pandas mixed-dtype loading in trust-artifact tests.

```powershell
.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\operations\__init__.py src\etf_cockpit\operations\models.py src\etf_cockpit\operations\event_store.py src\etf_cockpit\core\session_log.py src\etf_cockpit\core\workflow.py src\etf_cockpit\app\state.py src\etf_cockpit\app\pages\diagnostics.py src\etf_cockpit\app\pages\dashboard.py tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_workflow_runtime.py
.\.venv\Scripts\python.exe -m compileall -q src\etf_cockpit\operations src\etf_cockpit\core\session_log.py src\etf_cockpit\core\workflow.py src\etf_cockpit\app\state.py src\etf_cockpit\app\pages\diagnostics.py src\etf_cockpit\app\pages\dashboard.py tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_workflow_runtime.py
```

Result: both exit 0; Ruff reported `All checks passed!` and compilation produced no output.

Relevant current SHA-256 checksums:

```text
d55dd61c95e765cc5f3f2f3ed3a8cc49251eb3d4984754efb1c4f8109197923b  src/etf_cockpit/core/workflow.py
4d98c07219d5478648d1691b19bc2f95453d1e9813db48c06e81656572d1ce65  src/etf_cockpit/app/pages/dashboard.py
76e5ff07fd0764d4e9b9c322525ff3eb087ae88086dba69970e5db9e9731652e  src/etf_cockpit/operations/event_store.py
6bd606aa9e6ae001efba3dfe27450d37645406e382fb185f2902706fca418d12  src/etf_cockpit/core/session_log.py
6fbd7fc0a45958b840179146b28f0d61dfd787e9e29086be476ea6ac0a035bb7  src/etf_cockpit/app/state.py
9922f0163ebc78b80f4275defc082199a4a4683476160c8837c92846187193c4  src/etf_cockpit/app/pages/diagnostics.py
97e396fdb1b4f6f443c8a8286e2dc3a2e20046df8e7ce00f4ce691f016872730  tests/test_workflow_runtime.py
```

No Git repository is available in this project directory, so the review basis remains the specified Task 2 snapshot and current filesystem evidence rather than commit SHAs.
