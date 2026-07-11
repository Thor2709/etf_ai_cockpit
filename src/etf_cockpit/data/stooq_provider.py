from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from etf_cockpit.data.providers import PriceProvider


class StooqProvider(PriceProvider):
    name = "stooq"

    def fetch_daily_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        from io import StringIO

        frame = pd.read_csv(StringIO(response.text))
        if frame.empty:
            return frame
        frame = frame.rename(
            columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame["adjusted_close"] = frame["close"]
        frame["provider_symbol"] = symbol
        frame["source"] = self.name
        frame["is_adjusted"] = False
        return frame

    def validate_symbol(self, symbol: str) -> bool:
        try:
            end = date.today()
            start = end.replace(year=end.year - 1)
            return not self.fetch_daily_prices(symbol, start, end).empty
        except Exception:
            return False
