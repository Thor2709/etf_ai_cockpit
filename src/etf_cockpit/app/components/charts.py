from __future__ import annotations

from dataclasses import dataclass

import flet as ft
import pandas as pd

from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.theme import AMBER, BORDER, CYAN, GREEN, MUTED, RED, SURFACE_2, TEXT


@dataclass(frozen=True)
class ChartDescriptor:
    label: str
    export_table_id: str
    control: ft.Control
    available: bool
    data: dict[str, tuple[object, ...]]


def history_chart(frame: pd.DataFrame | None, *, title: str = "Price history") -> ChartDescriptor:
    available = isinstance(frame, pd.DataFrame) and not frame.empty
    label = title if available else f"{title} (unavailable)"
    data = _series_data(frame, ("date", "adjusted_close", "etf_id", "instrument_id")) if available else {}
    detail = f"{title}: {len(frame)} rows; series={', '.join(data)}" if available else f"{title}: unavailable; import dated adjusted prices first"
    control = ft.Container(
        content=ft.Column(
            [
                ft.Text(detail, color=TEXT if available else MUTED, selectable=True),
                _series_table(frame, ("date", "adjusted_close", "etf_id", "instrument_id")) if available else ft.Text("Recent values unavailable.", color=MUTED, selectable=True),
            ],
            spacing=6,
        ),
        padding=10,
        border=border_all(1, BORDER),
    )
    return ChartDescriptor(label, "price_history", control, available, data)


def equity_drawdown_chart(frame: pd.DataFrame | None) -> ChartDescriptor:
    available = isinstance(frame, pd.DataFrame) and not frame.empty and {"equity", "drawdown"}.issubset(frame.columns)
    data = _series_data(frame, ("date", "equity", "drawdown")) if available else {}
    control = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    f"Backtest equity and drawdown: {len(frame)} rows; series=equity, drawdown" if available else "Backtest equity and drawdown: unavailable",
                    color=TEXT if available else MUTED,
                    selectable=True,
                ),
                _series_table(frame, ("date", "equity", "drawdown")) if available else ft.Text("Recent values unavailable.", color=MUTED, selectable=True),
            ],
            spacing=6,
        ),
        padding=10,
        border=border_all(1, BORDER),
    )
    return ChartDescriptor("Backtest equity and drawdown", "backtest_equity_drawdown", control, available, data)


def _series_data(frame: pd.DataFrame | None, columns: tuple[str, ...]) -> dict[str, tuple[object, ...]]:
    if not isinstance(frame, pd.DataFrame):
        return {}
    return {column: tuple(frame[column].tolist()) for column in columns if column in frame.columns}


def _series_table(frame: pd.DataFrame, columns: tuple[str, ...]) -> ft.DataTable:
    """Render recent chart values as an observable, text-first Flet table."""

    available_columns = [column for column in columns if column in frame.columns]
    recent = frame.loc[:, available_columns].tail(12)
    rows = [
        ft.DataRow(
            cells=[ft.DataCell(ft.Text("" if pd.isna(value) else str(value), selectable=True, size=11)) for value in row]
        )
        for row in recent.itertuples(index=False, name=None)
    ]
    return ft.DataTable(
        columns=[ft.DataColumn(ft.Text(column, color=TEXT, size=11)) for column in available_columns],
        rows=rows,
        data_row_min_height=28,
        data_row_max_height=40,
        column_spacing=12,
    )


def drift_bar(current: float, target: float, soft_band: float, hard_band: float, width: int = 180) -> ft.Column:
    drift = current - target
    colour = GREEN if abs(drift) <= soft_band else AMBER if abs(drift) <= hard_band else RED
    fill_width = max(4, min(width, int(width * min(abs(drift) / max(hard_band, 0.001), 1.0))))
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(f"{current:.1%}", size=11, color=TEXT),
                    ft.Text(f"target {target:.1%}", size=11, color=MUTED),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Container(
                content=ft.Container(width=fill_width, height=6, bgcolor=colour, border_radius=4),
                width=width,
                height=6,
                bgcolor=SURFACE_2,
                border_radius=4,
                border=border_all(1, BORDER),
            ),
        ],
        spacing=4,
    )


def score_bar(value: float, width: int = 90) -> ft.Container:
    colour = GREEN if value > 0.2 else RED if value < -0.2 else AMBER
    fill_width = max(3, int(width * min(abs(value), 1.0)))
    alignment = ft.Alignment(x=-1, y=0) if value >= 0 else ft.Alignment(x=1, y=0)
    return ft.Container(
        content=ft.Container(width=fill_width, height=7, bgcolor=colour, border_radius=4),
        width=width,
        height=7,
        bgcolor=SURFACE_2,
        border_radius=4,
        alignment=alignment,
    )


def score_meter(value: float, width: int = 132) -> ft.Row:
    colour = GREEN if value > 0.25 else RED if value < -0.25 else AMBER
    label = f"{value:+.2f}"
    return ft.Row(
        [
            ft.Container(
                content=ft.Container(
                    width=max(4, int(width * min(abs(value), 1.0))),
                    height=8,
                    bgcolor=colour,
                    border_radius=4,
                ),
                width=width,
                height=8,
                bgcolor=SURFACE_2,
                border_radius=4,
                alignment=ft.Alignment(x=-1, y=0) if value >= 0 else ft.Alignment(x=1, y=0),
                border=border_all(1, BORDER),
            ),
            ft.Text(label, color=TEXT if abs(value) >= 0.25 else MUTED, size=12, width=44),
        ],
        spacing=7,
        tight=True,
    )


def model_status_dot(available: bool) -> ft.Container:
    return ft.Container(width=8, height=8, bgcolor=CYAN if available else MUTED, border_radius=4)
