from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.core.ui_acceptance import load_ui_acceptance_contracts, validate_ui_acceptance_inventory
from etf_cockpit.app.router import PAGES


def test_button_inventory_covers_workflow_and_recovery_actions() -> None:
    keys = {item.key for item in load_ui_acceptance_contracts()}
    assert "dashboard.refresh-yfinance" in keys
    assert "dashboard.export-audit" in keys
    assert "navigation.diagnostics" in keys
    assert "filings.fetch-sec" in keys
    assert "import-export.backup-restore" not in keys
    assert {"import-export.bulk-cache", "import-export.commit", "import-export.restore-commit", "import-export.restore-cancel"} <= keys


def test_button_inventory_covers_registered_routes_and_control_metadata() -> None:
    contracts = load_ui_acceptance_contracts()
    routes = {item.route for item in contracts}
    assert set(PAGES) <= routes
    validate_ui_acceptance_inventory(contracts, PAGES, source_root=Path("src/etf_cockpit/app"))
    keys = {item.key for item in contracts}
    assert {
        "dashboard.score-row-expand.*",
        "dashboard.renew-import.file-picker",
        "filings.import.file-picker",
        "errors.retry.*",
    } <= keys
    assert {item.control_type for item in contracts} >= {"navigation", "button", "file_picker", "expandable"}
    assert all(item.acceptance_test for item in contracts)
    assert all(item.success_signal and item.controlled_error_signal for item in contracts)


def test_button_inventory_fails_when_a_source_control_contract_is_removed() -> None:
    contracts = tuple(item for item in load_ui_acceptance_contracts() if item.key != "dashboard.export-audit")
    with pytest.raises(ValueError, match="source controls missing acceptance contracts"):
        validate_ui_acceptance_inventory(contracts, PAGES, source_root=Path("src/etf_cockpit/app"))
