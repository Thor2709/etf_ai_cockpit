from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Iterable

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.pages.onboarding import overlay_universe_config
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
    build_universe_manifest,
    create_import_resume_state,
    dry_run_universe_import,
    resume_universe_import,
    save_universe_manifest,
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


UNIVERSE_TABLE_PAGE_SIZE = 50
_UNIVERSE_SORT_FIELDS = {
    "ID": "instrument_id",
    "Name": "name",
    "Yahoo ticker": "ticker",
    "Type": "asset_type",
    "ISIN status": "isin_status",
    "Status": "enabled",
    "Policy evidence": "policy_state",
}


def _sort_universe_records(records: Iterable[UniverseRecord], column: str, ascending: bool) -> tuple[UniverseRecord, ...]:
    """Sort only display records, retaining missing values at the end."""

    field = _UNIVERSE_SORT_FIELDS.get(column)
    values = list(records)
    if field is None:
        return tuple(values)

    def value_for(record: UniverseRecord) -> object:
        if field == "enabled":
            return "ready" if record.enabled else "disabled"
        if field == "policy_state":
            return getattr(record, "policy_state", "unavailable")
        return getattr(record, field, None)

    present: list[UniverseRecord] = []
    missing: list[UniverseRecord] = []
    for record in values:
        value = value_for(record)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(record)
        else:
            present.append(record)
    present.sort(key=lambda record: str(value_for(record)).casefold(), reverse=not ascending)
    return tuple((*present, *missing))


def _table(
    records: Iterable[UniverseRecord],
    on_edit,
    policy_states: dict[str, tuple[str, str]] | None = None,
) -> ft.DataTable:
    policy_states = policy_states or {}
    all_records = tuple(records)

    def build_rows(view: Iterable[UniverseRecord]) -> list[ft.DataRow]:
        rows: list[ft.DataRow] = []
        for record in view:
            status = "disabled" if not record.enabled else "needs_verification" if record.isin_status != "verified" else "ready"
            policy_state, policy_reason = policy_states.get(
                record.instrument_id,
                ("unavailable", "No versioned policy evidence is available."),
            )
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(record.instrument_id, color=theme.TEXT)),
                        ft.DataCell(ft.Text(record.name, color=theme.TEXT)),
                        ft.DataCell(ft.Text(record.ticker, color=theme.MUTED)),
                        ft.DataCell(ft.Text(record.asset_type, color=theme.MUTED)),
                        ft.DataCell(ft.Text(record.isin_status, color=theme.AMBER if record.isin_status != "verified" else theme.GREEN)),
                        ft.DataCell(ft.Text(status, color=theme.AMBER if status != "ready" else theme.GREEN)),
                        ft.DataCell(
                            ft.Text(
                                policy_state,
                                color=theme.GREEN if policy_state == "current" else theme.AMBER,
                                tooltip=policy_reason,
                            )
                        ),
                        ft.DataCell(ft.Button("Edit", key=f"universe.edit.{record.instrument_id}", on_click=lambda _event, row=record: on_edit(row))),
                    ]
                )
            )
        return rows

    visible_records = all_records[:UNIVERSE_TABLE_PAGE_SIZE]
    table_ref: ft.DataTable | None = None

    def sort_column(column: str, event: ft.ControlEvent) -> None:
        ascending = bool(getattr(event, "ascending", True))
        if table_ref is not None:
            table_ref.rows = build_rows(_sort_universe_records(all_records, column, ascending)[:UNIVERSE_TABLE_PAGE_SIZE])

    columns = (
        "ID",
        "Name",
        "Yahoo ticker",
        "Type",
        "ISIN status",
        "Status",
        "Policy evidence",
        "Actions",
    )
    table = ft.DataTable(
        key="universe.table",
        columns=[
            ft.DataColumn(
                ft.Text(label, color=theme.TEXT, tooltip=f"Sort by {label}" if label in _UNIVERSE_SORT_FIELDS else None),
                on_sort=(lambda event, name=label: sort_column(name, event)) if label in _UNIVERSE_SORT_FIELDS else None,
            )
            for label in columns
        ],
        rows=build_rows(visible_records),
        column_spacing=16,
    )
    table_ref = table
    return table


