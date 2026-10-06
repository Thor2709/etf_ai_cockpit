from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
import math

import pandas as pd
import pytest

from etf_cockpit.data.fx_data import build_fx_rate_snapshot, fx_cross_rate, validate_fx_rates
from etf_cockpit.application.portfolio_views import project_portfolio_currency as facade_project_portfolio_currency
from etf_cockpit.portfolio.currency import project_portfolio_currency
from etf_cockpit.portfolio.costs import CostEstimate, PortfolioCostEstimate
from etf_cockpit.portfolio.sandbox import (
    PortfolioAllocationRow,
    PortfolioAnalysis,
    PortfolioCandidate,
    PortfolioHoldingRow,
)


def test_fx_triangular_and_reciprocal_consistency() -> None:
    rates = pd.DataFrame(
        [
            {"as_of_date": "2026-01-02", "base_currency": "EUR", "quote_currency": "USD", "rate": 1.1},
            {"as_of_date": "2026-01-02", "base_currency": "EUR", "quote_currency": "GBP", "rate": 0.85},
            {"as_of_date": "2026-01-02", "base_currency": "USD", "quote_currency": "EUR", "rate": 1.0 / 1.1},
        ]
    )
    rates["source"] = "ECB"
    rates["ingested_at"] = "2026-01-02T09:00:00Z"

    validation = validate_fx_rates(rates, today=date(2026, 1, 3))
    assert validation.ok, validation.errors
    assert validation.frame.loc[0, "pair"] == "EUR/USD"
    snapshot = build_fx_rate_snapshot(rates, decision_time="2026-01-03")
    assert snapshot.available

    cross = fx_cross_rate(snapshot, "USD", "GBP")
    assert cross is not None
    assert math.isclose(cross.rate, 0.85 / 1.1, rel_tol=0.0, abs_tol=1e-6)
    assert cross.execution_allowed is False
    assert "informational" in cross.label

    reciprocal_path = fx_cross_rate(snapshot, "GBP", "USD")
    assert reciprocal_path is not None
    assert reciprocal_path.legs[0].inverted is True
    assert reciprocal_path.legs[0].observed_pair == "EUR/GBP"

    inconsistent_triangle = pd.concat(
        [rates, pd.DataFrame([{"as_of_date": "2026-01-02", "base_currency": "USD", "quote_currency": "GBP", "rate": 0.8, "source": "ECB", "ingested_at": "2026-01-02T09:00:00Z"}])],
        ignore_index=True,
    )
    assert any("triangular" in error for error in validate_fx_rates(inconsistent_triangle, today=date(2026, 1, 3)).errors)

    inconsistent_reciprocal = rates.copy()
    reciprocal_mask = inconsistent_reciprocal["base_currency"].eq("USD") & inconsistent_reciprocal["quote_currency"].eq("EUR")
    inconsistent_reciprocal.loc[reciprocal_mask, "rate"] = 0.8
    assert any("reciprocal" in error for error in validate_fx_rates(inconsistent_reciprocal, today=date(2026, 1, 3)).errors)


def test_stale_fx_fails_closed() -> None:
    analysis = _analysis("2026-07-10")
    stale_rates = pd.DataFrame(
        {
            "date": ["2026-06-01"],
            "value": [1.0],
            "base_currency": ["EUR"],
            "quote_currency": ["USD"],
            "rate": [1.1],
            "source": ["ECB"],
            "ingested_at": ["2026-06-01T09:00:00Z"],
        }
    )
    stale_snapshot = build_fx_rate_snapshot(stale_rates, decision_time="2026-07-10")
    assert stale_snapshot.available is False
    assert stale_snapshot.staleness_status == "block"
    stale_projection = project_portfolio_currency(analysis, "USD", stale_rates)
    assert stale_projection.available is False
    assert stale_projection.reference_rate is None
    assert stale_projection.monetary_fields["current_value_eur"]["value"] is None
    assert "stale" in (stale_projection.reason or "")

    missing_date = stale_rates.copy()
    missing_date["date"] = [None]
    missing_snapshot = build_fx_rate_snapshot(missing_date, decision_time="2026-07-10")
    assert missing_snapshot.available is False
    assert "missing or invalid quote date" in (missing_snapshot.reason or "")
    missing_projection = project_portfolio_currency(analysis, "USD", missing_date)
    assert missing_projection.available is False
    assert missing_projection.monetary_fields["current_value_eur"]["value"] is None


