"""Shared chart machinery: scales, ticks, text, frame (axes/grid/legend), hit-testing, tooltip, empty state."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Sequence

import flet as ft
from flet import canvas as cv

from etf_cockpit.app.components.chartkit import palette as pal
from etf_cockpit.app.components.flet_compat import border_all

MINUS = "−"


# ----------------------------------------------------------------------------- numbers
def finite(value: Any) -> float | None:
    """Return float(value) or None for None/NaN/inf/non-numeric. Never 0 for missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def fmt(value: float | None, decimals: int = 1, *, signed: bool = False, unit: str = "") -> str:
    v = finite(value)
    if v is None:
        return "—"
    s = f"{abs(v):,.{decimals}f}"
    if v < 0 and float(s.replace(",", "")) != 0:
        s = MINUS + s
    elif signed and v > 0:
        s = "+" + s
    return s + unit


def nice_ticks(lo: float, hi: float, target: int = 5) -> tuple[list[float], float, float]:
    """Round tick values covering [lo, hi]; returns (ticks, new_lo, new_hi)."""
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        span = abs(hi) * 0.1 or 1.0
        lo, hi = lo - span, hi + span
    raw = (hi - lo) / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if raw <= step:
            break
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step
    n = int(round((end - start) / step))
    ticks = [round(start + i * step, 10) for i in range(n + 1)]
    return ticks, start, end


def tick_label(value: float, step_hint: float | None = None) -> str:
    if step_hint is not None and step_hint < 1:
        d = min(4, max(1, int(math.ceil(-math.log10(step_hint)))))
        return fmt(value, d)
    return fmt(value, 0 if abs(value) >= 100 or float(value).is_integer() else 1)


@dataclass
class Scale:
    """Linear scale domain -> pixel range (range may be inverted for y)."""

    d0: float
    d1: float
    r0: float
    r1: float

    def __call__(self, v: float) -> float:
        if self.d1 == self.d0:
            return (self.r0 + self.r1) / 2
        return self.r0 + (v - self.d0) / (self.d1 - self.d0) * (self.r1 - self.r0)

    def invert(self, px: float) -> float:
        if self.r1 == self.r0:
            return self.d0
        return self.d0 + (px - self.r0) / (self.r1 - self.r0) * (self.d1 - self.d0)


# ----------------------------------------------------------------------------- time x values
def is_time(x: Sequence[Any]) -> bool:
    return len(x) > 0 and all(isinstance(v, (date, datetime)) for v in x if v is not None)


def to_ordinal(v: Any) -> float:
    if isinstance(v, datetime):
        return v.toordinal() + (v.hour * 3600 + v.minute * 60 + v.second) / 86400
    return float(v.toordinal())


# ----------------------------------------------------------------------------- text
_ALIGN = {
    ("l", "t"): ft.Alignment(-1, -1), ("c", "t"): ft.Alignment(0, -1), ("r", "t"): ft.Alignment(1, -1),
    ("l", "m"): ft.Alignment(-1, 0), ("c", "m"): ft.Alignment(0, 0), ("r", "m"): ft.Alignment(1, 0),
    ("l", "b"): ft.Alignment(-1, 1), ("c", "b"): ft.Alignment(0, 1), ("r", "b"): ft.Alignment(1, 1),
}
_TEXT_ALIGN = {"l": ft.TextAlign.LEFT, "c": ft.TextAlign.CENTER, "r": ft.TextAlign.RIGHT}


def txt(
    x: float, y: float, s: str, *, size: float = 12.5, color: str = pal.T, weight: int = 400,
    h: str = "c", v: str = "m", rotate: float = 0.0, max_width: float | None = None,
    shadow: bool = False,
) -> cv.Text:
    style = ft.TextStyle(
        size=size, color=color, weight=getattr(ft.FontWeight, f"W_{weight}"),
        font_family=pal.FONT, font_family_fallback=pal.FONT_FALLBACK,
        shadow=ft.BoxShadow(blur_radius=4, color="#99000000", offset=ft.Offset(0, 1)) if shadow else None,
    )
    kw: dict[str, Any] = {}
    if max_width:
        kw["max_width"] = max_width
        kw["ellipsis"] = "…"
    return cv.Text(x=x, y=y, value=s, style=style, alignment=_ALIGN[(h, v)], text_align=_TEXT_ALIGN[h], rotate=rotate, **kw)


def text_width(s: str, size: float = 12.5) -> float:
    return sum(0.62 if c.isupper() or c.isdigit() else 0.52 for c in max(s.split("\n"), key=len)) * size


def line(x1: float, y1: float, x2: float, y2: float, color: str, width: float = 1.0, dash: list[float] | None = None) -> cv.Line:
    return cv.Line(x1=x1, y1=y1, x2=x2, y2=y2, paint=pal.stroke(color, width, dash))


