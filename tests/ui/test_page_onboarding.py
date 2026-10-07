from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.onboarding import onboarding_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    if isinstance(control, ft.Control):
        yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _sample_state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _text(result):
    controls = list(_walk(result.body))
    return "\n".join(str(getattr(control, "value", "") or getattr(control, "text", "")) for control in controls)


def test_renders_with_sample_data():
    result = onboarding_page(None, _sample_state())
    assert isinstance(result, PageView)
    text = _text(result)
    assert all(
        title in text
        for title in (
            "Setup steps",
            "Preferences",
            "Authority boundary",
            "Hardware and resource readiness",
            "Data source policy",
        )
    )
    assert "Traceback" not in text


def test_empty_data_shows_unavailable():
    result = onboarding_page(None, None)
    assert "Unavailable" in _text(result)
    assert not any(getattr(control, "value", None) == "0" for control in _walk(result.body))
