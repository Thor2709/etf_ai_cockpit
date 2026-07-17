from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.ui_facade import DataHealthReport, DataHealthRow, DataHealthStatus, build_data_health, bulk_cache_health, export_data_health, filter_data_health_rows


def data_health_page(page: ft.Page, state: AppState) -> ft.Control:
    report = build_data_health(state.snapshot.config, ROOT, as_of_date=state.snapshot.data_report.as_of_date)
    cache_report = bulk_cache_health(ROOT)
    visible_rows = list(report.rows)

    def row_controls(row: DataHealthRow) -> ft.Control:
        colour = theme.GREEN if row.status is DataHealthStatus.HEALTHY else theme.AMBER if row.status in {DataHealthStatus.STALE, DataHealthStatus.UNAVAILABLE, DataHealthStatus.MISSING} else theme.RED
        return ft.Container(
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
                    ft.Row(
                        [_action_link(page, state, row.dataset, link.label, link.route) for link in row.links],
                        spacing=6,
                        wrap=True,
                    ),
                ],
                spacing=10,
            ),
        )

    inventory_rows = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)

    def redraw(_event: ft.ControlEvent | None = None) -> None:
        nonlocal visible_rows
        visible_rows = list(
            filter_data_health_rows(
                report.rows,
                status=status_filter.value,
                dataset=dataset_filter.value,
                provider=provider_filter.value,
            )
        )
        inventory_rows.controls = [row_controls(row) for row in visible_rows]
        try:
            page.update()
        except Exception:
            pass

    status_filter = ft.Dropdown(
        label="Filter status",
        key="data-health.filter.status",
        value="All",
        options=[ft.dropdown.Option("All")] + [ft.dropdown.Option(status.value) for status in DataHealthStatus],
        on_select=redraw,
        width=180,
    )
    dataset_filter = ft.Dropdown(
        label="Filter dataset",
        key="data-health.filter.dataset",
        value="All",
        options=[ft.dropdown.Option("All")] + [ft.dropdown.Option(row.dataset) for row in report.rows],
        on_select=redraw,
        width=190,
    )
    provider_filter = ft.Dropdown(
        label="Filter provider",
        key="data-health.filter.provider",
        value="All",
        options=[ft.dropdown.Option("All")] + [ft.dropdown.Option(provider) for provider in sorted({row.provider for row in report.rows if row.provider})],
        on_select=redraw,
        width=190,
    )
    redraw()

    def export(_event: ft.ControlEvent) -> None:
        destination = ROOT / "data" / "derived" / "data_health.csv"
        export_data_health(DataHealthReport(report.created_at, report.as_of_date, tuple(visible_rows)), destination)
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
                        section_header("Bulk source cache", "Raw bulk sources are immutable and content-addressed. Only validated staged generations may be promoted into analysis."),
                        ft.Text(f"Status={cache_report['status']} | objects={cache_report['object_count']} | manifests={cache_report['manifest_count']} | staged={cache_report['staged_file_count']} | promoted generations={cache_report['promoted_generation_count']} | network_calls=false", color=theme.MUTED, selectable=True),
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Dataset inventory", "Each store exposes its path, status, freshness, provenance checksum and most recent success or failure without hidden columns."),
                        ft.Text("Filters update the inventory and export the visible rows only.", color=theme.MUTED, size=11),
                        ft.Row(
                            [
                                ft.Text("Filter status", color=theme.MUTED, size=11),
                                status_filter,
                                ft.Text("Filter dataset", color=theme.MUTED, size=11),
                                dataset_filter,
                                ft.Text("Filter provider", color=theme.MUTED, size=11),
                                provider_filter,
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        ft.Row(
                            [
                                ft.Text("Dataset", color=theme.MUTED, size=11, weight=ft.FontWeight.BOLD),
                                ft.Text("Status", color=theme.MUTED, size=11, weight=ft.FontWeight.BOLD),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        inventory_rows,
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


def _action_link(page: ft.Page, state: AppState, dataset: str, label: str, route: str) -> ft.Control:
    def navigate(_event: ft.ControlEvent) -> None:
        from etf_cockpit.app.router import navigate_to

        navigate_to(page, state, route)

    key = {
        "/providers": "navigation.providers",
        "/filings": "navigation.filings",
        "/etf": "navigation.etf",
        "/errors": "navigation.errors",
    }.get(route, "data-health.export")
    return ft.TextButton(
        content=ft.Text(label, color=theme.CYAN, size=11),
        key=key,
        on_click=navigate,
        tooltip=f"Open {label}",
    )
