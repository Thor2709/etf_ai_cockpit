from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from etf_cockpit.data.fx_data import build_fx_rate_snapshot, validate_fx_rates
from etf_cockpit.data.market_adjustments import (
    CorporateAction,
    FXObservation,
    apply_total_return_adjustments,
    derive_fx_cross,
)
from etf_cockpit.data.market_calendar import (
    ListingCalendarEvidence,
    MarketCalendarService,
    MarketClockError,
)


UTC = timezone.utc


def _action(
    action_id: str,
    action_type: str,
    *,
    ex_date: str,
    payable_at: str | None = None,
    known_at: str = "2024-01-02T00:00:00Z",
    ratio: float | None = None,
    amount: float | None = None,
    source: str = "fixture:official-actions",
    source_id: str | None = None,
) -> CorporateAction:
    return CorporateAction(
        action_id=action_id,
        instrument_id="US-ETF-001",
        action_type=action_type,
        announced_at="2023-12-15T00:00:00Z",
        effective_at="2024-01-10T00:00:00Z",
        ex_date=ex_date,
        payable_at=payable_at,
        known_at=known_at,
        revision=1,
        source=source,
        source_id=source_id or f"{source}:{action_id}:r1",
        source_checksum=f"sha256:{action_id}:r1",
        ratio=ratio,
        amount=amount,
        currency="USD",
    )


def _fx(
    observation_id: str,
    base: str,
    quote: str,
    rate: float,
    *,
    valid_at: str,
    authority: str,
    source_id: str,
) -> FXObservation:
    return FXObservation(
        observation_id=observation_id,
        base_currency=base,
        quote_currency=quote,
        rate=Decimal(str(rate)),
        valid_at=valid_at,
        published_at=valid_at,
        retrieved_at=valid_at,
        known_at=valid_at,
        revision=1,
        source="fixture:fx",
        source_id=source_id,
        source_checksum=f"sha256:{observation_id}:r1",
        is_reference=True,
        executable=False,
        authority=authority,
    )


def test_fx_direct_official_quote_ranks_a_near_equal_manual_inverse_first() -> None:
    direct = _fx(
        "EURUSD-OFFICIAL",
        "EUR",
        "USD",
        1.10,
        valid_at="2024-01-10T00:00:00Z",
        authority="official",
        source_id="fixture:official:EURUSD",
    )
    inverse = _fx(
        "USDEUR-MANUAL",
        "USD",
        "EUR",
        1 / 1.1000005,
        valid_at="2024-01-10T00:00:00Z",
        authority="manual",
        source_id="fixture:manual:USDEUR",
    )

    result = derive_fx_cross(
        (inverse, direct), "EUR", "USD", as_of="2024-01-11T00:00:00Z"
    )

    assert result.available is True
    assert result.rate == pytest.approx(1.10)
    assert result.source_ids == ("fixture:official:EURUSD",)
    assert result.execution_allowed is False


def test_fx_triangle_with_a_stale_leg_does_not_quarantine_the_fresh_direct_quote() -> None:
    direct = _fx(
        "USDEUR-FRESH",
        "USD",
        "EUR",
        0.90,
        valid_at="2024-01-10T00:00:00Z",
        authority="official",
        source_id="fixture:official:USDEUR",
    )
    gbp_eur = _fx(
        "GBPEUR-FRESH",
        "GBP",
        "EUR",
        0.85,
        valid_at="2024-01-10T00:00:00Z",
        authority="official",
        source_id="fixture:official:GBPEUR",
    )
    usd_gbp = _fx(
        "USDGBP-STALE",
        "USD",
        "GBP",
        0.70,
        valid_at="2024-01-08T00:00:00Z",
        authority="official",
        source_id="fixture:official:USDGBP",
    )

    result = derive_fx_cross(
        (direct, gbp_eur, usd_gbp),
        "USD",
        "EUR",
        as_of="2024-01-10T00:00:00Z",
    )

    assert result.available is True
    assert result.rate == pytest.approx(0.90)
    assert result.path == ("USD/EUR",)
    assert result.execution_allowed is False


