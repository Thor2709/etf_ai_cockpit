from __future__ import annotations

from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
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
)


def import_export_page(page: ft.Page, state: AppState) -> ft.Control:
    picker = ft.FilePicker(key="import-export.import.file-picker")
    try:
        page.services.append(picker)
    except Exception:
        try:
            page.overlay.append(picker)
        except Exception:
            pass
    import_type = ft.Dropdown(label="Import type", value="broker", options=[ft.dropdown.Option(value, value.replace("_", " ").title()) for value in ("broker", "candidate", "manual_notes", "etf_holdings", "news", "events", "rss_list")], width=190)
    path_field = ft.TextField(label="Local source path", hint_text="Choose a CSV, JSON, Parquet or RSS file", expand=True, key="import-export.import-path")
    preview_text = ft.Text("Preview required before commit.", color=theme.MUTED, selectable=True, key="import-export.preview-status")
    commit_button = ft.OutlinedButton("Commit validated import", key="import-export.commit", disabled=True)
    selected_preview: ImportPreview | None = None
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
        selected_preview = validate_import(import_type.value or "broker", source)
        commit_button.disabled = not selected_preview.valid
        colour = theme.GREEN if selected_preview.valid else theme.RED
        show(f"Preview {'valid' if selected_preview.valid else 'rejected'}: {selected_preview.rows} rows; source {source}; errors={'; '.join(selected_preview.errors) or 'none'}.", colour=colour)

    def commit(_event: ft.ControlEvent) -> None:
        if selected_preview is None or not selected_preview.valid:
            show("Commit blocked: run a valid preview first.", colour=theme.RED)
            return
        try:
            service = ImportService(ROOT)
            service.register(selected_preview)
            result = service.commit(selected_preview.preview_id)
            show(f"Import committed: {result.rows} rows at {result.destination} (execution_allowed=false).", colour=theme.GREEN)
        except Exception as exc:
            show(f"Import failed: {type(exc).__name__}: {exc}; previous clean state preserved.", colour=theme.RED)

    commit_button.on_click = commit

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
        try:
            result = ContentAddressedCache(ROOT).store_local_file(bulk_source_id.value or "local-bulk-source", source)
            bulk_status.value = f"Cached and checksum-verified {result.manifest.source_id}: {result.manifest.content_sha256[:16]}…; version {result.manifest.version}; raw object is immutable."
            bulk_status.color = theme.GREEN
        except Exception as exc:
            bulk_status.value = f"Bulk cache rejected: {type(exc).__name__}: {exc}; no partial object was promoted."
            bulk_status.color = theme.RED
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
        restore_status.value = (
            f"Restore preview {'valid' if restore_preview.valid else 'rejected'} for {archive}; destination {ROOT}; "
            f"{len(restore_preview.entries)} entries; errors={'; '.join(restore_preview.errors) or 'none'}."
        )
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
                frame = pd.read_parquet(scoreboard_path)
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
        if category == "audit_packet":
            try:
                destination = state.export_audit_packet()
                state.last_export_path = destination
                show(f"Export complete: audit packet at {destination}.", colour=theme.GREEN)
            except Exception as exc:
                show(f"Export unavailable: audit packet: {type(exc).__name__}: {exc}.", colour=theme.RED)
            return
        frame = _export_frame(category)
        destination = Path(export_path.value or ROOT / "exports" / f"{category}.csv") if category == "scoreboard" else ROOT / "exports" / f"{category}.csv"
        result = export_table(category, frame, destination)
        state.last_export_path = result.destination
        show(f"Export {'complete' if result.ok else 'unavailable'}: {result.destination}; {result.error or f'{result.rows} rows'}.", colour=theme.GREEN if result.ok else theme.RED)

    def export_scoreboard(_event: ft.ControlEvent) -> None:
        export_category("scoreboard")

    return ft.Column(
        [
            panel(ft.Column([section_header("Import and Export Centre", "Preview and validate local evidence before any commit. All actions remain non-executable."), ft.Text("execution_allowed=false", color=theme.AMBER), ft.Row([import_type, path_field, ft.OutlinedButton("Choose and preview", key="import-export.import", icon=ft.Icons.UPLOAD_FILE, on_click=open_import)], wrap=True), ft.Row([commit_button], wrap=True), preview_text], spacing=10)),
            panel(ft.Column([section_header("Bulk source cache", "Cache a local bulk snapshot by content hash before parsing. Interrupted, changed or invalid sources remain outside the promoted generation."), ft.Row([bulk_source_id, ft.OutlinedButton("Cache local source", key="import-export.bulk-cache", icon=ft.Icons.FOLDER_COPY, on_click=cache_bulk_source)], wrap=True), ft.Text(cache_summary, color=theme.MUTED, size=11, selectable=True), bulk_status], spacing=10)),
            panel(ft.Column([section_header("Exports", "Scoreboard, audit packet, watchlist, journals, plan/issues snapshot and analytical tables use explicit local paths."), ft.Row([export_path, ft.OutlinedButton("Export scoreboard", key="import-export.export-scoreboard", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("scoreboard")), ft.OutlinedButton("Export audit packet", key="import-export.export-audit-packet", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("audit_packet")), ft.OutlinedButton("Export watchlist", key="import-export.export-watchlist", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("watchlist")), ft.OutlinedButton("Export paper-trade journal", key="import-export.export-paper-trade-journal", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("paper_trade_journal")), ft.OutlinedButton("Export decision journal", key="import-export.export-decision-journal", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("decision_journal")), ft.OutlinedButton("Export plan/issues snapshot", key="import-export.export-plan-issues-snapshot", icon=ft.Icons.DOWNLOAD, on_click=lambda _event: export_category("plan_issues_snapshot"))], wrap=True), ft.Text("Export status and destination are shown above; unavailable sources are reported without writing placeholders.", color=theme.MUTED, selectable=True)], spacing=10)),
            panel(ft.Column([section_header("Backup and Restore", "Validate a restore preview before an explicit commit; cancel leaves the destination unchanged."), ft.Row([backup_path, ft.OutlinedButton("Create backup", key="import-export.create-backup", icon=ft.Icons.ARCHIVE, on_click=backup)], wrap=True), ft.Row([restore_path, ft.OutlinedButton("Validate restore preview", key="import-export.restore-validate", icon=ft.Icons.RESTORE, on_click=validate_restore_preview), restore_commit_button, restore_cancel_button], wrap=True), restore_status], spacing=10)),
            ft.Text(state.last_message, color=theme.MUTED, selectable=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
