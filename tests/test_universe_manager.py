from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flet as ft

import etf_cockpit.app.pages.universe_manager as manager
from etf_cockpit.app.pages.universe_manager import universe_manager_page
from etf_cockpit.core.config import (
    AppConfig,
    CostConfig,
    ETFConfig,
    ModelSettings,
    PortfolioTargets,
    RiskLimits,
    UISettings,
    UniverseConfig,
)
from etf_cockpit.data.universe_store import UniverseRecord, UniverseSaveResult, UniverseStoreSnapshot


class _Page:
    def __init__(self) -> None:
        self.overlay: list[ft.Control] = []
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


def _state() -> SimpleNamespace:
    config = AppConfig(
        universe=UniverseConfig(etfs=[ETFConfig(id="A", name="Alpha", ticker="A", role="core")]),
        targets=PortfolioTargets(),
        risks=RiskLimits(),
        costs=CostConfig(),
        models=ModelSettings(),
        ui=UISettings(),
        chatgpt_schema={},
    )
    return SimpleNamespace(snapshot=SimpleNamespace(config=config))


def _walk(control: ft.Control):
    if not isinstance(control, ft.Control):
        return
    yield control
    for attr in ("controls", "rows", "cells", "actions"):
        values = getattr(control, attr, None)
        if values:
            for child in values:
                yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_real_crud_controls_stage_changes_and_save_captured_revision(monkeypatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary", "", True, "daily", "EUR", "NO", "", "", "")
    monkeypatch.setattr(manager, "load_universe", lambda: UniverseStoreSnapshot((record,), "captured-revision", Path("store.json")))
    saved: list[tuple[tuple[UniverseRecord, ...], str]] = []

    def fake_save(records, expected_revision, **_kwargs):
        rows = tuple(records)
        saved.append((rows, expected_revision))
        revision = f"revision-{len(saved)}"
        return UniverseSaveResult(Path("store.json"), revision, len(rows))

    monkeypatch.setattr(manager, "save_universe", fake_save)
    page = _Page()
    root = universe_manager_page(page, _state())
    controls = {str(control.key): control for control in _walk(root) if control.key}
    buttons = {key: control for key, control in controls.items() if isinstance(control, ft.Button)}
    assert {"universe.add", "universe.save", "universe.edit.A", "universe.disable.A", "universe.remove.A"} <= set(buttons)
    assert "universe.allow-cross-tier-duplicates" in controls

    # Disable and add use the real callbacks, and neither callback invokes a
    # workflow service. The newly added record proves full add control wiring.
    buttons["universe.disable.A"].on_click(None)
    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    assert "universe.enable.A" in buttons
    buttons["universe.enable.A"].on_click(None)
    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    assert "universe.disable.A" in buttons
    buttons["universe.add"].on_click(None)
    assert page.overlay
    dialog = page.overlay[-1]
    fields = {str(control.label): control for control in _walk(dialog) if isinstance(control, ft.TextField) and control.label}
    fields["ID"].value = "B"
    fields["Name"].value = "Beta"
    fields["Yahoo ticker"].value = "B"
    fields["ISIN"].value = "NO0000000002"
    fields["ISIN status"].value = "verified"
    enabled_checkbox = next(control for control in _walk(dialog) if isinstance(control, ft.Checkbox) and control.label == "Enabled for normal workflows")
    enabled_checkbox.value = False
    next(control for control in _walk(dialog) if isinstance(control, ft.Button) and control.key == "universe.add-save").on_click(None)

    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    buttons["universe.save"].on_click(None)
    buttons = {str(control.key): control for control in _walk(root) if isinstance(control, ft.Button) and control.key}
    buttons["universe.save"].on_click(None)
    assert [revision for _rows, revision in saved] == ["captured-revision", "revision-1"]
    assert {row.instrument_id for row in saved[-1][0]} == {"A", "B"}
    assert next(row for row in saved[-1][0] if row.instrument_id == "B").enabled is False

    # Search is wired to a callback that rebuilds the three visible tier tabs.
    query = next(control for control in _walk(root) if isinstance(control, ft.TextField) and control.label == "Search universe")
    query.value = "Beta"
    query.on_change(None)
    tabs = next(control for control in _walk(root) if isinstance(control, ft.TabBar))
    assert [tab.label for tab in tabs.tabs] == ["Primary", "Secondary", "Sparebanken"]
