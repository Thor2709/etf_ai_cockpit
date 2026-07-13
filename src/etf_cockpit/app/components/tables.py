from __future__ import annotations

from dataclasses import dataclass

import flet as ft
import pandas as pd

from etf_cockpit.app.components.charts import score_meter
from etf_cockpit.app.theme import MUTED, TEXT
from etf_cockpit.core.types import SignalResult


@dataclass(frozen=True)
class AccessibleTable:
    """Table view metadata kept alongside the Flet control for text-first QA."""

    control: ft.DataTable
    table_id: str
    search_label: str
    sortable_columns: tuple[str, ...]
    status_text: str
    frame: pd.DataFrame
    search_callback: object
    sort_callback: object

    def search(self, query: str) -> pd.DataFrame:
        return self.search_callback(query)

    def sort(self, column: str, ascending: bool = True) -> pd.DataFrame:
        return self.sort_callback(column, ascending)


def accessible_table(
    frame: pd.DataFrame,
    *,
    table_id: str,
    searchable: bool = True,
    sortable: bool = True,
) -> AccessibleTable:
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    columns = tuple(str(column) for column in data.columns)
    rows = [
        ft.DataRow(cells=[ft.DataCell(ft.Text("" if pd.isna(value) else str(value), selectable=True)) for value in row])
        for row in data.itertuples(index=False, name=None)
    ]
    control = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(column, tooltip=f"Sort by {column}")) for column in columns],
        rows=rows,
        data_row_min_height=36,
        data_row_max_height=56,
        column_spacing=14,
    )

    def search_callback(query: str) -> pd.DataFrame:
        text = str(query or "").strip().casefold()
        if not text:
            return data.copy()
        mask = data.astype("string").apply(lambda column: column.str.casefold().str.contains(text, na=False)).any(axis=1)
        return data.loc[mask].copy()

    def sort_callback(column: str, ascending: bool = True) -> pd.DataFrame:
        if column not in columns or not sortable:
            return data.copy()
        return data.sort_values(column, ascending=bool(ascending), kind="stable", na_position="last").reset_index(drop=True)

    return AccessibleTable(
        control=control,
        table_id=str(table_id),
        search_label=f"Search {table_id}" if searchable else "",
        sortable_columns=columns if sortable else (),
        status_text=f"{len(data)} rows; status is shown as text",
        frame=data,
        search_callback=search_callback,
        sort_callback=sort_callback,
    )


def signals_table(signals: list[SignalResult], allocation_lookup: dict[str, dict[str, float]]) -> ft.DataTable:
    rows: list[ft.DataRow] = []
    for signal in sorted(signals, key=lambda item: (-item.total_score, item.action == "no_trade", -item.confidence)):
        metrics = signal.supporting_metrics
        model_text = f"Toto {signal.components.toto:+.2f} | TimesFM {signal.components.timesfm:+.2f}"
        context = ", ".join(signal.blocked_by or signal.warnings) or f"edge {float(metrics.get('expected_edge_bps') or 0):+.0f} bps"
        cost_warning = metrics.get("cost_stress_warning")
        if cost_warning:
            context = f"{context} | costs: {cost_warning}"
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(signal.etf_id, color=TEXT, size=12, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(score_meter(signal.total_score)),
                    ft.DataCell(ft.Text(model_text, color=TEXT, size=11)),
                    ft.DataCell(ft.Text(signal.reason_short, color=TEXT, size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Text(context, color=MUTED, size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)),
                ]
            )
        )
    return ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Instrument")),
            ft.DataColumn(ft.Text("Evidence score")),
            ft.DataColumn(ft.Text("Models")),
            ft.DataColumn(ft.Text("Explanation")),
            ft.DataColumn(ft.Text("Context")),
        ],
        rows=rows,
        column_spacing=14,
        data_row_min_height=56,
        data_row_max_height=68,
    )
