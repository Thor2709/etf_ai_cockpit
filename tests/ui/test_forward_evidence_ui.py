from __future__ import annotations

import inspect

import etf_cockpit.app.pages.forward_evidence as forward_evidence_module
from etf_cockpit.app.pages.forward_evidence import forward_evidence_page
from etf_cockpit.app.router import PAGES, workspace_for_route
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_forward_evidence_route_and_controls_are_visible_and_non_executable() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    controls = list(_walk(forward_evidence_page(None, state)))
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in controls)
    keys = {getattr(item, "key", "") for item in controls}

    assert PAGES["/forward-evidence"][0] == "Forward Evidence Diary"
    assert workspace_for_route("/forward-evidence") == "Backtest/Paper"
    assert {"forward-evidence.record", "forward-evidence.update"} <= keys
    assert "execution_allowed=false" in text
    assert "Paper proposals are evidence only" in text


def test_forward_evidence_page_uses_application_facade_and_is_explicitly_local() -> None:
    source = inspect.getsource(forward_evidence_page)
    assert "ForwardEvidenceDiary" in source
    assert "No external or broker action" in source


def test_forward_evidence_record_callback_reports_validation_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(forward_evidence_module, "DATA_DIR", tmp_path)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    controls = list(_walk(forward_evidence_page(None, state)))
    record = next(item for item in controls if getattr(item, "key", "") == "forward-evidence.record")
    status = next(item for item in controls if getattr(item, "value", "") == "No external or broker action is available; execution_allowed=false.")
    record.on_click(None)
    assert "Error: observation was not recorded" in status.value
    assert not (tmp_path / "forward_evidence_diary").exists()
