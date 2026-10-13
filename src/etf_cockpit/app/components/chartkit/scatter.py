"""ScatterBubble (FINAL_UI_SPEC 4.2, 6.7)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import flet as ft
from flet import canvas as cv

from etf_cockpit.app.components.chartkit import palette as pal
from etf_cockpit.app.components.chartkit.core import (
    Hit, LegendItem, Margins, Plot, Scale, Scene, empty_scene, finite, fmt, legend, make_chart, nice_ticks, tick_label, txt,
    x_axis_line, y_axis,
)


@dataclass
class Bubble:
    name: str
    x: float | None
    y: float | None
    size: float | None = None  # market cap; area proportional
    group: str = ""  # category (sector)
    highlight: bool = False  # analysed name: 2px white ring + label


def scatter_bubble(
    points: Sequence[Bubble],
    *,
    groups: Sequence[tuple[str, str]] | None = None,  # (name, colour); default categorical palette
    active_group: str | None = None,  # others fade to 8 %
    x_name: str | None = None,
    y_name: str | None = None,
    x_unit: str = "",
    y_unit: str = "",
    max_diameter: float = 38.0,
    min_diameter: float = 7.0,
    margins: Margins | None = None,
    width: float = 722,
    height: float = 330,
    unavailable_reason: str | None = None,
    empty_title: str = "No constituent fundamentals",
    insight: str | None = None,
) -> ft.Container:
    """Bubble scatter. Points with a missing x or y are skipped (never plotted at 0); a missing size draws the
    minimum diameter. Diameter = sqrt(size) scaled so that the largest bubble is max_diameter (area ~ market cap)."""
    pts = [p for p in points if finite(p.x) is not None and finite(p.y) is not None]
    gnames = [g for g, _ in groups] if groups else list(dict.fromkeys(p.group for p in pts if p.group))
    gcol = dict(groups) if groups else {g: pal.CATEGORICAL[i % len(pal.CATEGORICAL)] for i, g in enumerate(gnames)}

    def build(w: float, h: float) -> Scene:
        if unavailable_reason or not pts:
            return empty_scene(w, h, empty_title, unavailable_reason or "Import benchmark holdings and fundamentals to compare companies.", insight or "")
        sc = Scene(w, h, label=insight or "")
        plot = Plot(w, h, margins or Margins(62, 18, 34, 48))
        xs_v = [p.x for p in pts]  # type: ignore[misc]
        ys_v = [p.y for p in pts]  # type: ignore[misc]
        xmin, xmax = min(xs_v), max(xs_v)  # type: ignore[type-var]
        ymin, ymax = min(ys_v), max(ys_v)  # type: ignore[type-var]
        xpad, ypad = (xmax - xmin) * 0.06 or 1.0, (ymax - ymin) * 0.08 or 1.0
        ys = y_axis(sc, plot, ymin - ypad, ymax + ypad, name=y_name)
        x_axis_line(sc, plot, x_name)
        ticks, a, b = nice_ticks(xmin - xpad, xmax + xpad, 6)
        xs = Scale(a, b, plot.x0, plot.x1)
        step = ticks[1] - ticks[0] if len(ticks) > 1 else None
        for t in ticks:
            sc.add(txt(xs(t), plot.y1 + 14, tick_label(t, step)))
        sizes = [finite(p.size) for p in pts if (finite(p.size) or 0) > 0]
        smax = max(sizes) if sizes else 1.0
        order = sorted(pts, key=lambda p: -(finite(p.size) or 0))  # large first so small stay visible
        for p in order:
            col = gcol.get(p.group, pal.OTHER)
            faded = active_group is not None and active_group != "All" and p.group != active_group
            sz = finite(p.size)
            d = min_diameter if not sz or sz <= 0 else max(min_diameter, math.sqrt(sz / smax) * max_diameter)
            cx, cy = xs(p.x), ys(p.y)  # type: ignore[arg-type]
            alpha = 0.08 if faded else 0.85
            sc.add(cv.Circle(cx, cy, d / 2, pal.fill(pal.rgba(col, alpha))),
                   cv.Circle(cx, cy, d / 2, pal.stroke(pal.rgba("#ffffff", 0.85 * (0.15 if faded else 1)), 1)))
            if p.highlight and not faded:
                sc.add(cv.Circle(cx, cy, d / 2 + 2, pal.stroke("#ffffff", 2)),
                       txt(cx, cy - d / 2 - 8, p.name, weight=600, v="b", shadow=True))
            if not faded:
                sc.hits.insert(0, Hit("circle", (cx, cy, d / 2), p.name, [
                    (x_name or "x", fmt(p.x, 1, unit=x_unit), col), (y_name or "y", fmt(p.y, 1, unit=y_unit), None),
                    ("Market cap", fmt(sz, 0) if sz else "—", None)], anchor=(cx, cy - d / 2)))
        legend(sc, plot, [LegendItem(g, gcol[g], "bar") for g in gnames])
        return sc

    return make_chart(build, width, height)
