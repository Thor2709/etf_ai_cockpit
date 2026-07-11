from __future__ import annotations

from pathlib import Path

from etf_cockpit.core.config import load_config
from etf_cockpit.data.duckdb_store import read_price_csv, write_prices
from etf_cockpit.data.validation import validate_prices


def import_price_csv(path: Path) -> None:
    config = load_config()
    prices = read_price_csv(path)
    report = validate_prices(prices, min_history_days=min(etf.min_history_days for etf in config.universe.etfs))
    if report.status == "Blocked":
        messages = "; ".join(issue.message for issue in report.issues if issue.severity == "block")
        raise ValueError(f"Price CSV blocked: {messages}")
    write_prices(prices)
