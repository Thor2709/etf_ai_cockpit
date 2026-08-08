from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import etf_cockpit.audit.thesis_diary as thesis_diary
from etf_cockpit.audit.local_llm import LocalAuditCommentary, save_local_audit_commentary
from etf_cockpit.app.pages.chatgpt_audit import _thesis_diary_text
from etf_cockpit.app.selectors.instrument_detail import _backtest_panel, _thesis_diary_panel
from etf_cockpit.services import build_snapshot
from etf_cockpit.audit.thesis_diary import (
    ThesisDiaryConflictError,
    ThesisDiaryIntegrityError,
    ThesisDiaryStore,
    build_thesis_entry,
    reproduce_thesis_from_packet,
)
from etf_cockpit.chatgpt_bridge import export_pack


def _entry(
    *,
    thesis_id: str | None = "thesis-1",
    prompt: str = "Review the evidence",
    decision_time: str | None = "2026-08-03T00:00:00+00:00",
    created_at: str | None = "2026-08-03T00:00:00+00:00",
    expires_at: str | None = None,
    instrument_id: str = "VWCE",
    backtest_validity: str = "unknown",
):
    return build_thesis_entry(
        thesis_id=thesis_id,
        prompt=prompt,
        model="local-test-model",
        source_snapshot={"source_id": "snapshot-1", "source_checksum": "source-checksum"},
        retrieval_snapshot={"retrieval_id": "retrieval-1", "retrieved_at": "2026-08-03T00:00:00+00:00"},
        evidence_snapshot={"etf_id": "VWCE", "as_of_date": "2026-08-01", "status": "valid"},
        llm_output={"summary": "Commentary only", "executable_authority": False},
        instrument_id=instrument_id,
        input_sources=["cockpit_snapshot", "signal:VWCE"],
        thesis_summary="Commentary only",
        risk_summary="No trade authority",
        contradiction_summary="No contradiction supplied",
        uncertainty=0.5,
        evidence_score=7.5,
        evidence_quality=6.5,
        risk_friction=5.5,
        final_advisory_label="manual_review",
        backtest_validity=backtest_validity,
        decision_time=decision_time,
        created_at=created_at,
        expires_at=expires_at,
    )


