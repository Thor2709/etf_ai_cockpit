from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.data.validation import validate_prices


def _prices(*, outlier_at: int | None = None) -> pd.DataFrame:
    # Non-zero ordinary variation keeps the existing robust-sigma detector active.
    returns = 0.001 * np.sin(np.arange(512))
    if outlier_at is not None:
        returns[outlier_at] = 0.2
    close = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "date": pd.bdate_range("2023-01-02", periods=512),
        "etf_id": "ETF-A",
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "adjusted_close": close,
        "volume": 1000.0,
        "currency": "EUR",
    })


@pytest.mark.parametrize("explicit_as_of", [False, True])
def test_old_return_outlier_outside_window_does_not_warn(explicit_as_of: bool) -> None:
    # The final 312 sessions start at index 200; index 199 is just outside.
    prices = _prices(outlier_at=199)
    as_of = prices["date"].iloc[-1].date() if explicit_as_of else None
    assert validate_prices(prices, as_of_date=as_of).issues == []
    # Prove the injected move really is detected while it is in the window.
    earlier = validate_prices(prices.iloc[:400])
    assert "return_outlier" in {issue.code for issue in earlier.issues}


@pytest.mark.parametrize("outlier_at", [200, 511])
def test_return_outlier_inside_window_warns(outlier_at: int) -> None:
    # Include the earliest warm-up session as well as the evaluated session.
    report = validate_prices(_prices(outlier_at=outlier_at))
    assert [(issue.code, issue.severity, issue.message) for issue in report.issues] == [
        ("return_outlier", "warning", "One-day return exceeds 8 robust sigma."),
    ]


@pytest.mark.parametrize("volume", [0.0, np.nan])
@pytest.mark.parametrize(("position", "warns"), [(199, False), (200, True), (511, True)])
def test_zero_volume_window(position: int, warns: bool, volume: float) -> None:
    prices = _prices()
    prices.loc[position, "volume"] = volume
    report = validate_prices(prices)
    warnings = [issue for issue in report.issues if issue.code == "zero_volume"]
    assert [(issue.severity, issue.message) for issue in warnings] == (
        [("warning", "Volume is zero or missing for at least one row.")] if warns else []
    )
    # Missing numeric values must still block, even outside this warning window.
    assert ("invalid_price_values" in {issue.code for issue in report.issues}) == bool(np.isnan(volume))


@pytest.mark.parametrize(("position", "warns"), [(87, False), (88, True), (450, False)])
def test_window_ends_at_effective_as_of(position: int, warns: bool) -> None:
    prices = _prices(outlier_at=position)
    prices.loc[position, "volume"] = 0
    # With only 400 sessions known, the first of the final 312 is index 88.
    as_of = prices["date"].iloc[399].date()
    report = validate_prices(prices, as_of_date=as_of)
    codes = {issue.code for issue in report.issues}
    assert ("return_outlier" in codes) == warns
    assert ("zero_volume" in codes) == warns
    assert "future_dated_rows" in codes
    known = validate_prices(prices.iloc[:400], as_of_date=as_of)
    assert [issue for issue in report.issues if issue.code != "future_dated_rows"] == known.issues


def test_old_negative_volume_and_missing_days_still_report() -> None:
    prices = _prices()
    prices.loc[10, "volume"] = -1
    prices = prices.drop(index=range(20, 26))
    report = validate_prices(prices, calendar_resolver=lambda _: None)
    assert [(issue.code, issue.severity, issue.message) for issue in report.issues] == [
        ("missing_trading_days", "warning", "6 expected days missing. Exchange calendar unknown or uncertified; weekday fallback."),
        ("negative_volume", "block", "1 rows have negative volume."),
    ]