def test_income_return_scales_daily_cash_by_cumulative_split_quantity() -> None:
    split = _action(
        "SPLIT-INCOME",
        "split",
        ex_date="2024-01-11",
        ratio=2.0,
    )
    dividend = _action(
        "DIV-INCOME",
        "dividend",
        ex_date="2024-01-12",
        payable_at="2024-01-15T00:00:00Z",
        amount=1.0,
    )
    prices = pd.DataFrame(
        {
            "date": ["2024-01-10", "2024-01-11", "2024-01-12"],
            "close": [100.0, 50.0, 49.0],
            "currency": "USD",
        }
    )

    result = apply_total_return_adjustments(prices, (split, dividend))

    assert result.available is True
    assert result.income_return == pytest.approx(0.02)
    assert result.total_return == pytest.approx(0.0)
    assert result.execution_allowed is False


def test_business_day_validity_uses_the_queried_date_at_berlin_boundary() -> None:
    listing = ListingCalendarEvidence(
        listing_id="listing:VWCE:XETR",
        instrument_id="ETF-A",
        mic="XETR",
        calendar_id="XETR",
        timezone="Europe/Berlin",
        source_id="identity-master:test-listing",
        source_checksum="a" * 64,
        valid_from=date(2025, 1, 2),
        valid_to=date(2025, 6, 1),
        known_at=datetime(2024, 12, 31, tzinfo=UTC),
    )
    service = MarketCalendarService()

    assert service.is_business_day(listing, date(2025, 5, 31)) is False
    with pytest.raises(MarketClockError):
        service.is_business_day(listing, date(2025, 1, 1))


def test_actions_resolve_before_range_filter_and_are_gated_by_each_price_vintage() -> None:
    in_range = _action(
        "DIV-RANGE-CONFLICT",
        "dividend",
        ex_date="2024-01-11",
        payable_at="2024-01-15T00:00:00Z",
        amount=1.0,
        source_id="fixture:provider:a",
    )
    out_of_range = _action(
        "DIV-RANGE-CONFLICT",
        "dividend",
        ex_date="2024-01-09",
        payable_at="2024-01-15T00:00:00Z",
        amount=1.0,
        source="fixture:secondary-actions",
        source_id="fixture:provider:b",
    )
    range_result = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": ["2024-01-10", "2024-01-11"],
                "close": [100.0, 99.0],
                "currency": "USD",
            }
        ),
        (in_range, out_of_range),
    )

    assert range_result.status == "quarantined"
    assert range_result.total_return is None

    late_known = _action(
        "DIV-LATE-KNOWLEDGE",
        "dividend",
        ex_date="2024-01-11",
        payable_at="2024-01-15T00:00:00Z",
        known_at="2024-01-11T12:00:00Z",
        amount=1.0,
    )
    vintage_result = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": ["2024-01-10", "2024-01-11", "2024-01-11"],
                "known_at": [
                    "2024-01-10T23:00:00Z",
                    "2024-01-11T11:00:00Z",
                    "2024-01-11T13:00:00Z",
                ],
                "close": [100.0, 99.0, 99.0],
                "currency": "USD",
            }
        ),
        (late_known,),
    )

    assert vintage_result.available is True
    assert vintage_result.frame.loc[1, "security_cash_flow"] == 0.0
    assert vintage_result.frame.loc[2, "security_cash_flow"] == 1.0
    assert vintage_result.frame.loc[1, "local_total_return"] == pytest.approx(-0.01)
    assert vintage_result.frame.loc[2, "local_total_return"] == pytest.approx(0.0)


def test_duplicate_candle_compares_null_evidence_to_the_actual_first_row() -> None:
    result = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": ["2024-01-10", "2024-01-10"],
                "known_at": ["2024-01-10T23:00:00Z", "2024-01-10T23:00:00Z"],
                "close": [100.0, 100.0],
                "currency": [None, "USD"],
            }
        )
    )

    assert result.status == "quarantined"
    assert any("conflicting_duplicate_candle" in warning for warning in result.warnings)
    assert result.execution_allowed is False


