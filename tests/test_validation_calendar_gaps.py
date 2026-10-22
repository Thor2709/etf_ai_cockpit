from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json

import exchange_calendars as xcals
import pandas as pd

from etf_cockpit.data.market_calendar import CalendarCorrection, MarketCalendarService
from etf_cockpit.data.validation import validate_prices


def _identity(mic: str = "XNYS", tz: str = "America/New_York") -> dict:
    return {
        "status": "available",
        "instrument_id": "ETF-A",
        "identity_decision_id": "test-calendar",
        "identity_decision_time": "2020-01-02T00:00:00+00:00",
        "identity_effective_at": "2020-01-01",
        "identity_objects": [{
            "object_type": "listing",
            "object_id": f"listing:{mic}",
            "fields": {"mic": mic, "calendar_id": mic, "timezone": tz},
        }],
        "identity_history": [{"source_id": "identity-master:test-listing"}],
        "execution_allowed": False,
    }


def _prices(mic: str = "XNYS", tz: str = "America/New_York") -> pd.DataFrame:
    sessions = xcals.get_calendar(mic).sessions_in_range("2024-01-02", "2024-12-31")
    return pd.DataFrame({
        "date": sessions,
        "etf_id": "ETF-A",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "adjusted_close": 100.0,
        "volume": 1000,
        "currency": "USD",
        "calendar_identity": [_identity(mic, tz) for _ in sessions],
    })


def _gaps(prices: pd.DataFrame):
    return [issue for issue in validate_prices(prices, min_history_days=1).issues if issue.code == "missing_trading_days"]


def test_complete_exchange_sessions_exclude_holidays_per_instrument() -> None:
    ny = _prices()
    london = _prices("XLON", "Europe/London")
    london["etf_id"] = "ETF-B"
    for identity in london["calendar_identity"]:
        identity["instrument_id"] = "ETF-B"
    london["calendar_identity"] = london["calendar_identity"].map(json.dumps)
    for prices in (ny, london):
        dates = pd.DatetimeIndex(prices["date"])
        assert len(pd.bdate_range(dates.min(), dates.max()).difference(dates)) > 5
    assert pd.Timestamp("2024-11-28") not in set(ny["date"])
    assert pd.Timestamp("2024-11-28") in set(london["date"])
    assert _gaps(pd.concat([ny, london], ignore_index=True)) == []


def test_six_missing_sessions_warn_with_true_count_and_same_severity() -> None:
    prices = _prices().drop(index=range(10, 16))
    issues = _gaps(prices)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].message == "6 expected days missing. Exchange calendar XNYS."


def test_five_missing_sessions_do_not_warn() -> None:
    assert _gaps(_prices().drop(index=range(10, 15))) == []


def test_unknown_calendar_preserves_weekday_count_and_explains_fallback() -> None:
    prices = _prices()
    dates = pd.DatetimeIndex(prices["date"])
    expected = len(pd.bdate_range(dates.min(), dates.max()).difference(dates))
    unknown = prices.copy()
    unknown["calendar_identity"] = [_identity("ZZZZ", "UTC") for _ in prices.index]
    for frame in (prices.drop(columns="calendar_identity"), unknown):
        issues = _gaps(frame)
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].message == (
            f"{expected} expected days missing. Exchange calendar unknown or uncertified; weekday fallback."
        )


def test_invalid_conflicting_or_future_identity_cannot_hide_weekday_gaps() -> None:
    prices = _prices()
    wrong = _identity()
    wrong["instrument_id"] = "ETF-B"
    future = _identity()
    future["identity_decision_time"] = "2025-01-01T00:00:00+00:00"
    partial_history = _identity()
    partial_history["identity_effective_at"] = "2024-06-01"
    conflicted = deepcopy(_identity())
    conflicted["identity_conflict_ids"] = ["conflict"]
    for identity in (wrong, future, partial_history, conflicted, "{", None):
        frame = prices.copy()
        frame["calendar_identity"] = [identity for _ in frame.index]
        assert "weekday fallback" in _gaps(frame)[0].message
    prices.at[prices.index[-1], "calendar_identity"] = _identity("XLON", "Europe/London")
    assert "weekday fallback" in _gaps(prices)[0].message


def test_known_exceptional_closure_is_not_a_gap(monkeypatch) -> None:
    prices = _prices()
    missing = list(prices["date"].iloc[10:16])
    service = MarketCalendarService(corrections=[CalendarCorrection.exceptional_closure(
        correction_id="test-closure",
        mic="XNYS",
        session_date=missing[0].date(),
        revision=1,
        reason="Test closure",
        source_id="test-calendar-source",
        source_checksum="a" * 64,
        timezone="America/New_York",
        valid_from=date(2020, 1, 1),
        known_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
    )])
    monkeypatch.setattr(MarketCalendarService, "from_correction_ledger", lambda path: service)
    assert _gaps(prices.drop(index=range(10, 16))) == []
