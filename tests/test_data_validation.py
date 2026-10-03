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


def test_missing_dates_block_explicitly_and_never_raise_nat_comparison_errors() -> None:
    config = load_config()
    as_of = pd.Timestamp("2026-06-26").date()
    prices = generate_sample_prices(config, periods=300, end_date=as_of)
    baseline = validate_prices(prices, as_of_date=as_of)
    assert "invalid_dates" not in {issue.code for issue in baseline.issues}

    damaged = prices.copy()
    damaged["date"] = pd.to_datetime(damaged["date"])
    damaged.loc[damaged.index[:2], "date"] = pd.NaT
    report = validate_prices(damaged, as_of_date=as_of)
    blocked = {issue.code for issue in report.issues if issue.severity == "block"}
    assert "invalid_dates" in blocked
    assert report.as_of_date == as_of

    # Without an explicit as-of the latest valid date is used, not a NaT/date comparison.
    assert validate_prices(damaged).as_of_date == max(pd.to_datetime(prices["date"]).dt.date)

    all_missing = prices.copy()
    all_missing["date"] = pd.NaT
    only = validate_prices(all_missing, as_of_date=as_of)
    assert [issue.code for issue in only.issues] == ["invalid_dates"]
