from __future__ import annotations

from etf_cockpit.app.pages.help_glossary import help_glossary_page
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_help_glossary_explains_authority_and_unavailable_states() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    view = help_glossary_page(None, state)
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(view))
    assert "Authority" in text
    assert "Manual review" in text
    assert "Unavailable" in text


def test_help_glossary_retains_hash_target_for_keyboard_navigation() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {"route": "/help#manual_review"})()
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(help_glossary_page(page, state)))
    assert "Selected definition" in text
