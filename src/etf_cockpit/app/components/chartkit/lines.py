"""LineChart (time + category), DrawdownPanel, price+drawdown hero chart, Sparkline (FINAL_UI_SPEC 4.1 / 4.2)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Sequence

import flet as ft
from flet import canvas as cv

from etf_cockpit.app.components.chartkit import palette as pal
from etf_cockpit.app.components.chartkit.core import (
    Hit, LegendItem, Margins, Plot, Scale, Scene, empty_scene, finite, fmt, is_time, legend, line, make_chart,
    poly, smooth_segments, to_ordinal, txt, x_axis_line, y_axis,
)


@dataclass
class Series:
    name: str
    values: Sequence[float | None]
    color: str = pal.P
    width: float = 3.0
    dashed: bool = False
    glow: bool = False
    area: bool = False
    area_alpha: tuple[float, float] = (0.30, 0.0)  # (at the line extreme, at the baseline)
    area_base: float | None = None  # value of the area baseline; None = bottom of the plot
    markers: float = 0.0  # marker diameter px (0 = none)
    marker_ring: bool = False
    opacity: float = 1.0
    smooth: bool = False
    legend: bool = True
    unit: str = ""
    decimals: int = 2


@dataclass
class Band:
    """Forecast fan: filled between lower and upper (aligned with x; None where absent)."""

    name: str
    lower: Sequence[float | None]
    upper: Sequence[float | None]
    color: str = pal.VIO
    alpha: float = 0.16
    unit: str = ""
    decimals: int = 2


@dataclass
class EventMark:
    """Marker on a series point, e.g. an ex-dividend date (label 'Div')."""

    index: int
    label: str = "Div"
    series: int = 0


def x_positions(x: Sequence[Any], x0: float, x1: float, *, edge_to_edge: bool) -> list[float]:
    n = len(x)
    if n == 0:
        return []
    if is_time(x):
        ords = [to_ordinal(v) for v in x]
        lo, hi = min(ords), max(ords)
        sc = Scale(lo, hi, x0, x1)
        return [sc(o) for o in ords]
    if edge_to_edge:
        return [x0 + (x1 - x0) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
    return [x0 + (x1 - x0) * (i + 0.5) / n for i in range(n)]


def x_label(v: Any, fmt_: str) -> str:
    if isinstance(v, (date, datetime)):
        return v.strftime(fmt_)
    return str(v)


def _runs(vals: Sequence[float | None]) -> list[list[int]]:
    runs: list[list[int]] = []
    cur: list[int] = []
    for i, v in enumerate(vals):
        if v is None:
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append(i)
    if cur:
        runs.append(cur)
    return runs


def draw_bands(sc: Scene, xs: Sequence[float], ys: Scale, bands: Sequence[Band]) -> None:
    for b in bands:
        lo = [finite(v) for v in b.lower]
        hi = [finite(v) for v in b.upper]
        ok = [None if (a is None or c is None) else (a, c) for a, c in zip(lo, hi)]
        run: list[int] = []
        for i, pair in enumerate(list(ok) + [None]):
            if pair is not None:
                run.append(i)
                continue
            if len(run) >= 2:
                up = [(xs[j], ys(ok[j][1])) for j in run]  # type: ignore[index]
                dn = [(xs[j], ys(ok[j][0])) for j in reversed(run)]  # type: ignore[index]
                sc.add(poly(up + dn, pal.fill(pal.rgba(b.color, b.alpha)), close=True))
            run = []


def draw_series(sc: Scene, plot: Plot, xs: Sequence[float], ys: Scale, series: Sequence[Series]) -> None:
    for s in series:
        vals = [finite(v) for v in s.values][: len(xs)]
        col = pal.rgba(s.color, s.opacity) if s.opacity < 1 else s.color
        for run in _runs(vals):
            pts = [(xs[i], ys(vals[i])) for i in run]  # type: ignore[arg-type]
            if len(pts) >= 2:
                if s.area:
                    base_y = ys(s.area_base) if s.area_base is not None else plot.y1
                    ytop = min(min(p[1] for p in pts), base_y)
                    ybot = max(max(p[1] for p in pts), base_y)
                    els = (smooth_segments(pts) if s.smooth else [cv.Path.MoveTo(*pts[0])] + [cv.Path.LineTo(*p) for p in pts[1:]])
                    els += [cv.Path.LineTo(pts[-1][0], base_y), cv.Path.LineTo(pts[0][0], base_y), cv.Path.Close()]
                    sc.add(cv.Path(els, paint=pal.vgradient(pal.rgba(s.color, s.area_alpha[0]), pal.rgba(s.color, s.area_alpha[1]), ytop, ybot if ybot > ytop else ytop + 1)))
                els = smooth_segments(pts) if s.smooth else [cv.Path.MoveTo(*pts[0])] + [cv.Path.LineTo(*p) for p in pts[1:]]
                if s.glow:
                    sc.add(cv.Path(els, paint=pal.stroke(pal.rgba(s.color, 0.10), s.width + 10)),
                           cv.Path(els, paint=pal.stroke(pal.rgba(s.color, 0.20), s.width + 5)))
                sc.add(cv.Path(els, paint=pal.stroke(col, s.width, [6, 4] if s.dashed else None)))
            if s.markers:
                for i in run:
                    cx, cy = xs[i], ys(vals[i])  # type: ignore[arg-type]
                    sc.add(cv.Circle(cx, cy, s.markers / 2, pal.fill(s.color)))
                    if s.marker_ring:
                        sc.add(cv.Circle(cx, cy, s.markers / 2, pal.stroke("#ffffff", 1.5)))


def draw_events(sc: Scene, xs: Sequence[float], ys: Scale, series: Sequence[Series], events: Sequence[EventMark]) -> None:
    for ev in events:
        if not (0 <= ev.series < len(series)) or not (0 <= ev.index < len(xs)):
            continue
        v = finite(series[ev.series].values[ev.index]) if ev.index < len(series[ev.series].values) else None
        if v is None:
            continue
        cx, cy = xs[ev.index], ys(v)
        sc.add(cv.Circle(cx, cy, 5.5, pal.fill(pal.SECOND)), cv.Circle(cx, cy, 5.5, pal.stroke(pal.T, 2)),
               txt(cx, cy - 12, ev.label, size=11, v="b"))


def _domain(series: Sequence[Series], bands: Sequence[Band], y_min: float | None, y_max: float | None, extra: Sequence[float] = ()) -> tuple[float, float] | None:
    vals: list[float] = list(extra)
    for s in series:
        vals += [v for v in (finite(x) for x in s.values) if v is not None]
        if s.area and s.area_base is not None:
            vals.append(s.area_base)
    for b in bands:
        vals += [v for v in (finite(x) for x in list(b.lower) + list(b.upper)) if v is not None]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    return (y_min if y_min is not None else lo, y_max if y_max is not None else hi)


def column_hits(
    sc: Scene, plot: Plot, x: Sequence[Any], xs: Sequence[float], ys: Scale, series: Sequence[Series],
    bands: Sequence[Band], time_fmt: str, extra_rows: Callable[[int], list[tuple[str | None, str, str | None]]] | None = None,
) -> None:
    n = len(xs)
    for i in range(n):
        rows: list[tuple[str | None, str, str | None]] = []
        ypts: list[float] = []
        for s in series:
            v = finite(s.values[i]) if i < len(s.values) else None
            if v is not None:
                rows.append((s.name, fmt(v, s.decimals, unit=s.unit), s.color))
                ypts.append(ys(v))
        for b in bands:
            lo = finite(b.lower[i]) if i < len(b.lower) else None
            hi = finite(b.upper[i]) if i < len(b.upper) else None
            if lo is not None and hi is not None:
                rows.append((b.name, f"{fmt(lo, b.decimals, unit=b.unit)} – {fmt(hi, b.decimals, unit=b.unit)}", b.color))
        if extra_rows:
            rows += extra_rows(i)
        if not rows:
            continue
        left = (xs[i - 1] + xs[i]) / 2 if i > 0 else plot.x0 - 4
        right = (xs[i] + xs[i + 1]) / 2 if i < n - 1 else plot.x1 + 4
        sc.hits.append(Hit("rect", (left, plot.y0, max(right - left, 1.0), plot.h), x_label(x[i], time_fmt), rows,
                           anchor=(xs[i], min(ypts) if ypts else plot.y0 + 20)))


def draw_today(sc: Scene, plot: Plot, x_px: float, label: str = "today") -> None:
    sc.add(line(x_px, plot.y0, x_px, plot.y1, pal.SECOND, 1.5, [5, 4]))
    flip = x_px + 50 > plot.x1
    sc.add(txt(x_px + (-6 if flip else 6), plot.y0 + 9, label, size=12, h="r" if flip else "l"))


def _label_idx(n: int, plot_w: float, every: int | None) -> list[int]:
    if n == 0:
        return []
    step = every if every else max(1, math.ceil(n / max(2, plot_w / 96)))
    return list(range(0, n, step))


def line_chart(
    x: Sequence[Any],
    series: Sequence[Series],
    *,
    bands: Sequence[Band] = (),
    events: Sequence[EventMark] = (),
    today: Any = None,
    x_name: str | None = None,
    y_name: str | None = None,
    x_labels: Sequence[str] | None = None,
    x_label_every: int | None = None,
    x_format: str = "%b %y",
    tooltip_date_format: str = "%d %b %Y",
    edge_to_edge: bool | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    nice: bool = True,
    margins: Margins | None = None,
    legend_at: str = "top-right",
    width: float = 600,
    height: float = 300,
    unavailable_reason: str | None = None,
    empty_title: str = "No data",
    insight: str | None = None,
) -> ft.Container:
    """Time (x are date/datetime) or category (x are labels) line chart.

    Missing values (None/NaN) break the line; they are never drawn as 0. series[i].values align with x.
    bands = forecast fans; events = point markers (ex-div); today = x value of the vertical "today" marker.
    """
    xl = list(x)

    def build(w: float, h: float) -> Scene:
        dom = _domain(series, bands, y_min, y_max)
        if unavailable_reason or dom is None or not xl:
            return empty_scene(w, h, empty_title, unavailable_reason or "No values to chart.", insight or "")
        sc = Scene(w, h, label=insight or "")
        plot = Plot(w, h, margins or Margins(62, 20, 36, 52))
        timeaxis = is_time(xl)
        edge = edge_to_edge if edge_to_edge is not None else timeaxis
        xs = x_positions(xl, plot.x0, plot.x1, edge_to_edge=edge)
        ys = y_axis(sc, plot, dom[0], dom[1], name=y_name, nice=nice)
        x_axis_line(sc, plot, x_name)
        labels = list(x_labels) if x_labels is not None else [x_label(v, x_format) for v in xl]
        for i in _label_idx(len(xl), plot.w, x_label_every):
            sc.add(txt(xs[i], plot.y1 + 14, labels[i], color=pal.T2 if timeaxis else pal.T))
        draw_bands(sc, xs, ys, bands)
        draw_series(sc, plot, xs, ys, series)
        draw_events(sc, xs, ys, series, events)
        if today is not None:
            tx = x_positions(xl + [today], plot.x0, plot.x1, edge_to_edge=edge)[-1] if timeaxis else None
            if tx is not None and plot.x0 <= tx <= plot.x1:
                draw_today(sc, plot, tx)
        column_hits(sc, plot, xl, xs, ys, series, bands, tooltip_date_format)
        legend(sc, plot, [LegendItem(s.name, s.color, "dashed" if s.dashed else "line", marker=s.markers > 0 or s.glow or s.width >= 3)
                          for s in series if s.legend], where=legend_at)
        return sc

    return make_chart(build, width, height)


def drawdown_panel(
    x: Sequence[Any],
    drawdown: Sequence[float | None],
    *,
    x_name: str | None = "Date",
    y_name: str = "Drawdown (%)",
    x_format: str = "%b %y",
    margins: Margins | None = None,
    width: float = 600,
    height: float = 160,
    unavailable_reason: str | None = None,
    empty_title: str = "No drawdown",
    insight: str | None = None,
) -> ft.Container:
    """Drawdown line + red area to 0 (values in percent, <= 0). Standalone panel; shares x logic with the hero chart."""
    ser = Series("Drawdown", drawdown, pal.NEG, width=2.0, area=True, area_alpha=(0.05, 0.50), area_base=0.0, unit="%", decimals=1)
    return line_chart(x, [ser], x_name=x_name, y_name=y_name, x_format=x_format, y_max=0.0, nice=False,
                      margins=margins or Margins(68, 26, 16, 52), width=width, height=height,
                      unavailable_reason=unavailable_reason, empty_title=empty_title, insight=insight)


def price_drawdown_chart(
    x: Sequence[Any],
    series: Sequence[Series],
    drawdown: Sequence[float | None],
    *,
    bands: Sequence[Band] = (),
    events: Sequence[EventMark] = (),
    today: Any = None,
    price_name: str = "Price",
    x_format: str = "%b %y",
    tooltip_date_format: str = "%d %b %Y",
    width: float = 1169,
    height: float = 470,
    unavailable_reason: str | None = None,
    empty_title: str = "No price history",
    insight: str | None = None,
) -> ft.Container:
    """Stock hero: price/forecast panel (top ~56%) and drawdown panel sharing the x axis (spec 6.3)."""
    xl = list(x)

    def build(w: float, h: float) -> Scene:
        dom = _domain(series, bands, None, None)
        if unavailable_reason or dom is None or not xl:
            return empty_scene(w, h, empty_title, unavailable_reason or "No values to chart.", insight or "")
        sc = Scene(w, h, label=insight or "")
        up = Plot(w, h, Margins(68, 26, 40, h - (40 + 0.56 * h)))
        lo_top = 0.74 * h
        dn = Plot(w, h, Margins(68, 26, lo_top, 52))
        xs = x_positions(xl, up.x0, up.x1, edge_to_edge=True)
        ys = y_axis(sc, up, dom[0], dom[1], name=price_name)
        dd = [finite(v) for v in drawdown]
        ddk = [v for v in dd if v is not None]
        dlo = min(ddk) if ddk else -1.0
        ticks = [dlo, dlo / 2, 0.0] if dlo < 0 else [-1.0, -0.5, 0.0]
        yd = y_axis(sc, dn, min(ticks), 0.0, name="Drawdown (%)", ticks=ticks, nice=False, fmt_fn=lambda v: fmt(v, 1))
        sc.add(line(up.x0, up.y1, up.x1, up.y1, pal.AXIS, 1))
        x_axis_line(sc, dn, "Date", name_gap=38)
        for i in _label_idx(len(xl), dn.w, max(1, round(60 * len(xl) / max(len(xl), 60))) if len(xl) > 120 else None):
            sc.add(txt(xs[i], dn.y1 + 16, x_label(xl[i], x_format), color=pal.T2))
        draw_bands(sc, xs, ys, bands)
        draw_series(sc, up, xs, ys, series)
        draw_events(sc, xs, ys, series, events)
        draw_series(sc, dn, xs, yd, [Series("Drawdown", drawdown, pal.NEG, 2.0, area=True, area_alpha=(0.05, 0.50), area_base=0.0)])
        if today is not None:
            tx = x_positions(xl + [today], up.x0, up.x1, edge_to_edge=True)[-1]
            if up.x0 <= tx <= up.x1:
                draw_today(sc, up, tx)
                sc.add(line(tx, dn.y0, tx, dn.y1, pal.SECOND, 1, [5, 4]))
        full = Plot(w, h, Margins(68, 26, 40, 52))
        column_hits(sc, full, xl, xs, ys, series, bands, tooltip_date_format,
                    extra_rows=lambda i: [("Drawdown", fmt(dd[i], 1, unit="%"), pal.NEG)] if i < len(dd) and dd[i] is not None else [])
        legend(sc, up, [LegendItem(s.name, s.color, "dashed" if s.dashed else "line") for s in series if s.legend], where="top-left", y=18)
        return sc

    return make_chart(build, width, height)


def sparkline(
    values: Sequence[float | None],
    *,
    color: str = pal.P,
    width: float = 120,
    height: float = 36,
    fill: bool = True,
    smooth: bool = True,
    line_width: float = 2.0,
    unavailable_reason: str | None = None,
    insight: str | None = None,
) -> ft.Container:
    """Axis-less sparkline for stat tiles. No data -> an em dash (never a flat zero line)."""
    vals = [finite(v) for v in values]

    def build(w: float, h: float) -> Scene:
        known = [v for v in vals if v is not None]
        if unavailable_reason or len(known) < 2:
            return empty_scene(w, h, "—", unavailable_reason or "", insight or "")
        sc = Scene(w, h, label=insight or "")
        lo, hi = min(known), max(known)
        if hi == lo:
            hi, lo = hi + 1, lo - 1
        ys = Scale(lo, hi, h - 3, 3)
        xs = [(w - 1) * i / (len(vals) - 1) for i in range(len(vals))]
        ser = Series("", vals, color, line_width, area=fill, smooth=smooth)
        draw_series(sc, Plot(w, h, Margins(0, 0, 3, 3)), xs, ys, [ser])
        return sc

    return make_chart(build, width, height)
