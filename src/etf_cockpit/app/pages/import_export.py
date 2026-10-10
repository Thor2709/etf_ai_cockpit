from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from tempfile import TemporaryDirectory
import threading

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    Field,
    GlassCard,
    KpiTile,
    Note,
    Segmented,
    TableColumn,
    Tag,
    Well,
    field_input_style,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.state import AppState
from etf_cockpit.application.portfolio_imports import PortfolioImportApplication
from etf_cockpit.core.paths import CONFIG_DIR, DATA_DIR, DERIVED_DIR, ROOT
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.application.ui_facade import (
    DecisionJournal,
    ContentAddressedCache,
    ImportPreview,
    ImportService,
    JournalIntegrityError,
    commit_restore,
    create_backup,
    export_table,
    redact_private_fields,
    validate_import,
    validate_restore,
    bulk_cache_health,
    load_simple_scoreboard,
)


def _record_export_terminal(
    state: AppState,
    *,
    label: str,
    message: str,
    destination: Path,
    ok: bool,
    error: str | None,
    action_id: str,
) -> None:
    if ok:
        state.finish_activity(
            message,
            output_path=destination,
            label=label,
            expected_action_id=action_id,
        )
        return
    state.update_activity(
        "Export unavailable",
        output_path=destination,
        expected_action_id=action_id,
    )
    state.fail_activity(
        label,
        RuntimeError(error or "export was unavailable"),
        expected_action_id=action_id,
    )


def _refresh_activity_shell(page: ft.Page, state: AppState) -> None:
    if not hasattr(page, "views"):
        page.update()
        return
    from etf_cockpit.app.router import render_shell

    render_shell(page, state, getattr(page, "route", "") or state.snapshot.config.ui.default_page)


def _table_cell(value: object) -> object:
    try:
        return None if value is None or bool(pd.isna(value)) else value
    except (TypeError, ValueError):
        return value


