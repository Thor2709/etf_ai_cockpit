from __future__ import annotations

from functools import lru_cache

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.import_export import import_export_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


@lru_cache(maxsize=1)
def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _walk(control):
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
    result = import_export_page(None, _state())
    assert isinstance(result, PageView)
    text = _text(result.body)
    for segment in result.chrome.segment_groups[0].items[1:]:
        result.chrome.segment_groups[0].on_change(segment)
        text += "\n" + _text(result.body)
    titles = (
        "Import", "Preview", "Bulk source cache", "Portfolio source rollback",
        "Identity mapping", "Account mapping", "Corrections", "Audit exports",
        "Reconciliation result", "Export destination", "Scoreboard", "Audit packet",
        "Watchlist", "Paper-trade journal", "Decision journal", "Plan/issues snapshot",
        "Backup and Restore",
    )
    assert all(title in text for title in titles)
    assert "Traceback" not in text


def test_empty_data_shows_unavailable():
    result = import_export_page(None, None)
    text = _text(result.body)
    assert "Unavailable" in text or "No portfolio rows staged" in text
    for control in _walk(result.body):
        if (getattr(control, "data", None) or {}).get("kit") == "DataTableRow":
            assert "0" not in _text(control)
