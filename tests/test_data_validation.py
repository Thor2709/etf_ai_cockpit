from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.data.validation import validate_prices


def test_stale_data_blocks_signal_generation() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-01-01").date())
    report = validate_prices(prices, as_of_date=pd.Timestamp("2026-06-26").date())
    assert "stale_data" in {issue.code for issue in report.issues if issue.severity == "block"}


def test_invalid_ohlc_blocks_etf() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-06-26").date())
    prices.loc[0, "high"] = 0
    report = validate_prices(prices, as_of_date=pd.Timestamp("2026-06-26").date())
    assert "invalid_ohlc" in {issue.code for issue in report.issues}