def test_currency_projection_immutability() -> None:
    analysis = _analysis("2026-07-10")
    before = deepcopy(asdict(analysis))
    rates = pd.DataFrame(
        [
            {"as_of_date": "2026-07-09", "base_currency": "EUR", "quote_currency": "USD", "rate": 1.1},
            {"as_of_date": "2026-07-09", "base_currency": "EUR", "quote_currency": "USD", "rate": 1.15},
            {"as_of_date": "2026-07-09", "base_currency": "EUR", "quote_currency": "GBP", "rate": 0.85},
            {"as_of_date": "2026-07-11", "base_currency": "EUR", "quote_currency": "USD", "rate": 1.2},
        ]
    )
    rates["source"] = "ECB"
    rates["ingested_at"] = [
        "2026-07-09T09:00:00Z",
        "2026-07-10T12:00:00Z",
        "2026-07-09T09:00:00Z",
        "2026-07-09T09:00:00Z",
    ]

    usd = project_portfolio_currency(analysis, "USD", rates)
    gbp = project_portfolio_currency(analysis, "GBP", rates)

    assert usd.available
    assert usd.currency == "USD"
    assert usd.reference_rate == 1.1
    assert usd.fx_snapshot_date == date(2026, 7, 9)
    assert "informational" in usd.reference_rate_label
    assert usd.execution_allowed is False
    assert usd.projection_id != gbp.projection_id
    assert usd.monetary_fields["current_value_eur"]["value"] == 1320.0
    assert usd.monetary_fields["current_value_eur"]["currency"] == "USD"
    assert usd.monetary_fields["current_value_eur"]["source_snapshot"] == usd.source_snapshot
    assert math.isclose(usd.monetary_fields["allocations[0].signed_notional_eur"]["value"], 110.0)
    assert math.isclose(usd.monetary_fields["cost.estimates[0].commission_eur"]["value"], 1.32)
    with pytest.raises(TypeError):
        usd.monetary_fields["current_value_eur"]["value"] = 0.0
    assert deepcopy(asdict(analysis)) == before


def test_currency_projection_handles_invalid_monetary_value_during_snapshot() -> None:
    analysis = replace(_analysis("2026-07-10"), current_value_eur="not-a-number")

    projection = project_portfolio_currency(analysis, "EUR", pd.DataFrame())

    field = projection.monetary_fields["current_value_eur"]
    assert projection.analysis_source_snapshot is not None
    assert field["value"] is None
    assert field["unavailable_reason"] == "Source monetary amount is invalid."


def test_currency_facade_gives_detail_and_bulk_identical_projection() -> None:
    analysis = _analysis("2026-07-10")
    rates = pd.DataFrame(
        [
            {"as_of_date": "2026-07-09", "base_currency": "EUR", "quote_currency": "USD", "rate": 1.1},
        ]
    )
    rates["source"] = "ECB"
    rates["ingested_at"] = "2026-07-09T09:00:00Z"

    detail_projection = facade_project_portfolio_currency(analysis, "USD", rates)
    bulk_projection = facade_project_portfolio_currency(analysis, "USD", rates)

    assert detail_projection == bulk_projection


def _analysis(source_as_of: str) -> PortfolioAnalysis:
    candidate = PortfolioCandidate(
        candidate_id="fixture-candidate",
        name="Fixture",
        analysis_notional_eur=1000.0,
        target_weights=(("fixture-instrument", 1.0),),
        cash_weight=0.0,
        source_revision="fixture-revision",
        source_checksum="fixture-analysis-checksum",
        source_as_of=source_as_of,
    )
    allocation = PortfolioAllocationRow(
        instrument_id="fixture-instrument",
        name="Fixture instrument",
        current_weight=0.5,
        target_weight=0.6,
        drift=0.1,
        signed_notional_eur=100.0,
        market_value_eur=500.0,
        drift_status="above_soft_band",
    )
    holding = PortfolioHoldingRow(
        instrument_id="fixture-instrument",
        name="Fixture instrument",
        asset_type="etf",
        holding_view="direct",
        current_weight=0.5,
        market_value_eur=500.0,
        capability_status="supported",
        capability_reason="fixture",
    )
    estimate = CostEstimate(
        estimate_id="fixture-estimate",
        model_id="fixture-model",
        instrument_id="fixture-instrument",
        order_value_eur=100.0,
        commission_eur=1.2,
        spread_bps=2.0,
        slippage_bps=0.0,
        volatility_volume_impact_bps=0.0,
        square_root_impact_bps=0.0,
        market_impact_bps=0.0,
        fx_bps=0.0,
        gap_bps=0.0,
        uncertainty_multiplier=1.0,
        total_cost_bps=2.0,
        total_cost_eur=1.2,
        capacity_eur=1000.0,
        capacity_status="available",
        data_quality="fixture",
    )
    cost = PortfolioCostEstimate(
        model_id="fixture-model",
        total_order_value_eur=100.0,
        total_cost_eur=1.2,
        weighted_cost_bps=120.0,
        capacity_eur=1000.0,
        estimates=(estimate,),
    )
    return PortfolioAnalysis(
        candidate=candidate,
        allocations=(allocation,),
        sector_exposure=(),
        region_exposure=(),
        currency_exposure=(),
        warnings=(),
        cost=cost,
        current_value_eur=1200.0,
        current_cash_weight=0.0,
        source_stale=False,
        overlap=None,  # type: ignore[arg-type]
        holdings=(holding,),
    )
