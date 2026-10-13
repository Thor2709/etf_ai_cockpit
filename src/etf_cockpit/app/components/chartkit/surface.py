"""Surface3D: painter's-algorithm shaded surface with a fixed camera (FINAL_UI_SPEC 9.6, 6.3)."""
from __future__ import annotations

import math
from typing import Sequence

import flet as ft

from etf_cockpit.app.components.chartkit import palette as pal
from etf_cockpit.app.components.chartkit.core import (
    Hit, Scene, empty_scene, finite, fmt, line, make_chart, nice_ticks, poly, tick_label, txt,
)


def surface3d(
    z: Sequence[Sequence[float | None]],
    x_values: Sequence[float],
    y_values: Sequence[float],
    *,
    x_name: str = "Horizon (months)",
    y_name: str = "Volatility (%)",
    z_name: str = "Return (%)",
    elevation: float = 24.0,
    azimuth: float = 30.0,
    z_unit: str = "",
    width: float = 600,
    height: float = 320,
    unavailable_reason: str | None = None,
    empty_title: str = "No scenario surface",
    empty_reason: str = "Needs forecasts for at least 3 horizons and 2 saved stress scenarios.",
    insight: str | None = None,
) -> ft.Container:
    """z[row][col]: rows = y_values (volatility scenarios), cols = x_values (horizons). Cells that are None or NaN
    are not drawn. Fewer than 3 columns or 2 rows of usable data -> EmptyState."""
    rows, cols = len(z), (len(z[0]) if z else 0)
    zf = [[finite(v) for v in r] for r in z]
    usable = [v for r in zf for v in r if v is not None]

    def build(w: float, h: float) -> Scene:
        if (unavailable_reason or cols < 3 or rows < 2 or len(x_values) != cols or len(y_values) != rows
                or len(usable) < 6):
            return empty_scene(w, h, empty_title, unavailable_reason or empty_reason, insight or "")
        sc = Scene(w, h, label=insight or "")
        zlo, zhi = min(usable), max(usable)
        zt, z0, z1 = nice_ticks(zlo, zhi, 4)
        el, az = math.radians(elevation), math.radians(azimuth)
        box_xy, box_z = 1.0, 0.46

        def world(ci: float, ri: float, zv: float) -> tuple[float, float, float]:
            return (ci / (cols - 1) * 2 - 1) * box_xy, (ri / (rows - 1) * 2 - 1) * box_xy, (zv - z0) / ((z1 - z0) or 1) * 2 * box_z

        def project(p: tuple[float, float, float]) -> tuple[float, float, float]:
            x, y, zz = p
            xr = x * math.cos(az) - y * math.sin(az)
            yr = x * math.sin(az) + y * math.cos(az)
            return xr, zz * math.cos(el) + yr * math.sin(el), yr  # screen x, screen-up, depth (larger = farther)

        corners = [project((sx, sy, sz)) for sx in (-1, 1) for sy in (-1, 1) for sz in (0, 2 * box_z)]
        minx, maxx = min(c[0] for c in corners), max(c[0] for c in corners)
        miny, maxy = min(c[1] for c in corners), max(c[1] for c in corners)
        pad_l, pad_r, pad_t, pad_b = 54, 40, 18, 52
        scale = min((w - pad_l - pad_r) / (maxx - minx), (h - pad_t - pad_b) / (maxy - miny))
        ox = pad_l + ((w - pad_l - pad_r) - (maxx - minx) * scale) / 2 - minx * scale
        oy = pad_t + ((h - pad_t - pad_b) - (maxy - miny) * scale) / 2 + maxy * scale

        def scr(p: tuple[float, float, float]) -> tuple[float, float]:
            px, py, _ = project(p)
            return ox + px * scale, oy - py * scale

        # floor grid + frame
        for ci in range(cols):
            sc.add(line(*scr(world(ci, 0, z0)), *scr(world(ci, rows - 1, z0)), pal.GRID, 1))
        for ri in range(rows):
            sc.add(line(*scr(world(0, ri, z0)), *scr(world(cols - 1, ri, z0)), pal.GRID, 1))
        floor = [world(0, 0, z0), world(cols - 1, 0, z0), world(cols - 1, rows - 1, z0), world(0, rows - 1, z0)]
        sc.add(poly([scr(p) for p in floor], pal.stroke(pal.AXIS, 1), close=True))

        # quads, far to near
        light = (-0.4, -0.5, 0.75)
        quads = []
        for ri in range(rows - 1):
            for ci in range(cols - 1):
                cells = [(ci, ri), (ci + 1, ri), (ci + 1, ri + 1), (ci, ri + 1)]
                vals = [zf[r][c] for c, r in cells]
                if any(v is None for v in vals):
                    continue
                pts3 = [world(c, r, v) for (c, r), v in zip(cells, vals)]  # type: ignore[arg-type]
                depth = sum(project(p)[2] for p in pts3) / 4
                quads.append((depth, pts3, sum(vals) / 4))  # type: ignore[arg-type]
        for _, pts3, mean in sorted(quads, key=lambda q: -q[0]):
            ux, uy, uz = (pts3[1][i] - pts3[0][i] for i in range(3))
            vx, vy, vz = (pts3[3][i] - pts3[0][i] for i in range(3))
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            lam = abs(nx * light[0] + ny * light[1] + nz * light[2]) / nl
            base = pal.ramp_color((mean - zlo) / ((zhi - zlo) or 1.0))
            col = pal.mix(base, "#000000", max(0.0, 0.32 - 0.36 * lam)) if lam < 0.9 else pal.mix(base, "#ffffff", 0.10)
            screen = [scr(p) for p in pts3]
            sc.add(poly(screen, pal.fill(col), close=True), poly(screen, pal.stroke("#33000000", 0.8), close=True))

        # axes: x along the front edge, y along the right edge, z on the left-most vertical edge
        step_x = 1 if cols <= 6 else 2
        for ci in range(0, cols, step_x):
            px, py = scr(world(ci, 0, z0))
            sc.add(txt(px, py + 18, fmt(x_values[ci], 0), size=12))
        mx, my = scr(world((cols - 1) / 2, 0, z0))
        sc.add(txt(mx, my + 40, x_name, size=13, weight=500, color=pal.T2))
        for ri in range(1, rows):
            px, py = scr(world(cols - 1, ri, z0))
            sc.add(txt(px + 12, py, fmt(y_values[ri], 0), size=12, h="l"))
        mx, my = scr(world(cols - 1, (rows - 1) / 2, z0))
        sc.add(txt(mx + 40, my + 8, y_name, size=13, weight=500, color=pal.T2, h="l", rotate=0))
        zc = min(((0, 0), (cols - 1, 0), (0, rows - 1), (cols - 1, rows - 1)), key=lambda c: scr(world(c[0], c[1], z0))[0])
        step = zt[1] - zt[0] if len(zt) > 1 else None
        for t in zt:
            ax, ay = scr(world(zc[0], zc[1], t))
            sc.add(line(ax - 4, ay, ax, ay, pal.AXIS, 1), txt(ax - 8, ay, tick_label(t, step), size=12, h="r"))
        a0, a1 = scr(world(zc[0], zc[1], z0)), scr(world(zc[0], zc[1], z1))
        sc.add(line(*a0, *a1, pal.AXIS, 1))
        sc.add(txt(a0[0] - 46, (a0[1] + a1[1]) / 2, z_name, size=13, weight=500, color=pal.T2, rotate=-math.pi / 2))

        # hover points at grid nodes
        for ri in range(rows):
            for ci in range(cols):
                v = zf[ri][ci]
                if v is None:
                    continue
                px, py = scr(world(ci, ri, v))
                sc.hits.append(Hit("circle", (px, py, 9), f"{fmt(x_values[ci], 0)} / {fmt(y_values[ri], 0)}", [
                    (x_name, fmt(x_values[ci], 0), None), (y_name, fmt(y_values[ri], 0), None),
                    (z_name, fmt(v, 1, signed=True, unit=z_unit), None)], anchor=(px, py)))
        return sc

    return make_chart(build, width, height)
