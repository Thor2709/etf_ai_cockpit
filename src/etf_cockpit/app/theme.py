from __future__ import annotations

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
SURFACE_2 = "rgba(9,16,32,.80)"
BORDER = "rgba(255,255,255,.20)"
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
GLASS_PANEL_BORDER = "rgba(255,255,255,.20)"
GLASS_PANEL_SHADOW = "inset 0 1px 0 rgba(255,255,255,.4),inset 0 2px 10px rgba(255,255,255,.05),inset 0 -2px 7px rgba(0,0,0,.28),0 1px 2px rgba(0,0,0,.3),0 14px 30px rgba(2,6,20,.3),0 40px 80px rgba(2,6,20,.4)"
RECESSED_WELL_GRADIENT = "linear-gradient(180deg,rgba(9,16,32,.88),rgba(9,16,32,.72))"
RECESSED_WELL_BORDER = "rgba(255,255,255,.07)"
RAISED_CONTROL_GRADIENT = "linear-gradient(180deg,rgba(255,255,255,.26),rgba(255,255,255,.07))"
HAIRLINE_BORDER = "rgba(255,255,255,.14)"
CARD_RADIUS = 30
INNER_RADIUS = 22
TEXT_SHADOW = "0 1px 8px rgba(0,0,0,.55)"
FOOTER_RAIL_BACKGROUND = GLASS_PANEL_GRADIENT
FOOTER_RAIL_BORDER = GLASS_PANEL_BORDER
FOOTER_RAIL_RADIUS = 24
QUAIL_SELECTED_GRADIENT = "linear-gradient(180deg,#47806b,#2a5645 55%,#21463a)"
QUAIL_SELECTED_COLORS = ("#47806b", "#2a5645", "#21463a")
QUAIL_SELECTED_INK = "#f0c2ae"
QUAIL_SELECTED_HIGHLIGHT = "rgba(255,225,210,.4)"
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
