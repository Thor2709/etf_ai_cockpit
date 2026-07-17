from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.components.charts import drift_bar
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import allocation_frame, concentration_warnings, exposure_summary


def _exposure_table(title: str, frame) -> ft.Control:
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row.iloc[0]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(f"{row['current_weight']:.1%}", color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(f"{row['target_weight']:.1%}", color=theme.MUTED, size=12)),
            ]
        )
        for _, row in frame.iterrows()
    ]
    return panel(
        ft.Column(
            [
                ft.Text(title, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Bucket")), ft.DataColumn(ft.Text("Current")), ft.DataColumn(ft.Text("Target"))],
                    rows=rows,
                    data_row_min_height=34,
                    data_row_max_height=40,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def portfolio_page(_page: ft.Page, state: AppState) -> ft.Control:
    allocation = allocation_frame(state.snapshot.config, state.snapshot.holdings)
    rows = []
    for _, row in allocation.iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(row["etf_id"], color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(row["name"], color=theme.TEXT, size=12)),
                    ft.DataCell(drift_bar(row["current_weight"], row["target_weight"], row["soft_band"], row["hard_band"])),
                    ft.DataCell(ft.Text(f"{row['drift']:+.1%}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(row["drift_status"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(f"EUR {row['market_value_eur']:,.0f}", color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{row.get('unrealised_gain_pct', 0):+.1%}", color=theme.TEXT, size=12)),
                ]
            )
        )
    warnings = concentration_warnings(state.snapshot.config, allocation)
    total_value = state.snapshot.holdings["market_value_eur"].sum()
    cash_weight = max(0.0, 1.0 - state.snapshot.holdings["current_weight"].sum())
    return ft.Column(
        [
            ft.Row(
                [
                    panel(ft.Column([ft.Text("Portfolio value", color=theme.MUTED), ft.Text(f"EUR {total_value:,.0f}", color=theme.TEXT, size=22, weight=ft.FontWeight.BOLD)]), expand=True),
                    panel(ft.Column([ft.Text("Cash context", color=theme.MUTED), ft.Text(f"{cash_weight:.1%}", color=theme.TEXT, size=22, weight=ft.FontWeight.BOLD)]), expand=True),
                    panel(ft.Column([ft.Text("Allocation notes", color=theme.MUTED), ft.Text(str(len(warnings)), color=theme.TEXT, size=22, weight=ft.FontWeight.BOLD)]), expand=True),
                ],
                spacing=12,
            ),
            panel(
                ft.Column(
                    [
                        section_header("Portfolio context", "Weights and target drifts are shown for awareness. They do not override the instrument evidence score."),
                        ft.DataTable(
                            columns=[
                                ft.DataColumn(ft.Text("Instrument")),
                                ft.DataColumn(ft.Text("Name")),
                                ft.DataColumn(ft.Text("Weight")),
                                ft.DataColumn(ft.Text("Drift")),
                                ft.DataColumn(ft.Text("Context")),
                                ft.DataColumn(ft.Text("Value")),
                                ft.DataColumn(ft.Text("Unrealised")),
                            ],
                            rows=rows,
                            data_row_min_height=48,
                            data_row_max_height=58,
                        ),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
            ),
            ft.Row(
                [
                    _exposure_table("Sector context", exposure_summary(allocation, "sector")),
                    _exposure_table("Region context", exposure_summary(allocation, "region")),
                    _exposure_table("Currency context", exposure_summary(allocation, "currency")),
                ],
                spacing=12,
            ),
            panel(ft.Text("\n".join(warnings or ["No allocation context warnings."]), color=theme.MUTED, selectable=True)),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
