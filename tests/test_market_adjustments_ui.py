from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.app.pages.etf_detail import etf_detail_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import load_market_series_projection
from etf_cockpit.data.market_adjustments import (
    CorporateAction,
    CorporateActionCoverage,
    CorporateActionCoverageStore,
    CorporateActionStore,
    FXObservation,
    FXObservationStore,
)
from etf_cockpit.services import build_snapshot


def _walk(control: object):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _prices(instrument_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "etf_id": [instrument_id, instrument_id],
            "date": ["2024-01-10", "2024-01-11"],
            "close": [100.0, 101.0],
            "adjusted_close": [100.0, 101.0],
        }
    )


def _coverage(instrument_id: str) -> CorporateActionCoverage:
    return CorporateActionCoverage(
        instrument_id=instrument_id,
        coverage_through="2024-01-11T00:00:00Z",
        published_at="2024-01-09T00:00:00Z",
        retrieved_at="2024-01-10T00:00:00Z",
        known_at="2024-01-11T00:00:00Z",
        revision=1,
        source="fixture:official-actions",
        source_id=f"fixture:official-actions:coverage:{instrument_id}:r1",
        source_checksum="c" * 64,
    )


def test_market_series_facade_keeps_raw_available_but_blocks_uncovered_adjusted_bases(tmp_path: Path) -> None:
    prices = _prices("ETF-1")
    original = prices.copy(deep=True)

    raw = load_market_series_projection(prices, "ETF-1", basis="raw", local_currency="EUR", storage_root=tmp_path)
    adjusted = load_market_series_projection(prices, "ETF-1", basis="adjusted", local_currency="EUR", storage_root=tmp_path)
    total = load_market_series_projection(prices, "ETF-1", basis="total_return", local_currency="EUR", storage_root=tmp_path)

    assert raw["status"] == "available"
    assert {adjusted["status"], total["status"]} == {"unavailable"}
    assert adjusted["reason_code"] == "corporate_action_coverage_unavailable"
    assert total["reason_code"] == "corporate_action_coverage_unavailable"
    assert raw["frame"]["series_value"].tolist() == [100.0, 101.0]
    assert all(result["execution_allowed"] is False for result in (raw, adjusted, total))
    pd.testing.assert_frame_equal(prices, original)


def test_base_currency_switch_fails_closed_without_dated_fx(tmp_path: Path) -> None:
    with CorporateActionCoverageStore(tmp_path) as coverage:
        coverage.append(_coverage("ETF-1"))
    result = load_market_series_projection(
        _prices("ETF-1"),
        "ETF-1",
        basis="total_return",
        local_currency="USD",
        output_currency="EUR",
        storage_root=tmp_path,
    )

    assert result["status"] == "unavailable"
    assert result["reason_code"] == "required_fx_missing_stale_or_conflicted"
    assert result["execution_allowed"] is False


def test_facade_applies_persisted_actions_and_dated_fx_without_mutating_local_prices(tmp_path: Path) -> None:
    prices = _prices("ETF-1")
    prices["close"] = [100.0, 100.0]
    with CorporateActionCoverageStore(tmp_path) as coverage:
        coverage.append(_coverage("ETF-1"))
    with CorporateActionStore(tmp_path) as actions:
        actions.append(
            CorporateAction(
                action_id="DIV-UI-1",
                instrument_id="ETF-1",
                action_type="dividend",
                announced_at="2024-01-09T00:00:00Z",
                effective_at="2024-01-11T00:00:00Z",
                ex_date="2024-01-11",
                payable_at="2024-01-15T00:00:00Z",
                known_at="2024-01-09T00:00:00Z",
                revision=1,
                source="fixture:official-actions",
                source_id="fixture:div-ui-1",
                source_checksum="a" * 64,
                amount=1.0,
                currency="USD",
            )
        )
    with FXObservationStore(tmp_path) as fx:
        for identifier, valid_at, rate in (
            ("USDEUR-1", "2024-01-10T00:00:00Z", "0.90"),
            ("USDEUR-2", "2024-01-11T00:00:00Z", "0.99"),
        ):
            fx.append(
                FXObservation(
                    observation_id=identifier,
                    base_currency="USD",
                    quote_currency="EUR",
                    rate=rate,
                    valid_at=valid_at,
                    published_at=valid_at,
                    retrieved_at=valid_at,
                    known_at=valid_at,
                    revision=1,
                    source="fixture:official-fx",
                    source_id=f"fixture:{identifier}",
                    source_checksum="b" * 64,
                )
            )

    result = load_market_series_projection(
        prices,
        "ETF-1",
        basis="total_return",
        local_currency="USD",
        output_currency="EUR",
        storage_root=tmp_path,
        decision_time="2024-01-11T00:00:00Z",
    )

    assert result["status"] == "available"
    assert result["frame"]["series_value"].tolist() == pytest.approx([100.0, 111.1])
    assert result["execution_allowed"] is False


def test_market_series_facade_returns_controlled_unavailable_for_malformed_prices(tmp_path: Path) -> None:
    malformed = _prices("ETF-1")
    malformed["close"] = ["not-a-price", 101.0]

    result = load_market_series_projection(
        malformed,
        "ETF-1",
        basis="raw",
        local_currency="USD",
        storage_root=tmp_path,
    )

    assert result["status"] == "unavailable"
    assert result["reason_code"] == "market_adjustment_evidence_invalid"
    assert result["frame"].empty
    assert result["execution_allowed"] is False


def test_etf_detail_exposes_price_basis_currency_and_series_controls() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    control = etf_detail_page(None, state)
    keys = {str(getattr(item, "key", "")) for item in _walk(control)}

    assert {
        "instrument-detail.price-basis",
        "instrument-detail.price-currency",
        "instrument-detail.price-series",
    } <= keys
