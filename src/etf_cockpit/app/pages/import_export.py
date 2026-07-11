from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState


def import_export_page(_page: ft.Page, state: AppState) -> ft.Control:
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
                                ft.OutlinedButton("Open local import", key="import-export.import", icon=ft.Icons.UPLOAD_FILE, on_click=lambda _event: _set_message(state, "Choose a local file; validation must complete before commit.")),
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
