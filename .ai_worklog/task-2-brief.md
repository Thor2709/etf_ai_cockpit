### Task 2: Make the session trace the operational event authority

**Dependency resolution:** The foundation interface table requires `OperationalEvent`, but the completed Task 1 brief only produced verification and closure-evidence records. Task 2 therefore owns the narrow addition of `OperationalEvent` to `operations/models.py`; this preserves the approved single-model-module interface without reopening the independently reviewed Task 1 deliverable.

**Files:**

- Create: `src/etf_cockpit/operations/event_store.py`, `tests/operations/test_operational_events.py`, `tests/operations/test_event_store.py`, `tests/operations/test_redaction.py`
- Modify: `src/etf_cockpit/operations/__init__.py:1-end` (export the new public type), `src/etf_cockpit/operations/models.py:1-end` (add the typed `OperationalEvent` consumed by this task only), `src/etf_cockpit/core/session_log.py:1-276`, `src/etf_cockpit/app/state.py:1-358`, `src/etf_cockpit/app/pages/diagnostics.py:1-end`

**Consumes:** Task 1 verification/closure records and the existing `session.jsonl` redaction.

**Produces:** typed `OperationalEvent` records and one event stream from UI action through workflow, files and audit outputs.

**Task interface:**

```python
class OperationalEvent(BaseModel):
    event_id: str
    session_id: str
    sequence_number: int
    timestamp_utc: datetime
    event_type: str
    status: str | None = None
    component: str | None = None
    action_id: str | None = None
    prior_event_hash: str | None = None
    event_hash: str | None = None

def load_events_with_tail_recovery(path: Path) -> tuple[list[OperationalEvent], TailRecovery]: ...
def append_operational_event(event: OperationalEvent, *, path: Path = SESSION_LOG_PATH) -> None: ...
def current_activity_view(events: Iterable[OperationalEvent]) -> ActivityView: ...
```

New writes must populate `event_id`, `prior_event_hash` and `event_hash`; the loader may represent pre-existing valid rows without those fields as legacy records, but must never silently discard a valid complete row.

- [x] **Step 1: Write RED tests for ordering, tail recovery and state derivation**

```python
def test_event_store_recovers_only_the_incomplete_jsonl_tail(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(valid_event_json + "\n" + '{"event_id":', encoding="utf-8")
    events, recovery = load_events_with_tail_recovery(path)
    assert [event.event_id for event in events] == ["event-1"]
    assert recovery.quarantined_tail is True

def test_ui_activity_is_derived_from_workflow_events() -> None:
    state = build_state_with_events([queued_event, completed_event])
    assert state.current_activity_view().status == "completed"
```

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py -q`

Expected: FAIL because no typed event-store loader or activity projection exists.

- [x] **Step 3: Implement the event adapter without replacing the current JSONL store**

```python
def append_operational_event(event: OperationalEvent, *, path: Path = SESSION_LOG_PATH) -> None:
    append_event(event.model_dump(mode="json"), path=path)

def current_activity_view(events: Iterable[OperationalEvent]) -> ActivityView:
    latest = max(events, key=lambda item: item.sequence_number, default=None)
    return ActivityView.from_event(latest)
```

Preserve existing nested secret redaction. Append sequence number, prior-event hash and current-event hash before the write, but retain graceful logging failure behaviour.

- [x] **Step 4: Run GREEN plus diagnostics regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_operational_events.py tests\operations\test_event_store.py tests\operations\test_redaction.py tests\test_trust_critical_artifacts.py -q`

Expected: PASS; diagnostics still renders a redacted, readable session trace.

- [x] **Step 5: Record a reviewer-ready deliverable**

Store a JSONL fixture checksum, a diagnostics screenshot/semantic capture plan and the review package range in the ledger. A separate reviewer must verify that no competing mutable activity store remains authoritative.
