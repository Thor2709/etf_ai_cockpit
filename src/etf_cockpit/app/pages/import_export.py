from __future__ import annotations

from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.portfolio_imports import PortfolioImportApplication
from etf_cockpit.core.paths import CONFIG_DIR, DATA_DIR, DERIVED_DIR, ROOT
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
    owns_activity: bool,
) -> None:
    if ok:
        if owns_activity:
            state.finish_activity(message, output_path=destination, label=label)
        return
    state.fail_activity(label, RuntimeError(error or "export was unavailable"))


def import_export_page(page: ft.Page, state: AppState) -> ft.Control:
    picker = ft.FilePicker(key="import-export.import.file-picker")
    try:
        page.services.append(picker)
    except Exception:
        try:
            page.overlay.append(picker)
        except Exception:
            pass
    import_type = ft.Dropdown(label="Import type", value="portfolio_history", options=[ft.dropdown.Option(value, value.replace("_", " ").title()) for value in ("portfolio_history", "broker", "candidate", "manual_notes", "etf_holdings", "news", "events", "rss_list")], width=190)
    path_field = ft.TextField(label="Local source path", hint_text="Choose a CSV, JSON, Parquet or RSS file", expand=True, key="import-export.import-path")
    preview_text = ft.Text("Preview required before commit.", color=theme.MUTED, selectable=True, key="import-export.preview-status")
    commit_button = ft.OutlinedButton("Commit validated import", key="import-export.commit", disabled=True)
    selected_preview: ImportPreview | None = None
    portfolio_imports = PortfolioImportApplication(ROOT)
    staging_report = ft.Text(
        "No portfolio rows staged.",
        color=theme.MUTED,
        selectable=True,
        key="import-export.portfolio-staging-report",
    )
    reconciliation_status = ft.Text(
        "Portfolio reconciliation not run.",
        color=theme.MUTED,
        selectable=True,
        key="import-export.portfolio-reconciliation-status",
    )
    rollback_batch = ft.TextField(
        label="Portfolio batch ID",
        width=300,
        key="import-export.portfolio-rollback-batch",
    )
    rollback_reason = ft.TextField(
        label="Rollback reason",
        width=300,
        key="import-export.portfolio-rollback-reason",
    )
    portfolio_export_path = ft.TextField(
        label="Canonical portfolio export",
        value=str(ROOT / "exports" / "portfolio_history.csv"),
        expand=True,
        key="import-export.portfolio-export-path",
    )
    portfolio_source_system = ft.TextField(label="Source system", value="user_local", width=180, key="import-export.portfolio-source-system")
    portfolio_provider = ft.TextField(label="Provider", value="user_local", width=180, key="import-export.portfolio-provider")
    portfolio_locale = ft.Dropdown(label="Numeric locale", value="en_US", options=[ft.dropdown.Option("en_US", "1,234.56"), ft.dropdown.Option("de_DE", "1.234,56")], width=170, key="import-export.portfolio-locale")
    mapping_source = ft.TextField(label="Source ticker/ISIN/listing", width=210, key="import-export.portfolio-mapping-source")
    mapping_canonical = ft.TextField(label="Canonical instrument ID", width=210, key="import-export.portfolio-mapping-canonical")
    mapping_reviewer = ft.TextField(label="Reviewer", width=170, key="import-export.portfolio-mapping-reviewer")
    mapping_reason = ft.TextField(label="Mapping reason", width=240, key="import-export.portfolio-mapping-reason")
    bulk_source_id = ft.TextField(label="Bulk source ID", value="local-bulk-source", width=220, key="import-export.bulk-source-id")
    bulk_status = ft.Text("No bulk source cached in this session.", color=theme.MUTED, selectable=True, key="import-export.bulk-status")

    def show(message: str, *, colour: str = theme.MUTED) -> None:
        state.last_message = message
        preview_text.value = message
        preview_text.color = colour
        page.update()

    async def open_import(_event: ft.ControlEvent) -> None:
        nonlocal selected_preview
        try:
            files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["csv", "xlsx", "xls", "json", "jsonl", "parquet", "pq", "rss", "xml"], with_data=True)
        except Exception as exc:
            selected_preview = None
            commit_button.disabled = True
            show(f"Import picker failed: {type(exc).__name__}; no data changed.", colour=theme.RED)
            return
        if not files:
            selected_preview = None
            commit_button.disabled = True
            show("Local import cancelled; no data changed.")
            return
        selected = files[0]
        source = Path(selected.path or selected.name)
        path_field.value = str(source)
        if import_type.value == "portfolio_history":
            selected_preview = portfolio_imports.preview(source, source_format="broker_csv", numeric_locale=portfolio_locale.value or "en_US", source_system=portfolio_source_system.value or None, provider_id=portfolio_provider.value or None)
            if not selected_preview.frame.empty:
                staged = selected_preview.frame
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
            selected_preview = validate_import(import_type.value or "broker", source)
        commit_button.disabled = not selected_preview.valid
        colour = theme.GREEN if selected_preview.valid else theme.RED
        show(f"Preview {'valid' if selected_preview.valid else 'rejected'}: {selected_preview.rows} rows; source {source}; errors={'; '.join(selected_preview.errors) or 'none'}.", colour=colour)

    def commit(_event: ft.ControlEvent) -> None:
        if selected_preview is None or not selected_preview.valid:
            show("Commit blocked: run a valid preview first.", colour=theme.RED)
            return
        label = f"Import {selected_preview.import_type}"
        owns_activity = state.current_activity is None
        if owns_activity:
            state.begin_activity(label, "Committing validated import")
        else:
            state.update_activity("Committing validated import")
        try:
            output_path = None
            if selected_preview.import_type == "portfolio_history":
                portfolio_result = portfolio_imports.commit(selected_preview)
                message = f"Portfolio import {portfolio_result.status}: batch {portfolio_result.batch_id}; accepted={portfolio_result.accepted}, quarantined={portfolio_result.quarantined}, duplicates={portfolio_result.duplicates}, corrections={portfolio_result.corrections} (execution_allowed=false)."
            else:
                service = ImportService(ROOT)
                service.register(selected_preview)
                generic_result = service.commit(selected_preview.preview_id)
                output_path = generic_result.destination
                message = f"Import committed: {generic_result.rows} rows at {generic_result.destination} (execution_allowed=false)."
            show(message, colour=theme.GREEN)
            state.update_activity("Import committed", completed_units=1, total_units=1)
            if owns_activity:
                state.finish_activity(message, output_path=output_path, label=label)
        except Exception as exc:
            failure = f"Import failed: {type(exc).__name__}: {exc}; previous clean state preserved."
            show(failure, colour=theme.RED)
            if owns_activity:
                state.fail_activity(label, exc)

    commit_button.on_click = commit

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
            commit_button.disabled = not selected_preview.valid
            mapped = selected_preview.frame
            exceptions = mapped.loc[mapped["staging_status"].isin(["quarantined", "correction"]), ["source_id", "raw_instrument_id", "instrument_id", "identity_candidates", "staging_status", "quarantine_reason"]].head(8)
            staging_report.value = f"Mapping revision staged: preview={selected_preview.preview_id}; exceptions={exceptions.to_dict(orient='records') or 'none'}; mapping decision is checksum-bound and immutable."
            staging_report.color = theme.AMBER if mapped["staging_status"].eq("quarantined").any() else theme.GREEN
            page.update()
        except Exception as exc:
            show(f"Mapping rejected: {type(exc).__name__}: {exc}; prior staging revision preserved.", colour=theme.RED)

    def reconcile_portfolio(_event: ft.ControlEvent) -> None:
        try:
            result = portfolio_imports.reconcile()
            reconciliation_status.value = f"Rebuilt from zero: {len(result.holdings)} holding positions, {len(result.cash)} cash balances, {len(result.active_events)} active rows; accounting={'balanced' if result.balanced else 'unbalanced'}; reconciliation_errors={list(result.reconciliation_errors) or 'none'}; quarantined={len(result.quarantined)} ({'complete' if result.quarantined.empty else 'manual review'}); execution_allowed=false."
            reconciliation_status.color = theme.GREEN if result.balanced and result.quarantined.empty else theme.AMBER
        except Exception as exc:
            reconciliation_status.value = f"Reconciliation unavailable: {type(exc).__name__}: {exc}; no data changed."
            reconciliation_status.color = theme.RED
        page.update()

    def rollback_portfolio(_event: ft.ControlEvent) -> None:
        try:
            portfolio_imports.rollback(rollback_batch.value or "", reason=rollback_reason.value or "")
            reconciliation_status.value = f"Rollback recorded for {rollback_batch.value}; rebuild required; execution_allowed=false."
            reconciliation_status.color = theme.GREEN
        except Exception as exc:
            reconciliation_status.value = f"Rollback blocked: {type(exc).__name__}: {exc}; no data changed."
            reconciliation_status.color = theme.RED
        page.update()

    def export_portfolio(_event: ft.ControlEvent) -> None:
        try:
            destination = portfolio_imports.export_canonical(Path(portfolio_export_path.value or ""))
            reconciliation_status.value = f"Canonical portfolio history exported to {destination}; quarantined rows excluded."
            reconciliation_status.color = theme.GREEN
        except Exception as exc:
            reconciliation_status.value = f"Portfolio export unavailable: {type(exc).__name__}: {exc}; no placeholder written."
            reconciliation_status.color = theme.RED
        page.update()

    async def cache_bulk_source(_event: ft.ControlEvent) -> None:
        try:
            files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["csv", "json", "jsonl", "parquet", "pq", "zip", "tar", "gz"], with_data=True)
        except Exception as exc:
            bulk_status.value = f"Bulk cache picker failed: {type(exc).__name__}; no data changed."
            bulk_status.color = theme.RED
            page.update()
            return
        if not files:
            bulk_status.value = "Bulk cache selection cancelled; no data changed."
            bulk_status.color = theme.MUTED
            page.update()
            return
        source = Path(files[0].path or files[0].name)
        label = "Rebuild local source cache"
        owns_activity = state.current_activity is None
        if owns_activity:
            state.begin_activity(label, "Validating cache source")
        else:
            state.update_activity("Validating cache source")
        try:
            result = ContentAddressedCache(ROOT).store_local_file(bulk_source_id.value or "local-bulk-source", source)
            bulk_status.value = f"Cached and checksum-verified {result.manifest.source_id}: {result.manifest.content_sha256[:16]}…; version {result.manifest.version}; raw object is immutable."
            bulk_status.color = theme.GREEN
            state.update_activity("Cache source promoted", completed_units=1, total_units=1)
            if owns_activity:
                cache = ContentAddressedCache(ROOT)
                state.finish_activity(
                    bulk_status.value,
                    output_path=cache._manifest_path(result.manifest.source_id),
                    label=label,
                )
        except Exception as exc:
            bulk_status.value = f"Bulk cache rejected: {type(exc).__name__}: {exc}; no partial object was promoted."
            bulk_status.color = theme.RED
            if owns_activity:
                state.fail_activity(label, exc)
        page.update()

    cache_report = bulk_cache_health(ROOT)
    cache_summary = f"Status={cache_report['status']} | objects={cache_report['object_count']} | manifests={cache_report['manifest_count']} | staged={cache_report['staged_file_count']} | promoted generations={cache_report['promoted_generation_count']} | network_calls=false"

    export_path = ft.TextField(label="Export destination", value=str(ROOT / "exports" / "scoreboard.csv"), expand=True, key="import-export.export-path")

    backup_path = ft.TextField(label="Backup archive destination", value=str(ROOT / "backups" / "cockpit-backup.zip"), expand=True, key="import-export.backup-path")
    restore_path = ft.TextField(label="Restore archive", expand=True, key="import-export.restore-path")
    restore_status = ft.Text("Restore validation preview required; nothing will be written.", color=theme.MUTED, selectable=True, key="import-export.restore-status")
    restore_commit_button = ft.OutlinedButton("Commit restore", key="import-export.restore-commit", disabled=True)
    restore_cancel_button = ft.TextButton("Cancel restore", key="import-export.restore-cancel", disabled=True)
    restore_preview = None

    def backup(_event: ft.ControlEvent) -> None:
        try:
            manifest = create_backup([DATA_DIR, CONFIG_DIR, ROOT / "pyproject.toml", ROOT / "CHANGELOG.md"], Path(backup_path.value or "backup.zip"))
            show(f"Backup created at {manifest.archive}; {len(manifest.checksums)} files; checksum manifest validated.", colour=theme.GREEN)
        except Exception as exc:
            show(f"Backup failed: {type(exc).__name__}: {exc}.", colour=theme.RED)

    def validate_restore_preview(_event: ft.ControlEvent) -> None:
        nonlocal restore_preview
        archive = Path(restore_path.value or "")
        restore_preview = validate_restore(archive)
        restore_commit_button.disabled = not restore_preview.valid
        restore_cancel_button.disabled = False
        restore_status.value = f"Restore preview {'valid' if restore_preview.valid else 'rejected'} for {archive}; destination {ROOT}; {len(restore_preview.entries)} entries; errors={'; '.join(restore_preview.errors) or 'none'}."
        restore_status.color = theme.GREEN if restore_preview.valid else theme.RED
        page.update()

    def commit_restore_preview(_event: ft.ControlEvent) -> None:
        nonlocal restore_preview
        if restore_preview is None or not restore_preview.valid:
            restore_status.value = "Restore commit blocked: validate a valid preview first."
            restore_status.color = theme.RED
            page.update()
            return
        result = commit_restore(restore_preview, ROOT)
        restore_status.value = f"Restore {'complete' if result.ok else 'failed'} at {result.destination}; {result.error or f'{result.restored} files'}."
        restore_status.color = theme.GREEN if result.ok else theme.RED
        if result.ok:
            restore_preview = None
            restore_commit_button.disabled = True
            restore_cancel_button.disabled = True
        page.update()

    def cancel_restore_preview(_event: ft.ControlEvent) -> None:
        nonlocal restore_preview
        restore_preview = None
        restore_commit_button.disabled = True
        restore_cancel_button.disabled = True
        restore_status.value = "Restore cancelled; no files changed."
        restore_status.color = theme.MUTED
        page.update()

    restore_commit_button.on_click = commit_restore_preview
    restore_cancel_button.on_click = cancel_restore_preview

    def _export_frame(category: str) -> pd.DataFrame | None:
        if category == "scoreboard":
            frame = getattr(state.snapshot, "scoreboard", None)
            if isinstance(frame, pd.DataFrame):
                return frame
            return pd.DataFrame([getattr(signal, "__dict__", {}) for signal in getattr(state.snapshot, "signals", ())])
        if category == "watchlist":
            scoreboard_path = DERIVED_DIR / "scoreboard.parquet"
            if scoreboard_path.exists():
                frame = load_simple_scoreboard(scoreboard_path)
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

    def export_category(category: str) -> None:
        label = f"Export {category.replace('_', ' ')}"
        owns_activity = state.current_activity is None
        if owns_activity:
            state.begin_activity(label, "Preparing export")
        else:
            state.update_activity("Preparing export")
        try:
            if category == "audit_packet":
                destination = state.export_audit_packet()
                state.last_export_path = destination
                message = f"Export complete: audit packet at {destination}."
            else:
                frame = _export_frame(category)
                destination = Path(export_path.value or ROOT / "exports" / f"{category}.csv") if category == "scoreboard" else ROOT / "exports" / f"{category}.csv"
                result = export_table(category, frame, destination)
                state.last_export_path = result.destination
                message = f"Export {'complete' if result.ok else 'unavailable'}: {result.destination}; {result.error or f'{result.rows} rows'}."
            result_ok = True
            result_error = None
            if category != "audit_packet":
                result_ok = bool(result.ok)
                result_error = result.error
            show(message, colour=theme.GREEN if result_ok else theme.RED)
            _record_export_terminal(
                state,
                label=label,
                message=message,
                destination=destination,
                ok=result_ok,
                error=result_error,
                owns_activity=owns_activity,
            )
        except Exception as exc:
            show(f"Export unavailable: {category}: {type(exc).__name__}: {exc}.", colour=theme.RED)
            if owns_activity:
                state.fail_activity(label, exc)

    def export_scoreboard(_event: ft.ControlEvent) -> None:
        export_category("scoreboard")

    return ft.Column(
        [
            panel(ft.Column([section_header("Import and Export Centre", "Preview and validate local evidence before any commit. All actions remain non-executable."), ft.Text("execution_allowed=false", color=theme.AMBER), ft.Row([import_type, portfolio_source_system, portfolio_provider, portfolio_locale], wrap=True), ft.Row([path_field, ft.OutlinedButton("Choose and preview", key="import-export.import", icon=ft.Icons.UPLOAD_FILE, on_click=open_import)], wrap=True), ft.Row([commit_button], wrap=True), preview_text, staging_report], spacing=10)),
            panel(ft.Column([section_header("Portfolio reconciliation", "Review identity candidates, apply checksum-bound mapping decisions, rebuild holdings and cash from zero, roll back a batch, or export the canonical local ledger."), ft.Row([mapping_source, mapping_canonical, mapping_reviewer, mapping_reason, ft.OutlinedButton("Apply identity mapping", key="import-export.portfolio-apply-mapping", on_click=apply_portfolio_mapping)], wrap=True), ft.Row([ft.OutlinedButton("Reconcile portfolio history", key="import-export.portfolio-reconcile", on_click=reconcile_portfolio), rollback_batch, rollback_reason, ft.OutlinedButton("Rollback batch", key="import-export.portfolio-rollback", on_click=rollback_portfolio)], wrap=True), ft.Row([portfolio_export_path, ft.OutlinedButton("Export canonical portfolio", key="import-export.portfolio-export", icon=ft.Icons.DOWNLOAD, on_click=export_portfolio)], wrap=True), reconciliation_status], spacing=10)),
            panel(ft.Column([section_header("Bulk source cache", "Cache a local bulk snapshot by content hash before parsing. Interrupted, changed or invalid sources remain outside the promoted generation."), ft.Row([bulk_source_id, ft.OutlinedButton("Cache local source", key="import-export.bulk-cache", icon=ft.Icons.FOLDER_COPY, on_click=cache_bulk_source)], wrap=True), ft.Text(cache_summary, color=theme.MUTED, size=11, selectable=True), bulk_status], spacing=10)),
            panel(ft.Column([section_header("Exports", "Scoreboard, audit packet, watchlist, journals, plan/issues snapshot and analytical tables use explicit local paths."), ft.Row([export_path, ft.OutlinedButton("Export scoreboard", key="import-export.export-scoreboard", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("scoreboard")), ft.OutlinedButton("Export audit packet", key="import-export.export-audit-packet", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("audit_packet")), ft.OutlinedButton("Export watchlist", key="import-export.export-watchlist", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("watchlist")), ft.OutlinedButton("Export paper-trade journal", key="import-export.export-paper-trade-journal", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("paper_trade_journal")), ft.OutlinedButton("Export decision journal", key="import-export.export-decision-journal", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("decision_journal")), ft.OutlinedButton("Export plan/issues snapshot", key="import-export.export-plan-issues-snapshot", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("plan_issues_snapshot"))], wrap=True), ft.Text("Export status and destination are shown above; unavailable sources are reported without writing placeholders.", color=theme.MUTED, selectable=True)], spacing=10)),
            panel(ft.Column([section_header("Backup and Restore", "Validate a restore preview before an explicit commit; cancel leaves the destination unchanged."), ft.Row([backup_path, ft.OutlinedButton("Create backup", key="import-export.create-backup", icon=ft.Icons.ARCHIVE, on_click=backup)], wrap=True), ft.Row([restore_path, ft.OutlinedButton("Validate restore preview", key="import-export.restore-validate", icon=ft.Icons.RESTORE, on_click=validate_restore_preview), restore_commit_button, restore_cancel_button], wrap=True), restore_status], spacing=10)),
            ft.Text(state.last_message, color=theme.MUTED, selectable=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
