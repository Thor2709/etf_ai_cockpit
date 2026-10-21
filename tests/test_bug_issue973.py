"""#973 V8 research items and C112 attribution join, kept as regression guards."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.backtest.event_engine import (
    CertifiedSessionCalendar,
    EventDrivenBacktest,
    EventReplayError,
    MarketEvent,
    OrderRequest,
    SignalEvent,
    TargetEvent,
    UnsupportedExecutionDataError,
)
from etf_cockpit.data.market_calendar import ListingCalendarEvidence
from etf_cockpit.features.benchmark_attribution import build_benchmark_attribution

UTC = timezone.utc


def _engine(**kwargs: object) -> EventDrivenBacktest:
    calendar = CertifiedSessionCalendar(
        ListingCalendarEvidence(
            listing_id="listing:ETF-A:XNYS",
            instrument_id="ETF-A",
            mic="XNYS",
            calendar_id="XNYS",
            timezone="America/New_York",
            source_id="identity:test-calendar",
            source_checksum="a" * 64,
            valid_from=date(2020, 1, 1),
            known_at=datetime(2020, 1, 2, tzinfo=UTC),
        )
    )
    return EventDrivenBacktest(calendars={"ETF-A": calendar}, **kwargs)


def _at(minute: int) -> datetime:
    return datetime(2026, 7, 17, 10, minute)


def _bar(minute: int, high: float = 102.0, quantity: float | None = None) -> MarketEvent:
    return MarketEvent(_at(minute), "ETF-A", 100.0, high, 98.0, 101.0, available_quantity=quantity)


def _order() -> OrderRequest:
    return OrderRequest(_at(0), "o", "ETF-A", "buy", 5.0)


def test_c2_s16_n001_ledger_hash_binds_market_inputs_and_target_quantity() -> None:
    base = _engine().replay([_order(), _bar(1), TargetEvent(_at(0), "t", "ETF-A", 3.0)])
    other_bar = _engine().replay([_order(), _bar(1, high=110.0), TargetEvent(_at(0), "t", "ETF-A", 3.0)])
    other_target = _engine().replay([_order(), _bar(1), TargetEvent(_at(0), "t", "ETF-A", 4.0)])

    assert base.ledger_hash != other_bar.ledger_hash
    assert base.ledger_hash != other_target.ledger_hash


def test_c3_s16_n002_missing_liquidity_fails_closed_when_required() -> None:
    with pytest.raises(UnsupportedExecutionDataError, match="available_quantity"):
        _engine(require_liquidity=True).replay([_order(), _bar(1)])
    # The default research contract is unchanged: no declared liquidity means no cap.
    assert _engine().replay([_order(), _bar(1)]).fills[0].quantity == 5.0
    assert _engine(require_liquidity=True).replay([_order(), _bar(1, quantity=5.0)]).fills[0].quantity == 5.0


@pytest.mark.parametrize("listed", ["false", "False", 0, None])
def test_c2_s23_n001_listed_must_be_a_bool(listed) -> None:
    with pytest.raises(EventReplayError, match="listed"):
        MarketEvent(_at(1), "ETF-A", 100.0, 102.0, 98.0, 101.0, listed=listed)


def test_c5_s16_n002_limit_price_must_be_strictly_positive() -> None:
    for price in (0.0, -1.0):
        with pytest.raises(EventReplayError):
            OrderRequest(_at(0), "o", "ETF-A", "buy", 5.0, "limit", price)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"signal_id": " ", "instrument_id": "ETF-A", "action": "buy"},
        {"signal_id": "s", "instrument_id": "", "action": "buy"},
        {"signal_id": "s", "instrument_id": "ETF-A", "action": "liquidate"},
    ],
)
def test_c2_s16_n002_signal_event_is_validated_like_the_other_events(kwargs) -> None:
    with pytest.raises(EventReplayError):
        SignalEvent(_at(0), **kwargs)


def test_c112_n004_duplicate_date_attribution_join_is_safe() -> None:
    index = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-05", "2026-01-06"])
    instrument = pd.Series([0.01, 0.02, 0.02, -0.01, 0.03], index=index)
    broad = pd.Series([0.005, 0.01, 0.01, -0.005, 0.02], index=index)

    identical = build_benchmark_attribution(instrument, broad)
    assert identical.status == "available" and identical.sample_size == 4

    conflicting = instrument.copy()
    conflicting.iloc[2] = 0.05
    result = build_benchmark_attribution(conflicting, broad)
    assert result.status == "unavailable"
    assert "duplicate dates" in result.reason
