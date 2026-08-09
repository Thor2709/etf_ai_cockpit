from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from etf_cockpit.core.ui_acceptance import (
    UI_LANES,
    UICommandContract,
    build_main_ui_action_inventory,
    discover_actionable_controls,
    load_ui_acceptance_contracts,
    serialise_ui_action_inventory,
    ui_command_contracts,
    validate_generated_ui_action_inventory,
    validate_ui_acceptance_inventory,
)
from etf_cockpit.app.router import PAGES


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


def test_source_discovery_covers_constructor_post_binding_inputs_and_file_pickers() -> None:
    controls = discover_actionable_controls(Path("src/etf_cockpit/app"))
    assert controls["dashboard.refresh-yfinance"].events == ("on_click",)
    assert controls["operations.paper-open"].events == ("on_click",)
    assert controls["operations.paper-open"].callbacks == ("open_paper_account",)
    assert controls["stock-research.capital-basis"].events == ("on_change",)
    assert controls["stock-research.capital-basis"].callbacks == ("select_basis",)
    assert controls["data-health.filter.status"].events == ("on_select",)
    assert controls["dashboard.renew-import.file-picker"].events == ("file_picker",)
    assert controls["dashboard.renew-import.file-picker"].callbacks == ("pick_files",)
    assert controls["shell.command-palette.on-change"].events == ("on_change",)
    assert controls["shell.command-palette.on-change"].callbacks == ("render_palette_results",)
    assert controls["shell.command-palette.on-submit"].events == ("on_submit",)
    assert controls["shell.command-palette.on-submit"].callbacks == ("submit_palette",)
    assert "shell.command-palette" not in controls


@pytest.mark.parametrize("removed_key", ["dashboard.export-audit", "operations.paper-open"])
def test_button_inventory_fails_when_a_source_control_contract_is_removed(removed_key: str) -> None:
    contracts = tuple(item for item in load_ui_acceptance_contracts() if item.key != removed_key)
    with pytest.raises(ValueError, match=removed_key.replace("*", r"\*")):
        validate_ui_acceptance_inventory(contracts, PAGES, source_root=Path("src/etf_cockpit/app"))


def test_source_parity_rejects_stock_research_key_or_callback_mismatch(tmp_path: Path) -> None:
    contract = next(item for item in load_ui_acceptance_contracts() if item.key == "stock-research.capital-basis")
    source = Path("src/etf_cockpit/app/pages/stock_research.py").read_text(encoding="utf-8")
    source_root = tmp_path / "app"
    source_root.mkdir()
    (source_root / "stock_research.py").write_text(
        source.replace('key="stock-research.capital-basis"', 'key="stock-research-capital-basis"'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="stock-research-capital-basis"):
        validate_ui_acceptance_inventory((contract,), ("/stock-research",), source_root=source_root)

    (source_root / "stock_research.py").write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match="callback mismatch"):
        validate_ui_acceptance_inventory(
            (replace(contract, callback="invented_callback"),),
            ("/stock-research",),
            source_root=source_root,
        )


