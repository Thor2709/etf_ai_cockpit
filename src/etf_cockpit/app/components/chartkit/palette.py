"""Chart colours (FINAL_UI_SPEC section 2.1). Copied from the spec; theme.py is owned elsewhere."""
from __future__ import annotations

import flet as ft

FONT = "Inter"
FONT_FALLBACK = ["Segoe UI", "sans-serif"]

# text
INK = "#f4f7fd"
INK2 = "#c3cde2"
INK3 = "#8e9ab4"
T = "#eef1f7"  # tick labels, data labels, legends
T2 = "#b9c2d6"  # axis names, gauge caption

# semantic (chart)
POS = "#6fcfa6"
NEG = "#e8897c"
AMBER = "#e6c27a"

# entities
P = "#9ad1ff"  # primary entity
SECOND = "#e3ebf7"  # second entity / baseline
VIO = "#cfe8ff"  # model / forecast
BM = "#9aa6bd"  # benchmark (always dashed)

# bar gradients (top, bottom)
GP = ("#8fdcbc", "#4fae88")
GN = ("#f0aaa0", "#c8625a")
GB = ("#c4e4ff", "#6aaee8")
GOLD = ("#f0d79a", "#c9a45e")
BAR_KINDS = {"pos": GP, "neg": GN, "blue": GB, "gold": GOLD}

CATEGORICAL = ["#9ad1ff", "#6fcfb0", "#c9b8e8", "#e6c9a8", "#a9b6cc"]
OTHER = "#a9b6cc"
RETURN_RAMP = ["#a8605c", "#7c6f74", "#56768a", "#4b8fa6", "#5fb3b0"]

GRID = "#0fffffff"  # white 6 %
AXIS = "#42ffffff"  # white 26 %
TRACK = "#1fffffff"  # white 12 %
BORDER40 = "#66ffffff"
WELL_DARK = "#e60e1830"


def rgba(color: str, alpha: float) -> str:
    """'#rrggbb' + alpha 0..1 -> '#aarrggbb' (Flet colour order)."""
    c = color.lstrip("#")[-6:]
    return f"#{round(max(0.0, min(1.0, alpha)) * 255):02x}{c}"


def _rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")[-6:]
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ra, rb))


def ramp_color(t: float, ramp: list[str] | None = None) -> str:
    """Interpolate the return ramp; t in 0..1 (low -> high)."""
    ramp = ramp or RETURN_RAMP
    t = max(0.0, min(1.0, t)) * (len(ramp) - 1)
    i = min(int(t), len(ramp) - 2)
    return mix(ramp[i], ramp[i + 1], t - i)


def vgradient(top: str, bottom: str, y0: float, y1: float, x: float = 0.0) -> ft.Paint:
    """Vertical fill gradient in canvas coordinates."""
    return ft.Paint(
        gradient=ft.PaintLinearGradient((x, y0), (x, y1 if y1 != y0 else y0 + 1), [top, bottom]),
        style=ft.PaintingStyle.FILL,
    )


def fill(color: str) -> ft.Paint:
    return ft.Paint(color=color, style=ft.PaintingStyle.FILL)


def stroke(color: str, width: float = 1.0, dash: list[float] | None = None) -> ft.Paint:
    kw: dict = {"color": color, "stroke_width": width, "style": ft.PaintingStyle.STROKE}
    if dash:
        kw["stroke_dash_pattern"] = dash
    return ft.Paint(stroke_cap=ft.StrokeCap.ROUND, stroke_join=ft.StrokeJoin.ROUND, **kw)
