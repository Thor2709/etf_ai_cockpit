from __future__ import annotations

import pandas as pd

from etf_cockpit.application.data_service import _quarantine_invalid_ohlc
from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.universe_store import SPAREBANKEN_ROWS


def _result(frame: pd.DataFrame) -> ProviderResult:
    return ProviderResult("yfinance", "prices", "ok", "test", frame)


def test_invalid_ohlc_rows_are_quarantined_not_committed():
    frame = pd.DataFrame(
        {
            "etf_id": ["A", "A", "B"],
            "open": [10.0, 10.0, 5.0],
            "high": [11.0, 9.0, 6.0],  # second row: high below open -> impossible
            "low": [9.0, 8.0, 4.0],
            "close": [10.5, 8.5, 5.5],
        }
    )
    clean, quarantined = _quarantine_invalid_ohlc(_result(frame))
    assert len(clean.data) == 2
    assert len(quarantined) == 1
    assert quarantined["quarantine_reason"].tolist() == ["invalid_ohlc"]


def test_valid_frame_passes_through_untouched():
    frame = pd.DataFrame({"etf_id": ["A"], "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]})
    clean, quarantined = _quarantine_invalid_ohlc(_result(frame))
    assert quarantined is None
    assert clean.data.equals(frame)


def test_sparebank_fallback_symbols_are_listed_symbols():
    tickers = {row[1]: row[2] for row in SPAREBANKEN_ROWS}
    assert tickers["JAEREN"] == "JAREN.OL"
    assert "SADG" not in tickers  # merged into Sparebanken Norge (SBNOR) in 2024
