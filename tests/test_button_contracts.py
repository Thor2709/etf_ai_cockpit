from __future__ import annotations

from etf_cockpit.core.ui_acceptance import load_ui_acceptance_contracts


def test_button_inventory_covers_workflow_and_recovery_actions() -> None:
    keys = {item.key for item in load_ui_acceptance_contracts()}
    assert "dashboard.refresh-yfinance" in keys
    assert "dashboard.export-audit" in keys
    assert "navigation.diagnostics" in keys
