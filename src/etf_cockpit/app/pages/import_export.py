from __future__ import annotations

from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import CONFIG_DIR, DATA_DIR, ROOT
from etf_cockpit.data.backup_restore import commit_restore, create_backup, validate_restore
from etf_cockpit.data.export_tables import export_table
from etf_cockpit.data.import_export import ImportService, ImportPreview, validate_import


def import_export_page(page: ft.Page, state: AppState) -> ft.Control:
    picker = ft.FilePicker(key="import-export.import.file-picker")
    try:
        page.services.append(picker)
    except Exception:
        try:
            page.overlay.append(picker)
        except Exception:
            pass
    import_type = ft.Dropdown(label="Import type", value="broker", options=[ft.dropdown.Option(value, value.replace("_", " ").title()) for value in ("broker", "candidate", "manual_notes", "etf_holdings", "news")], width=190)
    path_field = ft.TextField(label="Local source path", hint_text="Choose a CSV, JSON, Parquet or RSS file", expand=True, key="import-export.import-path")
    preview_text = ft.Text("Preview required before commit.", color=theme.MUTED, selectable=True, key="import-export.preview-status")
    commit_button = ft.OutlinedButton("Commit validated import", key="import-export.commit", disabled=True)
    selected_preview: ImportPreview | None = None

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

    export_path = ft.TextField(label="Export destination", value=str(ROOT / "exports" / "scoreboard.csv"), expand=True, key="import-export.export-path")

    def export_scoreboard(_event: ft.ControlEvent) -> None:
        frame = getattr(state.snapshot, "scoreboard", None)
        if not isinstance(frame, pd.DataFrame):
            signals = getattr(state.snapshot, "signals", ())
            frame = pd.DataFrame([getattr(signal, "__dict__", {}) for signal in signals])
        result = export_table("scoreboard", frame, Path(export_path.value or "scoreboard.csv"))
        state.last_export_path = result.destination
        show(f"Export {'complete' if result.ok else 'failed'}: {result.destination}; {result.error or f'{result.rows} rows'}.", colour=theme.GREEN if result.ok else theme.RED)

    backup_path = ft.TextField(label="Backup archive destination", value=str(ROOT / "backups" / "cockpit-backup.zip"), expand=True, key="import-export.backup-path")
    restore_path = ft.TextField(label="Restore archive", expand=True, key="import-export.restore-path")

    def backup(_event: ft.ControlEvent) -> None:
        try:
            manifest = create_backup([DATA_DIR, CONFIG_DIR, ROOT / "version.json", ROOT / "CHANGELOG.md"], Path(backup_path.value or "backup.zip"))
            show(f"Backup created at {manifest.archive}; {len(manifest.checksums)} files; checksum manifest validated.", colour=theme.GREEN)
        except Exception as exc:
            show(f"Backup failed: {type(exc).__name__}: {exc}.", colour=theme.RED)

    def restore(_event: ft.ControlEvent) -> None:
        archive = Path(restore_path.value or "")
        preview = validate_restore(archive)
        if not preview.valid:
            show(f"Restore rejected before write: {'; '.join(preview.errors)}.", colour=theme.RED)
            return
        result = commit_restore(preview, ROOT)
        show(f"Restore {'complete' if result.ok else 'failed'} at {result.destination}; {result.error or f'{result.restored} files'}.", colour=theme.GREEN if result.ok else theme.RED)

    return ft.Column(
        [
            panel(ft.Column([section_header("Import and Export Centre", "Preview and validate local evidence before any commit. All actions remain non-executable."), ft.Text("execution_allowed=false", color=theme.AMBER), ft.Row([import_type, path_field, ft.OutlinedButton("Choose and preview", key="import-export.import", icon=ft.Icons.UPLOAD_FILE, on_click=open_import)], wrap=True), ft.Row([commit_button], wrap=True), preview_text], spacing=10)),
            panel(ft.Column([section_header("Exports", "Scoreboard, audit packet, watchlist, journals, plan/issues snapshot and analytical tables use explicit local paths."), ft.Row([export_path, ft.OutlinedButton("Export scoreboard CSV", key="import-export.export-scoreboard", icon=ft.Icons.DOWNLOAD, on_click=export_scoreboard)], wrap=True), ft.Text("Export status and destination are shown above; failures do not replace prior output.", color=theme.MUTED, selectable=True)], spacing=10)),
            panel(ft.Column([section_header("Backup and Restore", "Checksums and zip traversal are validated before atomic restore publication."), ft.Row([backup_path, ft.OutlinedButton("Create backup", key="import-export.create-backup", icon=ft.Icons.ARCHIVE, on_click=backup)], wrap=True), ft.Row([restore_path, ft.OutlinedButton("Validate and restore", key="import-export.restore", icon=ft.Icons.RESTORE, on_click=restore)], wrap=True)], spacing=10)),
            ft.Text(state.last_message, color=theme.MUTED, selectable=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
