from __future__ import annotations

import pandas as pd

from etf_cockpit.data.duckdb_store import load_holdings


def current_holdings() -> pd.DataFrame:
    return load_holdings()


def portfolio_value(holdings: pd.DataFrame) -> float:
    return float(holdings["market_value_eur"].sum())
