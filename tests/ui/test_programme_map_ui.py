from __future__ import annotations

from etf_cockpit.app.pages.programme_map import programme_map_page
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(control))


def test_programme_map_shows_canonical_status_dimensions() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(programme_map_page(None, state))

    assert "Programme Map" in text
    assert "Canonical issue records:" in text
    for label in ("Implementation", "Release", "Data", "Model", "Paper", "Live"):
        assert label in text
    assert "disabled_by_policy" in text
    assert "Release is the registry package status, not release certification." in text
    assert "ISSUE-0015" in text
