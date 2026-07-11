from __future__ import annotations

ALLOWED_ACTIONS = ("hold", "no_trade", "add_candidate", "trim_candidate", "manual_review", "buy", "add", "trim", "sell")
ALLOWED_ROLES = (
    "core",
    "regional",
    "sector",
    "theme",
    "bond",
    "cash_proxy",
    "commodity",
    "hedge",
    "watchlist",
)
TRADING_DAYS_PER_YEAR = 252
APP_VERSION = "0.1.0"
