from __future__ import annotations

from etf_cockpit.app.pages.release_readiness import release_readiness_page
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


def test_release_readiness_shows_fail_closed_certification_evidence() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(release_readiness_page(None, state))

    assert "Release Readiness" in text
    assert "ISSUE-0152" in text
    assert "blocked" in text.casefold()
    assert "execution_allowed=false" in text
    assert "Legal terms" in text
    assert "Accepted limitations" in text
