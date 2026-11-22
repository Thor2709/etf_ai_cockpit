"""D2 (OD-1 = b): one read-time reconstructed PIT rule for replay readers; stored stamps never change."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from etf_cockpit.data.import_pipeline import RECONSTRUCTED_PIT, reconstructed_price_availability
from etf_cockpit.data.replay_membership import ListingHistory
from tests.test_score_backfill import _config


def _stamps(*values):
    return pd.to_datetime(pd.Series(values), utc=True)


def test_reconstructed_rule_caps_stamps_at_the_session_close_and_labels_rows():
    stored = pd.DataFrame({
        "etf_id": ["AAA", "AAA", "AAA"],
        "date": [date(2024, 6, 26), date(2024, 6, 27), date(2024, 6, 28)],
        "available_at": _stamps("2024-06-26T20:00:00Z", "2026-11-20T03:00:00Z", None),
        "known_at": _stamps("2026-11-03T01:00:00Z", "2026-11-20T03:00:00Z", None),
    })
    original = stored.copy()

    replay = reconstructed_price_availability(stored)

    pd.testing.assert_frame_equal(stored, original)  # read time only: the stored stamps stay as fetched
    close = _stamps("2024-06-26T23:59:59Z", "2024-06-27T23:59:59Z", "2024-06-28T23:59:59Z")
    assert replay["available_at"].iloc[0] == pd.Timestamp("2024-06-26T20:00:00Z")  # an earlier fetch stamp stays
    assert replay["available_at"].iloc[1:].tolist() == close.iloc[1:].tolist()  # revised or unstamped: session close
    assert replay["known_at"].tolist() == close.tolist()
    assert replay["pit_basis"].eq(RECONSTRUCTED_PIT).all()


@pytest.mark.parametrize("stamp", [None, "2024-06-28T12:00:00"])  # empty, or without a timezone
def test_strict_etf_admission_counts_an_unstamped_genuine_bar_at_its_session_close(stamp):
    bar = {"etf_id": "VWCE", "date": "2024-06-28", "close": 100.0, "volume": 1000, "source": "yfinance",
           "available_at": stamp}
    history = ListingHistory().with_observed_trading(pd.DataFrame([bar]), _config())

    assert not history.snapshot(pd.Timestamp("2024-06-28T23:00:00Z").to_pydatetime(), ["VWCE"]).eligible_ids
    assert history.snapshot(date(2024, 6, 28), ["VWCE"]).observed_trading_ids == ("VWCE",)


def test_strict_etf_admission_counts_a_revised_bar_at_its_session_close():
    bar = {"etf_id": "VWCE", "date": "2024-06-28", "close": 100.0, "volume": 1000, "source": "yfinance",
           "available_at": pd.Timestamp("2026-11-21T02:00:00Z")}  # restamped by a later refetch

    snapshot = ListingHistory().with_observed_trading(pd.DataFrame([bar]), _config()).snapshot(date(2024, 6, 28), ["VWCE"])

    assert snapshot.observed_trading_ids == ("VWCE",)
    assert snapshot.pit_basis == RECONSTRUCTED_PIT
