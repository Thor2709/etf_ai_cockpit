from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState


def import_export_page(page: ft.Page, state: AppState) -> ft.Control:
    picker = ft.FilePicker(key="import-export.import.file-picker")
    try:
        page.services.append(picker)
    except Exception:
        try:
            page.overlay.append(picker)
        except Exception:
            pass

    async def open_import(_event: ft.ControlEvent) -> None:
        try:
            files = await picker.pick_files(file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["csv", "xlsx", "xls", "json", "jsonl", "parquet", "pq"], with_data=True)
        except Exception as exc:
            state.last_message = f"Local file picker unavailable: {type(exc).__name__}. No data changed."
            page.update()
            return
        if not files:
            state.last_message = "Local import cancelled; no data changed."
        else:
            selected = files[0]
            state.last_message = f"Selected local file {selected.name}; validation must complete before commit."
        page.update()

    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Import and Export", "Imports are previewed and schema-validated before commit. Exports show a concrete local output path."),
                        ft.Text("Supported local datasets: prices, FX, ETF factsheets, holdings, notes and provider evidence.", color=theme.MUTED),
                        ft.Text("Current last export: " + (str(state.last_export_path) if state.last_export_path else "none"), color=theme.MUTED, selectable=True),
                        ft.Row(
                            [
                                ft.OutlinedButton("Open local import", key="import-export.import", icon=ft.Icons.UPLOAD_FILE, on_click=open_import),
                                ft.OutlinedButton("Backup and Restore", key="import-export.backup-restore", icon=ft.Icons.ARCHIVE, on_click=lambda _event: _set_message(state, "Backup/restore requires an explicit local destination and checksum validation.")),
                            ],
                            wrap=True,
                        ),
                        ft.Text(state.last_message, color=theme.MUTED),
                    ],
                    spacing=10,
                )
            )
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _set_message(state: AppState, message: str) -> None:
    state.last_message = message
