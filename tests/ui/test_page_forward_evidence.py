from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.forward_evidence import forward_evidence_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.ui_facade import ForwardEvidenceDiary


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    if getattr(control, "content", None) is not None:
        yield from _walk(control.content)


def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _text(view) -> str:
    return "\r\n".join(str(item.value) for item in _walk(view.body) if isinstance(item, ft.Text))


def test_renders_with_sample_data(monkeypatch) -> None:
    monkeypatch.setattr(ForwardEvidenceDiary, "list_entries", lambda *_args, **_kwargs: ())
    view = forward_evidence_page(None, _state())
    assert isinstance(view, PageView)
    body = view.body
    rendered = []
    for option in view.chrome.segment_groups[0].items:
        view.chrome.segment_groups[0].on_change(option)
        rendered.append(_text(view))
    content = "\r\n".join(rendered)
    assert view.body is body
    assert all(
        title in content
        for title in (
            "Decision-time manifest / Mature outcome",
            "Quality-momentum forward paper evidence",
            "Outcomes over time",
            "Recent local diary entries",
            "OBSERVATION ID",
            "PROPOSAL OUTCOME",
            "DATA HASH",
            "OBSERVATION ID TO UPDATE",
            "OUTCOME AS-OF",
            "OUTCOME NOTES",
        )
    )
    assert "Traceback" not in content


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(ForwardEvidenceDiary, "list_entries", lambda *_args, **_kwargs: [])
    view = forward_evidence_page(None, SimpleNamespace(snapshot=SimpleNamespace(backtest=None)))
    content = _text(view)
    assert isinstance(view, PageView)
    assert "Unavailable" in content or "No observations yet" in content
    for control in _walk(view.body):
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "DataTable":
            assert all(str(value) != "0" for row in data.get("rows", ()) for value in row.values())


def test_missing_observations_are_shown_in_outcomes_card(monkeypatch) -> None:
    monkeypatch.setattr(ForwardEvidenceDiary, "list_entries", lambda *_args, **_kwargs: ())
    view = forward_evidence_page(None, _state())
    cards = [
        control
        for control in _walk(view.body)
        if isinstance(getattr(control, "data", None), dict) and control.data.get("kit") == "GlassCard"
    ]
    outcomes = next(card for card in cards if card.data.get("title") == "Outcomes over time")
    recent = next(card for card in cards if card.data.get("title") == "Recent local diary entries")
    assert "No observations yet" in _text_from_control(outcomes)
    assert "No diary entries yet" in _text_from_control(recent)
    assert all(not isinstance(control, ft.ListView) for control in _walk(outcomes))


def _text_from_control(control) -> str:
    return "\r\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))
