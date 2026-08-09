from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.core.ui_acceptance import (
    UI_LANES,
    build_main_ui_action_inventory,
    generate_ui_action_inventory,
    load_ui_acceptance_contracts,
    serialise_ui_action_inventory,
    ui_command_contracts,
    validate_generated_ui_action_inventory,
    validate_ui_acceptance_inventory,
)
from etf_cockpit.app.command_palette import all_commands
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS


def test_button_inventory_covers_workflow_and_recovery_actions() -> None:
    keys = {item.key for item in load_ui_acceptance_contracts()}
    assert "dashboard.refresh-yfinance" in keys
    assert "dashboard.export-audit" in keys
    assert "navigation.diagnostics" in keys
    assert "filings.fetch-sec" in keys
    assert "filings.import-manual-official" in keys
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
        "etf-disclosures.import-report",
        "etf-disclosures.verify-report",
        "etf-disclosures.reject-report",
        "errors.retry.*",
    } <= keys
    assert {item.control_type for item in contracts} >= {"navigation", "button", "file_picker", "expandable"}
    assert all(item.acceptance_test for item in contracts)
    assert all(item.success_signal and item.controlled_error_signal for item in contracts)


def test_button_inventory_fails_when_a_source_control_contract_is_removed() -> None:
    contracts = tuple(item for item in load_ui_acceptance_contracts() if item.key != "dashboard.export-audit")
    with pytest.raises(ValueError, match="source controls missing acceptance contracts"):
        validate_ui_acceptance_inventory(contracts, PAGES, source_root=Path("src/etf_cockpit/app"))


def test_generated_inventory_is_complete_stable_and_lane_covered() -> None:
    inventory = build_main_ui_action_inventory()
    assert {item.source for item in inventory} == {"control", "route", "command"}
    assert {item.lane for item in inventory} >= set(UI_LANES)
    assert len({item.action_id for item in inventory}) == len(inventory)
    assert len({item.command_id for item in inventory}) == len(inventory)
    assert all(item.execution_allowed is False for item in inventory)
    assert all(item.success_signal and item.failure_state for item in inventory)


def test_generated_inventory_is_idempotent_and_command_contracts_are_bound() -> None:
    first = build_main_ui_action_inventory()
    second = build_main_ui_action_inventory()
    assert serialise_ui_action_inventory(first) == serialise_ui_action_inventory(second)
    contracts = ui_command_contracts(first)
    assert len(contracts) == len(first)
    assert all(contract.callback and contract.idempotency_key for contract in contracts)
    assert all(contract.execution_allowed is False for contract in contracts)


def test_generated_inventory_rejects_duplicate_or_silent_metadata() -> None:
    inventory = list(generate_ui_action_inventory(load_ui_acceptance_contracts(), PAGES, all_commands(PAGES, WORKSPACE_GROUPS)))
    inventory[0] = inventory[0].__class__(**{**inventory[0].__dict__, "controlled_error_signal": ""})
    with pytest.raises(ValueError, match="visible failure coverage"):
        validate_generated_ui_action_inventory(inventory, PAGES)

    duplicate = inventory + [inventory[1]]
    with pytest.raises(ValueError, match="action IDs must be unique"):
        validate_generated_ui_action_inventory(duplicate, PAGES)
