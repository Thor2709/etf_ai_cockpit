from __future__ import annotations

from etf_cockpit.app.pages.trust_evidence import filings_page
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_filings_page_exposes_national_oam_discovery_control() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = filings_page(None, state)
    buttons = [item for item in _walk(page) if item.__class__.__name__ == "OutlinedButton"]

    assert any(getattr(item, "key", None) == "filings.discover-oam" for item in buttons)
    assert any(getattr(item, "content", None) == "Discover national OAM" for item in buttons)
