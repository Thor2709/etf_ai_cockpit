"""Wave 2 train F: stock value inputs (2026-11-23)."""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.analysis.stock_universe import as_traded_close, market_inputs, with_as_traded_factors
from etf_cockpit.data.stock_fundamentals import load_stock_config


def _legacy_prefix() -> pd.DataFrame:
    """Old rows stored before per-bar action evidence (False); the recent rows, with a later split, are evidenced."""

    return pd.DataFrame({
        "etf_id": ["NVDA"] * 4,
        "date": pd.to_datetime(["2022-10-17", "2022-11-30", "2024-06-10", "2024-06-11"]),
        "close": [11.888, 12.0, 121.0, 120.0],
        "adjusted_close": [11.5, 11.6, 120.5, 119.5],
        "volume": [100.0] * 4,
        "currency": ["USD"] * 4,
        "stock_splits": [0.0, 0.0, 10.0, 0.0],
        "dividends": [0.0] * 4,
        "actions_evidenced": [False, False, True, True],
    })


def _closes(prices: pd.DataFrame, day: date) -> list[tuple[float | None, str | None]]:
    """The close from the full series and from a decision-time cut that carries the full-series factors."""

    carried = with_as_traded_factors(prices)
    return [as_traded_close(prices, day), as_traded_close(carried.loc[carried["date"].dt.date <= day], day)]


def test_close_is_restored_when_every_later_row_is_evidenced():
    # Only the later rows' splits are reversed; they are evidenced, so the as-traded close is provable.
    assert _closes(_legacy_prefix(), date(2022, 11, 30)) == [(120.0, None)] * 2
    assert _closes(_legacy_prefix(), date(2024, 6, 11)) == [(120.0, None)] * 2


def test_unevidenced_split_in_the_reversed_window_stays_unavailable():
    prices = _legacy_prefix()
    prices.loc[2, "actions_evidenced"] = False  # the 10:1 split row is not evidenced
    for value, reason in _closes(prices, date(2022, 11, 30)):
        assert value is None and ("actions_evidence_missing" in reason or "split_history_invalid" in reason)
    # An unevidenced later row fails closed even when it shows no split.
    value, reason = as_traded_close(_legacy_prefix(), date(2022, 10, 17))
    assert value is None and "actions_evidence_missing" in reason


def test_unevidenced_dividend_rows_give_no_dividend_yield():
    prices = _legacy_prefix()
    prices.loc[1, "date"] = pd.Timestamp("2023-06-13")  # inside the trailing year before 2024-06-11, unevidenced
    market = market_inputs(prices, None, "USD", datetime(2024, 6, 12, 12, tzinfo=timezone.utc), pd.DataFrame(),
                           load_stock_config())
    assert market.price == 120.0
    assert market.dividends_per_share_12m is None and "actions_evidence_missing" in market.dividend_reason
