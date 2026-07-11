from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.health import DataHealthStatus, build_data_health, export_data_health


def data_health_page(page: ft.Page, state: AppState) -> ft.Control:
    report = build_data_health(state.snapshot.config, ROOT, as_of_date=state.snapshot.data_report.as_of_date)
    rows: list[ft.Control] = []
    for row in report.rows:
        colour = theme.GREEN if row.status is DataHealthStatus.HEALTHY else theme.AMBER if row.status in {DataHealthStatus.STALE, DataHealthStatus.UNAVAILABLE, DataHealthStatus.MISSING} else theme.RED
        rows.append(
            ft.Container(
                padding=12,
                border=border_all(1, theme.BORDER),
                border_radius=8,
                bgcolor=theme.SURFACE,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(row.dataset, color=theme.TEXT, weight=ft.FontWeight.BOLD, size=15),
                                evidence_chip("Status", row.status.value, colour),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            wrap=True,
                        ),
                        ft.Row(
                            [
                                _health_field("Path", row.path, width=360, selectable=True),
                                _health_field("Rows", str(row.row_count)),
                                _health_field("As of", row.as_of or "N/A"),
                                _health_field("Freshness", row.freshness),
                                _health_field("Provider", row.provider or "N/A"),
                                _health_field("Checksum", (row.checksum or "N/A")[:16], selectable=True),
                                _health_field("Last success", row.last_success or "N/A"),
                                _health_field("Last failure", row.last_failure or "N/A"),
                                _health_field("Warnings", "; ".join(row.warnings) or "none", width=300, selectable=True),
                            ],
                            spacing=14,
                            run_spacing=10,
                            wrap=True,
                        ),
                    ],
                    spacing=10,
                ),
            )
        )

    def export(_event: ft.ControlEvent) -> None:
        destination = ROOT / "data" / "derived" / "data_health.csv"
        export_data_health(report, destination)
        state.last_message = f"Data health exported: {destination}"
        from etf_cockpit.app.router import render_shell

        render_shell(page, state, "/data-health")

    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Data Health", "Every configured store is classified as healthy, stale, missing, corrupt, schema-mismatched or unavailable. Missing data is never inferred."),
                        ft.Row(
                            [
                                ft.OutlinedButton("Export health CSV", key="data-health.export", icon=ft.Icons.DOWNLOAD, on_click=export),
                                ft.Text(f"Created {report.created_at} | as of {report.as_of_date}", color=theme.MUTED),
                            ],
                            wrap=True,
                        ),
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Dataset inventory", "Each store exposes its path, status, freshness, provenance checksum and most recent success or failure without hidden columns."),
                        ft.Row(
                            [
                                ft.Text("Dataset", color=theme.MUTED, size=11, weight=ft.FontWeight.BOLD),
                                ft.Text("Status", color=theme.MUTED, size=11, weight=ft.FontWeight.BOLD),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        *rows,
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _health_field(label: str, value: str, *, width: int = 170, selectable: bool = False) -> ft.Control:
    return ft.Container(
        width=width,
        content=ft.Column(
            [
                ft.Text(label, color=theme.MUTED, size=10, weight=ft.FontWeight.BOLD),
                ft.Text(value, color=theme.TEXT, size=11, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS, selectable=selectable),
            ],
            spacing=2,
        ),
    )