def import_export_page(page: ft.Page, state: AppState) -> PageView:
    picker = ft.FilePicker(key="import-export.import.file-picker")
    try:
        page.services.append(picker)
    except Exception:
        try:
            page.overlay.append(picker)
        except Exception:
            pass
    import_types = ("portfolio_history", "broker", "candidate", "manual_notes", "etf_holdings", "news", "events", "rss_list")
    import_type_labels = tuple(value.replace("_", " ").title() for value in import_types)
    import_type_values = dict(zip(import_type_labels, import_types, strict=True))
    selections = {"import_type": "portfolio_history", "portfolio_locale": "en_US", "portfolio_authority": "broker"}
    path_field = ft.TextField(key="import-export.import-path", **field_input_style(placeholder="Choose a CSV, JSON, Parquet or RSS file"))
    preview_text = Note("Preview required before commit.", key="import-export.preview-status")
    preview_details = ft.Text("")
    action_status = Note("No import, export or recovery action has run in this session.")
    action_details = ft.Text("")
    commit_button_slot = ft.Container()
    selected_preview: ImportPreview | None = None
    portfolio_imports = PortfolioImportApplication(ROOT)
    staging_report = Note("No portfolio rows staged.", key="import-export.portfolio-staging-report")
    staging_details = ft.Text("")
    staging_table_slot = ft.Container(expand=True)
    reconciliation_status = Note("Portfolio reconciliation not run.", key="import-export.portfolio-reconciliation-status")
    reconciliation_summary = Note("Portfolio reconciliation has not been run.")
    reconciliation_details = ft.Text("")
    reconciliation_table_slot = ft.Container(expand=True)
    portfolio_as_of = ft.TextField(
        key="import-export.portfolio-as-of",
        value=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **field_input_style(placeholder="ISO-8601 timestamp"),
    )
    portfolio_known_at = ft.TextField(
        key="import-export.portfolio-known-at",
        value=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **field_input_style(placeholder="ISO-8601 timestamp"),
    )
    source_account_id = ft.TextField(
        key="import-export.portfolio-source-account", **field_input_style()
    )
    ledger_cash_account = ft.TextField(
        key="import-export.portfolio-ledger-cash", **field_input_style()
    )
    ledger_position_account = ft.TextField(
        key="import-export.portfolio-ledger-position", **field_input_style()
    )
    ledger_clearing_account = ft.TextField(
        key="import-export.portfolio-ledger-clearing", **field_input_style()
    )
    source_adjustment_event = ft.TextField(
        key="import-export.portfolio-adjust-event", **field_input_style()
    )
    orphan_entry_id = ft.TextField(
        key="import-export.portfolio-orphan-entry", **field_input_style()
    )
    rollback_batch = ft.TextField(
        key="import-export.portfolio-rollback-batch",
        **field_input_style(),
    )
    rollback_reason = ft.TextField(
        key="import-export.portfolio-rollback-reason",
        **field_input_style(),
    )
    portfolio_export_path = ft.TextField(
        value=str(ROOT / "exports" / "portfolio_history.csv"),
        key="import-export.portfolio-export-path",
        **field_input_style(),
    )
    portfolio_audit_path = ft.TextField(
        value=str(ROOT / "exports" / "portfolio_reconciliation.json"),
        key="import-export.portfolio-audit-path",
        **field_input_style(),
    )
    portfolio_source_system = ft.TextField(value="user_local", key="import-export.portfolio-source-system", **field_input_style())
    portfolio_provider = ft.TextField(value="user_local", key="import-export.portfolio-provider", **field_input_style())
    locale_items = ("1,234.56", "1.234,56")
    locale_values = {locale_items[0]: "en_US", locale_items[1]: "de_DE"}
    selections["portfolio_locale"] = "en_US"
    mapping_source = ft.TextField(key="import-export.portfolio-mapping-source", **field_input_style())
    mapping_canonical = ft.TextField(key="import-export.portfolio-mapping-canonical", **field_input_style())
    mapping_reviewer = ft.TextField(key="import-export.portfolio-mapping-reviewer", **field_input_style())
    mapping_reason = ft.TextField(key="import-export.portfolio-mapping-reason", **field_input_style())
    bulk_source_id = ft.TextField(value="local-bulk-source", key="import-export.bulk-source-id", **field_input_style())
    bulk_status = Note("No bulk source cached in this session.", key="import-export.bulk-status")
    bulk_status_summary = Note("No local bulk source has been cached.")
    bulk_details = ft.Text("")

    def set_commit_enabled(enabled: bool) -> None:
        commit_button_slot.content = Button.secondary(
            "Commit validated import",
            on_click=commit,
            disabled=not enabled,
            disabled_reason="Preview required before commit." if not enabled else None,
            key="import-export.commit",
        )

    def update_staging_table() -> None:
        frame = selected_preview.frame if selected_preview is not None else pd.DataFrame()
        rows = []
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            for _, record in frame.head(100).iterrows():
                status = str(record.get("staging_status", record.get("status", "unavailable")) or "unavailable")
                label, kind = {
                    "accepted": ("Accepted", "ok"),
                    "valid": ("Valid", "ok"),
                    "quarantined": ("Needs review", "warn"),
                    "correction": ("Correction", "warn"),
                    "rejected": ("Rejected", "bad"),
                }.get(status.casefold(), ("Unavailable", "bad"))
                source_row = _table_cell(record.get("source_id", record.get("source_row", None)))
                instrument = _table_cell(record.get("instrument_id", record.get("raw_instrument_id", None)))
                rows.append({"source": source_row, "instrument": instrument, "validation": Tag(label, kind)})
        staging_table_slot.content = DataTable(
            [
                TableColumn("source", "Source row"),
                TableColumn("instrument", "Instrument", flex=2),
                TableColumn("validation", "Validation"),
            ],
            rows,
            empty_title="No portfolio rows staged",
            empty_reason="No portfolio rows are staged for validation.",
            expand=True,
        )

    def update_reconciliation_table(discrepancies=()) -> None:
        rows = [
            {
                "kind": str(getattr(item, "kind", "Difference")).replace("_", " ").title(),
                "event": _table_cell(getattr(item, "event_id", None)),
                "entry": _table_cell(getattr(item, "ledger_entry_id", None)),
            }
            for item in discrepancies
        ]
        reconciliation_details.value = "\n".join(str(getattr(item, "detail", "")) for item in discrepancies)
        reconciliation_table_slot.content = DataTable(
            [
                TableColumn("kind", "Difference"),
                TableColumn("event", "Source event"),
                TableColumn("entry", "Ledger entry"),
            ],
            rows,
            empty_title="Unavailable",
            empty_reason="No reconciliation differences are available until reconciliation is run.",
            expand=True,
        )

    def show(message: str, *, colour: str = theme.MUTED, record: bool = True) -> None:
        summary = status_summary(message)
        if record:
            state.last_message = summary
        preview_text.value = summary
        preview_details.value = redact_text(message)
        preview_text.color = colour
        action_status.value = summary or "Action completed."
        action_details.value = redact_text(message)
        if page is not None:
            page.update()

    async def open_import(_event: ft.ControlEvent) -> None:
        nonlocal selected_preview
        try:
            files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["csv", "xlsx", "xls", "json", "jsonl", "parquet", "pq", "rss", "xml"], with_data=True)
        except Exception as exc:
            selected_preview = None
            set_commit_enabled(False)
            show(f"Import picker failed: {type(exc).__name__}; no data changed.", colour=theme.RED)
            return
        if not files:
            selected_preview = None
            set_commit_enabled(False)
            show("Local import cancelled; no data changed.")
            return
        selected = files[0]
        display_source = str(selected.path or selected.name)
        path_field.value = display_source
        source = Path(selected.path) if selected.path else None
        upload_directory = None
        if source is None:
            content = getattr(selected, "bytes", None)
            if not isinstance(content, (bytes, bytearray)):
                selected_preview = None
                set_commit_enabled(False)
                show("Import rejected: the selected browser file did not include readable bytes.", colour=theme.RED)
                return
            upload_directory = TemporaryDirectory(prefix="etf-import-", dir=tempfile.gettempdir())
            source = Path(upload_directory.name) / Path(selected.name).name
            source.write_bytes(content)
        try:
            if selections["import_type"] == "portfolio_history":
                selected_preview = portfolio_imports.preview(source, source_format="broker_csv", numeric_locale=selections["portfolio_locale"], source_system=portfolio_source_system.value or None, provider_id=portfolio_provider.value or None)
                if not selected_preview.frame.empty:
                    staged = selected_preview.frame
                    accounts = tuple(sorted(str(value) for value in staged["account_id"].dropna().unique()))
                    if len(accounts) == 1:
                        source_account_id.value = accounts[0]
                    counts = staged["staging_status"].value_counts().to_dict()
                    exceptions = staged.loc[
                        staged["staging_status"].isin(["quarantined", "correction"]),
                        [
                            "source_id",
                            "raw_instrument_id",
                            "instrument_id",
                            "identity_candidates",
                            "identity_review_decisions",
                            "staging_status",
                            "quarantine_reason",
                        ],
                    ].head(8)
                    staging_report.value = f"Staging counts={counts}; reconciliation exceptions={exceptions.to_dict(orient='records') or 'none'}. Identity ambiguities remain quarantined."
                    staging_report.color = theme.AMBER if counts.get("quarantined", 0) else theme.GREEN
            else:
                selected_preview = validate_import(str(selections["import_type"] or "broker"), source)
        finally:
            if upload_directory is not None:
                upload_directory.cleanup()
        set_commit_enabled(selected_preview.valid)
        update_staging_table()
        colour = theme.GREEN if selected_preview.valid else theme.RED
        show(f"Preview {'valid' if selected_preview.valid else 'rejected'}: {selected_preview.rows} rows; source {display_source}; errors={'; '.join(selected_preview.errors) or 'none'}.", colour=colour)

    def commit(_event: ft.ControlEvent) -> None:
        if selected_preview is None or not selected_preview.valid:
            show("Commit blocked: run a valid preview first.", colour=theme.RED)
            return
        label = f"Import {selected_preview.import_type}"
        if state.current_activity is not None:
            show(f"Commit blocked: {state.current_activity.label} is already running.", colour=theme.RED)
            return
        action_id = state.begin_activity(label, "Committing validated import").action_id
        try:
            output_path = None
            if selected_preview.import_type == "portfolio_history":
                with state.activity_publication(action_id):
                    portfolio_result = portfolio_imports.commit(selected_preview)
                message = f"Portfolio import {portfolio_result.status}: batch {portfolio_result.batch_id}; accepted={portfolio_result.accepted}, quarantined={portfolio_result.quarantined}, duplicates={portfolio_result.duplicates}, corrections={portfolio_result.corrections} (execution_allowed=false)."
            else:
                service = ImportService(ROOT)
                service.register(selected_preview)
                with state.activity_publication(action_id):
                    generic_result = service.commit(selected_preview.preview_id)
                output_path = generic_result.destination
                message = f"Import committed: {generic_result.rows} rows at {generic_result.destination} (execution_allowed=false)."
            show(message, colour=theme.GREEN)
            state.update_activity(
                "Import committed",
                completed_units=1,
                total_units=1,
                expected_action_id=action_id,
            )
            state.finish_activity(
                message,
                output_path=output_path,
                label=label,
                expected_action_id=action_id,
            )
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity(label, exc, expected_action_id=action_id)
            show(state.last_message, colour=theme.RED)
        finally:
            cancelled_message = state.restore_cancelled_activity_message(action_id)
            if cancelled_message is not None:
                show(cancelled_message)
            state.release_activity(action_id)
            _refresh_activity_shell(page, state)

    set_commit_enabled(False)

    def apply_portfolio_mapping(_event: ft.ControlEvent) -> None:
        nonlocal selected_preview
        if selected_preview is None or selected_preview.import_type != "portfolio_history":
            show("Mapping blocked: stage a portfolio import first.", colour=theme.RED)
            return
        try:
            selected_preview = portfolio_imports.apply_mapping(
                selected_preview.preview_id,
                source_identity=mapping_source.value or "",
                canonical_instrument_id=mapping_canonical.value or "",
                reviewer=mapping_reviewer.value or "",
                reason=mapping_reason.value or "",
            )
            set_commit_enabled(selected_preview.valid)
            update_staging_table()
            mapped = selected_preview.frame
            exceptions = mapped.loc[mapped["staging_status"].isin(["quarantined", "correction"]), ["source_id", "raw_instrument_id", "instrument_id", "identity_candidates", "staging_status", "quarantine_reason"]].head(8)
            staging_report.value = f"Mapping revision staged: preview={selected_preview.preview_id}; exceptions={exceptions.to_dict(orient='records') or 'none'}; mapping decision is checksum-bound and immutable."
            staging_report.color = theme.AMBER if mapped["staging_status"].eq("quarantined").any() else theme.GREEN
            page.update()
        except Exception as exc:
            show(f"Mapping rejected: {type(exc).__name__}: {redact_text(str(exc))}; prior staging revision preserved.", colour=theme.RED)

    def reconcile_portfolio(_event: ft.ControlEvent) -> None:
        try:
            result = portfolio_imports.reconcile(
                authority=str(selections["portfolio_authority"]),
                as_of=portfolio_as_of.value or "",
                known_at=portfolio_known_at.value or "",
            )
            issues = [
                {
                    "kind": item.kind,
                    "event_id": item.event_id,
                    "ledger_entry_id": item.ledger_entry_id,
                    "detail": item.detail,
                }
                for item in result.discrepancies[:8]
            ]
            replay = result.replay
            reconciliation_status.value = (
                f"Canonical replay: {len(replay.positions)} positions, {len(replay.cash)} cash balances, "
                f"{len(replay.trial_balance)} trial-balance rows; balanced={replay.trial_balance_balanced}; "
                f"source matched={result.matched_source_rows}/{result.active_source_rows}; "
                f"discrepancies={len(result.discrepancies)} {issues}; missing FX="
                f"{sum(item.status == 'missing' for item in replay.fx_conversions)}; "
                f"missing lots={list(replay.missing_lot_identity)}; execution_allowed=false."
            )
            reconciliation_status.color = theme.GREEN if replay.trial_balance_balanced and not result.discrepancies and not replay.missing_lot_identity else theme.AMBER
            reconciliation_summary.value = "Ledger reconciliation completed; review status and differences below."
            update_reconciliation_table(result.discrepancies)
        except Exception as exc:
            reconciliation_status.value = f"Reconciliation unavailable: {type(exc).__name__}: {redact_text(str(exc))}; no data changed."
            reconciliation_status.color = theme.RED
            reconciliation_summary.value = "Ledger reconciliation is unavailable."
            update_reconciliation_table()
        page.update()

    def rollback_portfolio_once(_event: ft.ControlEvent) -> None:
        try:
            portfolio_imports.rollback(rollback_batch.value or "", reason=rollback_reason.value or "")
            reconciliation_status.value = f"Source-evidence rollback recorded for {rollback_batch.value}; posted ledger facts remain immutable and require an explicit reversing adjustment; execution_allowed=false."
            reconciliation_status.color = theme.AMBER
            reconciliation_summary.value = "Source-evidence rollback was recorded."
        except Exception as exc:
            reconciliation_status.value = f"Rollback blocked: {type(exc).__name__}: {redact_text(str(exc))}; no data changed."
            reconciliation_status.color = theme.RED
            reconciliation_summary.value = "Source-evidence rollback was blocked."
        page.update()

    def export_portfolio(_event: ft.ControlEvent) -> None:
        try:
            destination = portfolio_imports.export_canonical(Path(portfolio_export_path.value or ""))
            reconciliation_status.value = f"Canonical portfolio history exported to {destination}; quarantined rows excluded."
            reconciliation_status.color = theme.GREEN
            reconciliation_summary.value = "Canonical portfolio history exported."
        except Exception as exc:
            reconciliation_status.value = f"Portfolio export unavailable: {type(exc).__name__}: {redact_text(str(exc))}; no placeholder written."
            reconciliation_status.color = theme.RED
            reconciliation_summary.value = "Canonical portfolio export is unavailable."
        page.update()

    def map_portfolio_account(_event: ft.ControlEvent) -> None:
        try:
            mapping = portfolio_imports.map_source_account(
                authority=str(selections["portfolio_authority"]),
                source_account_id=source_account_id.value or "",
                cash_account_id=ledger_cash_account.value or "",
                position_account_id=ledger_position_account.value or "",
                clearing_account_id=ledger_clearing_account.value or "",
                reviewer=mapping_reviewer.value or "",
                reason=mapping_reason.value or "",
            )
            reconciliation_status.value = f"Account mapping {mapping.mapping_id} recorded for source account {mapping.source_account_id}; reviewer={mapping.reviewer}; immutable decision."
            reconciliation_status.color = theme.GREEN
            reconciliation_summary.value = "Source account mapping was recorded."
        except Exception as exc:
            reconciliation_status.value = f"Account mapping rejected: {type(exc).__name__}: {redact_text(str(exc))}; prior mapping preserved."
            reconciliation_status.color = theme.RED
            reconciliation_summary.value = "Source account mapping was rejected."
        page.update()

    def apply_portfolio_adjustment(_event: ft.ControlEvent) -> None:
        try:
            result = portfolio_imports.apply_adjustment(
                source_adjustment_event.value or "",
                authority=str(selections["portfolio_authority"]),
                as_of=portfolio_as_of.value or "",
                known_at=portfolio_known_at.value or "",
                reviewer=mapping_reviewer.value or "",
                reason=mapping_reason.value or "",
            )
            reconciliation_status.value = f"Adjustment {result.adjustment_id} posted as {result.ledger_entry_id}; reversed={list(result.reversed_entry_ids)}; reviewer={result.reviewer}; execution_allowed=false."
            reconciliation_status.color = theme.AMBER
            reconciliation_summary.value = "Source correction was posted."
        except Exception as exc:
            reconciliation_status.value = f"Adjustment blocked: {type(exc).__name__}: {redact_text(str(exc))}; no ledger fact changed."
            reconciliation_status.color = theme.RED
            reconciliation_summary.value = "Source correction was blocked."
        page.update()

    def reverse_orphaned_portfolio_entry(_event: ft.ControlEvent) -> None:
        try:
            reversal_id = portfolio_imports.reverse_orphaned_entry(
                orphan_entry_id.value or "",
                authority=str(selections["portfolio_authority"]),
                reviewer=mapping_reviewer.value or "",
                reason=mapping_reason.value or "",
            )
            reconciliation_status.value = f"Orphan discrepancy reversed with immutable entry {reversal_id}; execution_allowed=false."
            reconciliation_status.color = theme.AMBER
            reconciliation_summary.value = "Orphaned source entry was reversed."
        except Exception as exc:
            reconciliation_status.value = f"Reversal blocked: {type(exc).__name__}: {redact_text(str(exc))}; no ledger fact changed."
            reconciliation_status.color = theme.RED
            reconciliation_summary.value = "Orphaned source reversal was blocked."
        page.update()

    def export_portfolio_audit(_event: ft.ControlEvent) -> None:
        try:
            destination = portfolio_imports.export_reconciliation_audit(
                Path(portfolio_audit_path.value or ""),
                authority=str(selections["portfolio_authority"]),
                as_of=portfolio_as_of.value or "",
                known_at=portfolio_known_at.value or "",
            )
            reconciliation_status.value = f"Deterministic reconciliation audit exported to {destination}; no ledger data changed."
            reconciliation_status.color = theme.GREEN
            reconciliation_summary.value = "Reconciliation audit exported."
        except Exception as exc:
            reconciliation_status.value = f"Audit export unavailable: {type(exc).__name__}: {redact_text(str(exc))}; no placeholder written."
            reconciliation_status.color = theme.RED
            reconciliation_summary.value = "Reconciliation audit export is unavailable."
        page.update()

    async def cache_bulk_source(_event: ft.ControlEvent) -> None:
        try:
            files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["csv", "json", "jsonl", "parquet", "pq", "zip", "tar", "gz"], with_data=True)
        except Exception as exc:
            bulk_status.value = f"Bulk cache picker failed: {type(exc).__name__}; no data changed."
            bulk_status_summary.value = "Bulk source could not be selected."
            bulk_status.color = theme.RED
            page.update()
            return
        if not files:
            bulk_status.value = "Bulk cache selection cancelled; no data changed."
            bulk_status_summary.value = "Bulk cache selection was cancelled."
            bulk_status.color = theme.MUTED
            page.update()
            return
        selected = files[0]
        source = Path(selected.path) if selected.path else None
        upload_directory = None
        if source is None:
            content = getattr(selected, "bytes", None)
            if not isinstance(content, (bytes, bytearray)):
                bulk_status.value = "Bulk cache rejected: the selected browser file did not include readable bytes."
                bulk_status_summary.value = "The selected source could not be read."
                bulk_status.color = theme.RED
                page.update()
                return
            upload_directory = TemporaryDirectory(prefix="etf-bulk-import-", dir=tempfile.gettempdir())
            source = Path(upload_directory.name) / Path(selected.name).name
            source.write_bytes(content)
        label = "Rebuild local source cache"
        if state.current_activity is not None:
            if upload_directory is not None:
                upload_directory.cleanup()
            bulk_status.value = f"Cache rebuild blocked: {state.current_activity.label} is already running."
            bulk_status_summary.value = "Bulk cache is blocked while another local job is running."
            bulk_status.color = theme.RED
            page.update()
            return
        action_id = state.begin_activity(label, "Validating cache source").action_id
        try:
            with state.activity_publication(action_id):
                result = ContentAddressedCache(ROOT).store_local_file(bulk_source_id.value or "local-bulk-source", source)
            bulk_status.value = f"Cached and checksum-verified {result.manifest.source_id}: {result.manifest.content_sha256[:16]}…; version {result.manifest.version}; raw object is immutable."
            bulk_status_summary.value = "Bulk source cache completed."
            bulk_details.value = bulk_status.value
            bulk_status.color = theme.GREEN
            state.update_activity(
                "Cache source promoted",
                completed_units=1,
                total_units=1,
                expected_action_id=action_id,
            )
            cache = ContentAddressedCache(ROOT)
            state.finish_activity(
                bulk_status.value,
                output_path=cache._manifest_path(result.manifest.source_id),
                label=label,
                expected_action_id=action_id,
            )
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity(label, exc, expected_action_id=action_id)
            bulk_status.value = state.last_message
            bulk_status_summary.value = "Bulk source cache failed."
            bulk_details.value = redact_text(state.last_message)
            bulk_status.color = theme.RED
        finally:
            if upload_directory is not None:
                upload_directory.cleanup()
            cancelled_message = state.restore_cancelled_activity_message(action_id)
            if cancelled_message is not None:
                bulk_status.value = cancelled_message
                bulk_status_summary.value = "Bulk source cache was cancelled."
                bulk_details.value = redact_text(cancelled_message)
                bulk_status.color = theme.MUTED
            state.release_activity(action_id)
            _refresh_activity_shell(page, state)

    cache_report = bulk_cache_health(ROOT)
    cache_summary = f"Status={cache_report['status']} | objects={cache_report['object_count']} | manifests={cache_report['manifest_count']} | staged={cache_report['staged_file_count']} | promoted generations={cache_report['promoted_generation_count']} | network_calls=false"

    export_path = ft.TextField(value=str(ROOT / "exports" / "scoreboard.csv"), key="import-export.export-path", **field_input_style())
    backup_path = ft.TextField(value=str(ROOT / "backups" / "cockpit-backup.zip"), key="import-export.backup-path", **field_input_style())
    restore_path = ft.TextField(key="import-export.restore-path", **field_input_style())
    restore_status = Note("Restore validation preview required; nothing will be written.", key="import-export.restore-status")
    restore_summary = Note("Restore validation preview required; nothing will be written.")
    restore_commit_slot = ft.Container()
    restore_cancel_slot = ft.Container()
    restore_preview = None

    def set_restore_controls(commit_enabled: bool, cancel_enabled: bool) -> None:
        restore_commit_slot.content = Button.primary(
            "Commit restore",
            on_click=commit_restore_preview,
            disabled=not commit_enabled,
            disabled_reason="Validate a restore preview before committing." if not commit_enabled else None,
            key="import-export.restore-commit",
        )
        restore_cancel_slot.content = ft.TextButton(
            "Cancel restore",
            on_click=cancel_restore_preview,
            disabled=not cancel_enabled,
            tooltip="No restore preview is active." if not cancel_enabled else None,
            key="import-export.restore-cancel",
        )

    def backup(_event: ft.ControlEvent) -> None:
        try:
            manifest = create_backup([DATA_DIR, CONFIG_DIR, ROOT / "pyproject.toml", ROOT / "CHANGELOG.md"], Path(backup_path.value or "backup.zip"))
            show(f"Backup created at {manifest.archive}; {len(manifest.checksums)} files; checksum manifest validated.", colour=theme.GREEN)
        except Exception as exc:
            show(f"Backup failed: {type(exc).__name__}: {redact_text(str(exc))}.", colour=theme.RED)

    def validate_restore_preview(_event: ft.ControlEvent) -> None:
        nonlocal restore_preview
        archive = Path(restore_path.value or "")
        restore_preview = validate_restore(archive, destination=ROOT)
        set_restore_controls(restore_preview.valid, True)
        restore_summary.value = "Restore preview is valid; nothing has been written." if restore_preview.valid else "Restore preview was rejected; nothing has been written."
        restore_status.value = f"Restore preview {'valid' if restore_preview.valid else 'rejected'} for {archive}; destination {ROOT}; {len(restore_preview.entries)} entries; errors={'; '.join(restore_preview.errors) or 'none'}."
        restore_status.color = theme.GREEN if restore_preview.valid else theme.RED
        page.update()

    def commit_restore_preview(_event: ft.ControlEvent) -> None:
        nonlocal restore_preview
        if restore_preview is None or not restore_preview.valid:
            restore_status.value = "Restore commit blocked: validate a valid preview first."
            restore_summary.value = "Restore commit is blocked until a valid preview is available."
            restore_status.color = theme.RED
            page.update()
            return
        result = commit_restore(restore_preview, ROOT)
        restore_status.value = f"Restore {'complete' if result.ok else 'failed'} at {result.destination}; {result.error or f'{result.restored} files'}."
        restore_summary.value = "Restore completed." if result.ok else "Restore failed."
        restore_status.color = theme.GREEN if result.ok else theme.RED
        if result.ok:
            restore_preview = None
            set_restore_controls(False, False)
        page.update()

    def cancel_restore_preview(_event: ft.ControlEvent) -> None:
        nonlocal restore_preview
        restore_preview = None
        set_restore_controls(False, False)
        restore_summary.value = "Restore cancelled; no files changed."
        restore_status.value = "Restore cancelled; no files changed."
        restore_status.color = theme.MUTED
        page.update()

    set_restore_controls(False, False)

    def _export_frame(category: str) -> pd.DataFrame | None:
        if category == "scoreboard":
            frame = getattr(state.snapshot, "scoreboard", None)
            if isinstance(frame, pd.DataFrame):
                return frame
            return pd.DataFrame([getattr(signal, "__dict__", {}) for signal in getattr(state.snapshot, "signals", ())])
        if category == "watchlist":
            scoreboard_path = DERIVED_DIR / "scoreboard.parquet"
            if scoreboard_path.exists():
                try:
                    frame = load_simple_scoreboard(scoreboard_path)
                except (OSError, ValueError):
                    # Corrupt scoreboard: the export reports the table unavailable instead of an empty file.
                    return None
                if "final_label" in frame.columns:
                    return frame.loc[frame["final_label"].astype(str).isin({"watchlist", "mixed_evidence_review", "hold_context"})].copy()
                return frame.iloc[0:0].copy()
            rows = [getattr(signal, "__dict__", {}) for signal in getattr(state.snapshot, "signals", ()) if getattr(signal, "action", "") in {"watchlist", "hold_context"}]
            return pd.DataFrame(rows)
        if category == "paper_trade_journal":
            path = ROOT / "data" / "derived" / "paper_trades.parquet"
            return pd.read_parquet(path) if path.exists() else None
        if category == "decision_journal":
            try:
                records = [redact_private_fields(entry.model_dump(mode="json")) for entry in DecisionJournal().list_entries(root=DATA_DIR)]
                return pd.DataFrame(records)
            except JournalIntegrityError:
                return None
        if category == "plan_issues_snapshot":
            rows = []
            for path in (ROOT / "plan.md", ROOT / "ISSUES.md", ROOT / "issues" / "open.md", ROOT / "issues" / "closed.md"):
                if path.is_file():
                    rows.append({"path": str(path), "content": path.read_text(encoding="utf-8")})
            return pd.DataFrame(rows) if rows else None
        return None

    def start_audit_packet_export() -> threading.Thread | None:
        label = "Export audit packet"
        if state.current_activity is not None:
            show(f"Export blocked: {state.current_activity.label} is already running.", colour=theme.RED)
            return None
        action_id = state.begin_activity(label, "Preparing export").action_id
        show("Exporting audit packet...")
        _refresh_activity_shell(page, state)

        def worker() -> None:
            try:
                with state.share_activity(action_id):
                    destination = state.export_audit_packet()
                if state.activity_was_cancelled(action_id):
                    return
                state.last_export_path = destination
                message = f"Export complete: audit packet at {destination}."
                _record_export_terminal(
                    state,
                    label=label,
                    message=message,
                    destination=destination,
                    ok=True,
                    error=None,
                    action_id=action_id,
                )
                show(message, colour=theme.GREEN)
            except Exception as exc:
                if not state.activity_was_cancelled(action_id):
                    state.fail_activity(
                        label,
                        exc,
                        retry_callback=lambda: start_audit_packet_export(),
                        expected_action_id=action_id,
                    )
                    show(state.last_message, colour=theme.RED)
            finally:
                cancelled_message = state.restore_cancelled_activity_message(action_id)
                if cancelled_message is not None:
                    show(cancelled_message, record=False)  # the canonical cancellation message stays authoritative
                state.release_activity(action_id)
                _refresh_activity_shell(page, state)

        background = threading.Thread(target=worker, daemon=True)
        background.start()
        return background

    def export_category(category: str) -> None:
        if category == "audit_packet":
            start_audit_packet_export()
            return
        label = f"Export {category.replace('_', ' ')}"
        if state.current_activity is not None:
            show(f"Export blocked: {state.current_activity.label} is already running.", colour=theme.RED)
            return
        action_id = state.begin_activity(label, "Preparing export").action_id
        try:
            frame = _export_frame(category)
            destination = Path(export_path.value or ROOT / "exports" / f"{category}.csv") if category == "scoreboard" else ROOT / "exports" / f"{category}.csv"
            with state.activity_publication(action_id):
                result = export_table(category, frame, destination)
            state.last_export_path = result.destination
            message = f"Export {'complete' if result.ok else 'unavailable'}: {result.destination}; {result.error or f'{result.rows} rows'}."
            result_ok = bool(result.ok)
            result_error = result.error
            _record_export_terminal(
                state,
                label=label,
                message=message,
                destination=destination,
                ok=result_ok,
                error=result_error,
                action_id=action_id,
            )
            show(message if result_ok else state.last_message, colour=theme.GREEN if result_ok else theme.RED)
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity(label, exc, expected_action_id=action_id)
            show(state.last_message, colour=theme.RED)
        finally:
            cancelled_message = state.restore_cancelled_activity_message(action_id)
            if cancelled_message is not None:
                show(cancelled_message)
            state.release_activity(action_id)
            _refresh_activity_shell(page, state)

    def export_scoreboard(_event: ft.ControlEvent) -> None:
        export_category("scoreboard")

    def status_summary(message: str) -> str:
        lowered = message.casefold()
        if "preview" in lowered:
            return "Import preview updated; review staged rows."
        if "backup" in lowered:
            return "Backup action updated; review details."
        if "restore" in lowered:
            return "Restore action updated; review details."
        if "export" in lowered:
            return "Export action updated; review details."
        if any(word in lowered for word in ("reconciliation", "mapping", "rollback", "adjustment", "reversal")):
            return "Portfolio action updated; review details."
        return "Local action updated; review details."

    def _invalidate_preview() -> None:
        nonlocal selected_preview
        selected_preview = None
        set_commit_enabled(False)

    def _select(name: str, values: dict[str, str]):
        def on_change(label: str) -> None:
            selections[name] = values[label]
            _invalidate_preview()
        return on_change

    import_type_control = Field("Import type", options=import_type_labels, value="Portfolio History",
        on_change=_select("import_type", import_type_values), expand=True)
    locale_control = Segmented(locale_items, locale_items[0],
        on_change=_select("portfolio_locale", locale_values),
        key="import-export.portfolio-locale")
    authority_values = {"Broker": "broker", "Paper": "paper"}
    authority_control = Segmented(tuple(authority_values), "Broker",
        on_change=_select("portfolio_authority", authority_values),
        key="import-export.portfolio-authority")

    source_path_disclosure = Disclosure("Local source path", Field("Local source path", control=path_field, expand=True))
    action_disclosure = Disclosure("Import and export details", ft.Column([preview_details, action_details], spacing=8))
    staging_disclosure = Disclosure("Staging validation details", ft.Column([staging_report, staging_details], spacing=8))
    cache_disclosure = Disclosure("Bulk source cache details", ft.Column([ft.Text(cache_summary), bulk_status, bulk_details], spacing=8))
    reconciliation_disclosure = Disclosure("Reconciliation details",
        ft.Column([reconciliation_status, reconciliation_details, reconciliation_table_slot], spacing=8))
    restore_disclosure = Disclosure("Restore validation details", restore_status)
    export_destination_disclosure = Disclosure("Export destination path", Field("Export destination", control=export_path, expand=True))
    backup_path_disclosure = Disclosure("Backup archive destination", Field("Backup archive destination", control=backup_path, expand=True))
    restore_path_disclosure = Disclosure("Restore archive path", Field("Restore archive", control=restore_path, expand=True))
    portfolio_export_disclosure = Disclosure("Canonical portfolio export path",
        Field("Canonical portfolio export", control=portfolio_export_path, expand=True))
    audit_export_disclosure = Disclosure("Deterministic ledger audit JSON path",
        Field("Deterministic ledger audit JSON", control=portfolio_audit_path, expand=True))

    rollback_confirmation: dict[str, tuple[str, str] | None] = {"armed": None}
    def rollback_portfolio(_event: ft.ControlEvent) -> None:
        target = (rollback_batch.value or "", rollback_reason.value or "")
        if rollback_confirmation["armed"] != target:
            rollback_confirmation["armed"] = target
            action_status.value = "Select Rollback batch again to confirm this source rollback."
            page.update()
            return
        rollback_confirmation["armed"] = None
        rollback_portfolio_once(_event)

    def import_view() -> ft.Control:
        import_card = GlassCard("Import", note="local validation before commit", body=ft.Column([
            import_type_control,
            ft.Row([Field("Source system", control=portfolio_source_system),
                    Field("Provider", control=portfolio_provider),
                    ft.Column([Note("Numeric locale"), locale_control], spacing=8, tight=True)], spacing=12, wrap=True),
            source_path_disclosure,
            ft.Row([Button.primary("Choose and preview", on_click=open_import, key="import-export.import"), commit_button_slot], spacing=12, wrap=True),
            preview_text, action_disclosure,
            Note("Imports remain local previews until explicitly committed."),
        ], spacing=12, expand=True), expand=5)
        preview_card = GlassCard("Preview", note="staged rows and validation", body=ft.Column([
            Well(staging_table_slot, expand=True), staging_disclosure,
        ], spacing=12, expand=True), expand=7)
        bulk_card = GlassCard("Bulk source cache", note="content-addressed local cache", body=ft.Column([
            Field("Bulk source ID", control=bulk_source_id, expand=True),
            Button.secondary("Cache local source", on_click=cache_bulk_source, key="import-export.bulk-cache"),
            KpiTile("Cache health", None, sub="Unavailable: cache-health values are shown in the details."),
            bulk_status_summary, cache_disclosure,
        ], spacing=12, expand=True), expand=True)
        rollback_card = GlassCard("Portfolio source rollback", note="future source reconciliation only", body=ft.Column([
            Field("Portfolio batch ID", control=rollback_batch, expand=True),
            Field("Rollback reason", control=rollback_reason, expand=True),
            ft.TextButton("Rollback batch", on_click=rollback_portfolio, key="import-export.portfolio-rollback"),
            Note("Select the control again to confirm this source rollback."), reconciliation_summary,
        ], spacing=12, expand=True), expand=True)
        return ft.Column([ft.Row([import_card, preview_card], spacing=24, expand=12),
            ft.Row([bulk_card, rollback_card], spacing=24, expand=12)],
            spacing=24, expand=True, scroll=ft.ScrollMode.AUTO)

    def reconcile_view() -> ft.Control:
        identity = GlassCard("Identity mapping", note="reviewer-bound instrument identity", body=ft.Column([
            Field("Source ticker/ISIN/listing", control=mapping_source, expand=True),
            Field("Canonical instrument ID", control=mapping_canonical, expand=True),
            Field("Reviewer", control=mapping_reviewer, expand=True),
            Field("Mapping reason", control=mapping_reason, expand=True),
            Button.secondary("Apply identity mapping", on_click=apply_portfolio_mapping, key="import-export.portfolio-apply-mapping"),
        ], spacing=12, expand=True), expand=True)
        account = GlassCard("Account mapping", note="canonical ledger authority and cutoffs", body=ft.Column([
            ft.Column([Note("Ledger authority"), authority_control], spacing=8, tight=True),
            ft.Row([Field("Effective cutoff (ISO-8601)", control=portfolio_as_of),
                    Field("Known-time cutoff (ISO-8601)", control=portfolio_known_at)], spacing=12, wrap=True),
            Field("Source account ID", control=source_account_id, expand=True),
            Field("Ledger cash account ID", control=ledger_cash_account, expand=True),
            Field("Ledger position account ID", control=ledger_position_account, expand=True),
            Field("Ledger clearing account ID", control=ledger_clearing_account, expand=True),
            ft.Row([Button.secondary("Map source account", on_click=map_portfolio_account, key="import-export.portfolio-map-account"),
                    Button.primary("Reconcile against ledger", on_click=reconcile_portfolio, key="import-export.portfolio-reconcile")],
                   spacing=12, wrap=True),
        ], spacing=12, expand=True), expand=True)
        corrections = GlassCard("Corrections", note="explicit reviewer decisions", body=ft.Column([
            Field("Source event ID to post", control=source_adjustment_event, expand=True),
            Button.secondary("Post/reverse source correction", on_click=apply_portfolio_adjustment, key="import-export.portfolio-adjust"),
            Field("Orphaned source-linked entry ID", control=orphan_entry_id, expand=True),
            Button.secondary("Reverse orphaned source entry", on_click=reverse_orphaned_portfolio_entry, key="import-export.portfolio-reverse-orphan"),
            Note("Corrections preserve immutable ledger history."),
        ], spacing=12, expand=True), expand=True)
        audit = GlassCard("Audit exports", note="canonical evidence and deterministic ledger audit", body=ft.Column([
            portfolio_export_disclosure,
            Button.secondary("Export source evidence", on_click=export_portfolio, key="import-export.portfolio-export"),
            audit_export_disclosure,
            Button.secondary("Export reconciliation audit", on_click=export_portfolio_audit, key="import-export.portfolio-audit-export"),
        ], spacing=12, expand=True), expand=True)
        result = GlassCard("Reconciliation result", note="canonical replay status and differences",
            body=ft.Column([reconciliation_summary, Well(reconciliation_table_slot, expand=True), reconciliation_disclosure],
                spacing=12, expand=True), expand=True)
        return ft.Column([ft.Row([identity, account], spacing=24, expand=12),
            ft.Row([corrections, audit], spacing=24, expand=12), result],
            spacing=24, expand=True, scroll=ft.ScrollMode.AUTO)

    def export_view() -> ft.Control:
        destination = GlassCard("Export destination", note="explicit local output path",
            body=export_destination_disclosure, expand=True)
        specs = (("Scoreboard", "scoreboard", "scoreboard"),
            ("Audit packet", "audit_packet", "audit-packet"),
            ("Watchlist", "watchlist", "watchlist"),
            ("Paper-trade journal", "paper_trade_journal", "paper-trade-journal"),
            ("Decision journal", "decision_journal", "decision-journal"),
            ("Plan/issues snapshot", "plan_issues_snapshot", "plan-issues-snapshot"))
        cards = []
        for title, category, slug in specs:
            cards.append(GlassCard(title, note="last export time", body=ft.Column([
                KpiTile("Last export", None, sub="Unavailable: this view has no export timestamp."),
                Button.secondary("Export", on_click=lambda _event, category=category: export_category(category),
                    key=f"import-export.export-{slug}"),
            ], spacing=12), expand=True))
        return ft.Column([destination, ft.Row(cards[:3], spacing=16, expand=1), ft.Row(cards[3:], spacing=16, expand=1),
            Note("Export status and destination are shown above; unavailable sources are reported without writing placeholders."),
            action_disclosure], spacing=16, expand=True, scroll=ft.ScrollMode.AUTO)

    def backup_view() -> ft.Control:
        card = GlassCard("Backup and Restore", note="validate before restoring", body=ft.Column([
            backup_path_disclosure,
            Button.primary("Create backup", on_click=backup, key="import-export.create-backup"),
            restore_path_disclosure,
            ft.Row([Button.secondary("Validate restore preview", on_click=validate_restore_preview, key="import-export.restore-validate"),
                    restore_commit_slot, restore_cancel_slot], spacing=12, wrap=True),
            restore_summary, restore_disclosure,
        ], spacing=12, expand=True), expand=True)
        return ft.Column([card], spacing=24, expand=True, scroll=ft.ScrollMode.AUTO)

    views = {"Import": import_view, "Reconcile": reconcile_view, "Export": export_view, "Backup": backup_view}
    update_staging_table()
    update_reconciliation_table()
    # Every view stays in the control tree (only the selected one is visible), so keyed controls remain reachable.
    built = {name: build() for name, build in views.items()}
    for name, panel in built.items():
        panel.visible = name == "Import"
    body_slot = ft.Column(list(built.values()), spacing=24, expand=True)

    def select_segment(value: str) -> None:
        built[value] = views[value]()
        for name, panel in built.items():
            panel.visible = name == value
        body_slot.controls = list(built.values())
        if page is not None:
            page.update()
    return PageView(chrome=PageChrome(
        title="Import & Export",
        subtitle="Preview and validate local evidence before any commit · explicit export paths",
        segment_groups=(SegmentGroup("import-export", ("Import", "Reconcile", "Export", "Backup"), "Import", on_change=select_segment),),
    ), body=body_slot)