def test_action_event_conventions_keep_total_return_and_split_only_share_basis() -> None:
    split = _action(
        "SPLIT-CONVENTION",
        "split",
        ex_date="2024-01-11",
        ratio=2.0,
    )
    dividend = _action(
        "DIV-SPLIT-CONVENTION",
        "dividend",
        ex_date="2024-01-11",
        payable_at="2024-01-12T00:00:00Z",
        amount=1.0,
    )
    split_adjusted = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": ["2024-01-10", "2024-01-11", "2024-01-12"],
                "close": [100.0, 50.0, 50.0],
                "currency": "USD",
            }
        ),
        (split, dividend),
        convention="split_adjusted",
    )

    assert split_adjusted.available is True
    assert split_adjusted.frame.loc[1, "security_cash_flow"] == 1.0
    assert split_adjusted.frame.loc[2, "security_cash_flow"] == 0.0
    assert split_adjusted.total_return == pytest.approx(0.01)
    assert set(split_adjusted.frame["adjusted_close_basis"]) == {"total_return"}
    assert split_adjusted.applied_ratio == pytest.approx(2.0)

    stock_dividend = _action(
        "STOCK-DIVIDEND-CONVENTION",
        "stock_dividend",
        ex_date="2024-01-11",
        payable_at="2024-01-12T00:00:00Z",
        ratio=1.1,
    )
    reinvested = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": ["2024-01-10", "2024-01-11", "2024-01-12"],
                "close": [100.0, 45.0, 45.0],
                "currency": "USD",
            }
        ),
        (split, stock_dividend, dividend),
        convention="price_plus_reinvested_income",
    )

    assert reinvested.available is True
    assert reinvested.frame.loc[1, "quantity_factor"] == pytest.approx(2.2)
    assert reinvested.frame.loc[1, "security_cash_flow"] == 1.0
    assert reinvested.frame.loc[2, "security_cash_flow"] == 0.0
    assert reinvested.frame.loc[1, "adjusted_close"] == pytest.approx(100.0)
    assert reinvested.frame.loc[1, "price_adjusted_close"] == pytest.approx(99.0)
    assert reinvested.total_return == pytest.approx(0.0)
    assert reinvested.applied_ratio == pytest.approx(2.0)

    payable_date = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": ["2024-01-10", "2024-01-11", "2024-01-12"],
                "close": [100.0, 99.0, 99.0],
                "currency": "USD",
            }
        ),
        (dividend,),
        convention="cash_on_payable_date",
    )

    assert payable_date.available is True
    assert payable_date.frame.loc[1, "security_cash_flow"] == 0.0
    assert payable_date.frame.loc[2, "security_cash_flow"] == 1.0


def test_fx_snapshot_caps_quote_day_at_knowledge_date_and_rejects_future_row_availability() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": ["2025-05-10"],
            "base_currency": ["EUR"],
            "quote_currency": ["USD"],
            "rate": [1.1],
            "source": ["fixture:fx"],
            "ingested_at": ["2025-05-01T12:00:00Z"],
        }
    )

    snapshot = build_fx_rate_snapshot(
        frame,
        decision_time="2025-05-10",
        known_at="2025-05-02T12:00:00Z",
    )
    validation = validate_fx_rates(frame, today=date(2025, 5, 10))

    assert snapshot.available is False
    assert snapshot.as_of_date is None
    assert "known by the analysis decision time" in (snapshot.reason or "")
    assert validation.ok is False
    assert any("later than their availability" in error for error in validation.errors)
    assert snapshot.execution_allowed is False


def test_late_known_at_action_on_undated_candles_fails_closed() -> None:
    dividend = _action(
        "DIV-LATE",
        "dividend",
        ex_date="2024-01-12",
        payable_at="2024-01-12T00:00:00Z",
        amount=1.0,
        known_at="2024-02-01T00:00:00Z",
    )
    prices = pd.DataFrame(
        {
            "date": ["2024-01-10", "2024-01-11", "2024-01-12"],
            "close": [100.0, 99.0, 98.0],
            "currency": "USD",
        }
    )

    result = apply_total_return_adjustments(prices, (dividend,))

    assert result.available is False
    assert "action_not_visible_at_applied_day:DIV-LATE" in result.warnings
    assert "DIV-LATE" not in result.action_ids
    assert result.total_return is None
    assert result.frame["adjusted_close"].isna().all()
    assert result.frame["security_cash_flow"].isna().all()
