from __future__ import annotations

from etf_cockpit.app.pages.diagnostics import diagnostics_page
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


def test_diagnostics_exposes_versioned_performance_and_resource_evidence() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(diagnostics_page(None, state))

    assert "Versioned budgets:" in text
    assert "local storage=" in text
    assert "network_calls=false" in text
    assert "Performance and recovery" in text
