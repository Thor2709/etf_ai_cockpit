"""FX1 (#956): FX conversion integrity regression tests (A109, D010, D110, B03-C2-N003)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.fx_data import FxRate, FxRateSnapshot, build_fx_rate_snapshot, fx_cross_rate, validate_fx_rates
from etf_cockpit.data.market_adjustments import (
    FXObservation,
    FXObservationStore,
    MarketAdjustmentError,
    derive_fx_cross,
    selected_currency_return,
)

TODAY = date(2026, 10, 9)
BATCH_AT = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def _frame(**overrides: object) -> pd.DataFrame:
    row = {
        "as_of_date": "2026-10-09",
        "base_currency": "USD",
        "quote_currency": "EUR",
        "rate": 0.5,
        "source": "fixture",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _obs(
    observation_id: str,
    base: str,
    quote: str,
    rate: object,
    *,
    valid_at: str = "2024-01-10T00:00:00Z",
    source: str = "fixture",
    authority: str = "official",
) -> FXObservation:
    return FXObservation(
        observation_id=observation_id,
        base_currency=base,
        quote_currency=quote,
        rate=rate,
        valid_at=valid_at,
        published_at=valid_at,
        retrieved_at=valid_at,
        known_at=valid_at,
        revision=1,
        source=source,
        source_id=f"{source}:{observation_id}",
        source_checksum=f"sha256:{observation_id}",
        authority=authority,
    )


# A109-N001 (+ B03-C2-N003 guard)
def test_batch_metadata_does_not_overwrite_row_timestamps() -> None:
    rows = _frame()
    rows["ingested_at"] = pd.Timestamp("2026-10-09T08:00:00Z")
    result = validate_fx_rates(rows, ingested_at=BATCH_AT, today=TODAY)
    assert result.ok, result.errors
    assert result.frame["ingested_at"].iloc[0] == pd.Timestamp("2026-10-09T08:00:00Z")
    # A batch time is only the fallback when a row carries none.
    fallback = validate_fx_rates(_frame(), ingested_at=BATCH_AT, today=TODAY)
    assert fallback.frame["ingested_at"].iloc[0] == pd.Timestamp(BATCH_AT)


def test_backfilled_quote_ingested_after_decision_is_not_eligible() -> None:
    rows = _frame()
    rows["ingested_at"] = pd.Timestamp("2026-10-12T08:00:00Z")
    # Batch metadata claiming an early import must not launder the late row timestamp.
    validated = validate_fx_rates(rows, ingested_at=datetime(2026, 10, 9, 8, tzinfo=timezone.utc), today=date(2026, 10, 12)).frame
    snapshot = build_fx_rate_snapshot(validated, decision_time=datetime(2026, 10, 9, 20, tzinfo=timezone.utc))
    assert snapshot.available is False
    assert snapshot.rates == ()


# A109-N002 / A109-N003
def test_contradictory_pair_fields_and_boolean_rate_are_rejected() -> None:
    contradictory = validate_fx_rates(_frame(pair="GBP/EUR"), today=TODAY)
    assert not contradictory.ok
    assert any("contradictory" in error for error in contradictory.errors)
    assert validate_fx_rates(_frame(pair="USD/EUR"), today=TODAY).ok

    for rate in (True, False):
        result = validate_fx_rates(_frame(rate=rate), today=TODAY)
        assert not result.ok
        assert any("boolean" in error or "greater than zero" in error for error in result.errors)
    boolean_dtype = _frame(rate=True)
    boolean_dtype["rate"] = boolean_dtype["rate"].astype(bool)
    assert not validate_fx_rates(boolean_dtype, today=TODAY).ok


@pytest.mark.parametrize("field,contradiction", [("base_currency", "GBP"), ("quote_currency", "JPY")])
def test_partial_explicit_currency_field_must_agree_with_pair(field: str, contradiction: str) -> None:
    other = "quote_currency" if field == "base_currency" else "base_currency"
    rows = _frame(pair="USD/EUR").drop(columns=[other])
    assert validate_fx_rates(rows, today=TODAY).ok
    rows[field] = contradiction
    result = validate_fx_rates(rows, today=TODAY)
    assert not result.ok
    assert result.frame.empty
    assert any("contradictory" in error for error in result.errors)


# D110-N001
def test_relative_tolerance_rejects_2_25_percent_gap_on_tiny_rates() -> None:
    first = _obs("a", "XXX", "EUR", Decimal("0.0000400"), source="s1")
    second = _obs("b", "XXX", "EUR", Decimal("0.0000409"), source="s2")
    for ordering in ((first, second), (second, first)):
        result = derive_fx_cross(ordering, "XXX", "EUR", "2024-01-10T00:00:00Z")
        assert result.status == "quarantined"
        assert result.rate is None
    close = _obs("c", "XXX", "EUR", Decimal("0.0000400000001"), source="s3")
    assert derive_fx_cross((first, close), "XXX", "EUR", "2024-01-10T00:00:00Z").available

    snapshot = FxRateSnapshot(
        date(2026, 10, 9), date(2026, 10, 9),
        (FxRate("XXX", "EUR", 0.00004, "s1"), FxRate("XXX", "EUR", 0.0000409, "s2")),
        "chk", 0, "ok", True, None,
    )
    assert fx_cross_rate(snapshot, "XXX", "EUR") is None


# D110-N002 / D110-N003
@pytest.mark.parametrize("rate", [0, Decimal("0"), -1, float("nan"), float("inf"), True, 5e-324, 1e-310, 1e308, "abc", None])
def test_zero_nonfinite_and_subnormal_rates_are_rejected_at_construction(rate: object) -> None:
    with pytest.raises(MarketAdjustmentError):
        _obs("bad", "USD", "EUR", rate)


def test_subnormal_rate_is_rejected_before_cross_derivation_and_inverse() -> None:
    assert not validate_fx_rates(_frame(rate=5e-324), today=TODAY).ok
    snapshot = FxRateSnapshot(
        date(2026, 10, 9), date(2026, 10, 9), (FxRate("USD", "EUR", 5e-324, "s"),), "chk", 0, "ok", True, None,
    )
    assert fx_cross_rate(snapshot, "EUR", "USD") is None
    assert fx_cross_rate(snapshot, "USD", "EUR") is None


@pytest.mark.parametrize("rate", [1e200, 1e-200, 1e154, 1e-154])
@pytest.mark.parametrize("intermediate", [False, True])
def test_accumulated_cross_rate_outside_supported_range_is_unavailable(rate: float, intermediate: bool) -> None:
    observations = [
        _obs("usd-gbp", "USD", "GBP", rate),
        _obs("gbp-next", "GBP", "JPY" if intermediate else "EUR", rate),
    ]
    if intermediate:
        # A later leg cannot rescue an unsupported accumulated rate.
        observations.append(_obs("jpy-eur", "JPY", "EUR", 1.0 / rate))
    result = derive_fx_cross(observations, "USD", "EUR", "2024-01-10T00:00:00Z")
    assert result.status == "unavailable"
    assert not result.available
    assert result.rate is None
    assert "fx_cross_rate_out_of_supported_range" in result.discrepancies
    assert result.execution_allowed is False


# D010-N001 / D010-N002
def test_implicit_return_start_is_per_currency_and_identity_needs_no_store(tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        store.append(_obs("old-gbp", "GBP", "EUR", Decimal("1.20"), valid_at="2024-01-02T00:00:00Z"))
        store.append(_obs("usd-1", "USD", "EUR", Decimal("0.90"), valid_at="2024-01-09T00:00:00Z"))
        store.append(_obs("usd-2", "USD", "EUR", Decimal("0.99"), valid_at="2024-01-10T00:00:00Z"))
        result = selected_currency_return(
            0.10, base_currency="USD", output_currency="EUR", fx_store=store, valuation_at="2024-01-10T00:00:00Z"
        )
        assert result.available
        # The unrelated, older GBP quote must not move the USD/EUR start.
        assert result.transaction_at == "2024-01-09T00:00:00Z"
        assert result.fx_return == pytest.approx(0.99 / 0.90 - 1.0)

        unrelated_only = selected_currency_return(
            0.10, base_currency="NOK", output_currency="EUR", fx_store=store, valuation_at="2024-01-10T00:00:00Z"
        )
        assert unrelated_only.available is False
        assert unrelated_only.reason_code in {"FX_MISSING", "FX_STALE"}

    with FXObservationStore(tmp_path / "empty") as empty:
        for store_arg in (empty, None):
            identity = selected_currency_return(
                0.10, base_currency="EUR", output_currency="EUR", fx_store=store_arg, valuation_at="2024-01-10T00:00:00Z"
            )
            assert identity.available
            assert identity.fx_return == 0.0
            assert identity.output_return == pytest.approx(0.10)
            assert identity.execution_allowed is False
        assert derive_fx_cross(empty, "EUR", "EUR", "2024-01-10T00:00:00Z").available


def test_implicit_return_start_includes_intermediate_edge_dates_without_lookahead(tmp_path: Path) -> None:
    for late in (False, True):
        with FXObservationStore(tmp_path / ("late" if late else "on-time")) as store:
            store.append(_obs("usd-gbp-1", "USD", "GBP", 2.0, valid_at="2024-01-01T00:00:00Z"))
            store.append(_obs("jpy-eur", "JPY", "EUR", 0.01, valid_at="2024-01-01T00:00:00Z"))
            bridge = _obs("gbp-jpy", "GBP", "JPY", 100.0, valid_at="2024-01-02T00:00:00Z")
            if late:
                bridge = replace(bridge, retrieved_at="2024-01-03T00:00:00Z", known_at="2024-01-03T00:00:00Z")
            store.append(bridge)
            store.append(_obs("usd-gbp-3", "USD", "GBP", 3.0, valid_at="2024-01-03T00:00:00Z"))
            result = selected_currency_return(
                0.10, base_currency="USD", output_currency="EUR", fx_store=store, valuation_at="2024-01-03T00:00:00Z"
            )
            assert result.available
            assert result.transaction_at == ("2024-01-03T00:00:00Z" if late else "2024-01-02T00:00:00Z")
            assert result.transaction_rate == pytest.approx(3.0 if late else 2.0)
            assert result.valuation_rate == pytest.approx(3.0)
            assert result.fx_return == pytest.approx(0.0 if late else 0.5)
            assert result.output_return == pytest.approx(0.10 if late else 0.65)
            assert result.execution_allowed is False
