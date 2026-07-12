from __future__ import annotations

from typing import Iterable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.data.universe_store import UniverseRecord, edit_record, load_universe, save_universe, validate_universe


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
    records = list(records_from_config(state))
    query = ft.TextField(label="Search universe", hint_text="ID, name, ticker, ISIN, sector or theme", dense=True, expand=True)
    status = ft.Text("No changes pending.", color=theme.MUTED, selectable=True)

    def edit_dialog(record: UniverseRecord) -> None:
        notes = ft.TextField(label="Notes", value=record.notes, multiline=True, min_lines=2)
        sector = ft.TextField(label="Sector", value=record.sector)

        def save_edit(_event: ft.ControlEvent) -> None:
            nonlocal records
            try:
                records = list(edit_record(records, record.instrument_id, notes=notes.value or "", sector=sector.value or ""))
                report = validate_universe(records)
                if not report.valid:
                    raise ValueError("; ".join(report.errors))
                status.value = "Validated edit pending save; no refresh or model call was started."
                dialog.open = False
            except Exception as exc:
                status.value = f"Edit rejected: {exc}"
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Edit {record.instrument_id}"),
            content=ft.Column([sector, notes], tight=True),
            actions=[ft.TextButton("Cancel", key="universe.edit-cancel", on_click=lambda _event: setattr(dialog, "open", False)), ft.Button("Validate and stage", key="universe.edit-save", on_click=save_edit)],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def save_changes(_event: ft.ControlEvent) -> None:
        report = validate_universe(records)
        if not report.valid:
            status.value = "Save blocked: " + "; ".join(report.errors)
            page.update()
            return
        try:
            snapshot = load_universe()
            result = save_universe(records, expected_revision=snapshot.revision)
            status.value = f"Saved revision {result.revision[:12]}; pending refresh remains visible and was not started."
        except Exception as exc:
            status.value = f"Save blocked: {exc}"
        page.update()

    # Build all three tabs up-front so the tier boundary remains visible even
    # when one collection is empty in a clean/offline environment.
    tabs: list[ft.Tab] = []
    for tier, title in (("primary", "Primary"), ("secondary", "Secondary"), ("sparebanken", "Sparebanken")):
        tier_rows = filter_records(records, tier=tier)
        tabs.append(ft.Tab(text=title, content=ft.Container(content=_table(tier_rows, edit_dialog), padding=8)))

    return ft.Column(
        [
            panel(ft.Column([section_header("Universe and watchlists", "Manage validated local candidates across the Primary, Secondary and Sparebanken tiers."), ft.Row([query, ft.Button("Save validated changes", key="universe.save", icon=ft.Icons.SAVE, on_click=save_changes)], wrap=True), status, ft.Text("Edits persist only after validation. Saving never starts yfinance, scoring, forecasts or broker execution.", color=theme.MUTED)], spacing=8)),
            panel(ft.Tabs(tabs=tabs, selected_index=0, expand=True)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
