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
    assert all(title in text for title in ("Data source", "Watchlist", "Review & save"))
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


def test_setup_cards_build_with_bounded_scroll_layout():
    result = onboarding_page(None, _sample_state())
    controls = list(_walk(result.body))
    cards = {
        (getattr(control, "data", None) or {}).get("title")
        for control in controls
        if (getattr(control, "data", None) or {}).get("kit") == "GlassCard"
    }
    assert {"Setup steps", "Authority boundary", "Hardware and resource readiness", "Data source policy"} <= cards
    for control in controls:
        if isinstance(control, ft.Column) and control.scroll == ft.ScrollMode.AUTO:
            assert all(not getattr(child, "expand", False) for child in control.controls)
            assert not any(type(child).__name__ == "ListView" for child in control.controls)

    stepper = next(
        control for control in controls
        if isinstance(getattr(control, "data", None), dict) and control.data.get("kit") == "Stepper"
    )
    watchlist_step = [
        control for control in _walk(stepper)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "StepperStep"
        and control.data.get("index") == 2
    ][0]
    open_watchlist = next(
        control for control in _walk(watchlist_step)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "Button"
        and control.data.get("text") == "Open"
    )
    open_watchlist.on_click(None)
    checkbox = next(control for control in _walk(result.body) if isinstance(control, ft.Checkbox))
    assert checkbox.disabled is True
    assert checkbox.value is False
