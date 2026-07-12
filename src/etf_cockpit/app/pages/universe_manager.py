from __future__ import annotations

from typing import Iterable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.config import load_config
from etf_cockpit.data.universe_store import (
    UniverseRecord,
    add_record,
    disable_record,
    edit_record,
    load_universe,
    remove_record,
    save_universe,
    validate_universe,
)


def records_from_config(state: AppState) -> tuple[UniverseRecord, ...]:
    rows: list[UniverseRecord] = []
    for etf in state.snapshot.config.universe.etfs:
        extra = getattr(etf, "model_extra", {}) or {}
        rows.append(
            UniverseRecord(
                instrument_id=etf.id,
                name=etf.name,
                isin=etf.isin or "needs_verification",
                isin_status=str(extra.get("isin_status", getattr(etf, "isin_status", "verified"))),
                ticker=etf.provider_symbol or etf.ticker,
                asset_type=str(extra.get("instrument_type", getattr(etf, "instrument_type", etf.asset_class))),
                tier=str(extra.get("analysis_tier", getattr(etf, "analysis_tier", "primary"))),
                group=str(extra.get("source_group", getattr(etf, "source_group", ""))),
                enabled=etf.enabled,
                data_policy=str(extra.get("data_policy", getattr(etf, "data_policy", "daily"))),
                currency=etf.currency,
                region=etf.region or "",
                sector=etf.sector or "",
                theme=etf.theme or "",
                notes=str(extra.get("notes", getattr(etf, "notes", ""))),
                leveraged=bool(extra.get("leveraged", getattr(etf, "leveraged", False))),
                inverse=bool(extra.get("inverse", getattr(etf, "inverse", False))),
            )
        )
    return tuple(rows)


def filter_records(records: Iterable[UniverseRecord], query: str = "", tier: str | None = None) -> tuple[UniverseRecord, ...]:
    needle = query.strip().casefold()
    selected = tier.strip().casefold() if tier else None
    return tuple(
        record
        for record in records
        if (selected is None or record.tier.casefold() == selected)
        and (not needle or needle in " ".join((record.instrument_id, record.name, record.ticker, record.isin, record.region, record.sector, record.theme)).casefold())
    )


def _table(records: Iterable[UniverseRecord], on_edit) -> ft.DataTable:
    rows: list[ft.DataRow] = []
    for record in records:
        status = "disabled" if not record.enabled else "needs_verification" if record.isin_status != "verified" else "ready"
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(record.instrument_id, color=theme.TEXT)),
                    ft.DataCell(ft.Text(record.name, color=theme.TEXT)),
                    ft.DataCell(ft.Text(record.ticker, color=theme.MUTED)),
                    ft.DataCell(ft.Text(record.asset_type, color=theme.MUTED)),
                    ft.DataCell(ft.Text(record.isin_status, color=theme.AMBER if record.isin_status != "verified" else theme.GREEN)),
                    ft.DataCell(ft.Text(status, color=theme.AMBER if status != "ready" else theme.GREEN)),
                    ft.DataCell(ft.Button("Edit", key=f"universe.edit.{record.instrument_id}", on_click=lambda _event, row=record: on_edit(row))),
                ]
            )
        )
    return ft.DataTable(
        columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in ("ID", "Name", "Yahoo ticker", "Type", "ISIN status", "Status", "Actions")],
        rows=rows,
        column_spacing=16,
    )