def universe_manager_page(page: ft.Page, state: AppState) -> ft.Control:
    # Capture the revision exactly once with the page snapshot. Save callbacks
    # must fail closed if another writer changes the store meanwhile.
    snapshot = load_universe()
    records = list(snapshot.records or records_from_config(state))
    policy_profiles = tuple(getattr(snapshot, "policy_profiles", ()))
    policy_states = {
        item.instrument_id: (item.state, item.reason)
        for item in getattr(snapshot, "policy_evidence", ())
    }
    expected_revision = snapshot.revision
    query = ft.TextField(
        label="Search universe",
        hint_text="ID, name, ticker, ISIN, sector or theme",
        dense=True,
        width=520,
    )
    integrity_errors = tuple(getattr(snapshot, "integrity_errors", ()))
    status = ft.Text(
        (
            "Policy evidence requires manual_review: " + "; ".join(integrity_errors)
            if integrity_errors
            else "No changes pending. needs_verification and pending refresh are shown per row."
        ),
        color=theme.AMBER if integrity_errors else theme.MUTED,
        selectable=True,
    )
    allow_duplicates = ft.Checkbox(
        label="Allow cross-tier duplicate tickers and verified ISINs (instrument IDs stay globally unique)",
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
        active_config = getattr(getattr(state, "snapshot", None), "config", None)
        if active_config is not None:
            refreshed_config = overlay_universe_config(active_config, refreshed_config)
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

        def cancel_edit(_event: ft.ControlEvent) -> None:
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Edit {record.instrument_id}"),
            content=ft.Column([*controls.values(), enabled, leveraged, inverse], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancel", key="universe.edit-cancel", on_click=cancel_edit), ft.Button("Validate and stage", key="universe.edit-save", on_click=save_edit)],
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

        def cancel_add(_event: ft.ControlEvent) -> None:
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Add universe record"),
            content=ft.Column([*controls.values(), enabled, leveraged, inverse], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancel", key="universe.add-cancel", on_click=cancel_add), ft.Button("Validate and add", key="universe.add-save", on_click=save_add)],
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
        if snapshot.integrity_errors:
            status.value = "Save blocked: " + "; ".join(snapshot.integrity_errors)
            page.update()
            return
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
                policy_profiles=(
                    tuple(
                        profile
                        for profile in policy_profiles
                        if profile.instrument_id
                        in {record.instrument_id for record in records}
                    )
                    if getattr(snapshot, "schema_version", 0) >= 3
                    else None
                ),
            )
            expected_revision = result.revision
            _apply_saved_config(result.revision)
            status.value = f"Saved revision {result.revision[:12]}; pending refresh remains visible and was not started."
        except Exception as exc:
            status.value = f"Save blocked: {exc}"
        page.update()

    def import_dialog(_event: ft.ControlEvent | None = None) -> None:
        session: dict[str, object] = {}
        source_type = ft.Dropdown(
            key="universe.import-source-type",
            label="Input",
            value="paste",
            options=[
                ft.DropdownOption(key="paste", text="Paste CSV/TSV"),
                ft.DropdownOption(key="csv", text="Local CSV path"),
                ft.DropdownOption(key="xlsx", text="Local XLSX path"),
                ft.DropdownOption(key="provider", text="Supplied provider rows"),
            ],
            width=240,
        )
        source = _field("CSV, TSV, JSON rows, or local path", multiline=True)
        provider = _field("Provider name (only labels supplied rows)")
        corrections = _field("Reviewed correction overlays (JSON by source row)", multiline=True)
        horizons = _field("Requested horizons (days, e.g. daily=252)")
        quotas = _field("Per-asset quotas (e.g. etf=25)")
        chunk_size = _field("Chunk size", "100")
        result_text = ft.Text("Dry-run has not been performed.", selectable=True, color=theme.MUTED)
        progress_text = ft.Text("Progress: 0/0 (not started)", key="universe.import-progress", selectable=True, color=theme.MUTED)

        def _options(value: str) -> dict[str, int]:
            output: dict[str, int] = {}
            for item in value.split(","):
                if not item.strip():
                    continue
                key, separator, raw = item.partition("=")
                if not separator:
                    raise ValueError("Use name=value pairs separated by commas.")
                output[key.strip()] = int(raw.strip())
            return output

        def _overlays(value: str) -> dict[int, dict[str, object]]:
            if not value.strip():
                return {}
            decoded = json.loads(value)
            if not isinstance(decoded, dict):
                raise ValueError("Correction overlays must be a JSON object keyed by source row.")
            output: dict[int, dict[str, object]] = {}
            for raw_row, overlay in decoded.items():
                if not str(raw_row).isdigit() or not isinstance(overlay, dict):
                    raise ValueError("Each correction overlay must be an object keyed by a positive source row.")
                row_number = int(raw_row)
                if row_number < 1:
                    raise ValueError("Correction overlay rows must be positive.")
                output[row_number] = overlay
            return output

        def _show_progress(state_value) -> None:
            progress_text.value = f"Progress: {state_value.next_row}/{state_value.total_rows} ({state_value.status})"
            progress_text.color = theme.GREEN if state_value.complete else theme.AMBER

        def dry_run(_dry_event: ft.ControlEvent | None = None) -> None:
            try:
                kind = str(source_type.value or "paste")
                report = dry_run_universe_import(
                    source.value or "",
                    source_kind=kind,
                    provider_name=provider.value or "",
                    correction_overlays=_overlays(corrections.value or ""),
                )
                manifest = build_universe_manifest(
                    report,
                    requested_horizons=_options(horizons.value or ""),
                    per_asset_quotas=_options(quotas.value or ""),
                )
                state_value = create_import_resume_state(report, chunk_size=int(chunk_size.value or ""))
                session.clear()
                session.update(report=report, manifest=manifest, state=state_value, processed=())
                result_text.value = (
                    f"Dry-run: {len(report.source_rows)} source rows, {len(report.records)} resolved, "
                    f"{len(report.unresolved_rows)} unresolved, {len(report.issues)} findings; "
                    f"manifest {manifest.manifest_id[:12]}. execution_allowed=False"
                )
                result_text.color = theme.AMBER if report.errors else theme.GREEN
                _show_progress(state_value)
            except Exception as exc:
                session.clear()
                result_text.value = f"Import rejected: {exc}"
                result_text.color = theme.AMBER
                progress_text.value = "Progress: 0/0 (rejected)"
                progress_text.color = theme.AMBER
            page.update()

        def resume_import(_resume_event: ft.ControlEvent | None = None) -> None:
            try:
                report = session.get("report")
                state_value = session.get("state")
                if report is None or state_value is None:
                    raise ValueError("Run dry-run validation before resuming.")
                chunk, state_value = resume_universe_import(report, state_value)
                processed = tuple(session.get("processed", ())) + chunk
                session.update(state=state_value, processed=processed)
                _show_progress(state_value)
                result_text.value = f"Validated {len(processed)} resolved rows in deterministic chunks; nothing has been staged."
                result_text.color = theme.GREEN if state_value.complete else theme.AMBER
            except Exception as exc:
                result_text.value = f"Resume blocked: {exc}"
                result_text.color = theme.AMBER
            page.update()

        def cancel_import(_cancel_event: ft.ControlEvent | None = None) -> None:
            try:
                report = session.get("report")
                state_value = session.get("state")
                if report is None or state_value is None:
                    raise ValueError("Run dry-run validation before cancelling.")
                _chunk, state_value = resume_universe_import(report, state_value, cancel=True)
                session["state"] = state_value
                _show_progress(state_value)
                result_text.value = "Import cancelled; no rows were staged and resume is disabled until a new dry-run."
                result_text.color = theme.AMBER
            except Exception as exc:
                result_text.value = f"Cancel blocked: {exc}"
                result_text.color = theme.AMBER
            page.update()

        def stage_import(_stage_event: ft.ControlEvent | None = None) -> None:
            try:
                report = session.get("report")
                manifest = session.get("manifest")
                state_value = session.get("state")
                processed = tuple(session.get("processed", ()))
                if report is None or manifest is None or state_value is None:
                    raise ValueError("Run dry-run validation before staging.")
                if not state_value.complete or len(processed) != state_value.total_rows:
                    raise ValueError("Complete all import chunks before staging.")
                blocking = tuple(
                    issue for issue in report.errors if issue.code != "unresolved_identity"
                )
                if blocking:
                    raise ValueError("Import has invalid rows; review findings before staging.")
                if not report.records:
                    raise ValueError("Import has no resolved rows to stage.")
                nonlocal records
                staged = tuple(records)
                for item in processed:
                    if not any(existing.instrument_id.casefold() == item.instrument_id.casefold() for existing in staged):
                        staged = add_record(
                            staged,
                            item,
                            allow_cross_tier_duplicates=bool(allow_duplicates.value),
                        )
                save_universe_manifest(manifest)
                _stage(f"Staged {len(processed)} imported rows and saved manifest {manifest.manifest_id[:12]}.", staged)
                dialog.open = False
            except Exception as exc:
                result_text.value = f"Stage blocked: {exc}"
                result_text.color = theme.AMBER
                page.update()

        def close_import(_close_event: ft.ControlEvent | None = None) -> None:
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Import watchlist / universe"),
            content=ft.Column([source_type, source, provider, corrections, horizons, quotas, chunk_size, result_text, progress_text], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Close", key="universe.import-close", on_click=close_import),
                ft.Button("Dry-run validate", key="universe.import-dry-run", on_click=dry_run),
                ft.Button("Resume next chunk", key="universe.import-resume", on_click=resume_import),
                ft.Button("Cancel import", key="universe.import-cancel", on_click=cancel_import),
                ft.Button("Stage import", key="universe.import-stage", on_click=stage_import),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
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

        def close_identity(_event: ft.ControlEvent) -> None:
            dialog.open = False
            page.update()

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
                    on_click=close_identity,
                )
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def classification_dialog(record: UniverseRecord) -> None:
        evidence = load_classification_projection(record.instrument_id)
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
        initial_values = {
            field_name: str(control.value or "").strip()
            for field_name, control in controls.items()
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
                and str(control.value or "").strip() != initial_values[field_name]
            )
            if not selected:
                status.value = "Classification override rejected: change at least one non-empty field."
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
            invalidate = getattr(state, "invalidate_classification_scores", None)
            if callable(invalidate):
                invalidate(record.instrument_id, root=ROOT)
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
        visible_rows = tuple(rows)
        table = _table(visible_rows, edit_dialog, policy_states)
        for row, record in zip(table.rows, visible_rows):
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
    table_page = 0
    table_status = ft.Text("", key="universe.table-status", selectable=True, color=theme.MUTED)
    previous_page = ft.TextButton(
        "Previous",
        key="universe.previous",
        tooltip="Show the previous universe page",
        disabled=True,
    )
    next_page = ft.TextButton(
        "Next",
        key="universe.next",
        tooltip="Show the next universe page",
        disabled=True,
    )
    page_indicator = ft.Text("Page 1 of 1", key="universe.page", selectable=True)

    def rebuild_table(_event: ft.ControlEvent | None = None, *, reset_page: bool = True) -> None:
        nonlocal table_page
        needle = query.value or ""
        selected_tier = str(tier_filter.value or "primary")
        filtered = filter_records(records, needle, tier=selected_tier)
        page_count = max(1, (len(filtered) + UNIVERSE_TABLE_PAGE_SIZE - 1) // UNIVERSE_TABLE_PAGE_SIZE)
        if reset_page:
            table_page = 0
        table_page = min(max(table_page, 0), page_count - 1)
        start = table_page * UNIVERSE_TABLE_PAGE_SIZE
        visible = filtered[start : start + UNIVERSE_TABLE_PAGE_SIZE]
        table_status.value = f"Showing {start + 1}-{start + len(visible)} of {len(filtered)} universe records" if filtered else "Showing 0 of 0 universe records"
        page_indicator.value = f"Page {table_page + 1} of {page_count}"
        previous_page.disabled = table_page == 0
        next_page.disabled = table_page >= page_count - 1
        table_host.controls = [
            ft.Row(
                [_table_with_actions(visible)],
                key="universe.table-scroll",
                scroll=ft.ScrollMode.AUTO,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            ft.Row(
                [previous_page, page_indicator, next_page, table_status],
                spacing=theme.SPACE_2,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ]
        page.update()

    def previous_page_click(_event: ft.ControlEvent) -> None:
        nonlocal table_page
        table_page -= 1
        rebuild_table(reset_page=False)

    def next_page_click(_event: ft.ControlEvent) -> None:
        nonlocal table_page
        table_page += 1
        rebuild_table(reset_page=False)

    previous_page.on_click = previous_page_click
    next_page.on_click = next_page_click
    query.on_change = lambda event: rebuild_table(event, reset_page=True)
    tier_filter.on_select = lambda event: rebuild_table(event, reset_page=True)
    add_button = ft.Button("Add record", key="universe.add", icon=ft.Icons.ADD, on_click=add_dialog)
    import_button = ft.Button("Import", key="universe.import", icon=ft.Icons.UPLOAD_FILE, on_click=import_dialog)
    rebuild_table()

    return ft.Column(
        [
            panel(ft.Column([section_header("Universe and watchlists", "Manage validated local candidates across the Primary, Secondary and Sparebanken tiers."), ft.Row([query, add_button, import_button, ft.Button("Save validated changes", key="universe.save", icon=ft.Icons.SAVE, on_click=save_changes)], wrap=True), allow_duplicates, status, ft.Text("Imports are local dry-runs; saving never starts providers, analysis, scoring, forecasts or broker execution.", color=theme.MUTED)], spacing=8)),
            panel(ft.Column([tier_filter, table_host], spacing=12)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
