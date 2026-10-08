"""Tile components: KpiTile, StatTile, KpiStrip, Headline, VerdictRing (spec 3.6, 3.7, 3.15, 3.16, 3.19)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import flet as ft
import flet.canvas as cv

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit._base import (
    drops,
    pad,
    ring,
    sym,
    tag_semantics,
    txt,
    vgradient,
)

_TONE_COLOURS = {"pos": theme.POS, "neg": theme.NEG, "attention": theme.AMBER}


def KpiTile(  # noqa: N802
    label: str,
    value: str | None,
    sub: str = "",
    tone: str | None = None,
    *,
    expand: bool | int = False,
    width: float | None = None,
    key: str | None = None,
) -> ft.Container:
    """Recessed KPI tile (spec 3.6). ``value=None`` shows ``Unavailable`` with ``sub`` as the reason."""
    if tone not in (None, "pos", "neg", "attention"):
        raise ValueError("tone must be None, 'pos', 'neg' or 'attention'")
    rows: list[ft.Control] = [txt(label, 11, 600, theme.INK3, tracking=0.08, upper=True, trunc=True)]
    if value is None:
        rows.append(txt("Unavailable", 20, 600, theme.INK2, trunc=True))
    else:
        rows.append(txt(value, 26, 700, _TONE_COLOURS.get(tone or "", theme.INK), tracking=-0.02, trunc=True))
    if sub:
        rows.append(txt(sub, 12, 400, theme.INK2, trunc=True))
    tile = ft.Container(
        content=ft.Column(rows, spacing=4, tight=True),
        padding=sym(16, 12),
        border_radius=theme.RADIUS_KPI,
        gradient=vgradient((theme.rgba(0, 0, 0, 0.26), theme.KPI_TILE_FILL)),
        border=ring(theme.rgba(255, 255, 255, 0.05)),
        expand=expand,
        width=width,
    )
    tag_semantics(tile, key=key, label=None)
    tile.data = {"kit": "KpiTile", "label": label, "value": value, "tone": tone}
    return tile


def _with_alpha(colour: str, alpha: float) -> str:
    return theme.rgba(int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16), alpha)


def _sparkline(series: Sequence[float], colour: str, width: float = 88, height: float = 40) -> cv.Canvas:
    shapes: list[cv.Shape] = []
    points = [float(item) for item in series if item is not None and math.isfinite(float(item))]
    if len(points) >= 2:
        low, high = min(points), max(points)
        span = (high - low) or 1.0
        inset = 2.0
        step = (width - 2 * inset) / (len(points) - 1)
        coords = [(inset + index * step, inset + (height - 2 * inset) * (1 - (value - low) / span))
                  for index, value in enumerate(points)]
        area = [cv.Path.MoveTo(coords[0][0], height), *[cv.Path.LineTo(x, y) for x, y in coords],
                cv.Path.LineTo(coords[-1][0], height), cv.Path.Close()]
        shapes.append(cv.Path(area, paint=ft.Paint(style=ft.PaintingStyle.FILL, color=_with_alpha(colour, 0.25))))
        line = [cv.Path.MoveTo(*coords[0]), *[cv.Path.LineTo(x, y) for x, y in coords[1:]]]
        shapes.append(
            cv.Path(
                line,
                paint=ft.Paint(
                    style=ft.PaintingStyle.STROKE,
                    stroke_width=1.6,
                    color=colour,
                    stroke_cap=ft.StrokeCap.ROUND,
                    stroke_join=ft.StrokeJoin.ROUND,
                ),
            )
        )
    return cv.Canvas(shapes=shapes, width=width, height=height)


def StatTile(  # noqa: N802
    label: str,
    value: str | None,
    spark_series: Sequence[float] | None = None,
    tone: str | None = None,
    *,
    expand: bool | int = False,
    width: float | None = None,
    key: str | None = None,
) -> ft.Container:
    """Stat tile with a 88x40 sparkline at the right (spec 3.7). Without a series the sparkline is omitted."""
    colour = _TONE_COLOURS.get(tone or "", theme.ACC)
    left = ft.Column(
        [
            txt(label, 11, 400, theme.INK3, tracking=0.06, upper=True, trunc=True),
            txt(value if value is not None else "—", 21, 500, colour if value is not None else theme.INK3,
                trunc=True),
        ],
        spacing=4,
        expand=True,
        tight=True,
    )
    cells: list[ft.Control] = [left]
    if spark_series:
        cells.append(_sparkline(spark_series, colour))
    tile = ft.Container(
        content=ft.Row(cells, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=pad(16, 12, 12, 8),
        border_radius=theme.RADIUS_KPI,
        gradient=vgradient((theme.rgba(0, 0, 0, 0.36), theme.STAT_TILE_FILL)),
        border=ring(theme.rgba(255, 255, 255, 0.05)),
        expand=expand,
        width=width,
    )
    tag_semantics(tile, key=key, label=None)
    tile.data = {"kit": "StatTile", "label": label, "value": value, "tone": tone, "points": len(spark_series or ())}
    return tile


@dataclass(frozen=True)
class KpiStripItem:
    """One KpiStrip column; ``tone`` is 'pos', 'neg' or None for the delta colour."""

    label: str
    value: str | None
    delta: str = ""
    tone: str | None = None


def KpiStrip(  # noqa: N802
    headline_label: str,
    headline: str,
    headline_sub: str,
    items: Sequence[KpiStripItem | tuple[str, str | None, str, str | None]],
    *,
    key: str | None = None,
) -> ft.Container:
    """Full-width glass strip: headline block then four KPI columns with left dividers (spec 3.19)."""
    from etf_cockpit.app.components.kit.surfaces import GlassCard

    entries = [item if isinstance(item, KpiStripItem) else KpiStripItem(*item) for item in items]
    if len(entries) != 4:
        raise ValueError("KpiStrip takes exactly four items")
    delta_colours = {"pos": theme.POS2, "neg": theme.STRIP_NEG}
    columns: list[ft.Control] = [
        ft.Container(
            content=ft.Column(
                [
                    txt(headline_label, 10.5, 600, theme.INK3, tracking=0.16, upper=True, trunc=True),
                    txt(headline, 24, 600, trunc=True),
                    txt(headline_sub, 12.5, 400, theme.INK2, trunc=True),
                ],
                spacing=4,
                tight=True,
            ),
            expand=2,
            padding=pad(right=20),
        )
    ]
    for entry in entries:
        cell: list[ft.Control] = [
            txt(entry.label, 11, 600, theme.INK3, tracking=0.08, upper=True, trunc=True),
            txt(entry.value if entry.value is not None else "Unavailable", 26 if entry.value is not None else 20,
                500 if entry.value is not None else 600, theme.INK if entry.value is not None else theme.INK2,
                tracking=-0.02, trunc=True),
        ]
        if entry.delta:
            cell.append(txt(entry.delta, 12.5, 400, delta_colours.get(entry.tone or "", theme.INK2), trunc=True))
        columns.append(
            ft.Row(
                [
                    ft.Container(width=1, height=64, bgcolor=theme.rgba(255, 255, 255, 0.12)),
                    ft.Container(content=ft.Column(cell, spacing=4, tight=True), padding=pad(left=20), expand=True),
                ],
                spacing=0,
                expand=1,
            )
        )
    strip = GlassCard("", quiet=True, body=ft.Row(columns, spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER))
    strip.data = {"kit": "KpiStrip", "items": [entry.label for entry in entries]}
    tag_semantics(strip, key=key, label=None)
    return strip


def Headline(word: str, size: float = 68, *, key: str | None = None) -> ft.ShaderMask:  # noqa: N802
    """Light-weight gradient headline word such as ``Qualifies`` (spec 3.15)."""
    mask = ft.ShaderMask(
        content=txt(word, size, 300, "#ffffff", tracking=-0.045, trunc=True),
        shader=ft.LinearGradient(
            colors=list(theme.HEADLINE_GRADIENT), begin=ft.Alignment(0, -1), end=ft.Alignment(0, 1)
        ),
        blend_mode=ft.BlendMode.SRC_IN,
    )
    tag_semantics(mask, key=key, label=None)
    mask.data = {"kit": "Headline", "word": word, "size": size}
    return mask


def VerdictRing(  # noqa: N802
    score: float | None,
    *,
    size: float = 128,
    caption: str = "of 100",
    key: str | None = None,
) -> ft.Stack:
    """128px disc with a 270 degree gauge, thickness 24, round caps (spec 3.16). ``None`` shows an em dash."""
    thickness = 24.0 * size / 128
    inset = thickness / 2
    clamped = None if score is None else max(0.0, min(100.0, float(score)))
    shapes: list[cv.Shape] = []
    box = size - thickness
    start = math.radians(135)  # 225 degrees counter-clockwise from the right = bottom-left, drawn clockwise
    sweep_total = math.radians(270)
    shapes.append(
        cv.Arc(
            inset,
            inset,
            box,
            box,
            start,
            sweep_total,
            use_center=False,
            paint=ft.Paint(
                style=ft.PaintingStyle.STROKE,
                stroke_width=thickness,
                stroke_cap=ft.StrokeCap.ROUND,
                color=theme.GAUGE_TRACK,
            ),
        )
    )
    if clamped:
        shapes.append(
            cv.Arc(
                inset,
                inset,
                box,
                box,
                start,
                sweep_total * clamped / 100.0,
                use_center=False,
                paint=ft.Paint(
                    style=ft.PaintingStyle.STROKE,
                    stroke_width=thickness,
                    stroke_cap=ft.StrokeCap.ROUND,
                    gradient=ft.PaintLinearGradient((0, size), (size, size), [theme.ACC, theme.CHART_POS]),
                ),
            )
        )
    disc = ft.Container(
        width=size,
        height=size,
        shape=ft.BoxShape.CIRCLE,
        gradient=ft.RadialGradient(
            center=ft.Alignment(0, -0.4),
            radius=0.75,
            colors=[theme.rgba(255, 255, 255, 0.10), theme.rgba(0, 0, 0, 0.22)],
        ),
        shadow=drops(((0, 10, 22, 0, theme.rgba(0, 0, 0, 0.30)),)),
    )
    # Safe radius: the arc band occupies [size/2 - thickness, size/2]; value and caption live inside the
    # inner circle (diameter size - 2 * thickness), scaled with the ring, so the arc never touches them.
    scale = size / 128
    inner = size - 2 * thickness - 8
    value_size = min(38 * scale, (inner - 8) / 1.75)  # three digits (100) must fit inside the safe circle
    centre = ft.Container(
        content=ft.Column(
            [
                txt("—" if clamped is None else f"{clamped:.0f}", value_size, 700, tracking=0),
                txt(caption, max(9.0, 11 * scale), 400, theme.CHART_T2, trunc=True),
            ],
            spacing=0,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=inner,
        height=inner,
        alignment=ft.Alignment(0, 0),
    )
    centre = ft.Container(content=centre, width=size, height=size, alignment=ft.Alignment(0, 0))
    ringed = ft.Stack(
        [disc, cv.Canvas(shapes=shapes, width=size, height=size), centre],
        width=size,
        height=size,
    )
    tag_semantics(ringed, key=key, label=None)
    ringed.data = {"kit": "VerdictRing", "score": clamped}
    return ringed
