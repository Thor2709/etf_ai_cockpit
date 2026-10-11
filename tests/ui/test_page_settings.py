from __future__ import annotations

from functools import lru_cache

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


@lru_cache(maxsize=1)
def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _walk(control):
    if isinstance(control, ft.Control):
        yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control):
    return "\n".join(
        str(getattr(item, "value", "") or getattr(item, "text", ""))
        for item in _walk(control)
    )


def test_renders_with_sample_data():
    result = settings_page(None, _state())
    assert isinstance(result, PageView)
    visible_text = [_text(result.body)]
    for view_name in ("Data & models", "Privacy", "About"):
        result.chrome.segment_groups[0].on_change(view_name)
        visible_text.append(_text(result.body))
    text = "\n".join(visible_text)
    assert all(
        title in text
        for title in (
            "Settings centre",
            "Change preview",
            "Guardrail settings",
            "Portfolio context targets",
            "Data providers",
            "Model settings",
            "Universe manager",
            "Primary tier universe",
            "Secondary and Sparebanken groups",
            "Asset support matrix",
            "Config folder",
            "Release and data metadata",
            "Offline update verification",
            "Legal terms, disclaimers and jurisdiction",
            "Third-party intake and upstream governance",
            "Settings status",
            "Privacy, backup and recovery",
        )
    )
    assert result.chrome.segment_groups[0].items == ("General", "Data & models", "Privacy", "About")
    assert result.chrome.segment_groups[0].on_change is not None
    assert "Traceback" not in text


def test_empty_data_shows_unavailable():
    result = settings_page(None, None)
    assert "Unavailable" in _text(result.body)
    assert not any(getattr(control, "value", None) == "0" for control in _walk(result.body))
