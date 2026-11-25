"""BF1: backfill hoists. One run FX book (B2), the run snapshot memo (B5) and the calendar negative cache (B7)."""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.data import fx_data, market_calendar
from tests.test_score_backfill import _fx


def _close(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)


def _read(book: fx_data.EurRateBook, days: list[date]) -> tuple[list, list, str]:
    series = book.series("NOK", days)
    return series.rates.tolist(), series.reasons.tolist(), book.identity(days[0], days[-1])


@pytest.mark.parametrize("late", [False, True])
def test_run_fx_book_reads_like_a_session_book_and_never_sees_a_late_row(late):
    fx = _fx(0.1)
    sessions = [date(2022, 6, 1), date(2022, 6, 8), date(2022, 6, 15)]
    if late:  # 2022-06-07 is known only after the 2022-06-08 close: session 06-08 must not read it
        row = fx.index[fx["as_of_date"].eq(date(2022, 6, 7))][0]
        fx.loc[row, "rate"] = 0.2
        fx.loc[row, "available_at"] = pd.Timestamp("2022-06-09 12:00", tz="UTC")
    days = [day.date() for day in pd.bdate_range("2022-05-20", "2022-06-15")]
    with fx_data.fx_run_memo(fx, known_by=_close(sessions[-1])):
        for session in sessions:
            window = [day for day in days if day <= session]
            assert _read(fx_data.eur_rate_book(fx, known_by=_close(session)), window) == _read(
                fx_data.EurRateBook(fx, known_by=_close(session)), window
            )
    if late:
        with fx_data.fx_run_memo(fx, known_by=_close(sessions[-1])):
            rate = fx_data.eur_rate_book(fx, known_by=_close(date(2022, 6, 8))).series("NOK", [date(2022, 6, 7)]).rates.iloc[0]
        assert rate == pytest.approx(0.1)  # 06-08 reads 06-06, the late 0.2 quote is not visible yet


def test_run_snapshot_memo_returns_the_session_snapshot_for_the_run_frame(monkeypatch):
    fx = _fx(0.1)
    built: list[date] = []
    original = fx_data.build_fx_rate_snapshot
    monkeypatch.setattr(fx_data, "build_fx_rate_snapshot", lambda frame, **kw: (built.append(kw["decision_time"]), original(frame, **kw))[1])
    day = date(2022, 6, 7)
    known_at = _close(day)
    with fx_data.fx_run_memo(fx, known_by=_close(date(2022, 6, 30))):
        first = fx_data.fx_rate_snapshot(fx, decision_time=day, known_at=known_at)
        again = fx_data.fx_rate_snapshot(fx, decision_time=day, known_at=known_at)
        other = fx_data.fx_rate_snapshot(fx.copy(), decision_time=day, known_at=known_at)  # not the run frame: built again
    assert first == again == original(fx, decision_time=day, known_at=known_at) == other
    assert built == [day, day]


def test_failed_exchange_calendar_window_is_built_once_and_raises_the_same_error(monkeypatch):
    calls: list[tuple] = []

    def failing(name, start, end):
        calls.append((name, start, end))
        raise ValueError(f"no holidays for {name} to {end}")

    monkeypatch.setattr(market_calendar.xcals, "get_calendar", failing)
    for _ in range(3):
        with pytest.raises(ValueError, match="no holidays for BF1TEST to 2031-12-31"):
            market_calendar._exchange_calendar("BF1TEST", 2025, 2031)
    assert len(calls) == 1
