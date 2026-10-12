from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.features.etf_economics import calculate_etf_liquidity


def _prices(rows: int = 80, *, instrument_id: str = "VWCE", currency: str = "EUR") -> pd.DataFrame:
    dates = pd.date_range("2026-04-01", periods=rows, freq="B")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "etf_id": instrument_id,
            "close": close,
            "volume": 10_000.0,
            "currency": currency,
        }
    )


def test_quote_nav_with_matching_identity_and_fresh_nav_are_available() -> None:
    prices = _prices()
    latest = prices["date"].max()
    report = calculate_etf_liquidity(
        load_config(),
        prices,
        "VWCE",
        as_of=latest,
        quote_evidence={
            "instrument_id": "VWCE",
            "quote_timestamp": latest + pd.Timedelta(hours=15),
            "bid_eur": 100.0,
            "ask_eur": 102.0,
            "nav": 100.0,
            "nav_currency": "EUR",
            "nav_instrument_id": "VWCE",
            "nav_timestamp": latest + pd.Timedelta(hours=14),
        },
    )

    assert report.quote_status == "available"
    assert report.nav_freshness == "fresh"
    assert report.quoted_spread_bps == pytest.approx(2.0 / 101.0 * 10_000.0)
    assert report.premium_discount_bps == pytest.approx(100.0)


def test_nav_for_another_instrument_is_unavailable_without_a_value() -> None:
    prices = _prices()
    latest = prices["date"].max()
    report = calculate_etf_liquidity(
        load_config(),
        prices,
        "VWCE",
        as_of=latest,
        quote_evidence={
            "instrument_id": "VWCE",
            "quote_timestamp": latest + pd.Timedelta(hours=15),
            "bid_eur": 100.0,
            "ask_eur": 102.0,
            "nav_eur": 100.0,
            "nav_instrument_id": "OTHER",
            "nav_timestamp": latest + pd.Timedelta(hours=14),
        },
    )

    assert report.quote_status == "unavailable"
    assert report.nav_eur is None
    assert report.premium_discount_bps is None
    assert "nav_identity" in report.missing_evidence


def test_nav_more_than_one_day_older_than_quote_is_unavailable() -> None:
    prices = _prices()
    latest = prices["date"].max()
    quote_timestamp = latest + pd.Timedelta(hours=15)
    report = calculate_etf_liquidity(
        load_config(),
        prices,
        "VWCE",
        as_of=latest,
        quote_evidence={
            "instrument_id": "VWCE",
            "quote_timestamp": quote_timestamp,
            "bid_eur": 100.0,
            "ask_eur": 102.0,
            "nav_eur": 100.0,
            "nav_timestamp": quote_timestamp - pd.Timedelta(days=2),
        },
    )

    assert report.quote_status == "unavailable"
    assert report.nav_freshness == "unavailable"
    assert report.nav_eur is None
    assert report.premium_discount_bps is None
    assert "nav_timestamp" in report.missing_evidence


def test_quote_without_instrument_identity_is_unavailable() -> None:
    prices = _prices()
    latest = prices["date"].max()
    report = calculate_etf_liquidity(
        load_config(),
        prices,
        "VWCE",
        as_of=latest,
        quote_evidence={
            "quote_timestamp": latest + pd.Timedelta(hours=15),
            "bid_eur": 100.0,
            "ask_eur": 102.0,
            "nav_eur": 100.0,
        },
    )

    assert report.quote_status == "unavailable"
    assert report.bid_eur is None
    assert report.nav_eur is None
    assert report.premium_discount_bps is None
    assert "quote_identity" in report.missing_evidence


def test_dated_pit_fx_evidence_converts_foreign_turnover_to_eur() -> None:
    prices = _prices(instrument_id="USD-ETF", currency="USD")
    latest = prices["date"].max()
    fx_date = latest - pd.offsets.BDay(1)
    fx_evidence = pd.DataFrame(
        [
            {
                "as_of_date": fx_date.date().isoformat(),
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate": 0.9,
                "source": "synthetic-test",
                "ingested_at": fx_date + pd.Timedelta(hours=16),
            }
        ]
    )
    report = calculate_etf_liquidity(
        load_config(),
        prices,
        "USD-ETF",
        order_value_eur=1_000.0,
        fx_evidence=fx_evidence,
        as_of=latest.date(),
    )
    native_turnover_20d = (prices["close"].tail(20) * prices["volume"].tail(20)).median()

    assert report.fx_status == "available"
    assert report.fx_rate_to_eur == pytest.approx(0.9)
    assert report.fx_rate_as_of == fx_date.date().isoformat()
    assert report.fx_source_snapshot
    assert report.rolling_turnover_eur_20d == pytest.approx(native_turnover_20d * 0.9)
    assert report.exchange_capacity_eur == pytest.approx(
        native_turnover_20d * 0.9 * load_config().costs.cost_model.max_participation_rate
    )


@pytest.mark.parametrize(
    "fx_evidence",
    [
        None,
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-07-20",
                    "base_currency": "USD",
                    "quote_currency": "EUR",
                    "rate": 0.9,
                    "source": "synthetic-test",
                }
            ]
        ),
        pd.DataFrame(
            [
                {
                    "as_of_date": "2026-06-01",
                    "base_currency": "USD",
                    "quote_currency": "EUR",
                    "rate": 0.9,
                    "source": "synthetic-test",
                    "ingested_at": "2026-06-01T16:00:00Z",
                }
            ]
        ),
    ],
    ids=("missing", "unknown-point-in-time-availability", "stale"),
)
def test_missing_or_unverifiable_fx_keeps_euro_capacity_unavailable(fx_evidence: pd.DataFrame | None) -> None:
    prices = _prices(instrument_id="USD-ETF", currency="USD")
    latest = prices["date"].max()
    report = calculate_etf_liquidity(
        load_config(),
        prices,
        "USD-ETF",
        order_value_eur=1_000.0,
        fx_evidence=fx_evidence,
        as_of=latest.date(),
    )

    assert report.fx_status == "unavailable"
    assert report.fx_rate_to_eur is None
    assert report.rolling_turnover_eur_20d is None
    assert report.exchange_capacity_eur is None
    assert report.capacity_status == "blocked_missing_liquidity"
    assert "fx_rate_to_eur" in report.missing_evidence
    assert report.fx_reason
    assert any(report.fx_reason in warning for warning in report.warnings)