def universe_manager_page(page: ft.Page, state: AppState) -> ft.Control:
    # Capture the revision exactly once with the page snapshot. Save callbacks
    # must fail closed if another writer changes the store meanwhile.
    snapshot = load_universe()
    records = list(snapshot.records or records_from_config(state))
    expected_revision = snapshot.revision
    query = ft.TextField(label="Search universe", hint_text="ID, name, ticker, ISIN, sector or theme", dense=True, expand=True)
    status = ft.Text("No changes pending. needs_verification and pending refresh are shown per row.", color=theme.MUTED, selectable=True)
    allow_duplicates = ft.Checkbox(
        label="Allow cross-tier duplicate IDs/tickers/ISINs (explicit override)",
        value=snapshot.allow_cross_tier_duplicates,
        key="universe.allow-cross-tier-duplicates",
    )

    def _field(label: str, value: object = "", *, multiline: bool = False) -> ft.TextField:
        return ft.TextField(label=label, value=str(value or ""), multiline=multiline, min_lines=2 if multiline else 1, dense=True)

    def _bool_value(control: ft.Checkbox) -> bool:
        return bool(control.value)

    def _stage(message: str, changed: tuple[UniverseRecord, ...]) -> None:
        nonlocal records
        records = list(changed)
        status.value = message + " Pending refresh remains visible; no yfinance, scoring, forecast or broker call was started."
        rebuild_tabs()
        page.update()

    def _apply_saved_config(revision: str) -> None:
        refreshed_config = load_config()
        apply_method = getattr(state, "apply_universe_config", None)
        if callable(apply_method):
            apply_method(refreshed_config, revision)
            return
        # Compatibility fallback for lightweight embedding/test state objects.
        state.snapshot.config = refreshed_config
        state.snapshot.universe_revision = revision
        state.universe_cache_revision = revision

    def edit_dialog(record: UniverseRecord) -> None:
        controls = {
            "instrument_id": _field("ID", record.instrument_id),
            "name": _field("Name", record.name),
            "isin": _field("ISIN", record.isin),
            "isin_status": _field("ISIN status", record.isin_status),
            "ticker": _field("Yahoo ticker", record.ticker),
            "asset_type": _field("Asset type", record.asset_type),
            "tier": _field("Tier", record.tier),
            "group": _field("Group", record.group),
            "data_policy": _field("Data policy / frequency", record.data_policy),
            "currency": _field("Currency", record.currency),
            "region": _field("Region", record.region),
            "sector": _field("Sector", record.sector),
            "theme": _field("Theme", record.theme),
            "notes": _field("Notes", record.notes, multiline=True),
        }
        enabled = ft.Checkbox(label="Enabled for normal workflows", value=record.enabled)
        leveraged = ft.Checkbox(label="Leveraged (manual review)", value=record.leveraged)
        inverse = ft.Checkbox(label="Inverse (manual review)", value=record.inverse)

        def save_edit(_event: ft.ControlEvent) -> None:
            try:
                changes = {name: control.value or "" for name, control in controls.items()}
                changes["enabled"] = _bool_value(enabled)
                changes["leveraged"] = _bool_value(leveraged)
                changes["inverse"] = _bool_value(inverse)
                _stage(
                    "Validated edit pending save.",
                    edit_record(
                        records,
                        record.instrument_id,
                        allow_cross_tier_duplicates=bool(allow_duplicates.value),
                        **changes,
                    ),
                )
                dialog.open = False
            except Exception as exc:
                status.value = f"Edit rejected: {exc}"
                page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Edit {record.instrument_id}"),
            content=ft.Column([*controls.values(), enabled, leveraged, inverse], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancel", key="universe.edit-cancel", on_click=lambda _event: setattr(dialog, "open", False)), ft.Button("Validate and stage", key="universe.edit-save", on_click=save_edit)],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def add_dialog(_event: ft.ControlEvent | None = None) -> None:
        controls = {
            "instrument_id": _field("ID"),
            "name": _field("Name"),
            "isin": _field("ISIN", "needs_verification"),
            "isin_status": _field("ISIN status", "needs_verification"),
            "ticker": _field("Yahoo ticker"),
            "asset_type": _field("Asset type", "stock"),
            "tier": _field("Tier", "secondary"),
            "group": _field("Group"),
            "data_policy": _field("Data policy / frequency", "daily"),
            "currency": _field("Currency", "EUR"),
            "region": _field("Region"),
            "sector": _field("Sector"),
            "theme": _field("Theme"),
            "notes": _field("Notes", multiline=True),
        }
        enabled = ft.Checkbox(label="Enabled for normal workflows", value=True)
        leveraged = ft.Checkbox(label="Leveraged (manual review)", value=False)
        inverse = ft.Checkbox(label="Inverse (manual review)", value=False)

        def save_add(_save_event: ft.ControlEvent) -> None:
            try:
                values = {name: control.value or "" for name, control in controls.items()}
                values["enabled"] = _bool_value(enabled)
                values["leveraged"] = _bool_value(leveraged)
                values["inverse"] = _bool_value(inverse)
                candidate = UniverseRecord(**values)
                _stage(
                    "Validated add pending save.",
                    add_record(
                        records,
                        candidate,
                        allow_cross_tier_duplicates=bool(allow_duplicates.value),
                    ),
                )
                dialog.open = False
            except Exception as exc:
                status.value = f"Add rejected: {exc}"
                page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Add universe record"),
            content=ft.Column([*controls.values(), enabled, leveraged, inverse], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancel", key="universe.add-cancel", on_click=lambda _event: setattr(dialog, "open", False)), ft.Button("Validate and add", key="universe.add-save", on_click=save_add)],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def disable_item(record: UniverseRecord) -> None:
        try:
            _stage(
                f"Disabled {record.instrument_id}.",
                disable_record(
                    records,
                    record.instrument_id,
                    allow_cross_tier_duplicates=bool(allow_duplicates.value),
                ),
            )
        except Exception as exc:
            status.value = f"Disable rejected: {exc}"
            page.update()

    def enable_item(record: UniverseRecord) -> None:
        try:
            _stage(
                f"Enabled {record.instrument_id}.",
                edit_record(
                    records,
                    record.instrument_id,
                    enabled=True,
                    allow_cross_tier_duplicates=bool(allow_duplicates.value),
                ),
            )
        except Exception as exc:
            status.value = f"Enable rejected: {exc}"
            page.update()

    def remove_item(record: UniverseRecord) -> None:
        try:
            _stage(f"Removed {record.instrument_id}.", remove_record(records, record.instrument_id))
        except Exception as exc:
            status.value = f"Remove rejected: {exc}"
            page.update()

    def save_changes(_event: ft.ControlEvent) -> None:
        nonlocal expected_revision
        report = validate_universe(records, allow_cross_tier_duplicates=bool(allow_duplicates.value))
        if not report.valid:
            status.value = "Save blocked: " + "; ".join(report.errors)
            page.update()
            return
        try:
            result = save_universe(
                records,
                expected_revision=expected_revision,
                allow_cross_tier_duplicates=bool(allow_duplicates.value),
            )
            expected_revision = result.revision
            _apply_saved_config(result.revision)
            status.value = f"Saved revision {result.revision[:12]}; pending refresh remains visible and was not started."
        except Exception as exc:
            status.value = f"Save blocked: {exc}"
        page.update()

    def _table_with_actions(rows: Iterable[UniverseRecord]) -> ft.DataTable:
        table = _table(rows, edit_dialog)
        for row, record in zip(table.rows, rows):
            if record.enabled:
                action_button = ft.Button(
                    "Disable",
                    key=f"universe.disable.{record.instrument_id}",
                    on_click=lambda _event, item=record: disable_item(item),
                )
            else:
                action_button = ft.Button(
                    "Enable",
                    key=f"universe.enable.{record.instrument_id}",
                    on_click=lambda _event, item=record: enable_item(item),
                )
            row.cells[-1] = ft.DataCell(ft.Row([
                ft.Button("Edit", key=f"universe.edit.{record.instrument_id}", on_click=lambda _event, item=record: edit_dialog(item)),
                action_button,
                ft.Button("Remove", key=f"universe.remove.{record.instrument_id}", on_click=lambda _event, item=record: remove_item(item)),
            ], wrap=True))
        return table

    tab_bar = ft.TabBar(tabs=[])
    tab_views = ft.TabBarView(controls=[], expand=True)
    tabs_control = ft.Tabs(
        length=3,
        selected_index=0,
        expand=True,
        content=ft.Column([tab_bar, tab_views], expand=True),
    )

    def rebuild_tabs(_event: ft.ControlEvent | None = None) -> None:
        needle = query.value or ""
        tiers = (("primary", "Primary"), ("secondary", "Secondary"), ("sparebanken", "Sparebanken"))
        tab_bar.tabs = [ft.Tab(label=title) for _tier, title in tiers]
        tab_views.controls = [
            ft.Container(content=_table_with_actions(filter_records(records, needle, tier=tier)), padding=8)
            for tier, _title in tiers
        ]
        page.update()

    query.on_change = rebuild_tabs
    add_button = ft.Button("Add record", key="universe.add", icon=ft.Icons.ADD, on_click=add_dialog)
    rebuild_tabs()

    return ft.Column(
        [
            panel(ft.Column([section_header("Universe and watchlists", "Manage validated local candidates across the Primary, Secondary and Sparebanken tiers."), ft.Row([query, add_button, ft.Button("Save validated changes", key="universe.save", icon=ft.Icons.SAVE, on_click=save_changes)], wrap=True), allow_duplicates, status, ft.Text("Edits persist only after validation. Saving never starts yfinance, scoring, forecasts or broker execution.", color=theme.MUTED)], spacing=8)),
            panel(tabs_control),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
