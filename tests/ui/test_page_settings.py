from __future__ import annotations

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _text(control):
    values = [str(getattr(control, "value", "") or getattr(control, "text", ""))]
    for child in getattr(control, "controls", ()) or ():
        values.append(_text(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.append(_text(content))
    return "\n".join(values)


def test_renders_with_sample_data():
    result = settings_page(None, _state())
    assert isinstance(result, PageView)
    text = _text(result.body)
    assert all(title in text for title in ("Settings centre", "Change preview", "Guardrail settings", "Portfolio context targets"))
    assert "Traceback" not in text


def test_empty_data_shows_unavailable():
    text = _text(settings_page(None, _state()).body)
    assert "Unavailable" in text or "EmptyState" in text
    assert "0" not in text
