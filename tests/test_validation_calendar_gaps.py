from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json

import exchange_calendars as xcals
import pandas as pd

from etf_cockpit.data.market_calendar import CalendarCorrection, MarketCalendarService, MarketClockError
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


def test_resolver_supplies_calendar_when_identity_column_is_absent() -> None:
    prices = _prices().drop(columns="calendar_identity")
    seen = []

    def resolve(instrument_id):
        seen.append(instrument_id)
        return "XNYS"

    for removed, expected in ((0, []), (5, []), (6, ["6 expected days missing. Exchange calendar XNYS."])):
        report = validate_prices(
            prices.drop(index=range(10, 10 + removed)), min_history_days=1, calendar_resolver=resolve,
        )
        gaps = [issue for issue in report.issues if issue.code == "missing_trading_days"]
        assert [issue.message for issue in gaps] == expected
        assert all(issue.severity == "warning" for issue in gaps)
    assert seen == ["ETF-A"] * 3


def test_default_universe_resolves_calendar_for_plain_production_frame() -> None:
    prices = _prices("XETR", "Europe/Berlin").drop(columns="calendar_identity")
    prices["etf_id"] = "VWCE"
    assert _gaps(prices) == []
    gaps = _gaps(prices.drop(index=range(10, 16)))
    assert len(gaps) == 1
    assert gaps[0].message == "6 expected days missing. Exchange calendar XETR."


def test_ledger_is_loaded_once_and_weekends_never_reach_business_day(monkeypatch) -> None:
    prices = _prices()
    other = prices.copy(deep=True)
    other["etf_id"] = "ETF-B"
    other["calendar_identity"] = [{**_identity(), "instrument_id": "ETF-B"} for _ in other.index]
    loads = []
    checked = []
    service = MarketCalendarService()
    original = service.is_business_day

    def load(path):
        loads.append(path)
        return service

    def business_day(listing, day, **kwargs):
        assert day.weekday() < 5
        checked.append(day)
        return original(listing, day, **kwargs)

    monkeypatch.setattr(MarketCalendarService, "from_correction_ledger", load)
    monkeypatch.setattr(service, "is_business_day", business_day)
    assert _gaps(pd.concat([prices, other], ignore_index=True)) == []
    assert len(loads) == 1 and checked


def test_unavailable_ledger_falls_back_for_explicit_and_resolved_calendars(monkeypatch) -> None:
    loads = []

    def unavailable(path):
        loads.append(path)
        raise MarketClockError("unreadable ledger")

    monkeypatch.setattr(MarketCalendarService, "from_correction_ledger", unavailable)
    for prices in (_prices(), _prices().drop(columns="calendar_identity")):
        report = validate_prices(prices, min_history_days=1, calendar_resolver=lambda _: "XNYS")
        gaps = [issue for issue in report.issues if issue.code == "missing_trading_days"]
        assert len(gaps) == 1 and "weekday fallback" in gaps[0].message
    assert len(loads) == 2


def test_unresolved_calendar_does_not_suppress_weekday_gaps() -> None:
    prices = _prices().drop(columns="calendar_identity")
    for calendar_id in (None, "ZZZZ"):
        report = validate_prices(prices, min_history_days=1, calendar_resolver=lambda _: calendar_id)
        gaps = [issue for issue in report.issues if issue.code == "missing_trading_days"]
        assert len(gaps) == 1 and "weekday fallback" in gaps[0].message


def test_resolved_calendar_applies_only_known_exceptional_closures(monkeypatch) -> None:
    prices = _prices().drop(columns="calendar_identity")
    missing = prices["date"].iloc[10].date()
    for known_at, expected_warnings in ((datetime(2020, 1, 2, tzinfo=timezone.utc), 0),
                                        (datetime(2025, 1, 1, tzinfo=timezone.utc), 1)):
        service = MarketCalendarService(corrections=[CalendarCorrection.exceptional_closure(
            correction_id="test-closure", mic="XNYS", session_date=missing, revision=1,
            reason="Test closure", source_id="test-source", source_checksum="a" * 64,
            timezone="America/New_York", valid_from=date(2020, 1, 1), known_at=known_at,
        )])
        monkeypatch.setattr(MarketCalendarService, "from_correction_ledger", lambda _: service)
        report = validate_prices(
            prices.drop(index=range(10, 16)), min_history_days=1, calendar_resolver=lambda _: "XNYS",
        )
        gaps = [issue for issue in report.issues if issue.code == "missing_trading_days"]
        assert len(gaps) == expected_warnings
