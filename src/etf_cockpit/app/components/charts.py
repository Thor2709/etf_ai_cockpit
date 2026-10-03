from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

import flet as ft
import pandas as pd
from flet import canvas as cv

from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.app.formatting import format_currency, format_percent
from etf_cockpit.app.theme import AMBER, BORDER, CYAN, GREEN, MUTED, RED, SURFACE_2, TEXT


@dataclass(frozen=True)
class ChartDescriptor:
    label: str
    export_table_id: str
    control: ft.Control
    available: bool
    data: dict[str, tuple[object, ...]]
    chart_type: Literal["line", "bar", "table"] = "table"


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


def portfolio_performance_chart(
    frame: pd.DataFrame | None,
    *,
    metric: str,
    unit: str,
    currency: str,
    status: str,
    reason: str | None,
    aggregation: str,
) -> ChartDescriptor:
    """Render saved portfolio series as an accessible, downloadable chart view."""
    available = (
        isinstance(frame, pd.DataFrame)
        and not frame.empty
        and "value" in frame.columns
        and pd.to_numeric(frame["value"], errors="coerce").notna().any()
    )
    data = _series_data(frame, ("period_start", "period_end", "value", "partial", "quality", "status", "source_snapshot"))
    title = f"Portfolio performance: {metric.replace('_', ' ')} ({aggregation})"
    chart_type: Literal["line", "bar"] = "bar" if aggregation in {"quarter", "year"} else "line"
    detail = f"{title}; status={status}; unit={unit}; currency={currency}."
    if reason:
        detail = f"{detail} {reason}"
    if available:
        display = frame.copy()
        display["formatted_value"] = [
            _format_performance_value(value, unit, currency) for value in display["value"]
        ]
        table = _series_table(display, ("period_start", "period_end", "formatted_value", "partial", "status"))
    else:
        table = ft.Text(reason or "Selected performance values are unavailable.", color=MUTED, selectable=True)
    controls: list[ft.Control] = [ft.Text(detail, color=TEXT if available else MUTED, selectable=True)]
    if available:
        legend = partial_marker_legend(frame)
        controls.extend(
            [
                _performance_canvas(frame, chart_type),
                *([ft.Text(legend, size=10, color=AMBER, selectable=True)] if legend else []),
                ft.Row(
                    [
                        ft.Text(str(frame.iloc[0].get("period_start", "")), size=10, color=MUTED),
                        ft.Text(str(frame.iloc[-1].get("period_end", "")), size=10, color=MUTED),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ]
        )
    controls.append(table)
    control = ft.Container(
        content=ft.Column(
            controls,
            spacing=6,
        ),
        padding=10,
        border=border_all(1, BORDER),
    )
    return ChartDescriptor(title, "portfolio_performance_series", control, bool(available), data, chart_type)


def _performance_canvas(frame: pd.DataFrame, chart_type: Literal["line", "bar"]) -> cv.Canvas:
    width, height, padding = 640.0, 220.0, 18.0
    plot_width, plot_height = width - 2 * padding, height - 2 * padding
    values = [
        float(value) if pd.notna(value) and math.isfinite(float(value)) else None
        for value in pd.to_numeric(frame["value"], errors="coerce")
    ]
    numeric = [value for value in values if value is not None]
    minimum, maximum = min(numeric), max(numeric)
    if chart_type == "bar":
        minimum, maximum = min(0.0, minimum), max(0.0, maximum)
    if minimum == maximum:
        span = max(abs(minimum) * 0.1, 1.0)
        minimum, maximum = minimum - span, maximum + span

    def y_coordinate(value: float) -> float:
        return padding + (maximum - value) / (maximum - minimum) * plot_height

    shapes = [
        cv.Line(
            x1=padding,
            y1=padding + index * plot_height / 4,
            x2=width - padding,
            y2=padding + index * plot_height / 4,
            paint=ft.Paint(color=BORDER, stroke_width=1),
        )
        for index in range(5)
    ]
    if chart_type == "line":
        def x_coordinate(index: int) -> float:
            return padding + index * plot_width / max(len(values) - 1, 1)

        shapes.extend(
            cv.Line(
                x1=x_coordinate(index),
                y1=y_coordinate(value),
                x2=x_coordinate(index + 1),
                y2=y_coordinate(next_value),
                paint=ft.Paint(color=CYAN, stroke_width=2),
            )
            for index, (value, next_value) in enumerate(zip(values, values[1:]))
            if value is not None and next_value is not None
        )
    else:
        baseline = y_coordinate(0.0)
        slot_width = plot_width / len(values)
        bar_width = max(1.0, slot_width * 0.65)
        for index, value in enumerate(values):
            if value is None:
                continue
            value_y = y_coordinate(value)
            shapes.append(
                cv.Rect(
                    x=padding + index * slot_width + (slot_width - bar_width) / 2,
                    y=min(baseline, value_y),
                    width=bar_width,
                    height=max(abs(baseline - value_y), 1.0),
                    paint=ft.Paint(color=GREEN if value >= 0 else RED),
                )
            )
    partial_flags = _partial_flags(frame)
    for index, (value, partial) in enumerate(zip(values, partial_flags)):
        if not partial or value is None:
            continue
        if chart_type == "line":
            marker_x = padding + index * plot_width / max(len(values) - 1, 1)
        else:
            marker_x = padding + index * (plot_width / len(values)) + plot_width / len(values) / 2
        shapes.append(
            cv.Circle(
                x=marker_x,
                y=y_coordinate(value),
                radius=4,
                paint=ft.Paint(color=AMBER, stroke_width=2, style=ft.PaintingStyle.STROKE),
            )
        )
    return cv.Canvas(width=width, height=height, shapes=shapes)


def _partial_flags(frame: pd.DataFrame) -> list[bool]:
    if "partial" not in frame.columns:
        return [False] * len(frame)
    return [_truthy(value) for value in frame["partial"].tolist()]


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "partial"}
    try:
        return bool(value) and not pd.isna(value)
    except (TypeError, ValueError):
        return False


def partial_marker_legend(frame: pd.DataFrame | None) -> str | None:
    """Text legend for partial-period markers; None when no period is partial."""

    if not isinstance(frame, pd.DataFrame) or not any(_partial_flags(frame)):
        return None
    count = sum(_partial_flags(frame))
    return f"Amber ring = partial period ({count} marked); values cover an incomplete period."


def _format_performance_value(value: object, unit: str, currency: str) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return "N/A"
    if unit == "currency":
        return format_currency(number, currency=currency)
    if unit == "percent":
        return format_percent(number)
    return f"{float(number):.2f}"


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


DONUT_PALETTE = (CYAN, GREEN, "#a99bf0", "#8e9ab4", "#7fb3e6", "#6fcfa6")
UNKNOWN_COLOUR = AMBER
UNMAPPED_COLOUR = RED


def _weight_or_none(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def allocation_donut(
    slices: list[tuple[str, object]],
    *,
    key: str,
    title: str = "Allocation",
    unknown_weight: object = None,
    unmapped_weight: object = None,
    unavailable_reason: str = "weight evidence is not available for this view",
) -> ft.Control:
    """Donut of weight shares with explicit Unknown and Unmapped slices (5.2 chart contract).

    Weights are drawn as given (fractions of 1.0); nothing is renormalised and a missing
    Unknown/Unmapped weight is labelled Unavailable, never drawn as zero.
    """

    known = [(label, _weight_or_none(value)) for label, value in slices]
    unknown = _weight_or_none(unknown_weight)
    unmapped = _weight_or_none(unmapped_weight)
    drawn: list[tuple[str, float, str]] = [
        (label, weight, DONUT_PALETTE[index % len(DONUT_PALETTE)])
        for index, (label, weight) in enumerate(known)
        if weight is not None and weight > 0
    ]
    if unknown is not None and unknown > 0:
        drawn.append(("Unknown", unknown, UNKNOWN_COLOUR))
    if unmapped is not None and unmapped > 0:
        drawn.append(("Unmapped", unmapped, UNMAPPED_COLOUR))
    size, stroke = 180.0, 26.0
    inset = stroke / 2
    shapes: list[cv.Shape] = [
        cv.Arc(
            x=inset, y=inset, width=size - stroke, height=size - stroke,
            start_angle=0, sweep_angle=2 * math.pi,
            paint=ft.Paint(color=BORDER, stroke_width=stroke, style=ft.PaintingStyle.STROKE),
        )
    ]
    angle = -math.pi / 2
    total = 0.0
    for _label, weight, colour in drawn:
        sweep = min(weight, max(1.0 - total, 0.0)) * 2 * math.pi
        if sweep <= 0:
            break
        shapes.append(
            cv.Arc(
                x=inset, y=inset, width=size - stroke, height=size - stroke,
                start_angle=angle, sweep_angle=sweep,
                paint=ft.Paint(color=colour, stroke_width=stroke, style=ft.PaintingStyle.STROKE),
            )
        )
        angle += sweep
        total += weight
    legend = [
        ft.Text(f"{label}: {weight:.1%}", size=11, color=TEXT, selectable=True)
        for label, weight, _colour in drawn
        if label not in {"Unknown", "Unmapped"}
    ]
    for label, value in (("Unknown", unknown), ("Unmapped", unmapped)):
        legend.append(
            ft.Text(
                f"{label}: {value:.1%}" if value is not None else f"{label}: Unavailable ({unavailable_reason})",
                size=11,
                color=TEXT if value is not None else MUTED,
                selectable=True,
            )
        )
    if not drawn:
        legend.insert(0, ft.Text(f"{title}: Unavailable ({unavailable_reason})", size=11, color=MUTED, selectable=True))
    body: list[ft.Control] = [ft.Text(title, color=TEXT, weight=ft.FontWeight.BOLD)]
    if drawn:
        body.append(cv.Canvas(width=size, height=size, shapes=shapes))
    body.extend(legend)
    return ft.Container(content=ft.Column(body, spacing=4), key=key, padding=10, border=border_all(1, BORDER))


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
