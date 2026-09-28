"""Tests for optional OHLCV fallback providers (Stooq, Twelve Data, Tiingo)

Tests cover:
1. Mock Stooq OHLCV normalisation to the canonical schema.
2. Twelve Data rate limiting refusing excess calls with a non-blocking quota state.
3. Tiingo without an API key returning unavailable/api_key_required with zero I/O.
4. Split mismatch between providers detected as a discrepancy.
5. Missing bars reported, not filled.
6. Provider disagreement lowering candle quality cap without mutating higher-confidence data.
"""

from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import MagicMock

import pandas as pd
import pytest

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.data.ohlcv_discrepancy import (
    CANONICAL_OHLCV_COLUMNS,
    build_discrepancy_report,
    normalise_ohlcv,
)
from etf_cockpit.data.stooq_provider import StooqProvider
from etf_cockpit.data.tiingo_provider import TiingoProvider
from etf_cockpit.data.twelvedata_provider import RateLimiter, TwelveDataProvider


def test_mock_stooq_ohlcv_normalises_to_canonical_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """1. Mock Stooq OHLCV normalises to the canonical schema."""
    csv_payload = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-09-21,120.5,121.8,120.1,121.2,45000\n"
        "2026-09-22,121.5,122.3,121.0,121.9,52000\n"
    )

    mock_response = MagicMock()
    mock_response.text = csv_payload
    mock_response.raise_for_status = MagicMock()

    import requests
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: mock_response)

    stooq = StooqProvider(ProviderSection(active_provider="stooq"))
    stooq_raw = stooq.fetch_daily_prices("vwce.de", date(2026, 9, 21), date(2026, 9, 22))

    assert not stooq_raw.empty
    normalised = normalise_ohlcv(stooq_raw)

    # Validate canonical schema columns and structure
    assert list(normalised.columns) == list(CANONICAL_OHLCV_COLUMNS)
    assert len(normalised) == 2

    # Check date objects and types
    assert normalised["date"].iloc[0] == date(2026, 9, 21)
    assert normalised["date"].iloc[1] == date(2026, 9, 22)

    # Check numeric columns
    assert normalised["close"].iloc[0] == 121.2
    assert normalised["adjusted_close"].iloc[0] == 121.2
    assert normalised["volume"].iloc[0] == 45000.0
    assert normalised["split_factor"].iloc[0] == 1.0
    assert normalised["dividend"].iloc[0] == 0.0
    assert normalised["source"].iloc[0] == "stooq"
    assert normalised["provider_symbol"].iloc[0] == "vwce.de"
    assert normalised["is_adjusted"].iloc[0] is False


def test_twelvedata_quota_rate_limit_refuses_excess_calls_non_blocking() -> None:
    """2. Twelve Data quota/rate limit: the limiter refuses excess calls with a non-blocking quota state."""
    calls_made: list[str] = []

    def mock_transport(url: str, headers: dict[str, str]) -> dict[str, object]:
        calls_made.append(url)
        return {
            "meta": {"symbol": "VWCE", "currency": "EUR"},
            "values": [
                {
                    "datetime": "2026-09-25",
                    "open": "120.0",
                    "high": "121.0",
                    "low": "119.5",
                    "close": "120.5",
                    "volume": "10000",
                }
            ],
            "status": "ok",
        }

    # Strict limit: 2 calls per minute
    limiter = RateLimiter(calls_per_minute=2)
    provider = TwelveDataProvider(
        section=ProviderSection(active_provider="twelvedata", api_key="secret_test_key"),
        limiter=limiter,
        transport=mock_transport,
    )

    # First two calls succeed
    df1 = provider.fetch_daily_prices("VWCE", date(2026, 9, 25), date(2026, 9, 25))
    assert not df1.empty
    assert len(calls_made) == 1

    df2 = provider.fetch_daily_prices("VWCE", date(2026, 9, 25), date(2026, 9, 25))
    assert not df2.empty
    assert len(calls_made) == 2

    # Third call is refused by the limiter
    df3 = provider.fetch_daily_prices("VWCE", date(2026, 9, 25), date(2026, 9, 25))
    assert df3.empty
    assert len(calls_made) == 2  # No network I/O attempted

    # Verify limiter state is non-blocking and refused
    state = provider.last_limiter_state
    assert state is not None
    assert state.allowed is False
    assert state.non_blocking is True
    assert state.status in {"rate_limited", "quota_exhausted"}
    assert state.retry_after > 0

    # Bulk fetch also surfaces non-blocking unavailable status
    bulk_result = provider.fetch_prices(["VWCE"], date(2026, 9, 25), date(2026, 9, 25))
    assert bulk_result.status == "unavailable"
    assert "rate limit" in bulk_result.message.lower()
    assert "non-blocking" in bulk_result.message.lower()
    assert len(calls_made) == 2


