"""BarChart, GroupedBarChart, HorizontalStackedBar, Histogram (FINAL_UI_SPEC 4.1 / 4.2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import flet as ft
from flet import canvas as cv

from etf_cockpit.app.components.chartkit import palette as pal
from etf_cockpit.app.components.chartkit.core import (
    Hit, LegendItem, Margins, Plot, Scene, Scale, bar_rect, category_labels, empty_scene, finite, fmt, legend as draw_legend,
    line, make_chart, nice_ticks, tick_label, txt, x_axis_line, y_axis,
)


def _colors(kind: str | None, value: float, color: str | tuple[str, str] | None = None) -> tuple[str, str]:
    if isinstance(color, tuple):
        return color
    if isinstance(color, str):
        return color, pal.mix(color, "#000000", 0.35)
    if kind in pal.BAR_KINDS:
        return pal.BAR_KINDS[kind]
    return pal.GP if value >= 0 else pal.GN


def _empty(width: float, height: float, title: str, reason: str | None, default: str, insight: str | None) -> Scene:
    return empty_scene(width, height, title, reason or default, insight or "")


# ======================================================================== BarChart
def bar_chart(
    categories: Sequence[str],
    values: Sequence[float | None],
    *,
    kinds: Sequence[str | None] | None = None,
    colors: Sequence[str | tuple[str, str] | None] | None = None,
    bases: Sequence[float | None] | None = None,
    labels: Sequence[str | None] | None = None,
    x_name: str | None = None,
    y_name: str | None = None,
    unit: str = "",
    decimals: int = 1,
    signed_labels: bool = True,
    show_labels: bool = True,
    bar_width: float = 0.46,
    radius: float = 6,
    y_min: float | None = None,
    y_max: float | None = None,
    margins: Margins | None = None,
    label_size: float | None = None,
    label_every: int = 1,
    width: float = 600,
    height: float = 300,
    unavailable_reason: str | None = None,
    empty_title: str = "No data",
    insight: str | None = None,
    series_name: str | None = None,
) -> ft.Container:
    """Vertical signed bar chart. Missing (None/NaN) values draw no bar and no label (never 0).

    kinds: per-bar 'pos'|'neg'|'blue'|'gold' (default by sign). bases: per-bar start (waterfall: a transparent
    stacked base); a bar spans base..base+value. labels: per-bar label text override.
    """
    cats, vals = list(categories), [finite(v) for v in values]

    def build(w: float, h: float) -> Scene:
        if unavailable_reason or not any(v is not None for v in vals):
            return _empty(w, h, empty_title, unavailable_reason, "No values to chart.", insight)
        sc = Scene(w, h, label=insight or "")
        plot = Plot(w, h, margins or Margins())
        spans: list[tuple[float, float] | None] = []
        for i, v in enumerate(vals):
            if v is None:
                spans.append(None)
                continue
            b = finite(bases[i]) if bases and i < len(bases) else 0.0
            b = 0.0 if b is None else b
            spans.append((min(b, b + v), max(b, b + v)))
        known = [s for s in spans if s]
        lo = y_min if y_min is not None else min(0.0, min(s[0] for s in known))
        hi = y_max if y_max is not None else max(0.0, max(s[1] for s in known))
        if hi == lo:
            hi = lo + 1
        ys = y_axis(sc, plot, lo, hi, name=y_name)
        x_axis_line(sc, plot, x_name)
        n = len(cats)
        slot = plot.w / max(n, 1)
        bw = max(2.0, slot * bar_width)
        xs = [plot.x0 + slot * (i + 0.5) for i in range(n)]
        category_labels(sc, plot, cats, xs, size=label_size, every=label_every)
        for i, (c, v, sp) in enumerate(zip(cats, vals, spans)):
            if v is None or sp is None:
                continue
            kind = kinds[i] if kinds and i < len(kinds) else None
            col = colors[i] if colors and i < len(colors) else None
            top, bot = _colors(kind, v, col)
            y_top, y_bot = ys(min(sp[1], ys.d1)), ys(max(sp[0], ys.d0))
            sc.add(*bar_rect(xs[i] - bw / 2, y_top, bw, y_bot - y_top, top, bot, round_top=v >= 0, radius=radius))
            if show_labels:
                text = (labels[i] if labels and i < len(labels) and labels[i] is not None
                        else fmt(v, decimals, signed=signed_labels, unit=unit))
                if v >= 0:
                    sc.add(txt(xs[i], y_top - 8, text, weight=700, v="b"))
                else:
                    sc.add(txt(xs[i], y_bot + 8, text, weight=700, v="t"))
            sc.hits.append(Hit("rect", (xs[i] - slot / 2, plot.y0, slot, plot.h), c,
                               [(series_name or y_name, fmt(v, decimals, signed=signed_labels and v > 0, unit=unit), top)],
                               anchor=(xs[i], y_top)))
        return sc

    return make_chart(build, width, height)


# ======================================================================== GroupedBarChart
@dataclass
class BarSeries:
    name: str
    values: Sequence[float | None]
    kind: str = "blue"  # blue | gold | pos | neg
    color: str | None = None


@dataclass
class LineSeries:
    name: str
    values: Sequence[float | None]
    color: str = pal.SECOND
    width: float = 3.0
    marker: float = 9.0


def grouped_bar_chart(
    categories: Sequence[str],
    bars: Sequence[BarSeries],
    *,
    line_series: LineSeries | None = None,
    x_name: str | None = None,
    y_name: str | None = None,
    y2_name: str | None = None,
    y_max: float | None = None,
    y_min: float | None = None,
    unit: str = "",
    y2_unit: str = "",
    decimals: int = 1,
    bar_width: float = 0.46,
    gap: float = 4.0,
    radius: float = 5,
    margins: Margins | None = None,
    label_size: float | None = None,
    show_legend: bool = True,
    width: float = 600,
    height: float = 300,
    unavailable_reason: str | None = None,
    empty_title: str = "No data",
    insight: str | None = None,
) -> ft.Container:
    """Grouped bars with an optional secondary line axis (right). A bar above y_max is clipped and labelled "<v> ▲"."""
    cats = list(categories)

    def build(w: float, h: float) -> Scene:
        allv = [finite(v) for s in bars for v in s.values]
        if unavailable_reason or not any(v is not None for v in allv):
            return _empty(w, h, empty_title, unavailable_reason, "No values to chart.", insight)
        sc = Scene(w, h, label=insight or "")
        plot = Plot(w, h, margins or Margins(58, 56 if line_series else 20, 36, 50))
        known = [v for v in allv if v is not None]
        hi = y_max if y_max is not None else max(0.0, max(known))
        lo = y_min if y_min is not None else min(0.0, min(known))
        ys = y_axis(sc, plot, lo, max(hi, lo + 1e-9), name=y_name)
        x_axis_line(sc, plot, x_name)
        n, k = len(cats), max(len(bars), 1)
        slot = plot.w / max(n, 1)
        group_w = slot * bar_width * (1 + 0.5 * (k - 1)) if k > 1 else slot * bar_width
        bw = max(2.0, (group_w - gap * (k - 1)) / k)
        xs = [plot.x0 + slot * (i + 0.5) for i in range(n)]
        category_labels(sc, plot, cats, xs, size=label_size)
        rows_by_cat: list[list[tuple[str | None, str, str | None]]] = [[] for _ in range(n)]
        for si, s in enumerate(bars):
            top, bot = (s.color, pal.mix(s.color, "#000000", 0.35)) if s.color else pal.BAR_KINDS.get(s.kind, pal.GB)
            for i in range(n):
                v = finite(s.values[i]) if i < len(s.values) else None
                if v is None:
                    continue
                x = xs[i] - group_w / 2 + si * (bw + gap)
                clipped = v > ys.d1
                y_top = ys(min(max(v, 0.0), ys.d1))
                y_bot = ys(max(min(v, 0.0), ys.d0))
                sc.add(*bar_rect(x, y_top, bw, y_bot - y_top, top, bot, round_top=not clipped and v >= 0, radius=radius))
                if clipped:
                    sc.add(txt(x + bw / 2, y_top + 12, f"{fmt(v, 0)} ▲", weight=700, color="#ffffff", size=11.5))
                rows_by_cat[i].append((s.name, fmt(v, decimals, unit=unit), top))
        if line_series is not None:
            lv = [finite(v) for v in line_series.values]
            kn = [v for v in lv if v is not None]
            if kn:
                ticks, l0, l1 = nice_ticks(min(kn), max(kn), 5)
                y2 = y_axis(sc, plot, l0, l1, name=y2_name, side="right", ticks=ticks, grid=False)
                pts = [(i, xs[i], y2(v), v) for i, v in enumerate(lv[:n]) if v is not None]
                # segments only between neighbouring valid points (adjacent category indices)
                for (ia, xa, ya, _), (ib, xb, yb, _) in zip(pts, pts[1:]):
                    if ib == ia + 1:
                        sc.add(line(xa, ya, xb, yb, line_series.color, line_series.width))
                for _, x, y, v in pts:
                    sc.add(cv.Circle(x, y, line_series.marker / 2, pal.fill(line_series.color)),
                           cv.Circle(x, y, line_series.marker / 2, pal.stroke("#ffffff", 1.5)))
                for i, v in enumerate(lv[:n]):
                    if v is not None:
                        rows_by_cat[i].append((line_series.name, fmt(v, decimals, unit=y2_unit), line_series.color))
        for i in range(n):
            if rows_by_cat[i]:
                sc.hits.append(Hit("rect", (xs[i] - slot / 2, plot.y0, slot, plot.h), cats[i], rows_by_cat[i],
                                   anchor=(xs[i], plot.y0 + 20)))
        if show_legend:
            items = [LegendItem(s.name, (s.color or pal.BAR_KINDS.get(s.kind, pal.GB)[0]), "bar") for s in bars]
            if line_series:
                items.append(LegendItem(line_series.name, line_series.color, "line"))
            draw_legend(sc, plot, items)
        return sc

    return make_chart(build, width, height)


# ======================================================================== HorizontalStackedBar
@dataclass
class Segment:
    value: float
    kind: str = "pos"  # pos (train) | gold (test) | blue | neg
    label: str = ""


def horizontal_stacked_bar(
    rows: Sequence[str],
    segments: Sequence[Sequence[Segment]],
    *,
    x_name: str | None = None,
    x_max: float | None = None,
    bar_height: float = 0.46,
    radius: float = 6,
    unit: str = "",
    margins: Margins | None = None,
    width: float = 600,
    height: float = 300,
    unavailable_reason: str | None = None,
    empty_title: str = "No data",
    insight: str | None = None,
    legend: Sequence[LegendItem] | None = None,
) -> ft.Container:
    """Horizontal stacked bars, first row at the top. First segment rounds left, last rounds right."""
    row_names = list(rows)

    def build(w: float, h: float) -> Scene:
        totals = [sum(finite(s.value) or 0.0 for s in r) for r in segments]
        if unavailable_reason or not row_names or not any(finite(s.value) is not None for r in segments for s in r):
            return _empty(w, h, empty_title, unavailable_reason, "No folds to chart.", insight)
        sc = Scene(w, h, label=insight or "")
        plot = Plot(w, h, margins or Margins(78, 20, 20, 48))
        hi = x_max if x_max is not None else max(totals)
        ticks, _, nhi = nice_ticks(0, hi, 6)
        xs_ = Scale(0, nhi, plot.x0, plot.x1)
        step = ticks[1] - ticks[0] if len(ticks) > 1 else None
        for t in ticks:
            x = xs_(t)
            sc.add(line(x, plot.y0, x, plot.y1, pal.GRID, 1), txt(x, plot.y1 + 14, tick_label(t, step)))
        sc.add(line(plot.x0, plot.y0, plot.x0, plot.y1, pal.AXIS, 1))
        x_axis_line(sc, plot, x_name)
        slot = plot.h / len(row_names)
        bh = slot * bar_height
        for i, name in enumerate(row_names):
            cy = plot.y0 + slot * (i + 0.5)
            sc.add(txt(plot.x0 - 10, cy, name, h="r"))
            acc = 0.0
            segs = [s for s in segments[i] if finite(s.value) is not None and finite(s.value) > 0]
            for j, s in enumerate(segs):
                top, bot = pal.BAR_KINDS.get(s.kind, pal.GP)
                xa, xb = xs_(acc), xs_(acc + s.value)
                sc.add(*bar_rect(xa, cy - bh / 2, xb - xa, bh, top, bot, round_top=True, radius=radius,
                                 round_left=(j == 0), round_right=(j == len(segs) - 1)))
                if s.label:
                    sc.add(txt((xa + xb) / 2, cy, s.label, weight=700, size=11.5, color="#0b1424"))
                sc.hits.append(Hit("rect", (xa, cy - bh / 2, xb - xa, bh), name,
                                   [(s.label or s.kind, fmt(s.value, 0, unit=unit), top)], anchor=((xa + xb) / 2, cy - bh / 2)))
                acc += s.value
        if legend is not None:
            draw_legend(sc, plot, legend)
        return sc

    return make_chart(build, width, height)


# ======================================================================== Histogram
def histogram(
    bins: Sequence[str],
    counts: Sequence[float | None],
    *,
    negative: Sequence[bool] | None = None,
    x_name: str | None = None,
    y_name: str = "Companies (count)",
    margins: Margins | None = None,
    width: float = 425,
    height: float = 300,
    unavailable_reason: str | None = None,
    empty_title: str = "No data",
    insight: str | None = None,
) -> ft.Container:
    """Histogram: 90% width bars, negative bins gn, others gp, 10.5px bin labels (all shown)."""
    kinds = ["neg" if (negative and i < len(negative) and negative[i]) else "pos" for i in range(len(bins))]
    return bar_chart(
        bins, counts, kinds=kinds, x_name=x_name, y_name=y_name, bar_width=0.9, radius=4, show_labels=False,
        decimals=0, margins=margins or Margins(54, 12, 26, 52), label_size=10.5, y_min=0, width=width, height=height,
        unavailable_reason=unavailable_reason, empty_title=empty_title, insight=insight, series_name="Count",
    )
