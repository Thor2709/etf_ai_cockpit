from __future__ import annotations

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
