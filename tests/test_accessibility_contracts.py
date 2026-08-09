from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.app.router import PAGES, build_shell
from etf_cockpit.core.ui_acceptance import load_ui_acceptance_contracts
from etf_cockpit.services import build_snapshot
from etf_cockpit.app.state import AppState


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_declared_ui_actions_have_unique_keys_callbacks_and_signals() -> None:
    contracts = load_ui_acceptance_contracts()
    assert len(contracts) >= 10
    assert len({item.key for item in contracts}) == len(contracts)
    assert all(item.callback and (item.success_signal or item.controlled_error_signal) for item in contracts)
    assert all(item.route in PAGES or item.route == "/signals" for item in contracts)


def test_shell_exposes_stable_navigation_and_dashboard_keys() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {"width": 1400, "route": "/"})()
    view = build_shell(page, state, "/")
    keys = {str(control.key) for control in _walk(view) if getattr(control, "key", None)}
    expected = {item.key for item in load_ui_acceptance_contracts()}
    assert {key for key in expected if key.startswith("navigation.")} <= keys
    assert {"dashboard.refresh-yfinance", "dashboard.run-algorithms", "dashboard.run-forecasting-models", "dashboard.show-scores"} <= keys


def test_invalid_contracts_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "ui.yaml"
    path.write_text(
        "version: 3\ncontrols:\n"
        "  - {key: navigation.home, route: /, control_label: Home, callback: go, "
        "success_signal: auto, controlled_error_signal: auto, acceptance_test: tests/test.py}\n"
        "  - {key: navigation.home, route: /, control_label: Duplicate, callback: go, "
        "success_signal: auto, controlled_error_signal: auto, acceptance_test: tests/test.py}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        load_ui_acceptance_contracts(path)
