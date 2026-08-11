from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.app.pages.instrument_detail import render_event_calendar_panel
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.data.event_calendar import EVENT_TYPES, CalendarEvent, events_available_as_of, load_calendar_events, normalise_event_decision_time, persist_calendar_events, validate_event
from etf_cockpit.services import build_snapshot


def _event(**changes: str) -> CalendarEvent:
    values = {
        "event_id": "earnings-msft-2026q2",
        "instrument_id": "MSFT",
        "event_type": "earnings",
        "event_date": "2026-07-30",
        "available_at": "2026-07-01T09:00:00+00:00",
        "ingested_at": "2026-07-01T09:01:00+00:00",
        "source_id": "issuer-calendar",
        "source_authority": "issuer",
        "source_url": "https://example.invalid/events/msft",
        "title": "Quarterly earnings",
        "risk_level": "high",
    }
    values.update(changes)
    return CalendarEvent(**values)


def test_event_validation_requires_point_in_time_provenance_and_keeps_context_only() -> None:
    valid = validate_event(_event(), datetime(2026, 7, 2, tzinfo=timezone.utc))
    assert valid.status == "valid_context"
    assert valid.backtest_eligible is True
    assert valid.context_only is True
    assert valid.execution_allowed is False

    assert validate_event(_event(available_at="2026-07-01")).status == "ambiguous_availability"
    assert validate_event(_event(event_time="2026-07-30T08:00:00", precision="minute")).status == "ambiguous_event_time"
    assert validate_event(_event(), datetime(2026, 6, 30, tzinfo=timezone.utc)).status == "after_decision_time"


@pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
def test_event_validation_accepts_every_required_context_event_type(event_type: str) -> None:
    assert validate_event(_event(event_type=event_type), datetime(2026, 7, 2, tzinfo=timezone.utc)).status == "valid_context"


def test_event_validation_rejects_blank_or_invalid_timezone_metadata() -> None:
    assert validate_event(_event(timezone_name="")).status == "invalid_timezone"
    assert validate_event(_event(timezone_name="Not/IANA")).status == "invalid_timezone"
    assert validate_event(_event(timezone_name="America/New_York")).status == "valid_context"
    invalid_row = pd.DataFrame([{**_event(timezone_name="Not/IANA").__dict__, "backtest_eligible": True, "event_checksum": "invalid"}])
    assert events_available_as_of(invalid_row, datetime(2026, 7, 2, tzinfo=timezone.utc), "MSFT").empty


def test_event_decision_time_normalisation_rejects_ambiguous_datetimes() -> None:
    assert normalise_event_decision_time("2026-07-02") == pd.Timestamp("2026-07-02T23:59:59Z")
    assert normalise_event_decision_time("2026-07-02T12:00:00+02:00") == pd.Timestamp("2026-07-02T10:00:00Z")
    assert normalise_event_decision_time("2026-07-02T12:00:00") is None


def test_event_availability_applies_both_cutoffs_and_identity() -> None:
    frame = pd.DataFrame([
        {**_event(event_id="a").__dict__, "backtest_eligible": True, "event_checksum": "a"},
        {**_event(event_id="late-ingest", ingested_at="2026-07-03T09:01:00+00:00").__dict__, "backtest_eligible": True, "event_checksum": "b"},
        {**_event(event_id="other", instrument_id="OTHER").__dict__, "backtest_eligible": True, "event_checksum": "c"},
    ])
    result = events_available_as_of(frame, datetime(2026, 7, 2, tzinfo=timezone.utc), "MSFT")
    assert list(result["event_id"]) == ["a"]


def test_event_persistence_is_idempotent_and_atomic(tmp_path) -> None:
    event = _event()
    first = persist_calendar_events([event], raw_dir=tmp_path / "raw" / "event_calendar", clean_path=tmp_path / "clean.parquet")
    second = persist_calendar_events([event], raw_dir=tmp_path / "raw" / "event_calendar", clean_path=tmp_path / "clean.parquet")
    assert first.rows == second.rows == 1
    assert second.idempotent is True
    assert len(load_calendar_events(tmp_path / "clean.parquet")) == 1
    assert len(list((tmp_path / "raw" / "event_calendar").glob("*.json"))) == 1

    with pytest.raises(ValueError, match="Conflicting observations"):
        persist_calendar_events([_event(title="Changed")], raw_dir=tmp_path / "raw" / "event_calendar", clean_path=tmp_path / "clean.parquet")
    assert len(load_calendar_events(tmp_path / "clean.parquet")) == 1


