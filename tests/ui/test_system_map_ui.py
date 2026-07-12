from __future__ import annotations

from etf_cockpit.app.pages.system_map import system_map_page
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


def test_system_map_shows_future_execution_as_non_interactive() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    text = _text(system_map_page(None, state))
    assert "Not installed" in text
    assert "Enable trading" not in text
    assert "No broker execution" in text


def test_system_map_reports_loaded_dependencies_and_data_health_validation() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    text = _text(system_map_page(None, state))
    assert "Readiness:" in text
    assert "feature_registry=loaded" in text
    assert "Validation: data-health=" in text
    assert "No explicit limitation recorded" in text or "Policy load failure" in text