def test_tiingo_without_key_returns_unavailable_api_key_required_and_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3. Tiingo without a key returns unavailable/api_key_required and performs no I/O."""
    monkeypatch.delenv("ETF_COCKPIT_TIINGO_API_KEY", raising=False)

    transport_called = False

    def mock_transport(_url: str, _headers: dict[str, str]) -> list[object]:
        nonlocal transport_called
        transport_called = True
        return []

    provider = TiingoProvider(
        section=ProviderSection(active_provider="tiingo", api_key=""),
        transport=mock_transport,
    )

    # Capabilities probe check
    caps = provider.probe_capabilities()
    assert len(caps) == 1
    cap = caps[0]
    assert cap.status == "unavailable"
    assert cap.entitlement == "api_key_required"
    assert cap.configured is False
    assert cap.secret_present is False
    assert "api key" in cap.message.lower()

    # Price fetching attempts
    df = provider.fetch_daily_prices("VWCE", date(2026, 9, 1), date(2026, 9, 5))
    assert df.empty

    result = provider.fetch_prices(["VWCE"], date(2026, 9, 1), date(2026, 9, 5))
    assert result.status == "unavailable"
    assert not result.ok

    # Validate that zero network I/O occurred
    assert transport_called is False


def test_split_mismatch_between_providers_detected_as_discrepancy() -> None:
    """4. A split mismatch between two providers is detected as a discrepancy."""
    dates = [date(2026, 9, 20), date(2026, 9, 21), date(2026, 9, 22)]

    primary_df = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0, 100.0, 100.0],
            "high": [102.0, 102.0, 102.0],
            "low": [99.0, 99.0, 99.0],
            "close": [101.0, 101.0, 101.0],
            "adjusted_close": [101.0, 101.0, 101.0],
            "volume": [10000.0, 10000.0, 10000.0],
            "split_factor": [1.0, 1.0, 1.0],  # No split reported
            "dividend": [0.0, 0.0, 0.0],
            "currency": ["EUR", "EUR", "EUR"],
            "provider_symbol": ["VWCE", "VWCE", "VWCE"],
            "source": ["yfinance", "yfinance", "yfinance"],
            "is_adjusted": [False, False, False],
        }
    )

    secondary_df = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0, 50.0, 50.0],
            "high": [102.0, 51.0, 51.0],
            "low": [99.0, 49.5, 49.5],
            "close": [101.0, 50.5, 50.5],
            "adjusted_close": [101.0, 101.0, 101.0],
            "volume": [10000.0, 20000.0, 20000.0],
            "split_factor": [1.0, 2.0, 1.0],  # 2:1 split reported on 2026-09-21
            "dividend": [0.0, 0.0, 0.0],
            "currency": ["EUR", "EUR", "EUR"],
            "provider_symbol": ["VWCE", "VWCE", "VWCE"],
            "source": ["tiingo", "tiingo", "tiingo"],
            "is_adjusted": [True, True, True],
        }
    )

    report = build_discrepancy_report(
        primary_df,
        secondary_df,
        symbol="VWCE",
        primary_name="yfinance",
        secondary_name="tiingo",
    )

    assert report.has_discrepancies is True
    split_discs = [d for d in report.discrepancies if d.field == "split_factor"]
    assert len(split_discs) == 1

    disc = split_discs[0]
    assert disc.date == date(2026, 9, 21)
    assert disc.value_a == 1.0
    assert disc.value_b == 2.0
    assert "split factor mismatch" in disc.message.lower()


def test_missing_bars_reported_not_filled() -> None:
    """5. Missing bars are reported, not filled."""
    dates_p = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
    dates_s = [date(2026, 9, 21), date(2026, 9, 23)]  # 2026-09-22 missing in secondary

    primary_df = pd.DataFrame(
        {
            "date": dates_p,
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "adjusted_close": [100.5, 101.5, 102.5],
            "volume": [1000.0, 1000.0, 1000.0],
            "source": ["yfinance"] * 3,
            "provider_symbol": ["VWCE"] * 3,
        }
    )

    secondary_df = pd.DataFrame(
        {
            "date": dates_s,
            "open": [100.0, 102.0],
            "high": [101.0, 103.0],
            "low": [99.0, 101.0],
            "close": [100.5, 102.5],
            "adjusted_close": [100.5, 102.5],
            "volume": [1000.0, 1000.0],
            "source": ["stooq"] * 2,
            "provider_symbol": ["VWCE"] * 2,
        }
    )

    report = build_discrepancy_report(
        primary_df,
        secondary_df,
        symbol="VWCE",
        primary_name="yfinance",
        secondary_name="stooq",
    )

    # Missing bar detected
    missing_discs = [d for d in report.discrepancies if d.field == "missing_bar"]
    assert len(missing_discs) == 1
    assert missing_discs[0].date == date(2026, 9, 22)
    assert missing_discs[0].provider_b == "stooq"
    assert missing_discs[0].value_b is None

    # CRITICAL: Verify neither series was filled with zeros or dummy bars
    assert len(secondary_df) == 2
    assert len(report.secondary_series) == 2
    assert date(2026, 9, 22) not in report.secondary_series["date"].values

    assert len(primary_df) == 3
    assert len(report.primary_series) == 3


def test_disagreement_lowers_candle_quality_cap_and_never_overwrites_primary() -> None:
    """6. Disagreement lowers the candle quality cap. The report never overwrites the higher-confidence series."""
    dates = [date(2026, 9, 21), date(2026, 9, 22)]

    primary_df = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0, 100.0],
            "high": [102.0, 102.0],
            "low": [99.0, 99.0],
            "close": [100.0, 100.0],
            "adjusted_close": [100.0, 100.0],
            "volume": [5000.0, 5000.0],
            "source": ["primary_high_confidence"] * 2,
            "provider_symbol": ["VWCE"] * 2,
        }
    )

    # Clean matching secondary
    clean_secondary_df = primary_df.copy()
    clean_secondary_df["source"] = "secondary_clean"

    clean_report = build_discrepancy_report(
        primary_df,
        clean_secondary_df,
        symbol="VWCE",
        primary_name="primary_high_confidence",
        secondary_name="secondary_clean",
    )
    assert clean_report.candle_quality_cap == 1.0
    assert not clean_report.has_discrepancies

    # Disagreeing secondary (close is 120.0 instead of 100.0 on 2026-09-22: 20% diff >> 0.5% tol)
    dirty_secondary_df = primary_df.copy()
    dirty_secondary_df["source"] = "secondary_dirty"
    dirty_secondary_df.loc[dirty_secondary_df["date"] == date(2026, 9, 22), "close"] = 120.0
    dirty_secondary_df.loc[dirty_secondary_df["date"] == date(2026, 9, 22), "adjusted_close"] = 120.0

    dirty_report = build_discrepancy_report(
        primary_df,
        dirty_secondary_df,
        symbol="VWCE",
        primary_name="primary_high_confidence",
        secondary_name="secondary_dirty",
    )

    # Disagreement strictly lowers candle quality cap
    assert dirty_report.candle_quality_cap < 1.0
    assert dirty_report.candle_quality_cap < clean_report.candle_quality_cap
    assert dirty_report.has_discrepancies is True

    # Higher confidence primary series is NEVER overwritten with secondary data
    primary_close_at_mismatch = (
        dirty_report.primary_series.loc[dirty_report.primary_series["date"] == date(2026, 9, 22), "close"].iloc[0]
    )
    assert primary_close_at_mismatch == 100.0
    assert primary_close_at_mismatch != 120.0

    # Ensure all primary series values are identical to input
    pd.testing.assert_frame_equal(dirty_report.primary_series, normalise_ohlcv(primary_df, source="primary_high_confidence", symbol="VWCE"))


def test_tiingo_fetch_daily_prices_normalises_splits_and_adjusted_fields() -> None:
    """Tiingo daily fetch parses adjClose, splitFactor and maps to canonical schema."""
    tiingo_payload = [
        {
            "date": "2026-09-24T00:00:00.000Z",
            "close": 120.3,
            "high": 120.6,
            "low": 119.5,
            "open": 119.8,
            "volume": 52000,
            "adjClose": 120.3,
            "adjHigh": 120.6,
            "adjLow": 119.5,
            "adjOpen": 119.8,
            "adjVolume": 52000,
            "divCash": 0.5,
            "splitFactor": 1.0,
        }
    ]

    provider = TiingoProvider(
        section=ProviderSection(active_provider="tiingo", api_key="test_tiingo_token"),
        transport=lambda _url, _headers: tiingo_payload,
    )

    df = provider.fetch_daily_prices("VWCE", date(2026, 9, 24), date(2026, 9, 24))
    assert not df.empty
    assert list(df.columns) == list(CANONICAL_OHLCV_COLUMNS)
    assert df["date"].iloc[0] == date(2026, 9, 24)
    assert df["adjusted_close"].iloc[0] == 120.3
    assert df["dividend"].iloc[0] == 0.5
    assert df["split_factor"].iloc[0] == 1.0
    assert df["source"].iloc[0] == "tiingo"
    assert df["provider_symbol"].iloc[0] == "VWCE"
