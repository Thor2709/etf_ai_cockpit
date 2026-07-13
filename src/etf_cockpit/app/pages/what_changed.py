from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.data.run_changes import compare_runs


def what_changed_page(_page: ft.Page, _state: AppState) -> ft.Control:
    path = DERIVED_DIR / "score_history.parquet"
    try:
        history = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    except Exception:
        history = pd.DataFrame()
    if history.empty or "run_id" not in history.columns:
        body: ft.Control = ft.Text("No completed score runs are available yet. Run the deterministic scoring workflow twice to compare changes.", color=theme.MUTED)
    else:
        if "run_completed_at" in history.columns:
            history = history.sort_values(["run_completed_at", "run_id"], kind="stable")
        runs = list(dict.fromkeys(history["run_id"].astype(str).tolist()))
        current = runs[-1]
        previous = runs[-2] if len(runs) > 1 else None
        report = compare_runs(history, current, previous)
        rows = []
        for change in report.changes:
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
        body = ft.Column(
            [
                ft.Text(f"Current run: {current} | Previous: {previous or 'none'}", color=theme.MUTED),
                ft.Text(report.summary, color=theme.MUTED),
                ft.DataTable(columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in headers], rows=rows),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    return ft.Column([panel(ft.Column([section_header("What Changed", "Historical score and warning differences are informational only and cannot override current evidence gates."), body], spacing=10))], expand=True, scroll=ft.ScrollMode.AUTO)
