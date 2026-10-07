from __future__ import annotations

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.jobs import jobs_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


class _Page:
    def update(self):
        pass


def _text(control):
    values = [str(getattr(control, "value", "") or getattr(control, "text", ""))]
    for child in getattr(control, "controls", ()) or ():
        values.append(_text(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.append(_text(content))
    return "\n".join(values)


def test_renders_with_sample_data():
    result = jobs_page(_Page(), _state())
    assert isinstance(result, PageView)
    text = _text(result)
    assert all(title in text for title in ("Workflows", "Resource readiness", "Timeline", "Audit events"))
    assert "Traceback" not in text


def test_empty_data_shows_unavailable():
    text = _text(jobs_page(_Page(), _state()))
    assert "Unavailable" in text or "EmptyState" in text or "No durable workflows" in text
    assert "0" not in text
