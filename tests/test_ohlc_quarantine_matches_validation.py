from __future__ import annotations

import pandas as pd

from etf_cockpit.data.price_quarantine import quarantine_invalid_ohlc
from etf_cockpit.data.providers import ProviderResult


def test_zero_low_row_is_quarantined_not_a_commit_block():
    # Yahoo rows such as CNL 2021-10-08 (low 0.0) passed the quarantine, then blocked the whole commit as invalid_ohlc.
    frame = pd.DataFrame(
        {"etf_id": ["A", "A"], "open": [1.2, 1.2], "high": [2.4, 2.4], "low": [0.0, 1.0], "close": [1.2, 1.2]}
    )
    clean, quarantined = quarantine_invalid_ohlc(ProviderResult("yfinance", "prices", "ok", "test", frame))
    assert quarantined["low"].tolist() == [0.0]
    assert clean.data["low"].tolist() == [1.0]
