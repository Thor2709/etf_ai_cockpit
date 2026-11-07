"""CB1: FX rows carry an explicit availability time, so an unrevised backfill is usable at its own close."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from etf_cockpit.data.fx_data import EurRateBook, stamp_fx_availability, validate_fx_rates

FETCHED = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
KNOWN_BY = datetime(2026, 1, 10, tzinfo=timezone.utc)
SESSION = date(2026, 1, 8)


def _quotes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "as_of_date": [date(2026, 1, 7), date(2026, 1, 8)],
            "base_currency": "NOK",
            "quote_currency": "EUR",
            "pair": "NOK/EUR",
            "rate": [0.0850, 0.0852],
            "source": "yfinance",
        }
    )


def _rate(frame: pd.DataFrame) -> tuple[float, str | None, str | None]:
    book = EurRateBook(frame, known_by=KNOWN_BY)
    series = book.series("NOK", [SESSION])
    return float(series.rates.iloc[0]), series.reasons.iloc[0], book.unavailable_reason


def test_backfilled_unrevised_close_is_usable_at_its_own_date() -> None:
    stamped = stamp_fx_availability(_quotes(), ingested_at=FETCHED)
    assert set(stamped["availability_basis"]) == {"market_close_unrevised"}
    assert stamped["available_at"].iloc[1] == pd.Timestamp("2026-01-08T23:59:59Z")
    assert (stamped["ingested_at"] == pd.Timestamp(FETCHED)).all()
    validation = validate_fx_rates(stamped)
    assert validation.ok and {"available_at", "availability_basis"} <= set(validation.frame.columns)
    rate, reason, _ = _rate(stamped)
    assert rate == 0.0852 and reason is None


def test_row_available_after_the_cutoff_is_rejected() -> None:
    stamped = stamp_fx_availability(_quotes(), ingested_at=FETCHED)
    late = stamped.assign(available_at=pd.Timestamp("2026-01-11T00:00:00Z"))
    rate, reason, unavailable = _rate(late)
    assert pd.isna(rate) and "known by the analysis decision time" in (reason or unavailable or "")


def test_legacy_row_without_available_at_is_still_gated_by_ingested_at() -> None:
    legacy = _quotes().assign(ingested_at=pd.Timestamp(FETCHED))
    rate, reason, unavailable = _rate(legacy)
    assert pd.isna(rate) and "known by the analysis decision time" in (reason or unavailable or "")
    early = _quotes().assign(ingested_at=pd.Timestamp("2026-01-09T12:00:00Z"))
    assert _rate(early)[0] == 0.0852


def test_missing_or_unknown_basis_and_unparseable_time_fail_closed() -> None:
    stamped = stamp_fx_availability(_quotes(), ingested_at=FETCHED)
    for broken in (
        stamped.drop(columns=["availability_basis"]),
        stamped.assign(availability_basis="made_up"),
        stamped.assign(available_at="not-a-time"),
        stamped.assign(available_at=None),
    ):
        rate, _, unavailable = _rate(broken)
        assert pd.isna(rate) and unavailable is not None and "availab" in unavailable
        assert not validate_fx_rates(broken).ok


def test_available_at_later_than_ingestion_fails_closed_and_a_partial_day_is_live() -> None:
    stamped = stamp_fx_availability(_quotes(), ingested_at=FETCHED)
    impossible = stamped.assign(available_at=stamped["ingested_at"] + pd.Timedelta(hours=1))
    rate, _, unavailable = _rate(impossible)
    assert pd.isna(rate) and "later than ingested_at" in (unavailable or "")
    today = _quotes().assign(as_of_date=[date(2026, 10, 20), date(2026, 10, 21)])
    live = stamp_fx_availability(today, ingested_at=FETCHED)
    assert list(live["availability_basis"]) == ["market_close_unrevised", "live_ingestion"]
    assert live["available_at"].iloc[1] == pd.Timestamp(FETCHED)


def test_market_close_basis_rejects_an_available_at_before_the_quote_date_close() -> None:
    stamped = stamp_fx_availability(_quotes(), ingested_at=FETCHED)
    early = stamped.assign(available_at=pd.Timestamp("2026-01-08T00:00:00Z"))
    assert not validate_fx_rates(early).ok
    book = EurRateBook(early, known_by=datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc))
    assert pd.isna(book.series("NOK", [SESSION]).rates.iloc[0])
    assert book.unavailable_reason is not None and "before the quote date close" in book.unavailable_reason
