"""Sankey and Treemap (FINAL_UI_SPEC 4.2, 6.7)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import flet as ft
from flet import canvas as cv

from etf_cockpit.app.components.chartkit import palette as pal
from etf_cockpit.app.components.chartkit.core import Hit, Scene, empty_scene, finite, fmt, make_chart, txt


# ======================================================================== Sankey
@dataclass
class SankeyNode:
    name: str
    color: str = pal.P


@dataclass
class SankeyLink:
    source: str
    target: str
    value: float


def sankey(
    nodes: Sequence[SankeyNode],
    links: Sequence[SankeyLink],
    *,
    node_width: float = 16,
    node_gap: float = 14,
    inset: tuple[float, float, float, float] = (10, 10, 120, 10),  # left, top, right, bottom
    link_opacity: float = 0.5,
    unit: str = "",
    width: float = 600,
    height: float = 300,
    unavailable_reason: str | None = None,
    empty_title: str = "No causal path",
    insight: str | None = None,
) -> ft.Container:
    """Sankey: node width 16, gap 14, curved links at 50 % opacity with a source -> target colour gradient."""
    nlist = list(nodes)

    def build(w: float, h: float) -> Scene:
        index = {n.name: i for i, n in enumerate(nlist)}
        good = [(index[lk.source], index[lk.target], finite(lk.value)) for lk in links
                if lk.source in index and lk.target in index and lk.source != lk.target and (finite(lk.value) or 0) > 0]
        if unavailable_reason or not good:
            return empty_scene(w, h, empty_title, unavailable_reason or "No links to draw.", insight or "")
        sc = Scene(w, h, label=insight or "")
        n = len(nlist)
        depth = [0] * n
        for _ in range(n):  # longest path, bounded passes (cycle safe)
            for s, t, _v in good:
                if depth[t] < depth[s] + 1 and depth[s] + 1 < n:
                    depth[t] = depth[s] + 1
        used = sorted({i for s, t, _ in good for i in (s, t)})
        cols = sorted({depth[i] for i in used})
        colmap = {d: k for k, d in enumerate(cols)}
        incoming = {i: sum(v for s, t, v in good if t == i) for i in used}
        outgoing = {i: sum(v for s, t, v in good if s == i) for i in used}
        size = {i: max(incoming[i], outgoing[i]) for i in used}
        left, top, right, bottom = inset
        area_h = h - top - bottom
        by_col: dict[int, list[int]] = {}
        for i in used:
            by_col.setdefault(colmap[depth[i]], []).append(i)
        k = min((area_h - node_gap * (len(m) - 1)) / sum(size[i] for i in m) for m in by_col.values())
        k = max(k, 0.0001)
        ncols = len(cols)
        span = w - left - right - node_width
        colx = {c: left + (span * c / (ncols - 1) if ncols > 1 else 0) for c in range(ncols)}
        pos: dict[int, tuple[float, float, float]] = {}  # node -> (x, y, height)
        for c, members in by_col.items():
            total = sum(size[i] * k for i in members) + node_gap * (len(members) - 1)
            y = top + (area_h - total) / 2
            for i in members:
                pos[i] = (colx[c], y, size[i] * k)
                y += size[i] * k + node_gap
        out_off = {i: 0.0 for i in used}
        in_off = {i: 0.0 for i in used}
        for s, t, v in sorted(good, key=lambda g_: (pos[g_[1]][1], pos[g_[0]][1])):
            sx, sy, _ = pos[s]
            tx, ty, _ = pos[t]
            lh = v * k
            y0s, y0t = sy + out_off[s], ty + in_off[t]
            out_off[s] += lh
            in_off[t] += lh
            x0, x1 = sx + node_width, tx
            xm = (x0 + x1) / 2
            els = [cv.Path.MoveTo(x0, y0s), cv.Path.CubicTo(xm, y0s, xm, y0t, x1, y0t), cv.Path.LineTo(x1, y0t + lh),
                   cv.Path.CubicTo(xm, y0t + lh, xm, y0s + lh, x0, y0s + lh), cv.Path.Close()]
            paint = ft.Paint(gradient=ft.PaintLinearGradient(
                (x0, 0), (x1, 0), [pal.rgba(nlist[s].color, link_opacity), pal.rgba(nlist[t].color, link_opacity)]),
                style=ft.PaintingStyle.FILL)
            sc.add(cv.Path(els, paint=paint))
            sc.hits.append(Hit("rect", (xm - 14, min(y0s, y0t), 28, abs(y0t - y0s) + lh),
                               f"{nlist[s].name} → {nlist[t].name}", [(None, fmt(v, 1, unit=unit), nlist[s].color)]))
        for i in used:
            x, y, nh = pos[i]
            sc.add(cv.Rect(x, y, node_width, max(nh, 2.0), border_radius=3, paint=pal.fill(nlist[i].color)))
            sc.add(txt(x + node_width + 8, y + nh / 2, nlist[i].name, size=12.5, h="l", max_width=right - 12 if depth[i] == cols[-1] else None))
            sc.hits.insert(0, Hit("rect", (x, y, node_width, max(nh, 2.0)), nlist[i].name,
                                  [("In", fmt(incoming[i], 1, unit=unit), None), ("Out", fmt(outgoing[i], 1, unit=unit), None)],
                                  anchor=(x + node_width, y)))
        return sc

    return make_chart(build, width, height)


# ======================================================================== Treemap
@dataclass
class TreeItem:
    name: str
    weight: float
    ret: float | None = None  # return in percent; None = unavailable (neutral tile)
    short: str | None = None  # label for tiles < 3 % ("RE")


def squarify(weights: Sequence[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Squarified treemap layout (Bruls et al.). weights must be > 0 and sorted descending; returns rects in order."""
    total = sum(weights)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0, 0) for _ in weights]
    scale = w * h / total
    areas = [wt * scale for wt in weights]
    rects: list[tuple[float, float, float, float]] = []
    i = 0
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        j = i + 1

        def worst(r: list[float]) -> float:
            s = sum(r)
            return max(max(side * side * a / (s * s), s * s / (side * side * a)) for a in r)

        while j < len(areas) and worst(row + [areas[j]]) <= worst(row):
            row.append(areas[j])
            j += 1
        s = sum(row)
        if w >= h:  # lay the row as a column on the left
            cw = s / h
            cy = y
            for a in row:
                rects.append((x, cy, cw, a / cw))
                cy += a / cw
            x += cw
            w -= cw
        else:
            rh = s / w
            cx = x
            for a in row:
                rects.append((cx, y, a / rh, rh))
                cx += a / rh
            y += rh
            h -= rh
        i = j
    return rects


