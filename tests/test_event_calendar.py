from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.app.pages.instrument_detail import render_event_calendar_panel
from etf_cockpit.app.pages.trust_evidence import news_context_page
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.data.event_calendar import CalendarEvent, events_available_as_of, load_calendar_events, persist_calendar_events, validate_event
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


def test_news_context_page_exposes_event_calendar_status(monkeypatch) -> None:
    import etf_cockpit.app.pages.trust_evidence as trust_evidence

    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: pd.DataFrame([{"event_id": "e1"}]))
    state = type("State", (), {"snapshot": type("Snapshot", (), {"prices": pd.DataFrame()})()})()
    rendered = news_context_page(None, state)
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
    assert "1 event records are available" in text
