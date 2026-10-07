from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import release_readiness
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _texts(control: object) -> list[str]:
    values = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(control, "controls", ()) or ():
        values.extend(_texts(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_texts(content))
    body = getattr(control, "body", None)
    if body is not None:
        values.extend(_texts(body))
    return values


def test_renders_with_sample_data() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    result = release_readiness.release_readiness_page(None, state)
    text = "\n".join(_texts(result))
    assert isinstance(result, PageView)
    assert all(title in text for title in ("Mandatory checks", "Release evidence", "Blockers", "Accepted limitations", "Quality programme", "Legal terms"))
    assert "Mandatory check evidence" in text
    assert "Traceback" not in text


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(release_readiness, "release_certification_report", lambda _root: {"status": "blocked", "network_calls": None, "execution_allowed": False, "checks": [], "blockers": [], "accepted_limitations": []})
    monkeypatch.setattr(release_readiness, "legal_terms_report", lambda _root: {})
    monkeypatch.setattr(release_readiness, "load_quality_programme_report", lambda _root: {})
    result = release_readiness.release_readiness_page(None, SimpleNamespace())
    texts = _texts(result)
    assert isinstance(result, PageView)
    assert any("Unavailable" in value or "unavailable" in value.casefold() for value in texts)
    assert "0" not in texts
