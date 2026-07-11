from __future__ import annotations

import pandas as pd

from etf_cockpit.data.providers import PriceProvider


class AlphaVantageProvider(PriceProvider):
    name = "alphavantage"

    def fetch_daily_prices(self, symbol, start, end):  # type: ignore[no-untyped-def]
        return pd.DataFrame()

    def validate_symbol(self, symbol: str) -> bool:
        return bool(symbol)
