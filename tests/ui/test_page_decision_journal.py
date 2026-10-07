from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.decision_journal import decision_journal_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.data.decision_journal import DecisionJournal, JournalEntry


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    if getattr(control, "content", None) is not None:
        yield from _walk(control.content)


def _text(view) -> str:
    return "\n".join(str(item.value) for item in _walk(view.body) if isinstance(item, ft.Text))


def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_renders_with_sample_data(monkeypatch) -> None:
    entry = JournalEntry(
        journal_entry_id="sample-entry",
        created_at="2026-10-06T09:00:00+00:00",
        thesis="Sample journal thesis",
        decision="Sample decision",
        outcome="pending",
        decision_state="pending",
        confidence=0.5,
        review_date="2026-10-20",
    )
    monkeypatch.setattr(DecisionJournal, "list_entries", lambda *_args, **_kwargs: [entry])
    view = decision_journal_page(None, _state())
    assert isinstance(view, PageView)
    content = _text(view)
    assert all(
        title in content
        for title in (
            "New decision",
            "Recent local entries",
            "Decisions by state",
            "Review calendar",
            "DECISION TITLE",
            "PRIVATE THESIS / NOTE",
            "EVIDENCE REFERENCES (COMMA-SEPARATED)",
            "ALTERNATIVES CONSIDERED (COMMA-SEPARATED)",
            "INVALIDATION RULES (COMMA-SEPARATED)",
            "INSTRUMENT IDS (COMMA-SEPARATED)",
        )
    )
    assert "Traceback" not in content


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(DecisionJournal, "list_entries", lambda *_args, **_kwargs: [])
    view = decision_journal_page(None, _state())
    content = _text(view)
    assert isinstance(view, PageView)
    assert "Unavailable" in content or "No local journal entries yet" in content
    for control in _walk(view.body):
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "DataTable":
            assert all(str(value) != "0" for row in data.get("rows", ()) for value in row.values())
