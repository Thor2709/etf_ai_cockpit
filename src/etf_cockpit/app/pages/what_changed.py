from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.data.run_changes import REQUIRED_CHANGE_DIMENSIONS, compare_runs


def what_changed_page(_page: ft.Page, _state: AppState) -> ft.Control:
    path = DERIVED_DIR / "score_history.parquet"
    try:
        history = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    except Exception:
        history = pd.DataFrame()
    report = None
    changes = []
    current = previous = None
    if not history.empty and "run_id" in history.columns:
        if "run_completed_at" in history.columns:
            history = history.sort_values(["run_completed_at", "run_id"], kind="stable")
        runs = list(dict.fromkeys(history["run_id"].astype(str).tolist()))
        current = runs[-1]
        previous = runs[-2] if len(runs) > 1 else None
        report = compare_runs(history, current, previous)
        changes = list(report.changes)

    search_field = ft.TextField(
        label="Search instrument",
        key="what-changed.filter.instrument",
        hint_text="ID or name",
        dense=True,
        width=220,
    )
    dimension_filter = ft.Dropdown(
        label="Filter dimension",
        key="what-changed.filter.dimension",
        value="all",
        options=[ft.dropdown.Option("all", "All dimensions")] + [ft.dropdown.Option(dimension, dimension.replace("_", " ").title()) for dimension in REQUIRED_CHANGE_DIMENSIONS],
        dense=True,
        width=210,
    )
    changed_only = ft.Checkbox(label="Changed only", key="what-changed.filter.changed-only", value=False)
    table_container = ft.Column(scroll=ft.ScrollMode.AUTO)

    def _changed(change, dimension: str) -> bool:
        if dimension == "all":
            return bool(change.summary and change.summary != "No tracked changes.")
        if dimension == "score":
            return change.score_delta not in (None, 0)
        if dimension == "rank":
            return change.score_rank_delta not in (None, 0)
        return bool(change.dimension_changes.get(dimension, False))

    def _render_rows(_event: ft.ControlEvent | None = None) -> None:
        query = (search_field.value or "").strip().casefold()
        dimension = dimension_filter.value or "all"
        visible = []
        for change in changes:
            if query and query not in change.instrument_id.casefold():
                continue
            if changed_only.value and not _changed(change, "all"):
                continue
            if dimension != "all" and not _changed(change, dimension):
                continue
            visible.append(change)
        rows = []
        for change in visible:
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(change.instrument_id, color=theme.TEXT)),
                        ft.DataCell(ft.Text("N/A" if change.score_delta is None else f"{change.score_delta:+.1f}", color=theme.CYAN)),
                        ft.DataCell(ft.Text("N/A" if change.score_rank_delta is None else f"{change.score_rank_delta:+.0f}", color=theme.CYAN)),
                        ft.DataCell(ft.Text("yes" if change.warnings_changed else "no", color=theme.AMBER if change.warnings_changed else theme.GREEN)),
                        ft.DataCell(ft.Text("yes" if change.freshness_changed else "no", color=theme.AMBER if change.freshness_changed else theme.GREEN)),
                        ft.DataCell(ft.Text("yes" if change.model_availability_changed else "no", color=theme.AMBER if change.model_availability_changed else theme.GREEN)),
                        ft.DataCell(ft.Text("yes" if change.forecast_changed else "no", color=theme.AMBER if change.forecast_changed else theme.GREEN)),
                        ft.DataCell(ft.Text("yes" if change.news_inventory_changed else "no", color=theme.AMBER if change.news_inventory_changed else theme.GREEN)),
                        ft.DataCell(ft.Text("yes" if change.backtest_trust_changed else "no", color=theme.AMBER if change.backtest_trust_changed else theme.GREEN)),
                        ft.DataCell(ft.Text("yes" if change.portfolio_risk_changed else "no", color=theme.AMBER if change.portfolio_risk_changed else theme.GREEN)),
                        ft.DataCell(ft.Text(change.current_action or "unavailable", color=theme.MUTED)),
                        ft.DataCell(ft.Text(change.summary, color=theme.MUTED, max_lines=3)),
                    ]
                )
            )
        headers = (
            "Instrument", "Score delta", "Rank delta", "Warnings", "Freshness", "Model availability",
            "Forecasts", "News inventory", "Backtest trust", "Portfolio risk", "Current action", "Summary",
        )
        table_container.controls = [
            ft.Text(f"{len(visible)} instrument(s) shown", color=theme.MUTED, size=11),
            ft.DataTable(columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in headers], rows=rows),
        ] if visible else [ft.Text("No instruments match the selected filters.", color=theme.MUTED)]
        try:
            if _page is not None:
                _page.update()
        except Exception:
            pass

    search_field.on_change = _render_rows
    dimension_filter.on_select = _render_rows
    changed_only.on_change = _render_rows
    if report is None:
        digest = ft.Text("No completed score runs are available yet. Run the deterministic scoring workflow twice to compare changes.", color=theme.MUTED)
    else:
        digest = ft.Column(
            [
                ft.Text(f"Current run: {current} | Previous: {previous or 'none'}", color=theme.MUTED),
                ft.Text(report.summary, color=theme.MUTED),
            ],
            spacing=4,
        )
    _render_rows()
    body = ft.Column([digest, ft.Row([search_field, dimension_filter, changed_only], wrap=True), table_container], spacing=10)
    return ft.Column([panel(ft.Column([section_header("What Changed", "Historical score and warning differences are informational only and cannot override current evidence gates."), body], spacing=10))], expand=True, scroll=ft.ScrollMode.AUTO)