def treemap(
    items: Sequence[TreeItem],
    *,
    inset: tuple[float, float, float, float] = (6, 6, 62, 6),  # left, top, right (legend), bottom
    gap: float = 8,
    radius: float = 22,
    ret_unit: str = "%",
    weight_unit: str = "%",
    width: float = 871,
    height: float = 360,
    unavailable_reason: str | None = None,
    empty_title: str = "No sector data",
    insight: str | None = None,
) -> ft.Container:
    """Squarified treemap: size = weight, colour = return on the return ramp, gap 8, radius 22, no borders,
    shadow 0 7 16, vertical colour legend on the right. Items without a return use a neutral tile."""
    pool = [t for t in items if (finite(t.weight) or 0) > 0]

    def build(w: float, h: float) -> Scene:
        if unavailable_reason or not pool:
            return empty_scene(w, h, empty_title, unavailable_reason or "No weights to chart.", insight or "")
        sc = Scene(w, h, label=insight or "")
        ordered = sorted(pool, key=lambda t: -t.weight)
        total = sum(t.weight for t in ordered)
        lft, t0, r, b = inset
        rects = squarify([t.weight for t in ordered], lft, t0, w - lft - r, h - t0 - b)
        rets = [v for v in (finite(t.ret) for t in ordered) if v is not None]
        rlo, rhi = (min(rets), max(rets)) if rets else (0.0, 0.0)
        for t, (x, y, rw, rh) in zip(ordered, rects):
            g = gap / 2
            tx, ty, tw, th = x + g, y + g, max(rw - gap, 1.0), max(rh - gap, 1.0)
            rv = finite(t.ret)
            col = "#4a5568" if rv is None else pal.ramp_color((rv - rlo) / (rhi - rlo) if rhi > rlo else 0.5)
            rad = min(radius, tw / 2, th / 2)
            sc.add(cv.Rect(tx, ty + 7, tw, th, border_radius=rad, paint=pal.fill("#47000000")))
            sc.add(cv.Rect(tx, ty, tw, th, border_radius=rad, paint=pal.fill(col)))
            share = t.weight / total * 100
            name = (t.short or t.name[:3]) if share < 3 else t.name
            body = f"{name}\n{fmt(share, 1, unit=weight_unit)}"
            if share >= 8:
                body += f"  ·  {fmt(rv, 1, signed=True, unit=ret_unit)}"
            if tw >= 34 and th >= 28:
                sc.add(txt(tx + tw / 2, ty + th / 2, body, size=14, weight=600, color="#ffffff", shadow=True, max_width=tw - 8))
            sc.hits.append(Hit("rect", (tx, ty, tw, th), t.name, [
                ("Weight", fmt(share, 1, unit=weight_unit), col), ("Return", fmt(rv, 1, signed=True, unit=ret_unit), None)]))
        if rets:
            bx, by1 = w - r + 8, h - 6
            by0 = by1 - 140
            ramp = list(reversed(pal.RETURN_RAMP))
            sc.add(cv.Rect(bx, by0, 12, 140, border_radius=6, paint=ft.Paint(
                gradient=ft.PaintLinearGradient((0, by0), (0, by1), ramp), style=ft.PaintingStyle.FILL)))
            sc.add(txt(bx + 18, by0 + 4, fmt(rhi, 1, signed=True, unit=ret_unit), size=11.5, h="l"),
                   txt(bx + 18, by1 - 4, fmt(rlo, 1, signed=True, unit=ret_unit), size=11.5, h="l"))
        return sc

    return make_chart(build, width, height)
