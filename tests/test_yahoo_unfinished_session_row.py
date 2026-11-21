"""Yahoo returns the latest session row unfinished (open and volume, no close): drop that row, not the instrument."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data import yfinance_provider

NAN = float("nan")


def _download(monkeypatch, close: list[float], adjusted: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "Open": [10.0, 10.5, 10.8], "High": [11.0, 11.0, 11.0], "Low": [9.0, 9.5, 9.5],
            "Close": close, "Adj Close": adjusted, "Volume": [100.0, 120.0, 90.0],
            "Dividends": [0.0, 0.0, 0.0], "Stock Splits": [0.0, 0.0, 0.0],
        },
        index=pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20"]),
    )
    monkeypatch.setattr(yfinance_provider, "_import_yfinance", lambda: SimpleNamespace(download=lambda *args, **kwargs: frame))
    provider = yfinance_provider.YFinanceProvider(default_currency="EUR")
    return provider._download_one(symbol="HEI.DE", etf_id="HEI", start_date=date(2026, 11, 6), end_date=date(2026, 11, 21), require_actions=True)


def test_unfinished_latest_row_is_dropped_and_the_completed_rows_are_kept(monkeypatch) -> None:
    out = _download(monkeypatch, close=[10.2, 10.6, NAN], adjusted=[10.2, 10.6, NAN])
    assert list(out["date"]) == [date(2026, 11, 18), date(2026, 11, 19)]
    assert out["adjusted_close"].notna().all() and out["actions_evidenced"].all()


@pytest.mark.parametrize(
    ("close", "adjusted"),
    [([10.2, NAN, 10.7], [10.2, NAN, 10.7]), ([10.2, 10.6, 10.7], [10.2, NAN, 10.7]), ([10.2, 10.6, 10.7], [10.2, 10.6, NAN])],
    ids=["gap-before-latest", "adjusted-gap-before-latest", "latest-close-without-adjusted"],
)
def test_any_other_missing_adjusted_close_still_rejects_the_instrument(monkeypatch, close, adjusted) -> None:
    with pytest.raises(ValueError, match="Adjusted close is missing or non-positive"):
        _download(monkeypatch, close=close, adjusted=adjusted)
