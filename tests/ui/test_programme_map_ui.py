from __future__ import annotations

import json

from etf_cockpit.app.pages import programme_map as programme_map_module
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
    assert "execution_allowed=false" in text
    assert "Release is the registry package status, not release certification." in text
    assert "ISSUE-0015" in text


def test_programme_map_hides_readiness_when_registry_is_malformed(tmp_path, monkeypatch) -> None:
    (tmp_path / "issues").mkdir()
    (tmp_path / "issues" / "issue_registry.json").write_text(json.dumps({"records": []}), encoding="utf-8")
    monkeypatch.setattr(programme_map_module, "ROOT", tmp_path)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(programme_map_module.programme_map_page(None, state))

    assert "Registry" in text
    assert "blocked" in text
    assert "No issue records are displayed while the registry is blocked." in text
    assert "ISSUE-0015" not in text
