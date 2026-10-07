from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.onboarding import onboarding_page


def _walk(control):
    if isinstance(control, ft.Control):
        yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_renders_with_sample_data():
    result = onboarding_page(None, None)
    assert isinstance(result, PageView)
    text = "\n".join(str(getattr(c, "value", "") or getattr(c, "text", "")) for c in _walk(result.body))
    assert all(title in text for title in ("Setup steps", "Authority boundary", "Hardware and resource readiness", "Data source policy"))
    assert "Traceback" not in text


def test_empty_data_shows_unavailable():
    result = onboarding_page(None, None)
    text = "\n".join(str(getattr(c, "value", "") or getattr(c, "text", "")) for c in _walk(result.body))
    assert "Unavailable" in text or "EmptyState" in text
    assert "0" not in text
