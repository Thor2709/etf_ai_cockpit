from __future__ import annotations

import flet as ft
from types import SimpleNamespace

from etf_cockpit.app.pages.operations import operations_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.app.components.shell.page_view import PageView


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


def test_renders_with_sample_data() -> None:
    view = operations_page(None, _state())
    assert isinstance(view, PageView)
    content = [_text(view)]
    for segment in ("Paper ledger", "Records"):
        view.chrome.segment_groups[0].on_change(segment)
        content.append(_text(view))
    rendered = "\r\n".join(content)
    assert all(
        title in rendered
        for title in (
            "Preview and confirm",
            "Paper equity",
            "Environments",
            "Post-trade TCA",
            "Open paper account",
            "Proposal decisions",
            "Fills",
            "Marks and corporate actions",
            "Outcomes",
            "Incidents",
            "Recent operation records",
        )
    )
    assert "Traceback" not in rendered


def test_empty_data_shows_unavailable() -> None:
    state = _state()
    state.application_api = SimpleNamespace(
        get_paper=lambda: SimpleNamespace(items=()),
        get_operations=lambda: SimpleNamespace(items=()),
    )
    view = operations_page(None, state)
    content = _text(view)
    assert "Unavailable" in content
    assert all(line != "0" for line in content.splitlines())


def test_paper_equity_has_card_and_cancel_is_text_button() -> None:
    view = operations_page(None, _state())
    descendants = list(_walk(view.body))
    paper_equity = next(
        control
        for control in descendants
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "GlassCard"
        and control.data.get("title") == "Paper equity"
    )
    assert "Paper equity unavailable" in _text_from_control(paper_equity)
    cancel = next(control for control in descendants if isinstance(control, ft.TextButton) and control.content == "Cancel workflow")
    assert cancel.key == "operations.cancel"
    assert all(not isinstance(control, ft.ListView) for control in _walk(paper_equity))


def _text_from_control(control) -> str:
    return "\r\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))