def poly(points: Sequence[tuple[float, float]], paint: ft.Paint, close: bool = False) -> cv.Path:
    els: list[Any] = [cv.Path.MoveTo(points[0][0], points[0][1])]
    els += [cv.Path.LineTo(px, py) for px, py in points[1:]]
    if close:
        els.append(cv.Path.Close())
    return cv.Path(els, paint=paint)


def smooth_segments(points: Sequence[tuple[float, float]]) -> list[Any]:
    """Cubic path elements (Catmull-Rom -> Bezier); first element is MoveTo."""
    els: list[Any] = [cv.Path.MoveTo(points[0][0], points[0][1])]
    n = len(points)
    for i in range(n - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < n else p2
        els.append(cv.Path.CubicTo(
            p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
            p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6, p2[0], p2[1]))
    return els


# ----------------------------------------------------------------------------- hit testing
@dataclass
class Hit:
    """A hover target. kind: rect(x,y,w,h) | circle(cx,cy,r) | sector(cx,cy,r0,r1,a0,a1)."""

    kind: str
    geom: tuple[float, ...]
    title: str | None
    rows: list[tuple[str | None, str, str | None]]  # (series name, value text, colour dot)
    anchor: tuple[float, float] | None = None

    def contains(self, px: float, py: float) -> bool:
        g = self.geom
        if self.kind == "rect":
            return g[0] <= px <= g[0] + g[2] and g[1] <= py <= g[1] + g[3]
        if self.kind == "circle":
            return math.hypot(px - g[0], py - g[1]) <= g[2] + 3
        if self.kind == "sector":
            cx, cy, r0, r1, a0, a1 = g
            d = math.hypot(px - cx, py - cy)
            if not (r0 <= d <= r1):
                return False
            return (math.atan2(py - cy, px - cx) - a0) % math.tau <= (a1 - a0)
        return False

    def tooltip_anchor(self) -> tuple[float, float]:
        if self.anchor:
            return self.anchor
        g = self.geom
        if self.kind == "rect":
            return g[0] + g[2] / 2, g[1]
        return g[0], g[1]


def find_hit(hits: Sequence[Hit], px: float, py: float) -> Hit | None:
    for h in hits:
        if h.contains(px, py):
            return h
    return None


# ----------------------------------------------------------------------------- scene
@dataclass
class Scene:
    width: float
    height: float
    shapes: list[Any] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    empty: bool = False
    title: str = ""
    reason: str = ""
    label: str = ""  # semantics label (insight sentence)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, *shapes: Any) -> None:
        self.shapes.extend(shapes)

    def texts(self) -> list[str]:
        return [s.value for s in self.shapes if isinstance(s, cv.Text)]


def empty_scene(width: float, height: float, title: str, reason: str, label: str = "") -> Scene:
    return Scene(width, height, empty=True, title=title, reason=reason, label=label or f"{title}. {reason}")


def empty_state(title: str, reason: str, width: float | None = None, height: float | None = None) -> ft.Container:
    """EmptyState (spec 3.23): centred 14/600 ink2 title, 12.5 ink3 reason."""
    return ft.Container(
        width=width, height=height, alignment=ft.Alignment(0, 0), padding=16,
        content=ft.Column(
            [ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=pal.INK2, text_align=ft.TextAlign.CENTER),
             ft.Text(reason, size=12.5, color=pal.INK3, text_align=ft.TextAlign.CENTER)],
            spacing=4, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
    )


# ----------------------------------------------------------------------------- frame
@dataclass
class Margins:
    left: float = 62
    right: float = 20
    top: float = 20
    bottom: float = 48


@dataclass
class Plot:
    """Plot rectangle inside the canvas."""

    width: float
    height: float
    m: Margins

    @property
    def x0(self) -> float: return self.m.left
    @property
    def x1(self) -> float: return self.width - self.m.right
    @property
    def y0(self) -> float: return self.m.top
    @property
    def y1(self) -> float: return self.height - self.m.bottom
    @property
    def w(self) -> float: return max(1.0, self.x1 - self.x0)
    @property
    def h(self) -> float: return max(1.0, self.y1 - self.y0)


def y_axis(
    scene: Scene, plot: Plot, lo: float, hi: float, *, name: str | None = None, target: int = 5,
    nice: bool = True, ticks: list[float] | None = None, grid: bool = True, side: str = "left",
    fmt_fn: Callable[[float], str] | None = None, name_x: float | None = None,
) -> Scale:
    """Draw y grid + ticks + name; returns the value->y scale. Domain is extended to nice ticks when `nice`."""
    if ticks is None:
        ticks, nlo, nhi = nice_ticks(lo, hi, target)
        if nice:
            lo, hi = nlo, nhi
        else:
            ticks = [t for t in ticks if lo - 1e-9 <= t <= hi + 1e-9]
    scale = Scale(lo, hi, plot.y1, plot.y0)
    step = (ticks[1] - ticks[0]) if len(ticks) > 1 else None
    for t in ticks:
        y = scale(t)
        if grid and side == "left":
            scene.add(line(plot.x0, y, plot.x1, y, pal.GRID, 1))
        label = fmt_fn(t) if fmt_fn else tick_label(t, step)
        if side == "left":
            scene.add(txt(plot.x0 - 8, y, label, h="r"))
        else:
            scene.add(txt(plot.x1 + 8, y, label, h="l"))
    ax = plot.x0 if side == "left" else plot.x1
    scene.add(line(ax, plot.y0, ax, plot.y1, pal.AXIS, 1))
    if name:
        if side == "left":
            nx = name_x if name_x is not None else max(11.0, plot.x0 - 46)
        else:
            nx = name_x if name_x is not None else min(plot.width - 11.0, plot.x1 + 46)
        # Rotated name: keep its whole length inside the canvas (truncate with an ellipsis, shift the centre).
        length = min(text_width(name, 13) * 1.08, plot.height - 8)
        cy = min(max((plot.y0 + plot.y1) / 2, 4 + length / 2), plot.height - 4 - length / 2)
        scene.add(txt(nx, cy, name, size=13, weight=500, color=pal.T2, max_width=length,
                      rotate=-math.pi / 2 if side == "left" else math.pi / 2))
    return scale


def x_axis_line(scene: Scene, plot: Plot, name: str | None = None, *, name_gap: float = 36) -> None:
    scene.add(line(plot.x0, plot.y1, plot.x1, plot.y1, pal.AXIS, 1))
    if name:
        length = min(text_width(name, 13) * 1.08, plot.width - 8)
        cx = min(max((plot.x0 + plot.x1) / 2, 4 + length / 2), plot.width - 4 - length / 2)
        scene.add(txt(cx, min(plot.y1 + name_gap, plot.height - 12), name, size=13, weight=500, color=pal.T2, max_width=length))


def category_labels(
    scene: Scene, plot: Plot, labels: Sequence[str], xs: Sequence[float], *, size: float | None = None,
    every: int = 1, y_off: float = 14,
) -> None:
    size = size or (11.5 if len(labels) > 8 else 12.5)
    for i, (lab, x) in enumerate(zip(labels, xs)):
        if i % max(every, 1) == 0:
            scene.add(txt(x, plot.y1 + y_off, lab, size=size, h="c", color=pal.T,
                          max_width=max(24.0, plot.w / max(len(labels), 1) * every * 1.05)))


@dataclass
class LegendItem:
    label: str
    color: str
    kind: str = "line"  # line | dashed | bar
    marker: bool = True


def legend(scene: Scene, plot: Plot, items: Sequence[LegendItem], *, where: str = "top-right", y: float | None = None) -> None:
    if not items:
        return
    y = y if y is not None else 11.0
    widths = [(26 if it.kind != "bar" else 18) + text_width(it.label, 12.5) + 6 for it in items]
    gap = 14.0
    total = sum(widths) + gap * (len(items) - 1)
    x = (plot.x1 - total) if where == "top-right" else plot.x0 + 2
    if where == "bottom":
        x = (plot.width - total) / 2
        y = plot.height - 10
    for it, w in zip(items, widths):
        if it.kind == "bar":
            scene.add(cv.Rect(x, y - 6, 12, 12, border_radius=3, paint=pal.fill(it.color)))
            sx = x + 18
        else:
            scene.add(line(x, y, x + 22, y, it.color, 2.4, [4, 3] if it.kind == "dashed" else None))
            if it.marker and it.kind != "dashed":
                scene.add(cv.Circle(x + 11, y, 4.5, pal.fill(it.color)))
            sx = x + 28
        scene.add(txt(sx, y, it.label, h="l"))
        x += w + gap


def bar_rect(x: float, y: float, w: float, h: float, top: str, bottom: str, *, round_top: bool, radius: float = 6,
             round_left: bool = False, round_right: bool = False, border: bool = True) -> list[Any]:
    """Gradient bar with 1px white-40% border and one rounded side. y/h in canvas space (h >= 0)."""
    h = max(h, 1.0)
    if round_left or round_right:
        r_l, r_r = (radius if round_left else 0), (radius if round_right else 0)
        br = ft.BorderRadius.only(top_left=r_l, bottom_left=r_l, top_right=r_r, bottom_right=r_r)
    elif round_top:
        br = ft.BorderRadius.only(top_left=radius, top_right=radius)
    else:
        br = ft.BorderRadius.only(bottom_left=radius, bottom_right=radius)
    out: list[Any] = [cv.Rect(x, y, w, h, border_radius=br, paint=pal.vgradient(top, bottom, y, y + h))]
    if border:
        out.append(cv.Rect(x, y, w, h, border_radius=br, paint=pal.stroke(pal.BORDER40, 1)))
    return out


# ----------------------------------------------------------------------------- view / tooltip
class ChartHandle:
    """Held in control.data of every chart: current scene + resize()."""

    def __init__(self, build: Callable[[float, float], Scene], width: float, height: float) -> None:
        self._build = build
        self.scene = build(width, height)
        self.host = ft.Container(width=width, height=height)
        self.canvas = cv.Canvas(shapes=[], width=width, height=height)
        self.tip_box = ft.Column([], spacing=2, tight=True)
        self.tip = ft.Container(
            visible=False, left=0, top=0, content=self.tip_box,
            padding=ft.Padding.symmetric(vertical=8, horizontal=10),
            bgcolor=pal.WELL_DARK, border_radius=12, border=border_all(1, "#2effffff"),
            shadow=ft.BoxShadow(blur_radius=14, color="#66000000", offset=ft.Offset(0, 4)),
        )
        self._hit: Hit | None = None
        self._apply(width, height)

    # --- layout
    def _apply(self, width: float, height: float) -> None:
        sc = self.scene
        self.host.width, self.host.height = width, height
        if sc.empty:
            self.host.content = empty_state(sc.title, sc.reason, width, height)
            return
        self.canvas.shapes = sc.shapes
        self.canvas.width, self.canvas.height = width, height
        stack = ft.Stack([
            ft.GestureDetector(content=self.canvas, on_hover=self._hover, on_exit=self._exit,
                               hover_interval=30, exclude_from_semantics=True),
            self.tip,
        ], width=width, height=height)
        self.host.content = ft.Semantics(label=sc.label, content=stack) if sc.label else stack

    def resize(self, width: float, height: float) -> None:
        self.scene = self._build(width, height)
        self._hit = None
        self.tip.visible = False
        self._apply(width, height)
        try:
            self.host.update()
        except Exception:  # not mounted yet
            pass

    # --- hover
    def _hover(self, e: Any) -> None:
        pos = getattr(e, "local_position", None)
        if pos is None:
            return
        self.show_at(pos.x, pos.y)

    def show_at(self, px: float, py: float) -> Hit | None:
        hit = find_hit(self.scene.hits, px, py)
        if hit is self._hit:
            return hit
        self._hit = hit
        if hit is None:
            self.tip.visible = False
        else:
            self.tip_box.controls = tooltip_rows(hit)
            ax, ay = hit.tooltip_anchor()
            est_w = max([text_width(hit.title or "", 12.5)]
                        + [text_width(f"{(n + '  ') if n else ''}{v}", 12.5) + 18 for n, v, _ in hit.rows] + [60.0]) + 22
            est_h = 16 + (18 if hit.title else 0) + 18 * len(hit.rows)
            left = min(max(4.0, ax + 12), max(4.0, self.host.width - est_w - 4))
            top = min(max(4.0, ay - est_h - 8), max(4.0, self.host.height - est_h - 4))
            self.tip.left, self.tip.top, self.tip.visible = left, top, True
        try:
            self.tip.update()
        except Exception:
            pass
        return hit

    def _exit(self, _e: Any) -> None:
        self._hit = None
        self.tip.visible = False
        try:
            self.tip.update()
        except Exception:
            pass


def tooltip_rows(hit: Hit) -> list[ft.Control]:
    out: list[ft.Control] = []
    if hit.title:
        out.append(ft.Text(hit.title, size=12.5, weight=ft.FontWeight.W_700, color="#f5f8ff"))
    for name, value, colour in hit.rows:
        parts: list[ft.Control] = []
        if colour:
            parts.append(ft.Container(width=8, height=8, border_radius=4, bgcolor=colour))
        if name:
            parts.append(ft.Text(name, size=12.5, color=pal.INK2))
        parts.append(ft.Text(value, size=12.5, weight=ft.FontWeight.W_600, color="#f5f8ff"))
        out.append(ft.Row(parts, spacing=6, tight=True))
    return out


def make_chart(build: Callable[[float, float], Scene], width: float, height: float) -> ft.Container:
    """Wrap a scene builder as a control; control.data is the ChartHandle (scene, resize())."""
    handle = ChartHandle(build, width, height)
    handle.host.data = handle
    return handle.host


def scene_of(control: ft.Control) -> Scene:
    return control.data.scene
