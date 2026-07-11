from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH, _safe_read_parquet, IDENTITY_COLUMNS


def universe_manager_page(_page: ft.Page, _state: AppState) -> ft.Control:
    frame = _safe_read_parquet(IDENTITY_PATH, IDENTITY_COLUMNS)
    rows = []
    for row in frame.head(60).fillna("").itertuples(index=False, name=None):
        values = dict(zip(frame.columns, row))
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(values.get("instrument_id", "")), color=theme.TEXT)),
                    ft.DataCell(ft.Text(str(values.get("source_group", "")), color=theme.MUTED)),
                    ft.DataCell(ft.Text(str(values.get("asset_class", "")), color=theme.MUTED)),
                    ft.DataCell(ft.Text(str(values.get("isin_status", "")), color=theme.AMBER if values.get("isin_status") != "verified" else theme.GREEN)),
                    ft.DataCell(ft.Text(str(values.get("yahoo_symbol", "")), color=theme.MUTED)),
                ]
            )
        )
    return ft.Column(
        [
            panel(ft.Column([section_header("Universe and watchlists", "Primary, Secondary and Sparebanken groups are read from the canonical identity store. Changes require validated revision-protected saves."), ft.Text(f"Source: {IDENTITY_PATH}", color=theme.MUTED, selectable=True)], spacing=8)),
            panel(ft.DataTable(columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT)) for label in ("Instrument", "Group", "Asset", "ISIN status", "Yahoo symbol")], rows=rows)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
