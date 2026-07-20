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
    controls = list(_walk(page))

    assert any(getattr(item, "key", None) == "filings.discover-oam" for item in buttons)
    assert any(getattr(item, "content", None) == "Discover official filings" for item in buttons)
    assert any(getattr(item, "key", None) == "filings.import-manual-official" for item in buttons)
    country = next(item for item in controls if getattr(item, "label", None) == "Official filing country")
    assert {option.key for option in country.options} == {"DK", "FI", "FR", "GB", "NL", "NO", "SE"}
    api_key = next(item for item in controls if getattr(item, "label", None) == "Companies House API key")
    assert api_key.password is True
    assert api_key.can_reveal_password is False
