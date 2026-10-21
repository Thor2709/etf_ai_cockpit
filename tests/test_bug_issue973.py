"""#973 V8 research items and C112 attribution join, kept as regression guards."""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
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
from etf_cockpit.features.regime import build_benchmark_attribution_lookup
from tests.test_evidence_derivatives import _available_reference, _available_registry

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


def _lookup_prices(periods: int = 140, drop_alt: slice | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2025-01-01", periods=periods)
    rows = []
    for instrument_id in ("BENCH", "ALT"):
        closes = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, periods))
        rows.extend({"date": dt, "etf_id": instrument_id, "adjusted_close": float(px)} for dt, px in zip(dates, closes))
    frame = pd.DataFrame(rows)
    if drop_alt is not None:
        alt = frame.index[frame["etf_id"] == "ALT"][drop_alt]
        frame = frame.drop(alt)
    return frame


def _lookup(prices: pd.DataFrame) -> dict[str, dict[str, object]]:
    return build_benchmark_attribution_lookup(
        prices, window=120, benchmark_id="BENCH", benchmark_reference=_available_reference(),
        benchmark_registry=_available_registry(),
    )


def test_c112_n001_non_simple_return_metrics_are_not_mixed() -> None:
    index = pd.bdate_range("2026-01-01", periods=10)
    broad = pd.Series(np.linspace(0.001, 0.01, 10), index=index)
    simple = pd.Series(np.linspace(0.002, 0.02, 10), index=index)
    assert build_benchmark_attribution(simple, broad).status == "available"

    mixed = simple.copy()
    mixed.iloc[4] = -1.5  # a log/percent/price-style value inside a simple-return series
    result = build_benchmark_attribution(mixed, broad)
    assert result.status == "unavailable"
    assert result.instrument_return is None
    assert "not simple period returns" in result.reason


def test_c112_n002_source_return_coverage_counts_in_confidence() -> None:
    index = pd.bdate_range("2026-01-01", periods=20)
    broad = pd.Series(np.linspace(0.001, 0.02, 20), index=index)
    full = pd.Series(np.linspace(0.002, 0.03, 20), index=index)
    ok = build_benchmark_attribution(full, broad)
    assert ok.status == "available" and ok.source_return_coverage == 1.0

    holes = full.copy()
    holes.iloc[[2, 4, 6, 8, 10, 12, 14, 16]] = np.nan  # 40% of shared dates carry no clean return
    result = build_benchmark_attribution(holes, broad)
    assert result.status == "unavailable" and "coverage" in result.reason

    prices = _lookup_prices()
    assert _lookup(prices)["ALT"]["source_return_coverage"] == 1.0
    gappy = _lookup_prices(drop_alt=slice(60, 130, 2))
    row = _lookup(gappy)["ALT"]
    assert row["status"] == "N/A" and row["instrument_return"] is None
    assert row["source_return_coverage"] is not None and row["source_return_coverage"] < 0.8
    assert "coverage" in row["label"]


def test_c112_n003_future_invalid_rows_do_not_break_as_of_replay() -> None:
    prices = _lookup_prices()
    cutoff = prices["date"].max() - pd.Timedelta(days=20)
    known = prices[prices["date"] <= cutoff]
    expected = _lookup(known)["ALT"]
    assert expected["status"] == "available"

    junk = pd.DataFrame(
        [
            {"date": cutoff + pd.Timedelta(days=3), "etf_id": "ALT", "adjusted_close": 0.0},
            {"date": cutoff + pd.Timedelta(days=5), "etf_id": "ALT", "adjusted_close": -3.0},
            {"date": cutoff + pd.Timedelta(days=6), "etf_id": "ALT", "adjusted_close": float("inf")},
            {"date": "not-a-date", "etf_id": "ALT", "adjusted_close": 5.0},
            {"date": cutoff + pd.Timedelta(days=4), "etf_id": "BENCH", "adjusted_close": float("nan")},
        ]
    )
    noisy = pd.concat([known, junk], ignore_index=True)
    assert _lookup(noisy)["ALT"] == expected

    # An invalid row inside the replay window is treated as missing, never as a price or a crash.
    inside = pd.concat(
        [known, pd.DataFrame([{"date": known["date"].iloc[5], "etf_id": "ALT", "adjusted_close": 99.0}])],
        ignore_index=True,
    )
    row = _lookup(inside)["ALT"]
    assert row["status"] == "N/A" and "conflicting duplicate" in row["label"]
