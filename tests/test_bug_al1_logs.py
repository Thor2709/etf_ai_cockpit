"""Bughunt D (#985): activity/event log and incident journal integrity."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from etf_cockpit.core import session_log
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.session_log import event_log_lock_path, log_event
from etf_cockpit.operations import event_store
from etf_cockpit.operations.event_store import current_activity_view, load_events_with_tail_recovery
from etf_cockpit.operations.models import OperationalEvent
from etf_cockpit.trading.incidents import IncidentJournal

AT = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
NEWLINE = chr(10)


def _rows(path: Path) -> list[dict]:
    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row.strip()]


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + NEWLINE for row in rows), encoding="utf-8")


def _log(path: Path, count: int) -> None:
    for index in range(count):
        log_event(event_type="activity_update", status=f"s{index}", path=path)


# D019-N001


@pytest.mark.parametrize("tamper", ["status_edit", "hash_stripped", "row_removed", "last_row_edit"])
def test_reader_detects_a_tampered_hash_chain(tmp_path: Path, tamper: str) -> None:
    path = tmp_path / "session.jsonl"
    _log(path, 3)
    assert [event.status for event in load_events_with_tail_recovery(path)[0]] == ["s0", "s1", "s2"]
    rows = _rows(path)
    if tamper == "status_edit":
        rows[1]["status"] = "forged"
    elif tamper == "hash_stripped":
        del rows[2]["event_hash"]
    elif tamper == "row_removed":
        del rows[1]
    else:
        rows[2]["status"] = "forged"
    _write_rows(path, rows)

    with pytest.raises(ValueError, match="hash"):
        load_events_with_tail_recovery(path)


# D019-N002 / D019-N003


def test_stale_process_counter_does_not_fork_the_sequence(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    _log(path, 2)
    session_log._SEQUENCE = 0  # a second session whose in-memory counter is stale
    _log(path, 2)

    assert [row["sequence_number"] for row in _rows(path)] == [1, 2, 3, 4]
    assert load_events_with_tail_recovery(path)[1].quarantined_tail is False


def test_two_processes_share_one_chain_and_sequence(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    script = (
        "import sys; from pathlib import Path; from etf_cockpit.core.session_log import log_event" + NEWLINE
        + "for i in range(12): log_event(event_type='activity_update', status=sys.argv[2] + str(i), path=Path(sys.argv[1]))"
        + NEWLINE
    )
    env = {**os.environ, "PYTHONPATH": str(Path(session_log.__file__).resolve().parents[2])}
    procs = [
        subprocess.Popen([sys.executable, "-c", script, str(path), tag], cwd=tmp_path, env=env)
        for tag in ("a", "b")
    ]
    assert [proc.wait(timeout=90) for proc in procs] == [0, 0]

    events, recovery = load_events_with_tail_recovery(path)  # validates the whole hash chain
    assert recovery.quarantined_tail is False
    assert [event.sequence_number for event in events] == list(range(1, 25))


def test_activity_view_ignores_a_stale_higher_sequence_from_an_earlier_session() -> None:
    def event(session: str, sequence: int, status: str) -> OperationalEvent:
        return OperationalEvent(
            session_id=session, sequence_number=sequence, timestamp_utc=AT, event_type="activity_update", status=status
        )

    view = current_activity_view([event("old", 500, "stale"), event("new", 3, "fresh"), event("new", 2, "fresh")])

    assert (view.status, view.sequence_number) == ("fresh", 3)


# D019-N004


def test_tail_recovery_waits_for_an_in_flight_writer_instead_of_truncating(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    _log(path, 1)
    whole = path.read_bytes()
    first = _rows(path)[0]
    # A second, hash-valid row that the "writer" appends in two pieces.
    second = {**first, "event_id": "second", "sequence_number": 2, "prior_event_hash": first["event_hash"]}
    second.pop("event_hash")
    second["event_hash"] = session_log._event_hash(second)
    row = json.dumps(second, sort_keys=True).encode() + b"\n"
    path.write_bytes(whole + row[:40])  # writer is mid-row
    guard_taken = threading.Event()

    def writer() -> None:
        with persistent_file_guard(event_log_lock_path(path)):
            guard_taken.set()
            time.sleep(0.4)
            with path.open("ab") as handle:
                handle.write(row[40:])  # finishes the row, then releases the lock

    thread = threading.Thread(target=writer)
    thread.start()
    assert guard_taken.wait(5)
    try:
        events, recovery = load_events_with_tail_recovery(path)
    finally:
        thread.join()

    assert recovery.quarantined_tail is False
    assert len(events) == 2
    assert path.read_bytes() == whole + row
    assert not list(tmp_path.glob("*.quarantine"))


def test_tail_recovery_never_truncates_without_the_writer_lock(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "session.jsonl"
    _log(path, 1)
    content = path.read_bytes() + b'{"event_id":'
    path.write_bytes(content)
    monkeypatch.setattr(event_store, "_RECOVERY_LOCK_TIMEOUT_SECONDS", 0.2)

    with persistent_file_guard(event_log_lock_path(path)):
        with pytest.raises(TimeoutError):
            load_events_with_tail_recovery(path)

    assert path.read_bytes() == content
    events, recovery = load_events_with_tail_recovery(path)
    assert recovery.quarantined_tail is True and len(events) == 1


# D119-N002 / D119-N003


def test_freeze_escalation_with_a_fixed_timestamp_does_not_collide(tmp_path: Path) -> None:
    journal = IncidentJournal(tmp_path)
    warning = journal.record("order_break", message="mismatch", related_id="o-1", occurred_at=AT)
    freeze = journal.record("order_break", message="mismatch", related_id="o-1", requires_freeze=True, occurred_at=AT)

    assert warning["incident_id"] != freeze["incident_id"]
    assert journal.is_frozen is True
    assert (
        journal.record("order_break", message="mismatch", related_id="o-1", requires_freeze=True, occurred_at=AT)
        == freeze
    )
    assert len(journal.events()) == 2


def test_legacy_freeze_incident_is_still_recognised_on_retry(tmp_path: Path) -> None:
    journal = IncidentJournal(tmp_path, account_id="legacy")
    at = AT.isoformat(timespec="microseconds")
    identity = {"account_id": "legacy", "code": "disconnect", "message": "m", "related_id": None, "occurred_at": at}
    legacy_id = "incident_" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    payload = {
        "account_id": "legacy",
        "incident_id": legacy_id,
        "code": "disconnect",
        "message": "m",
        "related_id": None,
        "requires_freeze": True,
        "execution_allowed": False,
    }
    journal._append([], "incident_recorded", payload, at)  # as the pre-fix code wrote it

    retry = journal.record("disconnect", message="m", requires_freeze=True, occurred_at=AT)

    assert retry["incident_id"] == legacy_id
    assert len(journal.events()) == 1


def test_secret_in_incident_evidence_is_redacted_before_it_is_written(tmp_path: Path) -> None:
    journal = IncidentJournal(tmp_path)
    incident = journal.record(
        "broker_error", message="login failed password=hunter2", requires_freeze=True, occurred_at=AT
    )
    journal.append_postmortem(
        str(incident["incident_id"]),
        summary="rotated token: sk-live-123456",
        evidence={"api_key": "SECRET-KEY-VALUE", "nested": {"note": "authorization: Bearer SECRET-BEARER"}, "rows": 3},
        occurred_at=AT,
    )

    raw = journal.path.read_text(encoding="utf-8")
    for secret in ("hunter2", "sk-live-123456", "SECRET-KEY-VALUE", "SECRET-BEARER"):
        assert secret not in raw
    postmortem = journal.events()[-1]["payload"]
    assert postmortem["evidence"]["api_key"] == "***redacted***"
    assert postmortem["evidence"]["rows"] == 3
    assert journal.snapshot()["frozen"] is True  # redacted rows keep a valid chain