@pytest.mark.parametrize(
    ("key", "callback", "mutation"),
    [
        (
            "training-centre.synthetic-scenario",
            "generate_synthetic_scenario",
            "on_click=lambda _event: None",
        ),
        (
            "universe.edit-cancel",
            "cancel_edit",
            "on_click=lambda _event: setattr(dialog, \"open\", False)",
        ),
    ],
)
def test_actionable_controls_reject_unresolved_or_invented_callbacks(
    tmp_path: Path,
    key: str,
    callback: str,
    mutation: str,
) -> None:
    contract = next(item for item in load_ui_acceptance_contracts() if item.key == key)
    source_root = tmp_path / "app"
    source_root.mkdir()
    source_file = source_root / "controls.py"
    source_file.write_text(
        f'ft.TextButton(key="{key}", {mutation})\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=rf"unresolved callbacks: {key}"):
        validate_ui_acceptance_inventory((contract,), (contract.route,), source_root=source_root)

    source_file.write_text(
        f"def {callback}(_event):\n    return None\n"
        f'ft.TextButton(key="{key}", on_click={callback})\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=rf"callback mismatch: {key}"):
        validate_ui_acceptance_inventory(
            (replace(contract, callback="invented_callback"),),
            (contract.route,),
            source_root=source_root,
        )


def test_actionable_control_rejects_undefined_named_callback(tmp_path: Path) -> None:
    contract = next(
        item
        for item in load_ui_acceptance_contracts()
        if item.key == "training-centre.synthetic-scenario"
    )
    source_root = tmp_path / "app"
    source_root.mkdir()
    (source_root / "controls.py").write_text(
        'ft.TextButton(key="training-centre.synthetic-scenario", on_click=undefined_callback)\n',
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match="unresolved callbacks: training-centre.synthetic-scenario",
    ):
        validate_ui_acceptance_inventory(
            (replace(contract, callback="undefined_callback"),),
            (contract.route,),
            source_root=source_root,
        )


def test_orphan_input_contract_is_rejected_instead_of_omitted() -> None:
    contracts = load_ui_acceptance_contracts()
    template = next(item for item in contracts if item.control_type == "input")
    orphan = replace(
        template,
        key="invented.orphan-input",
        callback="invented_callback",
        success_signal="ui.success.invented.orphan-input",
        controlled_error_signal="ui.failure.invented.orphan-input",
    )
    with pytest.raises(ValueError, match="invented.orphan-input"):
        validate_ui_acceptance_inventory(
            (*contracts, orphan),
            PAGES,
            source_root=Path("src/etf_cockpit/app"),
        )


def test_generated_inventory_is_complete_stable_and_lane_covered() -> None:
    inventory = build_main_ui_action_inventory()
    assert {item.source for item in inventory} == {"control", "route", "command"}
    assert {item.lane for item in inventory} >= set(UI_LANES)
    assert len({item.action_id for item in inventory}) == len(inventory)
    assert len({item.command_id for item in inventory}) == len(inventory)
    assert all(item.execution_allowed is False for item in inventory)
    assert all(item.success_signal and item.failure_state for item in inventory)
    palette_actions = {
        item.key: item.callback
        for item in inventory
        if item.key.startswith("shell.command-palette.")
    }
    assert palette_actions == {
        "shell.command-palette.on-change": "render_palette_results",
        "shell.command-palette.on-submit": "submit_palette",
    }


def test_generated_inventory_is_idempotent_and_command_contracts_are_bound() -> None:
    first = build_main_ui_action_inventory()
    second = build_main_ui_action_inventory()
    assert serialise_ui_action_inventory(first) == serialise_ui_action_inventory(second)
    contracts = ui_command_contracts(first)
    assert len(contracts) == len(first)
    assert all(contract.callback and contract.idempotency_key for contract in contracts)
    assert all(contract.execution_allowed is False for contract in contracts)


def test_generated_inventory_rejects_duplicate_or_silent_metadata() -> None:
    inventory = list(build_main_ui_action_inventory())
    inventory[0] = inventory[0].__class__(**{**inventory[0].__dict__, "controlled_error_signal": ""})
    with pytest.raises(ValueError, match="visible failure coverage"):
        validate_generated_ui_action_inventory(inventory, PAGES)

    duplicate = inventory + [inventory[1]]
    with pytest.raises(ValueError, match="action IDs must be unique"):
        validate_generated_ui_action_inventory(duplicate, PAGES)


def test_lane_and_signal_metadata_cannot_be_spoofed(tmp_path: Path) -> None:
    inventory = list(build_main_ui_action_inventory())
    live_index = next(index for index, item in enumerate(inventory) if item.key == "operations.preview")
    inventory[live_index] = replace(inventory[live_index], lane="research")
    with pytest.raises(ValueError, match="lane mismatch"):
        validate_generated_ui_action_inventory(inventory, PAGES)

    inventory = list(build_main_ui_action_inventory())
    research_index = next(index for index, item in enumerate(inventory) if item.key == "dashboard.refresh-yfinance")
    inventory[research_index] = replace(inventory[research_index], lane="live_stage")
    with pytest.raises(ValueError, match="lane mismatch"):
        validate_generated_ui_action_inventory(inventory, PAGES)

    metadata = tmp_path / "ui.yaml"
    metadata.write_text(
        "version: 3\ncontrols:\n"
        "  - {key: test.action, route: /, control_label: Test, callback: callback, "
        "success_signal: invented, controlled_error_signal: auto, acceptance_test: tests/test.py, control_type: button}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="signals are authoritative"):
        load_ui_acceptance_contracts(metadata)
    metadata.write_text(
        "version: 3\ncontrols:\n"
        "  - {key: test.action, route: /, control_label: Test, callback: callback, "
        "success_signal: auto, controlled_error_signal: auto, acceptance_test: tests/test.py, "
        "control_type: button, lane: live_stage}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="lane is authoritative"):
        load_ui_acceptance_contracts(metadata)


def test_command_contract_executes_success_failure_and_duplicate_visibly() -> None:
    contract = UICommandContract(
        command_id="control-command:test.action",
        action_id="control:test.action",
        route="/",
        callback="callback",
        success_signal="ui.success.test.action",
        controlled_error_signal="ui.failure.test.action",
        idempotency_key="ui:control:test.action",
    )
    calls: list[str] = []
    failures: list[str] = []

    def callback(_event: object | None) -> None:
        calls.append("called")

    invoked = {}
    completed = contract.invoke(callback, invoked=invoked, show_failure=failures.append)
    replayed = contract.invoke(callback, invoked=invoked, show_failure=failures.append)
    assert (completed.status, completed.signal, calls) == ("completed", contract.success_signal, ["called"])
    assert replayed.status == "completed" and replayed.replayed is True
    assert (replayed.signal, replayed.visible_message) == (completed.signal, completed.visible_message)
    assert calls == ["called"] and failures == []

    def failing_callback(_event: object | None) -> None:
        raise RuntimeError("visible test failure")

    failing_contract = replace(contract, callback="failing_callback", idempotency_key="ui:control:test.failure")
    failed = failing_contract.invoke(failing_callback, invoked=invoked, show_failure=failures.append)
    failed_replay = failing_contract.invoke(failing_callback, invoked=invoked, show_failure=failures.append)
    assert failed.status == "failed" and failed.signal == failing_contract.controlled_error_signal
    assert failed_replay.status == "failed" and failed_replay.replayed is True
    assert (failed_replay.signal, failed_replay.visible_message) == (failed.signal, failed.visible_message)
    assert failures == [failed.visible_message, failed.visible_message]
    assert failed.execution_allowed is False


def test_package_configuration_carries_and_smoke_validates_inventory() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    smoke = Path("scripts/smoke_app.py").read_text(encoding="utf-8")
    assert '"configs" = ["configs/ui_acceptance.yaml"]' in project
    assert "verify_ui_action_inventory()" in smoke
