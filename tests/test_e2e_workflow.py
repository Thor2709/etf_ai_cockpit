from __future__ import annotations

import time

from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.state import AppState
from etf_cockpit.app.router import PAGES, navigate_to
from etf_cockpit.services import build_snapshot


class _Page:
    route = "/"
    width = 1400
    update_count = 0
    views: list[object] = []

    def update(self) -> None:
        self.update_count += 1


def test_source_workflow_success_and_failure_have_visible_terminal_states(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etf_cockpit.app.state.ACTIVITY_LOG_PATH", tmp_path / "activity.jsonl")
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _Page()

    _run_action(page, state, "Deterministic success", lambda: "done")
    deadline = time.time() + 5
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.02)
    assert state.recent_activity[-1].status == "success"

    _run_action(page, state, "Deterministic failure", lambda: (_ for _ in ()).throw(TimeoutError("provider timeout")))
    deadline = time.time() + 5
    while state.current_activity is not None and time.time() < deadline:
        time.sleep(0.02)
    assert state.recent_activity[-1].status == "failed"
    assert "timeout" in state.recent_activity[-1].message.lower()
    assert page.update_count >= 4


def test_navigation_matrix_has_all_declared_trust_routes() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _Page()
    for route in ("/", "/providers", "/evidence", "/filings", "/etf-disclosures", "/news-context", "/diagnostics"):
        navigate_to(page, state, route)
        assert page.route == route
        assert route in PAGES
