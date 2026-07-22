from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Iterable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.config import load_config
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.ui_facade import (
    ClassificationOverride,
    UniverseRecord,
    add_record,
    disable_record,
    edit_record,
    load_classification_projection,
    load_identity_projection,
    load_universe,
    remove_record,
    save_universe,
    save_classification_overrides,
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
    query = ft.TextField(
        label="Search universe",
        hint_text="ID, name, ticker, ISIN, sector or theme",
        dense=True,
        width=520,
    )
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
        rebuild_table()
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

    def identity_dialog(record: UniverseRecord) -> None:
        evidence = load_identity_projection(record.instrument_id)
        resolution = str(evidence.get("identity_resolution_state", "unavailable"))
        confidence = str(evidence.get("identity_confidence", "unavailable"))
        safe_identity = (
            evidence.get("status") == "available"
            and resolution == "resolved"
            and confidence not in {"manual_review", "unavailable"}
        )
        state_line = (
            f"status={evidence.get('status', 'unavailable')} | "
            f"resolution={resolution} | "
            f"confidence={confidence} | "
            f"execution_allowed={bool(evidence.get('execution_allowed', False))}"
        )
        lineage = {
            "objects": evidence.get("identity_objects", "unavailable"),
            "conflicts": evidence.get("identity_conflicts", "unavailable"),
            "history": evidence.get("identity_history", "unavailable"),
            "reviews": evidence.get("identity_reviews", "unavailable"),
            "reason_code": evidence.get("reason_code", ""),
        }
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Identity master: {record.instrument_id}"),
            content=ft.Column(
                [
                    ft.Text(state_line, color=theme.GREEN if safe_identity else theme.AMBER),
                    ft.Text(json.dumps(lineage, sort_keys=True, indent=2, default=str), color=theme.MUTED, selectable=True),
                ],
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    key="universe.identity-close",
                    on_click=lambda _event: setattr(dialog, "open", False),
                )
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def classification_dialog(record: UniverseRecord) -> None:
        evidence = load_classification_projection(record.instrument_id, storage_root=ROOT)
        current = evidence.get("classification", {})
        current_context = current if isinstance(current, dict) else {}
        controls = {
            "instrument_type": _field(
                "Instrument type override",
                current_context.get("instrument_type", record.asset_type),
            ),
            "asset_class": _field(
                "Economic asset class override",
                current_context.get("asset_class", ""),
            ),
            "sector": _field("Sector override", current_context.get("sector", record.sector)),
            "industry": _field("Industry override", current_context.get("industry", "")),
            "strategy_label": _field(
                "Strategy label override",
                next(iter(current_context.get("strategy_labels", ())), "")
                if isinstance(current_context.get("strategy_labels", ()), (list, tuple))
                else "",
            ),
        }
        reason = _field("Override reason")

        def save_override(_event: ft.ControlEvent) -> None:
            reason_value = str(reason.value or "").strip()
            if not reason_value:
                status.value = "Classification override rejected: a review reason is required."
                page.update()
                return
            now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            selected = tuple(
                ClassificationOverride(
                    override_id=f"universe:{record.instrument_id}:{field_name}:{now}",
                    instrument_id=record.instrument_id,
                    field=field_name,
                    value=str(control.value or "").strip(),
                    reason=reason_value,
                    reviewer="local_user",
                    valid_from=now,
                    available_at=now,
                    dependent_score_keys=(f"classification:{record.instrument_id}:*",),
                )
                for field_name, control in controls.items()
                if str(control.value or "").strip()
            )
            if not selected:
                status.value = "Classification override rejected: at least one field is required."
                page.update()
                return
            result = save_classification_overrides(ROOT, selected)
            if result.get("status") != "saved":
                status.value = (
                    "Classification override rejected: "
                    + str(result.get("message") or result.get("reason_code") or "unknown error")
                )
                page.update()
                return
            refreshed = load_classification_projection(record.instrument_id, storage_root=ROOT)
            rendered.value = json.dumps(refreshed, sort_keys=True, indent=2, default=str)
            state_line.value = (
                f"status={refreshed.get('status', 'unavailable')} | "
                f"dependent_scores_invalidated={bool(result.get('dependent_scores_invalidated', False))} | "
                f"execution_allowed={bool(refreshed.get('execution_allowed', False))}"
            )
            status.value = (
                f"Saved versioned classification override for {record.instrument_id}; "
                "classification-dependent scores are invalid until recomputed."
            )
            page.update()

        state_line = ft.Text(
            (
                f"status={evidence.get('status', 'unavailable')} | "
                f"confidence={current_context.get('classification_confidence', 0.0)} | "
                f"sector_adapter_allowed={bool(current_context.get('sector_adapter_allowed', False))} | "
                f"execution_allowed={bool(evidence.get('execution_allowed', False))}"
            ),
            color=theme.GREEN if evidence.get("status") == "available" else theme.AMBER,
        )
        rendered = ft.Text(
            json.dumps(evidence, sort_keys=True, indent=2, default=str),
            color=theme.MUTED,
            selectable=True,
        )
        dialog: ft.AlertDialog

        def close_classification(_event: ft.ControlEvent) -> None:
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Classification context: {record.instrument_id}"),
            content=ft.Column(
                [state_line, rendered, *controls.values(), reason],
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    key="universe.classification-close",
                    on_click=close_classification,
                ),
                ft.Button(
                    "Save versioned override",
                    key="universe.classification-save",
                    on_click=save_override,
                ),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
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
                ft.Button("Identity", key=f"universe.identity.{record.instrument_id}", on_click=lambda _event, item=record: identity_dialog(item)),
                ft.Button("Classification", key=f"universe.classification.{record.instrument_id}", on_click=lambda _event, item=record: classification_dialog(item)),
                ft.Button("Edit", key=f"universe.edit.{record.instrument_id}", on_click=lambda _event, item=record: edit_dialog(item)),
                action_button,
                ft.Button("Remove", key=f"universe.remove.{record.instrument_id}", on_click=lambda _event, item=record: remove_item(item)),
            ], wrap=True))
        return table

    tiers = (("primary", "Primary"), ("secondary", "Secondary"), ("sparebanken", "Sparebanken"))
    tier_filter = ft.Dropdown(
        key="universe.tier",
        label="Tier",
        value="primary",
        options=[ft.DropdownOption(key=tier, text=title) for tier, title in tiers],
        width=220,
        dense=True,
    )
    table_host = ft.Column([], key="universe.table-host", spacing=0)

    def rebuild_table(_event: ft.ControlEvent | None = None) -> None:
        needle = query.value or ""
        selected_tier = str(tier_filter.value or "primary")
        table_host.controls = [
            ft.Row(
                [_table_with_actions(filter_records(records, needle, tier=selected_tier))],
                key="universe.table-scroll",
                scroll=ft.ScrollMode.AUTO,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        ]
        page.update()

    query.on_change = rebuild_table
    tier_filter.on_select = rebuild_table
    add_button = ft.Button("Add record", key="universe.add", icon=ft.Icons.ADD, on_click=add_dialog)
    rebuild_table()

    return ft.Column(
        [
            panel(ft.Column([section_header("Universe and watchlists", "Manage validated local candidates across the Primary, Secondary and Sparebanken tiers."), ft.Row([query, add_button, ft.Button("Save validated changes", key="universe.save", icon=ft.Icons.SAVE, on_click=save_changes)], wrap=True), allow_duplicates, status, ft.Text("Edits persist only after validation. Saving never starts yfinance, scoring, forecasts or broker execution.", color=theme.MUTED)], spacing=8)),
            panel(ft.Column([tier_filter, table_host], spacing=12)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