def test_event_ui_surfaces_available_and_unavailable_states(monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    snapshot = build_snapshot()
    events = pd.DataFrame([{**_event(instrument_id="VWCE").__dict__, "validation_status": "valid_context", "backtest_eligible": True, "context_only": True, "execution_allowed": False, "event_checksum": "x"}])
    model = build_instrument_detail(snapshot, "VWCE", events=events)
    assert model.sections["events"]["status"] == "available"
    assert model.sections["events"]["events"][0]["execution_allowed"] is False
    rendered = render_event_calendar_panel(model)
    assert rendered is not None

    monkeypatch.setattr(selector, "EVENT_CLEAN_PATH", selector.EVENT_CLEAN_PATH.with_name("missing-event-calendar.parquet"))
    unavailable = build_instrument_detail(snapshot, "VWCE")
    assert unavailable.sections["events"]["status"] == "unavailable"


def test_instrument_detail_filters_events_at_snapshot_decision_time_and_exposes_truth() -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    cutoff = pd.Timestamp(snapshot.data_report.as_of_date).tz_localize("UTC")
    events = pd.DataFrame([
        {
            **_event(
                event_id="known-event",
                instrument_id=instrument_id,
                available_at=(cutoff - pd.Timedelta(days=2)).isoformat(),
                ingested_at=(cutoff - pd.Timedelta(days=2) + pd.Timedelta(minutes=1)).isoformat(),
            ).__dict__,
            "validation_status": "valid_context",
            "backtest_eligible": True,
            "event_checksum": "known",
        },
        {
            **_event(
                event_id="future-event",
                instrument_id=instrument_id,
                available_at=(cutoff + pd.Timedelta(days=1)).isoformat(),
                ingested_at=(cutoff + pd.Timedelta(days=1, minutes=1)).isoformat(),
            ).__dict__,
            "validation_status": "valid_context",
            "backtest_eligible": True,
            "event_checksum": "future",
        },
    ])

    model = build_instrument_detail(snapshot, instrument_id, events=events)

    panel = model.sections["events"]
    assert panel["decision_time_available"] is True
    assert panel["available_at_decision_time"] is True
    assert [item["event_id"] for item in panel["events"]] == ["known-event"]
    assert panel["events"][0]["available_at_decision_time"] is True
    assert panel["events"][0]["timezone_name"] == "UTC"
    assert panel["events"][0]["source_url"] == "https://example.invalid/events/msft"

    rendered = render_event_calendar_panel(model)
    assert rendered is not None


def test_news_context_event_presentation_filters_to_snapshot_and_shows_provenance(monkeypatch) -> None:
    import etf_cockpit.app.pages.trust_evidence as trust_evidence

    snapshot = build_snapshot()
    cutoff = pd.Timestamp(snapshot.data_report.as_of_date).tz_localize("UTC")
    events = pd.DataFrame([
        {
            "event_id": "known-event",
            "instrument_id": snapshot.config.universe.enabled_ids[0],
            "event_type": "dividend",
            "event_date": "2026-07-01",
            "available_at": (cutoff - pd.Timedelta(days=1)).isoformat(),
            "ingested_at": (cutoff - pd.Timedelta(days=1, minutes=-1)).isoformat(),
            "source_url": "https://example.invalid/dividend",
            "timezone_name": "Europe/Oslo",
            "validation_status": "valid_context",
            "backtest_eligible": True,
            "event_checksum": "known",
        },
        {
            "event_id": "future-event",
            "instrument_id": snapshot.config.universe.enabled_ids[0],
            "event_type": "split",
            "event_date": "2026-08-01",
            "available_at": (cutoff + pd.Timedelta(days=1)).isoformat(),
            "ingested_at": (cutoff + pd.Timedelta(days=1, minutes=1)).isoformat(),
            "source_url": "https://example.invalid/split",
            "timezone_name": "UTC",
            "validation_status": "valid_context",
            "backtest_eligible": True,
            "event_checksum": "future",
        },
    ])
    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: events)
    state = type("State", (), {"snapshot": snapshot})()

    rendered = trust_evidence._news_context_extra(state)
    values: list[str] = []

    def collect(node: object) -> None:
        value = getattr(node, "value", None)
        if value:
            values.append(str(value))
        for child_name in ("controls", "content"):
            children = getattr(node, child_name, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    collect(child)
            elif children is not None:
                collect(children)

    collect(rendered)
    text = "\n".join(values)
    assert "1 event records are available at decision_time=" in text
    assert "source_url=https://example.invalid/dividend" in text
    assert "timezone_name=Europe/Oslo" in text
    assert "available_at_decision_time=True" in text
    assert "future-event" not in text


def test_news_context_page_exposes_event_calendar_status(monkeypatch) -> None:
    import etf_cockpit.app.pages.trust_evidence as trust_evidence

    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: pd.DataFrame([{"event_id": "e1"}]))
    state = type("State", (), {"snapshot": type("Snapshot", (), {"prices": pd.DataFrame()})()})()
    rendered = trust_evidence._news_context_extra(state)
    values: list[str] = []

    def collect(node: object) -> None:
        value = getattr(node, "value", None)
        if value:
            values.append(str(value))
        for child_name in ("controls", "content"):
            children = getattr(node, child_name, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    collect(child)
            elif children is not None:
                collect(children)

    collect(rendered)
    text = "\n".join(values)
    assert "Event calendar status" in text
    assert "snapshot decision time is unavailable" in text