def test_thesis_persistence_is_immutable_and_idempotent(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = _entry()

    assert store.create(entry) == entry
    assert store.create(entry) == entry
    with pytest.raises(ThesisDiaryConflictError):
        store.create(_entry(prompt="Different immutable thesis content"))
    assert len(store.list_entries()) == 1


def test_hash_bindings_replay_lifecycle_and_packet_reproduction(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    store.append_review(entry.thesis_id, status="approved", reviewer="human", notes="Checked sources", decision_time="2026-08-03T01:00:00+00:00")
    store.append_redaction(entry.thesis_id, state="redacted", reason="Personal note", decision_time="2026-08-03T02:00:00+00:00")
    store.append_expiry(entry.thesis_id, expires_at="2026-08-03T04:00:00+00:00", decision_time="2026-08-03T03:00:00+00:00")
    store.append_outcome(entry.thesis_id, outcome="held", observed_at="2026-08-03T05:00:00+00:00", decision_time="2026-08-03T05:00:00+00:00", details={"return": "not_used"})

    before_redaction = store.replay(entry.thesis_id, at="2026-08-03T01:30:00+00:00")
    assert before_redaction.redaction_state == "unredacted"
    assert before_redaction.human_review["status"] == "approved"
    assert before_redaction.outcomes == ()

    current = store.replay(entry.thesis_id, at="2026-08-03T06:00:00+00:00")
    assert current.redaction_state == "redacted"
    assert current.expired is True
    assert current.outcomes[0]["outcome"] == "held"
    assert current.execution_allowed is False

    packet = store.export_packet()
    reproduced = reproduce_thesis_from_packet(packet, entry.thesis_id, at="2026-08-03T06:00:00+00:00")
    assert reproduced.model_dump(mode="json") == current.model_dump(mode="json")


def test_event_retry_after_later_event_is_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    first = store.append_redaction(
        entry.thesis_id,
        state="redacted",
        reason="Personal note",
        decision_time="2026-08-03T01:00:00+00:00",
        event_id="event-retry",
    )
    store.append_review(
        entry.thesis_id,
        status="approved",
        reviewer="human",
        decision_time="2026-08-03T02:00:00+00:00",
    )

    assert (
        store.append_redaction(
            entry.thesis_id,
            state="redacted",
            reason="Personal note",
            decision_time="2026-08-03T01:00:00+00:00",
            event_id="event-retry",
        )
        == first
    )
    with pytest.raises(ThesisDiaryConflictError):
        store.append_redaction(
            entry.thesis_id,
            state="redacted",
            reason="Changed note",
            decision_time="2026-08-03T03:00:00+00:00",
            event_id="event-retry",
        )
    with pytest.raises(ThesisDiaryConflictError):
        store.append_review(
            entry.thesis_id,
            status="approved",
            reviewer="human",
            decision_time="2026-08-03T03:00:00+00:00",
            event_id="event-retry",
        )
    other = store.create(_entry(thesis_id="thesis-2"))
    with pytest.raises(ThesisDiaryConflictError):
        store.append_redaction(
            other.thesis_id,
            state="redacted",
            reason="Personal note",
            decision_time="2026-08-03T01:00:00+00:00",
            event_id="event-retry",
        )


def test_default_thesis_identity_includes_normalized_generation_time(monkeypatch: pytest.MonkeyPatch) -> None:
    class ControlledDateTime(datetime):
        current = datetime(2026, 8, 3, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current

    monkeypatch.setattr(thesis_diary, "datetime", ControlledDateTime)
    first = _entry(thesis_id=None, decision_time=None, created_at=None)
    retry = _entry(thesis_id=None, decision_time=first.decision_time, created_at=first.created_at)
    ControlledDateTime.current = datetime(2026, 8, 3, 0, 1, tzinfo=timezone.utc)
    second = _entry(thesis_id=None, decision_time=None, created_at=None)

    assert retry.thesis_id == first.thesis_id
    assert second.thesis_id != first.thesis_id


def test_replay_without_cutoff_uses_current_time_for_expiry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class ControlledDateTime(datetime):
        current = datetime(2026, 8, 3, 1, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current

    monkeypatch.setattr(thesis_diary, "datetime", ControlledDateTime)
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry(expires_at="2026-08-03T02:00:00+00:00"))

    assert store.replay(entry.thesis_id).expired is False
    assert store.replay(entry.thesis_id, at="2026-08-03T01:30:00+00:00").expired is False
    ControlledDateTime.current = datetime(2026, 8, 3, 3, tzinfo=timezone.utc)
    assert store.replay(entry.thesis_id).expired is True


def test_review_rejects_empty_reviewer(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())

    with pytest.raises(ValueError, match="non-empty reviewer"):
        store.append_review(
            entry.thesis_id,
            status="approved",
            reviewer="   ",
            decision_time="2026-08-03T01:00:00+00:00",
        )


def test_corrupt_store_and_inconsistent_packet_fail_closed(tmp_path: Path) -> None:
    store = ThesisDiaryStore(tmp_path)
    entry = store.create(_entry())
    entry_path = store.entry_path(entry.thesis_id)
    payload = json.loads(entry_path.read_text(encoding="utf-8"))
    payload["evidence_snapshot"]["status"] = "tampered"
    entry_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ThesisDiaryIntegrityError):
        store.export_packet()

    valid_packet = {
        "schema_version": "thesis-diary.v1",
        "execution_allowed": False,
        "entries": [],
        "events": [],
        "checksums": {"entries": {"unexpected": "0" * 64}, "events": "0" * 64},
    }
    with pytest.raises(ThesisDiaryIntegrityError):
        reproduce_thesis_from_packet(valid_packet, "thesis-1")


def test_local_llm_save_creates_non_executable_diary_record(tmp_path: Path) -> None:
    commentary = LocalAuditCommentary(summary="No trade authority", confidence=0.5)
    report_path = save_local_audit_commentary(
        commentary,
        model="local-test-model",
        context={"as_of_date": "2026-08-03", "signals": [], "authority": "commentary_only_no_trade_execution"},
        directory=tmp_path / "reports",
        diary_root=tmp_path / "data",
    )

    assert report_path.is_file()
    entries = ThesisDiaryStore(tmp_path / "data").list_entries()
    assert len(entries) == 1
    assert entries[0].execution_allowed is False
    assert entries[0].prompt_hash
    assert entries[0].evidence_snapshot_hash
    assert json.loads(report_path.read_text(encoding="utf-8"))["executable_authority"] is False


def test_audit_export_contains_reproducible_diary_records(tmp_path: Path) -> None:
    entry = ThesisDiaryStore(tmp_path / "data").create(_entry())
    destination = tmp_path / "evidence_export" / "thesis_diary.json"

    export_pack._export_thesis_diary(destination, root=tmp_path / "data")

    packet = json.loads(destination.read_text(encoding="utf-8"))
    reproduced = reproduce_thesis_from_packet(packet, entry.thesis_id)
    assert reproduced.entry.evidence_snapshot == entry.evidence_snapshot
    assert packet["execution_allowed"] is False
    assert packet["executable_authority"] is False


def test_structured_fields_and_forward_only_backtest_guard_are_explicit() -> None:
    entry = _entry()

    assert entry.instrument_id == "VWCE"
    assert entry.executable_authority is False
    assert entry.prompt_hash
    assert entry.input_sources == ["cockpit_snapshot", "signal:VWCE"]
    assert entry.thesis_summary and entry.risk_summary and entry.contradiction_summary
    assert entry.uncertainty == 0.5
    assert entry.human_review_status == "pending"
    assert entry.evidence_score == 7.5
    assert entry.evidence_quality == 6.5
    assert entry.risk_friction == 5.5
    assert entry.final_advisory_label == "manual_review"
    assert set(entry.outcomes) == {"20", "60", "120"}
    assert entry.backtest_validity == "unknown"

    with pytest.raises(ValueError, match="forward-only"):
        _entry(backtest_validity="forward_only")


def test_local_llm_save_scopes_records_and_keeps_diary_non_authoritative(tmp_path: Path) -> None:
    commentary = LocalAuditCommentary(summary="Review only", confidence=0.75)
    context = {
        "as_of_date": "2026-08-03",
        "authority": "commentary_only_no_trade_execution",
        "signals": [
            {"etf_id": "VWCE", "input_sources": ["scoreboard"], "evidence_score": 8.0, "evidence_quality": 7.0, "risk_friction": 6.0, "final_advisory_label": "watch"},
            {"etf_id": "XDWU", "input_sources": ["scoreboard"], "evidence_score": 5.0, "evidence_quality": 4.0, "risk_friction": 3.0, "final_advisory_label": "manual_review"},
        ],
    }
    original = json.loads(json.dumps(context))

    report_path = save_local_audit_commentary(commentary, model="local-test-model", context=context, directory=tmp_path / "reports", diary_root=tmp_path / "data")
    entries = ThesisDiaryStore(tmp_path / "data").list_entries()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert context == original
    assert {entry.instrument_id for entry in entries} == {"VWCE", "XDWU"}
    assert all(entry.execution_allowed is False for entry in entries)
    assert all(entry.backtest_validity == "unknown" for entry in entries)
    assert all(entry.evidence_score is not None for entry in entries)
    assert report["executable_authority"] is False
    assert len(report["thesis_ids"]) == 2


def test_instrument_and_audit_projections_are_context_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ThesisDiaryStore(tmp_path / "data")
    entry = store.create(_entry())
    store.append_outcome(entry.thesis_id, outcome="positive", horizon="20", observed_at="2026-09-01T00:00:00+00:00", decision_time="2026-09-01T00:00:00+00:00", details={"return": 0.1})

    panel = _thesis_diary_panel("VWCE", root=tmp_path / "data")
    assert panel["status"] == "available"
    assert panel["execution_allowed"] is False
    assert panel["executable_authority"] is False
    assert panel["score_eligible"] is False
    assert panel["action_authority"] is False
    assert panel["risk_gate_authority"] is False
    assert panel["entries"][0]["outcomes"]["20"]["outcome"] == "positive"

    monkeypatch.setattr("etf_cockpit.app.pages.chatgpt_audit.ThesisDiaryStore", lambda: store)
    audit_text = _thesis_diary_text()
    assert "VWCE" in audit_text
    assert "execution_allowed=false" in audit_text


def test_llm_backtest_panel_is_unknown_and_excluded_from_trust() -> None:
    panel = _backtest_panel(build_snapshot(), "VWCE", {})

    assert panel["llm_backtest_validity"] == "unknown"
    assert panel["llm_output_authority"] == "excluded_from_backtest"
    assert panel["execution_allowed"] is False
