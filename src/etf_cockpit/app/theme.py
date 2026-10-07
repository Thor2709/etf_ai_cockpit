from __future__ import annotations

from pathlib import Path

APP_NAME = "AI Evidence Cockpit"
APP_TAGLINE = "Local-first ETF research and evidence"

# Shared visual tokens keep the Flet implementation predictable across routes.
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

RADIUS_SM = 8
RADIUS_MD = 14
RADIUS_LG = 30
RADIUS_INNER = 22

FONT_XS = 11
FONT_SM = 12
FONT_MD = 14
FONT_LG = 17
FONT_XL = 20

# Aurelian Clear 3 (reference theme 25).
BG = "#0b1424"
SURFACE = "#0e1830"
SURFACE_2 = "#cc091020"
BORDER = "#33ffffff"
TEXT = "#f4f7fd"
MUTED = "#c3cde2"
GREEN = "#6fcfa6"
LIGHT_GREEN = "#8fdcbc"
AMBER = "#e6c27a"
RED = "#e8897c"
PURPLE = "#a99bf0"
CYAN = "#9ad1ff"
BLUE_GREY = "#8e9ab4"

# Named Flet equivalents for theme-25 CSS tokens.
GLASS_PANEL_GRADIENT = "linear-gradient(165deg,rgba(14,24,48,.30),rgba(8,16,36,.22))"
GLASS_PANEL_BLUR = 11
GLASS_PANEL_BORDER = "#33ffffff"
GLASS_PANEL_SHADOW = "inset 0 1px 0 rgba(255,255,255,.4),inset 0 2px 10px rgba(255,255,255,.05),inset 0 -2px 7px rgba(0,0,0,.28),0 1px 2px rgba(0,0,0,.3),0 14px 30px rgba(2,6,20,.3),0 40px 80px rgba(2,6,20,.4)"
RECESSED_WELL_GRADIENT = "linear-gradient(180deg,rgba(9,16,32,.88),rgba(9,16,32,.72))"
RECESSED_WELL_BORDER = "#12ffffff"
RAISED_CONTROL_GRADIENT = "linear-gradient(180deg,rgba(255,255,255,.26),rgba(255,255,255,.07))"
HAIRLINE_BORDER = "#24ffffff"
CARD_RADIUS = 30
INNER_RADIUS = 22
TEXT_SHADOW = "0 1px 8px rgba(0,0,0,.55)"
FOOTER_RAIL_BACKGROUND = GLASS_PANEL_GRADIENT
FOOTER_RAIL_BORDER = GLASS_PANEL_BORDER
FOOTER_RAIL_RADIUS = 24
QUAIL_SELECTED_GRADIENT = "linear-gradient(180deg,#47806b,#2a5645 55%,#21463a)"
QUAIL_SELECTED_COLORS = ("#47806b", "#2a5645", "#21463a")
QUAIL_SELECTED_INK = "#f0c2ae"
QUAIL_SELECTED_HIGHLIGHT = "#66ffe1d2"
QUAIL_SELECTED_SHADOW = "#10261e"
CYLINDER_BAR_COLORS = ("#6aaee8", "#c4e4ff", "#6aaee8")

ACTION_COLOURS = {
    "buy": GREEN,
    "add": LIGHT_GREEN,
    "add_candidate": LIGHT_GREEN,
    "hold": BLUE_GREY,
    "trim": AMBER,
    "trim_candidate": AMBER,
    "sell": RED,
    "no_trade": BLUE_GREY,
    "manual_review": PURPLE,
    "watchlist": CYAN,
}

SEVERITY_COLOURS = {
    "low": BLUE_GREY,
    "medium": AMBER,
    "high": RED,
    "block": RED,
    "warning": AMBER,
    "ok": GREEN,
}

STATE_COLOURS = {
    "empty": MUTED,
    "loading": CYAN,
    "success": GREEN,
    "warning": AMBER,
    "error": RED,
}

EVIDENCE_MODES = ("compact", "default", "advanced")
EVIDENCE_MODE_LABELS = {
    "compact": "Compact - decision summary",
    "default": "Default - evidence and uncertainty",
    "advanced": "Advanced - evidence and diagnostics",
}

# ---------------------------------------------------------------------------
# FINAL_UI_SPEC section 2 tokens (names follow the spec; flet-free plain data).
# Colours use Flet's "#AARRGGBB" notation where an alpha is required.
# ---------------------------------------------------------------------------


def rgba(red: int, green: int, blue: int, alpha: float) -> str:
    """Return a Flet "#AARRGGBB" colour for a CSS-style rgba() value."""
    return f"#{round(max(0.0, min(1.0, alpha)) * 255):02x}{red:02x}{green:02x}{blue:02x}"


def _white(alpha: float) -> str:
    return rgba(255, 255, 255, alpha)


def _black(alpha: float) -> str:
    return rgba(0, 0, 0, alpha)


# 2.1 colours: text and ink
INK = "#f4f7fd"
INK2 = "#c3cde2"
INK3 = "#8e9ab4"
ACC = "#9ad1ff"
CHART_T = "#eef1f7"
CHART_T2 = "#b9c2d6"

# 2.1 colours: semantic
POS = "#2fbf80"
NEG = "#ff7d6e"
POS2 = "#8cf5c6"
CHART_POS = "#6fcfa6"
CHART_NEG = "#e8897c"
STRIP_NEG = "#f0aa9e"

