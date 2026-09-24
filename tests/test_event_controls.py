from datetime import datetime, timezone

import pytest

from etf_cockpit.data.event_calendar import CalendarEvent, persist_calendar_events
from etf_cockpit.portfolio.event_controls import EventBlockPolicy, evaluate_event_control, verify_event_control


def _bundle(tmp_path, **changes):
    values = dict(event_id="earnings", instrument_id="MSFT", event_type="earnings", event_date="2026-07-30",
                  available_at="2026-07-01T00:00:00+00:00", ingested_at="2026-07-02T00:00:00+00:00",
                  source_id="issuer", source_authority="issuer", risk_level="high", timezone_name="America/New_York")
    values.update(changes)
    path = tmp_path / "clean" / "event_calendar.parquet"
    persist_calendar_events([CalendarEvent(**values)], clean_path=path, raw_dir=tmp_path / "raw" / "event_calendar")
    return path


def _evaluate(path, when="2026-07-30T12:00:00+00:00", **changes):
    values = dict(policy=EventBlockPolicy(policy_id="test", version="1"), target="proposal_preview",
                  instrument_id="MSFT", decision_time=datetime.fromisoformat(when), calendar_path=path)
    values.update(changes)
    return evaluate_event_control(**values)


def test_no_policy_never_requires_calendar_and_never_generates_authority(tmp_path):
    decision = _evaluate(tmp_path / "missing", policy=None)
    assert decision.status == "context_only" and not decision.blocks
    assert decision.execution_allowed is False and decision.executable_authority is False
    assert not {"score", "signal", "quantity", "order", "target_quantity"} & decision.to_payload().keys()


def test_explicit_policy_blocks_matching_available_event_with_reproducible_evidence(tmp_path):
    path = _bundle(tmp_path)
    decision = _evaluate(path)
    assert decision.status == "blocked" and decision.blocks
    assert decision.to_payload() == _evaluate(path).to_payload()
    assert len(decision.frame_checksum) == len(decision.policy_checksum) == 64
    assert decision.matched_events[0][0] == "earnings"
    assert _evaluate(path, instrument_id="VWCE").status == "clear"
    assert _evaluate(path, policy=EventBlockPolicy(policy_id="test", version="1", risk_levels=("critical",))).status == "clear"
    assert _evaluate(path, policy=EventBlockPolicy(policy_id="test", version="1", targets=("order_preview",))).status == "context_only"


@pytest.mark.parametrize(("when", "status"), [("2026-07-30T03:59:59+00:00", "clear"), ("2026-07-30T04:00:00+00:00", "blocked"), ("2026-07-31T03:59:59+00:00", "blocked"), ("2026-07-31T04:00:00+00:00", "clear")])
def test_date_only_uses_whole_declared_local_day(tmp_path, when, status):
    assert _evaluate(_bundle(tmp_path), when).status == status


def test_timed_window_and_ingestion_cutoff(tmp_path):
    path = _bundle(tmp_path, precision="minute", event_time="2026-07-30T10:00:00-04:00")
    policy = EventBlockPolicy(policy_id="window", version="1", pre_minutes=60, post_minutes=30)
    assert _evaluate(path, "2026-07-30T13:00:00+00:00", policy=policy).blocks
    assert not _evaluate(path, "2026-07-30T12:59:59+00:00", policy=policy).blocks
    assert _evaluate(path, "2026-07-30T14:30:00+00:00", policy=policy).blocks
    assert not _evaluate(path, "2026-07-30T14:30:01+00:00", policy=policy).blocks
    late = _bundle(tmp_path / "late", ingested_at="2026-07-31T00:00:00+00:00")
    assert _evaluate(late).status == "clear"
    future = _bundle(tmp_path / "future", available_at="2026-07-31T00:00:00+00:00", ingested_at="2026-07-31T01:00:00+00:00")
    assert _evaluate(future).status == "clear"


def test_missing_and_corrupt_evidence_blocks_only_under_policy(tmp_path):
    assert _evaluate(tmp_path / "missing").status == "evidence_unavailable"
    path = _bundle(tmp_path)
    path.with_name("event_calendar_audit.json").write_text("{}", encoding="utf-8")
    assert _evaluate(path).blocks
    assert _evaluate(path, policy=None).status == "context_only"


def test_strict_policy_and_decision_bindings_reject_tampering(tmp_path):
    with pytest.raises(ValueError):
        EventBlockPolicy(policy_id="x", version="1", targets=("live_order",))
    with pytest.raises(ValueError):
        EventBlockPolicy(policy_id="x", version="1", execution_allowed=True)
    decision = _evaluate(_bundle(tmp_path))
    payload = decision.to_payload()
    assert verify_event_control(payload, target="proposal_preview", instrument_id="MSFT") == decision
    with pytest.raises(ValueError, match="instrument"):
        verify_event_control(payload, target="proposal_preview", instrument_id="VWCE")
    with pytest.raises(ValueError, match="time"):
        verify_event_control(payload, target="proposal_preview", instrument_id="MSFT", decision_time=datetime(2026, 8, 1, tzinfo=timezone.utc))
    payload["status"] = "clear"
    with pytest.raises(ValueError, match="checksum"):
        verify_event_control(payload, target="proposal_preview", instrument_id="MSFT")


def test_policy_checksum_is_order_independent():
    left = EventBlockPolicy(policy_id="x", version="1")
    right = EventBlockPolicy(policy_id="x", version="1", event_types=tuple(reversed(left.event_types)))
    assert left.checksum == right.checksum


def test_historical_decision_does_not_change_after_future_ingestion(tmp_path):
    path = _bundle(tmp_path)
    before = _evaluate(path).to_payload()
    later = CalendarEvent(event_id="later", instrument_id="MSFT", event_type="earnings", event_date="2026-07-30",
        available_at="2026-07-31T00:00:00+00:00", ingested_at="2026-07-31T01:00:00+00:00", source_id="issuer", source_authority="issuer", risk_level="high")
    persist_calendar_events([later], clean_path=path, raw_dir=tmp_path / "raw" / "event_calendar")
    assert _evaluate(path).to_payload() == before


def test_date_only_dst_day_and_naive_cutoff(tmp_path):
    path = _bundle(tmp_path, event_date="2026-11-01")
    assert _evaluate(path, "2026-11-01T04:00:00+00:00").blocks
    assert _evaluate(path, "2026-11-02T04:59:59+00:00").blocks
    assert not _evaluate(path, "2026-11-02T05:00:00+00:00").blocks
    with pytest.raises(ValueError, match="timezone"):
        _evaluate(path, "2026-11-01T12:00:00")


def test_policy_checksum_binding_is_independently_verified(tmp_path):
    import hashlib
    import json

    payload = _evaluate(_bundle(tmp_path)).to_payload()
    payload["policy"]["version"] = "tampered"
    material = {key: value for key, value in payload.items() if key != "decision_checksum"}
    payload["decision_checksum"] = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ValueError, match="policy checksum"):
        verify_event_control(payload, target="proposal_preview", instrument_id="MSFT")
