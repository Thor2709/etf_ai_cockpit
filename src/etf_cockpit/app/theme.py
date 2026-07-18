from __future__ import annotations

APP_NAME = "AI Evidence Cockpit"
APP_TAGLINE = "Local-first ETF research and evidence"

# Shared visual tokens keep the Flet implementation predictable across routes
# and provide a stable contract for later frontend work.
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12

FONT_XS = 11
FONT_SM = 12
FONT_MD = 14
FONT_LG = 17
FONT_XL = 20

BG = "#101114"
SURFACE = "#181b20"
SURFACE_2 = "#22262e"
BORDER = "#343a46"
TEXT = "#f3f4f6"
MUTED = "#a7b0be"
GREEN = "#4ade80"
LIGHT_GREEN = "#9be7a7"
AMBER = "#f6b44b"
RED = "#f87171"
PURPLE = "#c084fc"
CYAN = "#67e8f9"
BLUE_GREY = "#7c8798"

ACTION_COLOURS = {
    "buy": GREEN,
    "add": LIGHT_GREEN,
    "add_candidate": LIGHT_GREEN,
    "hold": BLUE_GREY,
    "trim": AMBER,
    "trim_candidate": AMBER,
    "sell": RED,
    "no_trade": "#737373",
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
