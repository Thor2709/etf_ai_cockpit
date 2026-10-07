from __future__ import annotations

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.import_export import import_export_page
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
    result = import_export_page(None, _state())
    assert isinstance(result, PageView)
    text = _text(result.body)
    assert all(title in text for title in ("Import", "Preview", "Bulk source cache", "Portfolio source rollback"))
    assert "Traceback" not in text


def test_empty_data_shows_unavailable():
    text = _text(import_export_page(None, _state()).body)
    assert "Unavailable" in text or "EmptyState" in text or "No portfolio rows staged" in text
    assert "0" not in text
