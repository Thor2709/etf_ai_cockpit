from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import programme_map
from etf_cockpit.app.state import AppState
from etf_cockpit.application.programme_map import ProgrammeMap
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


def _kit_controls(control: object, kind: str) -> list[object]:
    found = []
    pending = [control]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        data = getattr(current, "data", None)
        if isinstance(data, dict) and data.get("kit") == kind:
            found.append(current)
        pending.extend(getattr(current, "controls", ()) or ())
        for name in ("content", "body"):
            child = getattr(current, name, None)
            if child is not None:
                pending.append(child)
    return found


def test_renders_with_sample_data() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    result = programme_map.programme_map_page(None, state)
    text = "\n".join(_texts(result))
    assert isinstance(result, PageView)
    assert all(title in text for title in ("Registry", "Issues by status", "Issues"))
    assert "Traceback" not in text
    map_data = programme_map.load_programme_map(programme_map.ROOT)
    assert map_data.status == "loaded"
    expected_blocked = sum(entry.implementation == "blocked" for entry in map_data.entries)
    result.chrome.segment_groups[0].on_change("Blocked")
    tables = _kit_controls(result.body, "DataTable")
    if expected_blocked:
        assert tables[-1].data["rows"] == expected_blocked
    else:
        assert "No issues in this view" in "\n".join(_texts(result))


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(programme_map, "load_programme_map", lambda _root: ProgrammeMap("blocked", "", (), (), "Registry unavailable"))
    result = programme_map.programme_map_page(None, SimpleNamespace())
    texts = _texts(result)
    assert isinstance(result, PageView)
    assert any("Registry blocked" in value or "Unavailable" in value for value in texts)
    assert "0" not in texts
