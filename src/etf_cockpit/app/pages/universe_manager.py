"""Universe page (FINAL_UI_SPEC 6.2): instrument table, local import, composition and enabled-by-tier charts.

Every edit stays a validated, pending change until "Save validated changes"; nothing here starts providers,
analysis, scoring, forecasts or broker execution (``execution_allowed=false``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
import json

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    CardMenu,
    DataTable,
    Disclosure,
    Field,
    GlassCard,
    Note,
    TableColumn,
    Tag,
    Toggle,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count
from etf_cockpit.app.pages import _p2_common as dialogs
from etf_cockpit.app.pages import _p4_common as common
from etf_cockpit.app.pages._p4_common import workflow_button as _workflow_button
from etf_cockpit.app.state import AppState
from etf_cockpit.application.onboarding_profile import overlay_universe_config
from etf_cockpit.application.settings import load_config
from etf_cockpit.application.ui_views import universe as view
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.ui_facade import (
    ClassificationOverride,
    UniverseRecord,
    add_record,
    build_universe_manifest,
    create_import_resume_state,
    disable_record,
    dry_run_universe_import,
    edit_record,
    load_classification_projection,
    load_identity_projection,
    load_universe,
    remove_record,
    resume_universe_import,
    save_classification_overrides,
    save_universe,
    save_universe_manifest,
    validate_universe,
)

_RECORD_FIELDS = (
    ("instrument_id", "ID"),
    ("name", "Name"),
    ("isin", "ISIN"),
    ("isin_status", "ISIN status"),
    ("ticker", "Yahoo ticker"),
    ("asset_type", "Asset type"),
    ("tier", "Tier"),
    ("group", "Group"),
    ("data_policy", "Data policy / frequency"),
    ("currency", "Currency"),
    ("region", "Region"),
    ("sector", "Sector"),
    ("theme", "Theme"),
    ("notes", "Notes"),
)
_TIER_OPTIONS = (("all", "All tiers"), ("primary", "Primary"), ("secondary", "Secondary"), ("sparebanken", "Sparebanken"))
_SAFETY = "Imports are local dry-runs; saving never starts providers, analysis, scoring, forecasts or broker execution."
_TABLE_ROW = 54
_SORTS = {
    "name": lambda r: r.name.casefold(),
    "ticker": lambda r: r.ticker.casefold(),
    "isin": lambda r: r.isin.casefold(),
    "type": lambda r: r.asset_type.casefold(),
    "tier": lambda r: view.TIERS.index(r.tier.casefold()) if r.tier.casefold() in view.TIERS else len(view.TIERS),
    "enabled": lambda r: not r.enabled,
}
_SLICE_COLOURS = {
    "Equity ETFs": ck.palette.P,
    "Bond ETFs": ck.palette.POS,
    "Stocks": ck.palette.SECOND,
    "Commodity": ck.palette.VIO,
    "Leveraged / inverse": ck.palette.NEG,
    "Funds": ck.palette.CATEGORICAL[2],
    "Bonds": ck.palette.CATEGORICAL[3],
    "Other": ck.palette.OTHER,
}
_LILAC = (ck.palette.mix(ck.palette.CATEGORICAL[2], ck.palette.INK, 0.35), ck.palette.mix(ck.palette.CATEGORICAL[2], ck.palette.INK3, 0.4))


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


def filter_records(records: Iterable[UniverseRecord], query: str = "", tier: str | None = None, kind: str = "All") -> tuple[UniverseRecord, ...]:
    return tuple(record for record in records if view.matches(record, query=query, tier=tier, kind=kind))


def _config_facts(state: AppState) -> tuple[dict[str, str], dict[str, bool | None]]:
    """Asset class and accumulating flag per configured instrument (display only)."""
    etfs = getattr(getattr(getattr(getattr(state, "snapshot", None), "config", None), "universe", None), "etfs", ()) or ()
    return {str(etf.id): str(etf.asset_class) for etf in etfs}, {str(etf.id): etf.accumulating for etf in etfs}


def _field_group(controls: dict[str, tuple[ft.Control, ft.TextField]]) -> list[ft.Control]:
    return [pair[0] for pair in controls.values()]


def universe_manager_page(page: ft.Page, state: AppState) -> PageView:
    # Capture the revision exactly once with the page snapshot. Save callbacks
    # must fail closed if another writer changes the store meanwhile.
    snapshot = load_universe()
    records = list(snapshot.records or records_from_config(state))
    baseline = {"records": tuple(records)}
    policy_profiles = tuple(getattr(snapshot, "policy_profiles", ()))
    policy_states = {item.instrument_id: (item.state, item.reason) for item in getattr(snapshot, "policy_evidence", ())}
    expected_revision = snapshot.revision
    asset_classes, accumulating = _config_facts(state)
    layout = common.make_layout(page)
    integrity_errors = tuple(getattr(snapshot, "integrity_errors", ()))
    ui: dict[str, object] = {
        "query": "",
        "tier": "all",
        "segment_tier": "All",
        "kind": "All",
        "sort": None,
        "descending": False,
        "message": ("Policy evidence requires manual_review: " + "; ".join(integrity_errors)) if integrity_errors else "",
    }

    query = common.text_input(key="universe.search", hint="ID, name, ticker, ISIN, sector or theme")
    tier_filter = common.dropdown(key="universe.tier", options=_TIER_OPTIONS, value="all")
    allow_duplicates = Toggle(bool(snapshot.allow_cross_tier_duplicates), key="universe.allow-cross-tier-duplicates")
    status = common.text("", 13, 500, theme.INK2, trunc=True, expand=True, key="universe.status")
    strip = Well(None, padding=ft.Padding(left=16, top=0, right=16, bottom=0), height=44)
    table_host = ft.Container(key="universe.table-host", expand=True)
    charts: dict[str, ft.Container] = {"composition": ft.Container(), "tier": ft.Container()}

    def duplicates() -> bool:
        return dialogs.toggle_on(allow_duplicates)

    def pending_count() -> int:
        before = {item.instrument_id: item for item in baseline["records"]}
        now = {item.instrument_id: item for item in records}
        return sum(1 for key, item in now.items() if before.get(key) != item) + sum(1 for key in before if key not in now)

    def sync_strip() -> None:
        pending = pending_count()
        message = str(ui["message"] or "")
        if pending:
            summary = f"{pending} pending changes · needs_verification and pending refresh are shown per row"
            status.value = f"{message} · {summary}" if message else summary
        else:
            status.value = message
        status.tooltip = status.value
        strip.visible = bool(pending or message)

    def say(message: str) -> None:
        ui["message"] = message
        sync_strip()
        page.update()

    def visible_records() -> list[UniverseRecord]:
        tier_value = str(tier_filter.value or "all")
        segment = str(ui["segment_tier"]).casefold()
        rows = [
            record
            for record in filter_records(records, str(query.value or ""), None if tier_value == "all" else tier_value, str(ui["kind"]))
            if segment == "all" or record.tier.casefold() == segment
        ]
        if ui["sort"] in _SORTS:
            rows.sort(key=_SORTS[str(ui["sort"])], reverse=bool(ui["descending"]))
        return rows

    def _stage(message: str, changed: tuple[UniverseRecord, ...]) -> None:
        nonlocal records
        records = list(changed)
        ui["message"] = message + " Pending refresh remains visible; no yfinance, scoring, forecast or broker call was started."
        rebuild_all()

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

    # ----- record dialogs ------------------------------------------------------------------------------------
    def record_form(title: str, record: UniverseRecord | None, on_save: Callable[[dict[str, object]], None]) -> tuple[list[ft.Control], Callable[[object], None], Callable[[ft.AlertDialog], None]]:
        """Form controls, the validating save handler and a setter that tells it which dialog to close."""
        fields = {
            name: dialogs.input_field(name, label, getattr(record, name, "") if record else _ADD_DEFAULTS.get(name, ""), multiline=name == "notes")
            for name, label in _RECORD_FIELDS
        }
        enabled_row, enabled = dialogs.switch_row("Enabled for normal workflows", record.enabled if record else True, key="universe.field.enabled")
        leveraged_row, leveraged = dialogs.switch_row("Leveraged (manual review)", record.leveraged if record else False, key="universe.field.leveraged")
        inverse_row, inverse = dialogs.switch_row("Inverse (manual review)", record.inverse if record else False, key="universe.field.inverse")
        holder: dict[str, ft.AlertDialog] = {}

        def submit(_event: object) -> None:
            values: dict[str, object] = {name: control[1].value or "" for name, control in fields.items()}
            values.update(enabled=dialogs.toggle_on(enabled), leveraged=dialogs.toggle_on(leveraged), inverse=dialogs.toggle_on(inverse))
            try:
                on_save(values)
                dialogs.close_dialog(page, holder["dialog"])
            except Exception as exc:
                ui["message"] = f"{title.split(' ')[0]} rejected: {exc}"
                sync_strip()
                page.update()

        return [*_field_group(fields), enabled_row, leveraged_row, inverse_row], submit, lambda dialog: holder.update(dialog=dialog)

    def edit_dialog(record: UniverseRecord) -> None:
        def stage_edit(changes: dict[str, object]) -> None:
            _stage("Validated edit pending save.", edit_record(records, record.instrument_id, allow_cross_tier_duplicates=duplicates(), **changes))

        title = f"Edit {record.instrument_id}"
        body, save_edit, attach = record_form(title, record, stage_edit)

        def cancel_edit(_event: object) -> None:
            dialogs.close_dialog(page, dialog)

        dialog = dialogs.glass_dialog(
            page,
            title,
            body,
            [
                _workflow_button("Cancel", key_name="universe.edit-cancel", on_click=cancel_edit),
                _workflow_button("Validate and stage", key_name="universe.edit-save", on_click=save_edit, primary=True),
            ],
        )
        attach(dialog)
        dialogs.show_dialog(page, dialog)

    def add_dialog(_event: object | None = None) -> None:
        def stage_add(values: dict[str, object]) -> None:
            _stage("Validated add pending save.", add_record(records, UniverseRecord(**values), allow_cross_tier_duplicates=duplicates()))

        body, save_add, attach = record_form("Add universe record", None, stage_add)

        def cancel_add(_event: object) -> None:
            dialogs.close_dialog(page, dialog)

        dialog = dialogs.glass_dialog(
            page,
            "Add universe record",
            body,
            [
                _workflow_button("Cancel", key_name="universe.add-cancel", on_click=cancel_add),
                _workflow_button("Validate and add", key_name="universe.add-save", on_click=save_add, primary=True),
            ],
        )
        attach(dialog)
        dialogs.show_dialog(page, dialog)

    def disable_item(record: UniverseRecord) -> None:
        try:
            _stage(f"Disabled {record.instrument_id}.", disable_record(records, record.instrument_id, allow_cross_tier_duplicates=duplicates()))
        except Exception as exc:
            ui["message"] = f"Disable rejected: {exc}"
            rebuild_table()

    def enable_item(record: UniverseRecord) -> None:
        try:
            _stage(f"Enabled {record.instrument_id}.", edit_record(records, record.instrument_id, enabled=True, allow_cross_tier_duplicates=duplicates()))
        except Exception as exc:
            ui["message"] = f"Enable rejected: {exc}"
            rebuild_table()

    def set_enabled(record: UniverseRecord, on: bool) -> None:
        enable_item(record) if on else disable_item(record)

    def remove_item(record: UniverseRecord) -> None:
        try:
            _stage(f"Removed {record.instrument_id}.", remove_record(records, record.instrument_id))
        except Exception as exc:
            ui["message"] = f"Remove rejected: {exc}"
            rebuild_table()

    def save_changes(_event: object = None) -> None:
        nonlocal expected_revision
        if snapshot.integrity_errors:
            say("Save blocked: " + "; ".join(snapshot.integrity_errors))
            return
        report = validate_universe(records, allow_cross_tier_duplicates=duplicates())
        if not report.valid:
            say("Save blocked: " + "; ".join(report.errors))
            return
        try:
            result = save_universe(
                records,
                expected_revision=expected_revision,
                allow_cross_tier_duplicates=duplicates(),
                policy_profiles=(
                    tuple(profile for profile in policy_profiles if profile.instrument_id in {record.instrument_id for record in records})
                    if getattr(snapshot, "schema_version", 0) >= 3
                    else None
                ),
            )
            expected_revision = result.revision
            baseline["records"] = tuple(records)
            _apply_saved_config(result.revision)
            say(f"Saved revision {result.revision[:12]}; pending refresh remains visible and was not started.")
        except Exception as exc:
            say(f"Save blocked: {exc}")

    def discard_changes(_event: object = None) -> None:
        nonlocal records
        records = list(baseline["records"])
        ui["message"] = "Pending changes discarded."
        rebuild_all()

    # ----- import --------------------------------------------------------------------------------------------
    csv_path = common.text_input(key="universe.import-csv", hint="C:\\imports\\universe.csv")
    xlsx_path = common.text_input(key="universe.import-xlsx", hint="C:\\imports\\universe.xlsx")
    paste = common.text_input(key="universe.import-paste", hint="ticker, isin, tier…", multiline=True)
    provider = common.text_input(key="universe.import-provider", hint="Provider name (only labels supplied rows)")
    corrections = common.text_input(key="universe.import-overlays", hint='{"1": {"canonical_id": "ID"}}', multiline=True, mono=True)
    horizons = common.text_input(key="universe.import-horizons", hint="daily=252")
    quotas = common.text_input(key="universe.import-quotas", hint="etf=25")
    chunk_size = common.text_input(key="universe.import-chunk", value="100")
    result_text = common.text("Dry-run has not been performed.", 12.5, 400, theme.INK2, max_lines=3, key="universe.import-result")
    progress_text = common.text("Progress: 0/0 (not started)", 12.5, 400, theme.INK2, key="universe.import-progress")
    session: dict[str, object] = {}
    import_dialog_ref: dict[str, ft.AlertDialog | None] = {"dialog": None}

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

    def _source() -> tuple[str, str]:
        pasted = str(paste.value or "").strip()
        if pasted:
            return ("provider" if str(provider.value or "").strip() else "paste"), str(paste.value)
        if str(csv_path.value or "").strip():
            return "csv", str(csv_path.value).strip()
        if str(xlsx_path.value or "").strip():
            return "xlsx", str(xlsx_path.value).strip()
        raise ValueError("Enter a local CSV path, a local XLSX path or pasted rows first.")

    def _show_progress(state_value) -> None:
        progress_text.value = f"Progress: {state_value.next_row}/{state_value.total_rows} ({state_value.status})"
        progress_text.color = theme.POS if state_value.complete else theme.AMBER

    def dry_run(_event: object | None = None) -> bool:
        try:
            kind, source = _source()
            report = dry_run_universe_import(source, source_kind=kind, provider_name=str(provider.value or ""), correction_overlays=_overlays(str(corrections.value or "")))
            manifest = build_universe_manifest(report, requested_horizons=_options(str(horizons.value or "")), per_asset_quotas=_options(str(quotas.value or "")))
            state_value = create_import_resume_state(report, chunk_size=int(chunk_size.value or ""))
            session.clear()
            session.update(report=report, manifest=manifest, state=state_value, processed=())
            result_text.value = (
                f"Dry-run: {len(report.source_rows)} source rows, {len(report.records)} resolved, "
                f"{len(report.unresolved_rows)} unresolved, {len(report.issues)} findings; "
                f"manifest {manifest.manifest_id[:12]}. execution_allowed=False"
            )
            _show_progress(state_value)
            return True
        except Exception as exc:
            session.clear()
            result_text.value = f"Import rejected: {exc}"
            progress_text.value = "Progress: 0/0 (rejected)"
            progress_text.color = theme.AMBER
            return False

    def validate_only(_event: object | None = None) -> None:
        dry_run()
        say(str(result_text.value))

    def resume_import(_event: object | None = None) -> None:
        try:
            report, state_value = session.get("report"), session.get("state")
            if report is None or state_value is None:
                raise ValueError("Run dry-run validation before resuming.")
            chunk, state_value = resume_universe_import(report, state_value)
            processed = tuple(session.get("processed", ())) + chunk
            session.update(state=state_value, processed=processed)
            _show_progress(state_value)
            result_text.value = f"Validated {len(processed)} resolved rows in deterministic chunks; nothing has been staged."
        except Exception as exc:
            result_text.value = f"Resume blocked: {exc}"
        page.update()

    def cancel_import(_event: object | None = None) -> None:
        try:
            report, state_value = session.get("report"), session.get("state")
            if report is None or state_value is None:
                raise ValueError("Run dry-run validation before cancelling.")
            _chunk, state_value = resume_universe_import(report, state_value, cancel=True)
            session["state"] = state_value
            _show_progress(state_value)
            result_text.value = "Import cancelled; no rows were staged and resume is disabled until a new dry-run."
        except Exception as exc:
            result_text.value = f"Cancel blocked: {exc}"
        page.update()

    def close_import(_event: object | None = None) -> None:
        if import_dialog_ref["dialog"] is not None:
            dialogs.close_dialog(page, import_dialog_ref["dialog"])

    def stage_import(_event: object | None = None) -> None:
        nonlocal records
        try:
            report, manifest, state_value = session.get("report"), session.get("manifest"), session.get("state")
            processed = tuple(session.get("processed", ()))
            if report is None or manifest is None or state_value is None:
                raise ValueError("Run dry-run validation before staging.")
            if not state_value.complete or len(processed) != state_value.total_rows:
                raise ValueError("Complete all import chunks before staging.")
            if tuple(issue for issue in report.errors if issue.code != "unresolved_identity"):
                raise ValueError("Import has invalid rows; review findings before staging.")
            if not report.records:
                raise ValueError("Import has no resolved rows to stage.")
            staged = tuple(records)
            for item in processed:
                if not any(existing.instrument_id.casefold() == item.instrument_id.casefold() for existing in staged):
                    staged = add_record(staged, item, allow_cross_tier_duplicates=duplicates())
            save_universe_manifest(manifest)
            close_import()
            _stage(f"Staged {len(processed)} imported rows and saved manifest {manifest.manifest_id[:12]}.", staged)
        except Exception as exc:
            result_text.value = f"Stage blocked: {exc}"
            page.update()

    def preview_import(_event: object | None = None) -> None:
        ok = dry_run()
        if not ok:
            say(str(result_text.value))
            return
        rows = [
            {"name": (row.name, row.detail), "tag": Tag(row.tag, row.kind, dense=True)}
            for row in view.preview_rows(session["report"], (record.instrument_id for record in records))
        ]
        table = DataTable(
            [TableColumn("name", "Row", flex=4, sortable=False), TableColumn("tag", "Change", width=112, sortable=False)],
            rows,
            row_height=48,
            max_visible_rows=6,
            empty_title="No rows",
            empty_reason="The dry-run produced no resolved or rejected rows.",
        )
        dialog = dialogs.glass_dialog(
            page,
            "Import preview",
            [result_text, progress_text, table, Note(_SAFETY)],
            [
                _workflow_button("Cancel", key_name="universe.import-close", on_click=close_import),
                _workflow_button("Resume next chunk", key_name="universe.import-resume", on_click=resume_import),
                _workflow_button("Cancel import", key_name="universe.import-cancel", on_click=cancel_import),
                _workflow_button("Apply to pending changes", key_name="universe.import-stage", on_click=stage_import, primary=True),
            ],
        )
        import_dialog_ref["dialog"] = dialog
        dialogs.show_dialog(page, dialog)

    # ----- identity and classification dialogs ---------------------------------------------------------------
    def identity_dialog(record: UniverseRecord) -> None:
        evidence = load_identity_projection(record.instrument_id)
        resolution = str(evidence.get("identity_resolution_state", "unavailable"))
        confidence = str(evidence.get("identity_confidence", "unavailable"))
        safe_identity = evidence.get("status") == "available" and resolution == "resolved" and confidence not in {"manual_review", "unavailable"}
        state_line = (
            f"status={evidence.get('status', 'unavailable')} | resolution={resolution} | confidence={confidence} | "
            f"execution_allowed={bool(evidence.get('execution_allowed', False))}"
        )
        lineage = {
            "objects": evidence.get("identity_objects", "unavailable"),
            "conflicts": evidence.get("identity_conflicts", "unavailable"),
            "history": evidence.get("identity_history", "unavailable"),
            "reviews": evidence.get("identity_reviews", "unavailable"),
            "reason_code": evidence.get("reason_code", ""),
        }
        def close_identity(_event: object) -> None:
            dialogs.close_dialog(page, dialog)

        dialog = dialogs.glass_dialog(
            page,
            f"Identity master: {record.instrument_id}",
            [
                common.text(state_line, 13, 500, theme.POS if safe_identity else theme.AMBER, trunc=False),
                Disclosure("lineage", json.dumps(lineage, sort_keys=True, indent=2, default=str), expanded=True),
            ],
            [_workflow_button("Close", key_name="universe.identity-close", on_click=close_identity)],
        )
        dialogs.show_dialog(page, dialog)

    def classification_dialog(record: UniverseRecord) -> None:
        evidence = load_classification_projection(record.instrument_id)
        current = evidence.get("classification", {})
        context = current if isinstance(current, dict) else {}
        labels = context.get("strategy_labels", ())
        fields = {
            "instrument_type": dialogs.input_field("instrument_type", "Instrument type override", context.get("instrument_type", record.asset_type), prefix="universe.override"),
            "asset_class": dialogs.input_field("asset_class", "Economic asset class override", context.get("asset_class", ""), prefix="universe.override"),
            "sector": dialogs.input_field("sector", "Sector override", context.get("sector", record.sector), prefix="universe.override"),
            "industry": dialogs.input_field("industry", "Industry override", context.get("industry", ""), prefix="universe.override"),
            "strategy_label": dialogs.input_field("strategy_label", "Strategy label override", next(iter(labels), "") if isinstance(labels, (list, tuple)) else "", prefix="universe.override"),
        }
        initial_values = {name: str(pair[1].value or "").strip() for name, pair in fields.items()}
        reason_field = dialogs.input_field("reason", "Override reason", prefix="universe.override")
        state_line = common.text(
            f"status={evidence.get('status', 'unavailable')} | confidence={context.get('classification_confidence', 0.0)} | "
            f"sector_adapter_allowed={bool(context.get('sector_adapter_allowed', False))} | execution_allowed={bool(evidence.get('execution_allowed', False))}",
            13, 500, theme.POS if evidence.get("status") == "available" else theme.AMBER, trunc=False,
        )
        rendered = Disclosure("classification evidence", json.dumps(evidence, sort_keys=True, indent=2, default=str), expanded=True)
        rendered_text = rendered.controls[1].content

        def save_override(_event: object) -> None:
            reason_value = str(reason_field[1].value or "").strip()
            if not reason_value:
                say("Classification override rejected: a review reason is required.")
                return
            now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            selected = tuple(
                ClassificationOverride(
                    override_id=f"universe:{record.instrument_id}:{name}:{now}",
                    instrument_id=record.instrument_id,
                    field=name,
                    value=str(pair[1].value or "").strip(),
                    reason=reason_value,
                    reviewer="local_user",
                    valid_from=now,
                    available_at=now,
                    dependent_score_keys=(f"classification:{record.instrument_id}:*",),
                )
                for name, pair in fields.items()
                if str(pair[1].value or "").strip() and str(pair[1].value or "").strip() != initial_values[name]
            )
            if not selected:
                say("Classification override rejected: change at least one non-empty field.")
                return
            result = save_classification_overrides(ROOT, selected)
            if result.get("status") != "saved":
                say("Classification override rejected: " + str(result.get("message") or result.get("reason_code") or "unknown error"))
                return
            invalidate = getattr(state, "invalidate_classification_scores", None)
            if callable(invalidate):
                invalidate(record.instrument_id, root=ROOT)
            refreshed = load_classification_projection(record.instrument_id, storage_root=ROOT)
            rendered_text.value = json.dumps(refreshed, sort_keys=True, indent=2, default=str)
            state_line.value = (
                f"status={refreshed.get('status', 'unavailable')} | dependent_scores_invalidated={bool(result.get('dependent_scores_invalidated', False))} | "
                f"execution_allowed={bool(refreshed.get('execution_allowed', False))}"
            )
            say(f"Saved versioned classification override for {record.instrument_id}; classification-dependent scores are invalid until recomputed.")

        def close_classification(_event: object) -> None:
            dialogs.close_dialog(page, dialog)

        dialog = dialogs.glass_dialog(
            page,
            f"Classification context: {record.instrument_id}",
            [state_line, rendered, *_field_group(fields), reason_field[0]],
            [
                _workflow_button("Close", key_name="universe.classification-close", on_click=close_classification),
                _workflow_button("Save versioned override", key_name="universe.classification-save", on_click=save_override, primary=True),
            ],
        )
        dialogs.show_dialog(page, dialog)

    # ----- table ---------------------------------------------------------------------------------------------
    def menu_label(text: str) -> ft.Control:
        return ft.Container(content=common.text(text, 13.5, 500, theme.INK, trunc=True), height=36, alignment=ft.Alignment(-1, 0))

    def row_menu(record: UniverseRecord) -> ft.Control:
        menu = CardMenu([])
        identity = ft.PopupMenuItem(content=menu_label("Identity…"), height=36, key=f"universe.identity.{record.instrument_id}")
        identity.on_click = lambda _event, item=record: identity_dialog(item)
        classification = ft.PopupMenuItem(content=menu_label("Classification…"), height=36, key=f"universe.classification.{record.instrument_id}")
        classification.on_click = lambda _event, item=record: classification_dialog(item)
        edit = ft.PopupMenuItem(content=menu_label("Edit…"), height=36, key=f"universe.edit.{record.instrument_id}")
        edit.on_click = lambda _event, item=record: edit_dialog(item)
        remove = ft.PopupMenuItem(content=menu_label("Remove…"), height=36, key=f"universe.remove.{record.instrument_id}")
        remove.on_click = lambda _event, item=record: remove_item(item)
        menu.items = [identity, classification, edit, remove]
        return menu

    def table_row(record: UniverseRecord) -> dict[str, object]:
        policy_state, policy_reason = policy_states.get(record.instrument_id, ("unavailable", "No versioned policy evidence is available."))
        review = view.review_tag(record, policy_state, policy_reason)
        tier_text, tier_kind = view.tier_tag(record)
        if review.text is None:
            review_cell: ft.Control = common.text("—", 13.5, 400, theme.INK3, tooltip=review.tooltip)
        else:
            review_cell = Tag(review.text, review.kind, dense=True)
            review_cell.tooltip = review.tooltip
        toggle = Toggle(
            record.enabled,
            on_change=lambda on, item=record: set_enabled(item, on),
            key=f"universe.enabled.{record.instrument_id}",
        )
        return {
            "name": (record.name, view.sub_line(record, accumulating.get(record.instrument_id))),
            "ticker": record.ticker or None,
            "isin": record.isin or None,
            "type": view.type_label(record.asset_type),
            "tier": Tag(tier_text, tier_kind, dense=True),
            "review": review_cell,
            "enabled": toggle,
            "menu": row_menu(record),
        }

    def on_sort(key: str, descending: bool) -> None:
        ui["sort"], ui["descending"] = key, descending
        rebuild_table()

    def build_table() -> ft.Control:
        rows = [table_row(record) for record in visible_records()]
        columns = [
            TableColumn("name", "Instrument", flex=5),
            TableColumn("ticker", "Ticker", flex=2),
            TableColumn("isin", "ISIN", flex=3),
            TableColumn("type", "Type", flex=2),
            TableColumn("tier", "Tier", flex=3),
            TableColumn("review", "Review", flex=3, sortable=False),
            TableColumn("enabled", "Enabled", width=72),
            TableColumn("menu", "", width=40, sortable=False),
        ]
        return DataTable(
            columns,
            rows,
            row_height=_TABLE_ROW,
            sort_key=str(ui["sort"]) if ui["sort"] else None,
            descending=bool(ui["descending"]),
            on_sort=on_sort,
            expand=True,
            empty_title="No instruments match",
            empty_reason="No universe record matches the search and filters. This is an explicit empty state, not zero.",
            key="universe.table",
        )

    def rebuild_table(_event: object | None = None) -> None:
        ui["query"] = str(query.value or "")
        table_host.content = build_table()
        sync_strip()
        page.update()

    # ----- charts --------------------------------------------------------------------------------------------
    def composition_card() -> ft.Control:
        slices = view.composition(records, asset_classes)
        review_count = sum(1 for record in records if view.flagged(record))
        insight = view.composition_insight(slices, review_count)
        width, height = layout.card_body(5, 1, insight=True)

        def chart(w: float, h: float) -> ft.Control:
            return ck.donut_chart(
                [ck.Slice(item.name, item.count, _SLICE_COLOURS[item.name]) for item in slices],
                width=w, height=h, insight=insight, empty_title="No instruments", unavailable_reason=None if slices else "The universe has no instruments.",
            )

        return GlassCard("Universe composition", "instruments by asset type", insight, body=Well(chart(width, height), width=width, height=height), width=layout.span_width(5), height=layout.row_heights[1])

    def tier_card() -> ft.Control:
        bars, disabled = view.enabled_by_tier(records, {key: value[0] for key, value in policy_states.items()})
        insight = view.tier_insight(bars)
        width, height = layout.card_body(7, 1, insight=True)

        def chart(w: float, h: float) -> ft.Control:
            return ck.bar_chart(
                [bar.label for bar in bars],
                [bar.count for bar in bars],
                colors=[ck.palette.GB, ck.palette.GP, _LILAC, ck.palette.GOLD],
                x_name="Tier", y_name="Instruments (count)", decimals=0, signed_labels=False, bar_width=0.36,
                margins=ck.Margins(62, 20, 20, 46), y_min=0, width=w, height=h, insight=insight, empty_title="No instruments",
                unavailable_reason=None if records else "The universe has no instruments.", series_name="Instruments",
            )

        return GlassCard("Enabled by tier", f"enabled instruments · {format_count(disabled)} more are disabled", insight, body=Well(chart(width, height), width=width, height=height), width=layout.span_width(7), height=layout.row_heights[1])

    def refresh_charts() -> None:
        charts["composition"].content = composition_card()
        charts["tier"].content = tier_card()

    def rebuild_all() -> None:
        refresh_charts()
        table_host.content = build_table()
        sync_strip()
        page.update()

    # ----- cards ---------------------------------------------------------------------------------------------
    def on_tier(_event: object | None = None) -> None:
        ui["tier"] = str(tier_filter.value or "all")
        rebuild_table()

    tier_filter.on_select = on_tier
    query.on_change = rebuild_table
    strip.content = ft.Row(
        [
            status,
            ft.Row([allow_duplicates, common.text("Allow cross-tier duplicate tickers and verified ISINs", 12.5, 500, theme.INK2, trunc=True, tooltip="Allow cross-tier duplicate tickers and verified ISINs (instrument IDs stay globally unique)")], spacing=12, tight=True),
            _workflow_button("Discard", key_name="universe.discard", on_click=discard_changes),
            _workflow_button("Save validated changes", key_name="universe.save", on_click=save_changes, primary=True),
        ],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    def instrument_card() -> ft.Control:
        width, height = layout.card_body(9, 0)
        controls = ft.Row(
            [
                Field("Search universe", control=query, expand=2),
                Field("Tier", control=tier_filter, expand=1),
                ft.Container(content=_workflow_button("Add record", key_name="universe.add", on_click=add_dialog), padding=ft.Padding(left=0, top=0, right=0, bottom=0)),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
        body = ft.Column([controls, strip, table_host], spacing=12, expand=True)
        return GlassCard("Instrument universe", "enabled instruments flow into scores, comparison and portfolio", body=ft.Container(content=body, width=width, height=height), width=layout.span_width(9), height=layout.row_heights[0])

    def add_card() -> ft.Control:
        width, height = layout.card_body(3, 0)
        options = ft.Column(
            [
                Field("Provider name", control=provider),
                Field("Reviewed correction overlays (JSON by source row)", control=corrections),
                Field("Requested horizons (days)", control=horizons),
                Field("Per-asset quotas", control=quotas),
                Field("Chunk size", control=chunk_size),
            ],
            spacing=12,
        )
        body = ft.Column(
            [
                Field("Local CSV path", control=csv_path),
                Field("Local XLSX path", control=xlsx_path),
                Field("Paste CSV/TSV", control=paste, multiline=True),
                ft.Row([_workflow_button("Preview import", key_name="universe.import", on_click=preview_import, primary=True), _workflow_button("Validate only", key_name="universe.import-validate", on_click=validate_only)], spacing=12),
                Note("Imported rows are validated and shown as a diff before anything is enabled."),
                Note(_SAFETY),
                Disclosure("import options", options),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        return GlassCard("Add instruments", "local files only · nothing is uploaded", body=ft.Container(content=body, width=width, height=height), width=layout.span_width(3), height=layout.row_heights[0])

    refresh_charts()
    table_host.content = build_table()
    sync_strip()
    grid = common.grid(
        layout,
        [[(instrument_card(), 9), (add_card(), 3)], [(charts["composition"], 5), (charts["tier"], 7)]],
    )

    def segment_tier(label: str) -> None:
        ui["segment_tier"] = label
        tier_filter.value = "all"
        rebuild_table()

    def segment_kind(label: str) -> None:
        ui["kind"] = label
        rebuild_table()

    enabled = sum(1 for record in records if record.enabled)
    groups = (
        SegmentGroup("tier", ["All", "Primary", "Secondary", "Sparebanken"], "All", segment_tier),
        SegmentGroup("type", list(view.TYPE_FILTERS), "All", segment_kind),
    )
    return common.page_view("Universe", view.subtitle(len(records), enabled), grid, groups)


_ADD_DEFAULTS = {"isin": "needs_verification", "isin_status": "needs_verification", "asset_type": "stock", "tier": "secondary", "data_policy": "daily", "currency": "EUR"}
