from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.contracts import ProviderCapability, SourceAuthority
from etf_cockpit.data.providers import PriceProvider


class StooqProvider(PriceProvider):
    name = "stooq"

    def __init__(self, section: ProviderSection | None = None) -> None:
        self.section = section or ProviderSection()

    def probe_capabilities(self) -> tuple[ProviderCapability, ...]:
        active = (self.section.active_provider or "none").strip().lower()
        configured = active not in {"", "none"}
        return (ProviderCapability(
            provider_id="stooq",
            dataset_type="prices",
            status="unavailable",
            authority=SourceAuthority.VENDOR,
            configured=configured,
            entitlement="configured" if configured else "disabled",
            rate_limit_note="probe only; no network request",
            last_success_at=None,
            error_fingerprint=None,
            secret_present=False,
            message="Stooq is optional and remains unavailable until explicitly enabled; no network request was made.",
        ),)

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
