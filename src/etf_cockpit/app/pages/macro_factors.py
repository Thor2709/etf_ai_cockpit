"""Local Macro and Factors workspace."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import MacroWarehouse, MacroWarehouseError
from etf_cockpit.core.paths import ROOT


def macro_factors_page(page: ft.Page | None, state: AppState) -> ft.Control:
    del page, state
    warehouse = MacroWarehouse()
    try:
        summary = warehouse.summary(root=ROOT)
        rows = warehouse.observations(root=ROOT)
        error_text = ""
    except (MacroWarehouseError, OSError) as exc:
        summary = {"status": "unavailable", "row_count": 0}
        rows = []
        error_text = f"Manual review required: local macro warehouse could not be read ({type(exc).__name__})."

    status = str(summary.get("status", "unavailable"))
    status_colour = theme.GREEN if status == "available" else theme.AMBER
    if error_text:
        status_text = error_text
    elif status == "available":
        status_text = (
            f"Available: {summary.get('row_count', 0)} selected observation(s) across "
            f"{len(summary.get('dataset_ids', []))} dataset(s). "
            f"Missing country/currency context: {summary.get('missing_country_or_currency_count', 0)}."
        )
    else:
        status_text = f"Unavailable: {summary.get('reason', 'no local snapshot is available')}."

    entries = [
        ft.Text(
            f"{row.dataset_id} | {row.series_id} | {row.period_start} | {row.value:g} {row.unit} | "
            f"available={row.available_at} | context={row.availability_status}",
            color=theme.TEXT,
            size=11,
            selectable=True,
        )
        for row in sorted(rows, key=lambda item: (item.dataset_id, item.period_start, item.series_id))[-24:]
    ]
    if not entries:
        entries = [ft.Text("No local macro/factor observations have been ingested yet.", color=theme.MUTED, selectable=True)]

    return ft.Column(
        [
            section_header(
                "Macro and Factors",
                "Local, versioned macro, factor, risk-free and benchmark snapshots; no remote fetch or execution authority.",
            ),
            panel(
                ft.Column(
                    [
                        ft.Text(status_text, color=status_colour, selectable=True),
                        ft.Text(
                            "Decision-time vintages select only observations whose available_at is on or before the decision time. "
                            "Revisions remain append-only and transformations retain source observation IDs.",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                        ft.Text("Execution allowed: false", color=theme.AMBER, selectable=True),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        ft.Text("Latest local observations", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        ft.Column(entries, spacing=6, scroll=ft.ScrollMode.AUTO),
                    ],
                    spacing=8,
                ),
                expand=True,
            ),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["macro_factors_page"]
