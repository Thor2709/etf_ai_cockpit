# Wave 0 Task 2 independent review 1

Date: 2026-07-11  
Reviewer: fresh independent Task 2 reviewer  
Scope: Task 2 only. This review neither closes issues nor approves later Wave 0 tasks.

## Verdict

**CHANGES_REQUIRED**

The typed event, redaction, hash-chain, tail-recovery and diagnostics work is sound in the reviewed paths, but the implementation has not made `session.jsonl` the sole persistent workflow/activity event authority. One user-facing sentence also directs users to the retired persistent activity file.

## Findings

### Important

1. `core/workflow.py` still writes a second durable workflow/activity trace.

   - Evidence: [`src/etf_cockpit/core/workflow.py`](../src/etf_cockpit/core/workflow.py) describes this as a “separate append-only activity trace” at lines 68-74, defaults it to `logs/workflow.jsonl` at line 77, invokes the write at line 180, and opens/appends the file at lines 187-194. The current workspace also contains `logs/workflow.jsonl`.
   - Reproduction: a focused probe constructing `WorkflowController(tmp_path / "workflow.jsonl", event_logger=lambda payload: None)`, then calling `start` and `finish`, produced `exists=True rows=2`.
   - Impact: each UI workflow lifecycle is persistently recorded both in `logs/workflow.jsonl` and in the session trace through `_session_event_logger` (lines 197-210). This conflicts with Task 2’s one-session-JSONL authority and “no competing persistent activity writer” requirement. The narrow Task 2 fix is to retain the in-memory controller state and session event callback, but remove or redirect this independent persistent append path with accompanying focused test updates.

2. The dashboard presents a retired file as the persistent activity destination.

   - Evidence: [`src/etf_cockpit/app/pages/dashboard.py`](../src/etf_cockpit/app/pages/dashboard.py) line 206 tells users actions are “saved to logs/activity_log.jsonl”, while [`src/etf_cockpit/app/state.py`](../src/etf_cockpit/app/state.py) lines 23-25 aliases `ACTIVITY_LOG_PATH` to `SESSION_LOG_PATH` and no production source writer targets `activity_log.jsonl`.
   - Impact: the displayed path contradicts the actual Task 2 authority and points users to a stale legacy file, undermining diagnostics and audit trace discoverability. Update it to `logs/session.jsonl` (and preferably describe it as the session trace).

### Minor

None.

### Critical

None.

## Confirmed requirements

- `OperationalEvent` is typed and re-exported: `operations/models.py:9-23`, `operations/__init__.py:3-5`.
- New session-log writes generate an ID and link/hash after recursive redaction: `core/session_log.py:265-277`, `298-314`.
- Valid legacy rows remain representable with absent event/hash fields, while malformed complete rows raise contextual `ValueError` and only an unterminated invalid final row is quarantined: `operations/event_store.py:40-64`.
- `AppState.current_activity_view()` reads and projects the session trace: `app/state.py:269-275`. `current_activity`, `recent_activity` and `WorkflowController._records` are process-memory fields, but the workflow file above makes the controller a competing **persistent** authority.
- Diagnostics reports tail quarantine or a contextual integrity failure without aborting its panel: `app/pages/diagnostics.py:90-112`.
- Reviewed Task 2 paths contain no broker/order/credential/upload implementation and preserve the non-execution boundary.

## Verification performed

```powershell
.\.venv\Scripts\python.exe -m pytest tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_trust_critical_artifacts.py -q
```

Result: exit 0, `21 passed`; existing GluonTS JSON and pandas mixed-dtype warnings only.

```powershell
.\.venv\Scripts\python.exe -m ruff check src\etf_cockpit\operations\__init__.py src\etf_cockpit\operations\models.py src\etf_cockpit\operations\event_store.py src\etf_cockpit\core\session_log.py src\etf_cockpit\app\state.py src\etf_cockpit\app\pages\diagnostics.py src\etf_cockpit\app\pages\dashboard.py tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py
```

Result: exit 0, `All checks passed!`.

The two Important findings are outside the existing Task 2 focused test set; resolution requires a narrow regression proving that workflow start/step/finish records only persist in the session trace and that the dashboard names that trace correctly.
