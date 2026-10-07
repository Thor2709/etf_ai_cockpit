"""RadarChart, DonutChart, Gauge (FINAL_UI_SPEC 4.2, 3.16)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import flet as ft
from flet import canvas as cv

from etf_cockpit.app.components.chartkit import palette as pal
from etf_cockpit.app.components.chartkit.core import (
    Hit, LegendItem, Margins, Plot, Scene, empty_scene, finite, fmt, legend, line, make_chart, poly, txt,
)


@dataclass
class RadarSeries:
    name: str
    values: Sequence[float | None]
    color: str = pal.P
    width: float = 3.0
    dashed: bool = False
    glow: bool = False
    fill_alpha: float = 0.25  # 0 = no fill


def radar_chart(
    axes: Sequence[str],
    series: Sequence[RadarSeries],
    *,
    lo: float = 0.0,
    hi: float = 100.0,
    rings: int = 4,
    split_area: bool = False,
    radius: float = 0.62,
    center: tuple[float, float] = (0.5, 0.5),
    legend_at: str = "bottom",
    axis_size: float = 13.0,
    decimals: int = 0,
    width: float = 400,
    height: float = 320,
    unavailable_reason: str | None = None,
    empty_title: str = "No data",
    insight: str | None = None,
) -> ft.Container:
    """Radar with split rings (and alternating 3%/10% grey split areas when split_area). A missing axis value
    is skipped (the polygon connects the remaining vertices) and shows "—" in the tooltip; never plotted at 0."""
    names = list(axes)

    def build(w: float, h: float) -> Scene:
        if unavailable_reason or len(names) < 3 or not any(finite(v) is not None for s in series for v in s.values):
            return empty_scene(w, h, empty_title, unavailable_reason or "No values to chart.", insight or "")
        sc = Scene(w, h, label=insight or "")
        n = len(names)
        cx, cy = w * center[0], h * center[1]
        r = min(w, h) / 2 * radius
        ang = [-math.pi / 2 + math.tau * i / n for i in range(n)]

        def pt(i: int, frac: float) -> tuple[float, float]:
            return cx + r * frac * math.cos(ang[i]), cy + r * frac * math.sin(ang[i])

        for k in range(rings, 0, -1):
            ring = [pt(i, k / rings) for i in range(n)]
            if split_area:
                sc.add(poly(ring, pal.fill("#1a808080" if (rings - k) % 2 == 1 else "#08808080"), close=True))
        for k in range(1, rings + 1):
            sc.add(poly([pt(i, k / rings) for i in range(n)], pal.stroke(pal.AXIS, 1), close=True))
        for i in range(n):
            sc.add(line(cx, cy, *pt(i, 1.0), pal.AXIS, 1))
            ex, ey = pt(i, 1.0)
            dx, dy = math.cos(ang[i]), math.sin(ang[i])
            hx = "c" if abs(dx) < 0.25 else ("l" if dx > 0 else "r")
            vy = "b" if dy < -0.6 else ("t" if dy > 0.6 else "m")
            sc.add(txt(ex + dx * 10, ey + dy * 10, names[i], size=axis_size, h=hx, v=vy))
        span = (hi - lo) or 1.0
        for s in series:
            idx = [i for i in range(n) if i < len(s.values) and finite(s.values[i]) is not None]
            pts = [pt(i, max(0.0, min(1.0, (finite(s.values[i]) - lo) / span))) for i in idx]  # type: ignore[operator]
            if len(pts) >= 3 and s.fill_alpha:
                sc.add(poly(pts, pal.fill(pal.rgba(s.color, s.fill_alpha)), close=True))
            if len(pts) >= 2:
                if s.glow:
                    sc.add(poly(pts, pal.stroke(pal.rgba(s.color, 0.12), s.width + 9), close=len(pts) >= 3),
                           poly(pts, pal.stroke(pal.rgba(s.color, 0.22), s.width + 4), close=len(pts) >= 3))
                sc.add(poly(pts, pal.stroke(s.color, s.width, [6, 4] if s.dashed else None), close=len(pts) >= 3))
            for (px, py) in pts:
                sc.add(cv.Circle(px, py, 4, pal.fill(s.color)))
        for i in range(n):
            rows = [(s.name, fmt(finite(s.values[i]) if i < len(s.values) else None, decimals), s.color) for s in series]
            sc.hits.append(Hit("circle", (*pt(i, 1.0), max(18.0, r * 0.12)), names[i], rows, anchor=pt(i, 1.0)))
        plot = Plot(w, h, Margins(8, 8, 8, 8))
        legend(sc, plot, [LegendItem(s.name, s.color, "dashed" if s.dashed else "line") for s in series],
               where="bottom" if legend_at == "bottom" else legend_at, y=14 if legend_at != "bottom" else None)
        return sc

    return make_chart(build, width, height)


# ======================================================================== Donut
@dataclass
class Slice:
    name: str
    value: float
    color: str


def _sector(cx: float, cy: float, r0: float, r1: float, a0: float, a1: float, step: float = 0.04) -> list[tuple[float, float]]:
    n = max(2, int((a1 - a0) / step))
    outer = [(cx + r1 * math.cos(a0 + (a1 - a0) * k / n), cy + r1 * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]
    inner = [(cx + r0 * math.cos(a1 - (a1 - a0) * k / n), cy + r0 * math.sin(a1 - (a1 - a0) * k / n)) for k in range(n + 1)]
    return outer + inner


def donut_chart(
    slices: Sequence[Slice],
    *,
    inner: float = 0.46,
    outer: float = 0.72,
    center: tuple[float, float] = (0.5, 0.46),
    corner: float = 8.0,
    gap_px: float = 3.0,
    unit: str = "",
    center_text: str | None = None,
    show_legend: bool = True,
    width: float = 420,
    height: float = 320,
    unavailable_reason: str | None = None,
    empty_title: str = "No data",
    insight: str | None = None,
) -> ft.Container:
    """Donut: inner 46 % / outer 72 % of the half-size, 3px separators, radius-8 corners, outside labels `Name\\ncount`.
    Zero / missing slices are omitted."""
    items = [s for s in slices if (finite(s.value) or 0) > 0]

    def build(w: float, h: float) -> Scene:
        total = sum(s.value for s in items)
        if unavailable_reason or total <= 0:
            return empty_scene(w, h, empty_title, unavailable_reason or "No values to chart.", insight or "")
        sc = Scene(w, h, label=insight or "")
        cx, cy = w * center[0], h * center[1]
        half = min(w, h) / 2
        r0, r1 = half * inner, half * outer
        a = -math.pi / 2
        for s in items:
            sweep = math.tau * s.value / total
            a0, a1 = a, a + sweep
            a = a1
            ri0, ri1 = r0 + corner / 2 + gap_px / 2, r1 - corner / 2 - gap_px / 2
            pad0, pad1 = (corner / 2 + gap_px / 2) / max(ri1, 1), (corner / 2 + gap_px / 2) / max(ri0, 1)
            pad = max(pad0, pad1)
            if a1 - a0 > 2 * pad + 0.01 and ri1 > ri0:
                shape = _sector(cx, cy, ri0, ri1, a0 + pad, a1 - pad)
                sc.add(poly(shape, pal.fill(s.color), close=True),
                       poly(shape, ft.Paint(color=s.color, stroke_width=corner, style=ft.PaintingStyle.STROKE,
                                            stroke_join=ft.StrokeJoin.ROUND), close=True))
            else:
                sc.add(poly(_sector(cx, cy, r0, r1, a0, a1), pal.fill(s.color), close=True))
            mid = (a0 + a1) / 2
            ex, ey = cx + r1 * math.cos(mid), cy + r1 * math.sin(mid)
            lx, ly = cx + (r1 + 14) * math.cos(mid), cy + (r1 + 14) * math.sin(mid)
            right = math.cos(mid) >= 0
            sc.add(line(ex, ey, lx, ly, pal.AXIS, 1),
                   txt(lx + (4 if right else -4), ly, f"{s.name}\n{fmt(s.value, 0, unit=unit)}", size=13,
                       h="l" if right else "r", v="m"))
            sc.hits.append(Hit("sector", (cx, cy, r0, r1, a0, a1), s.name,
                               [(None, f"{fmt(s.value, 0, unit=unit)}  ({s.value / total * 100:.1f}%)", s.color)],
                               anchor=(ex, ey)))
        if center_text:
            sc.add(txt(cx, cy, center_text, size=20, weight=600))
        if show_legend:
            legend(sc, Plot(w, h, Margins(8, 8, 8, 8)), [LegendItem(s.name, s.color, "bar") for s in items], where="bottom")
        return sc

    return make_chart(build, width, height)


# ======================================================================== Gauge
def gauge(
    value: float | None,
    *,
    maximum: float = 100.0,
    size: float = 128,
    caption: str | None = "of 100",
    decimals: int = 0,
    disc: bool = True,
    unavailable_reason: str | None = None,
    insight: str | None = None,
) -> ft.Container:
    """VerdictRing: disc + 270 degree arc (225 degrees to -45 degrees), thickness 24 at 128px, round caps, track
    white 12 %, progress gradient #9ad1ff -> #6fcfa6, centre value 38/700 and caption 11/400. No value -> track
    only with an em dash and the reason as caption (never a zero arc)."""
    v = None if unavailable_reason else finite(value)

    def build(w: float, h: float) -> Scene:
        sc = Scene(w, h, label=insight or (f"Score {fmt(v, decimals)} {caption or ''}".strip() if v is not None else "Score unavailable"))
        s = min(w, h)
        cx, cy = w / 2, h / 2
        k = s / 128
        thick = 24 * k
        r = s / 2 - thick / 2 - 3 * k
        if disc:
            sc.add(cv.Circle(cx, cy, s / 2 - 1, ft.Paint(
                gradient=ft.PaintRadialGradient((cx, cy - 0.2 * s), s / 2, ["#1affffff", "#38000000"]), style=ft.PaintingStyle.FILL)))
        start, sweep = math.radians(135), math.radians(270)
        box = dict(x=cx - r, y=cy - r, width=2 * r, height=2 * r, use_center=False)
        round_cap = ft.StrokeCap.ROUND
        sc.add(cv.Arc(start_angle=start, sweep_angle=sweep, paint=ft.Paint(
            color=pal.TRACK, stroke_width=thick, style=ft.PaintingStyle.STROKE, stroke_cap=round_cap), **box))
        if v is not None and maximum > 0:
            frac = max(0.0, min(1.0, v / maximum))
            if frac > 0:
                sc.add(cv.Arc(start_angle=start, sweep_angle=sweep * frac, paint=ft.Paint(
                    gradient=ft.PaintLinearGradient((cx - r, cy), (cx + r, cy), [pal.P, pal.POS]),
                    stroke_width=thick, style=ft.PaintingStyle.STROKE, stroke_cap=round_cap), **box))
        sc.add(txt(cx, cy - 4 * k, fmt(v, decimals) if v is not None else "—", size=38 * k, weight=700, color=pal.INK))
        cap = caption if v is not None else (unavailable_reason or "unavailable")
        if cap:
            sc.add(txt(cx, cy + 26 * k, cap, size=max(9.0, 11 * k), color=pal.T2, max_width=2 * r * 0.9))
        return sc

    return make_chart(build, size, size)