# 2.1 selected state (quail green + rose-gold ink); QUAIL_* names above stay valid.
SELECTED_BG = QUAIL_SELECTED_COLORS
SELECTED_INK = QUAIL_SELECTED_INK
SELECTED_UNDER = QUAIL_SELECTED_SHADOW
SELECTED_RIM = rgba(255, 225, 210, 0.45)
PRIMARY_RIM = rgba(255, 225, 210, 0.40)
PRIMARY_FILL = ("#47806b", "#21463a")

# 2.1 chart palette
CHART_PRIMARY = "#9ad1ff"
CHART_SECOND = "#e3ebf7"
CHART_MODEL = "#cfe8ff"
CHART_BENCHMARK = "#9aa6bd"
BAR_POSITIVE = ("#8fdcbc", "#4fae88")
BAR_NEGATIVE = ("#f0aaa0", "#c8625a")
BAR_BLUE = ("#c4e4ff", "#6aaee8")
BAR_GOLD = ("#f0d79a", "#c9a45e")
CATEGORICAL = ("#9ad1ff", "#6fcfb0", "#c9b8e8", "#e6c9a8", "#a9b6cc")
RETURN_RAMP = ("#a8605c", "#7c6f74", "#56768a", "#4b8fa6", "#5fb3b0")
GRID_LINE = _white(0.06)
AXIS_LINE = _white(0.26)
GAUGE_TRACK = _white(0.12)

# 2.2 typography
FONT_FAMILY = "Inter"
FONT_FAMILY_FALLBACK = ("Segoe UI",)
FONT_MONO = "Cascadia Mono"
FONT_MONO_FALLBACK = ("Consolas",)
HEADLINE_GRADIENT = ("#ffffff", "#d7e6ff")
TAG_TONES = {
    "ok": ("#8fdcbc", rgba(111, 207, 166, 0.16)),
    "warn": ("#e6c27a", rgba(230, 194, 122, 0.16)),
    "bad": ("#f0aaa0", rgba(232, 137, 124, 0.16)),
    "mute": ("#c3cde2", _white(0.10)),
}
DOT_COLOURS = {"ok": "#6fcfa6", "warn": "#e6c27a", "bad": "#e8897c", "info": "#9ad1ff"}

# 2.3 surfaces: gradients are (colour stops, angle degrees as CSS); shadows are
# (dx, dy, blur, spread, colour) drop shadows. Flutter has no inset shadow, so the
# kit emulates the "inset" parts with overlay gradients/rims.
GLASS_FILL = (rgba(14, 24, 48, 0.30), rgba(8, 16, 36, 0.22))
GLASS_FILL_SOLID = rgba(14, 24, 48, 0.72)  # "Reduce effects" replacement fill
GLASS_RIM_STOPS = (
    (0.0, _white(0.55)),
    (0.38, _white(0.07)),
    (0.62, _white(0.05)),
    (1.0, _white(0.20)),
)
GLASS_SHEEN_ALPHA = 0.14
GLASS_DROP_SHADOWS = (
    (0, 1, 2, 0, _black(0.30)),
    (0, 14, 30, 0, rgba(2, 6, 20, 0.30)),
)
WELL_FILL = rgba(9, 16, 32, 0.80)
WELL_RING = _white(0.07)
WELL_INSET_TOP = _black(0.35)
KPI_TILE_FILL = _black(0.14)
STAT_TILE_FILL = _black(0.20)
FIELD_FILL = _black(0.20)
SEGMENT_TRACK_FILL = _black(0.24)
RAISED_FILL = (_white(0.20), _white(0.07))
RAISED_RIM = _white(0.40)
RAISED_UNDER = _black(0.30)
RAISED_DROP = _black(0.25)
HAIRLINE = _white(0.07)
HAIRLINE_STRONG = _white(0.14)
HOVER_OVERLAY = _white(0.06)
ROW_HOVER = _white(0.04)
ROW_SELECTED_FILL = rgba(154, 209, 255, 0.08)

# Radii (spec 2.3). CARD_RADIUS above is already 30.
RADIUS_DOCK = 34
RADIUS_TOPBAR = 25
RADIUS_FOOTER = 24
RADIUS_WELL = 18
RADIUS_KPI = 16
RADIUS_FIELD = 12
RADIUS_SEGMENT_GROUP = 14
RADIUS_SEGMENT = 10
RADIUS_CTA = 13
RADIUS_PILL = 999
RADIUS_TRACK = 5

# Card padding: top, horizontal, bottom (quiet cards use the second tuple); snapped to the
# 4/8/12/16/20/24/28 spacing scale (owner rule 2026-10-07; spec says 22/24/18 and 18/20/14).
CARD_PADDING = (24, 24, 20)
CARD_PADDING_QUIET = (16, 20, 12)

# Asset names resolved by theme.asset_path().
ASSET_BACKGROUND = "background/bg_3200.jpg"
ASSET_FONT_INTER = "fonts/inter.woff2"

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def asset_path(relative: str) -> Path:
    """Return the packaged asset path (icons/, fonts/, background/) for a relative name."""
    return ASSETS_DIR / relative


def font_map() -> dict[str, str]:
    """Return the ``page.fonts`` mapping (paths are relative to ``ft.run(assets_dir=ASSETS_DIR)``)."""
    return {FONT_FAMILY: ASSET_FONT_INTER}
