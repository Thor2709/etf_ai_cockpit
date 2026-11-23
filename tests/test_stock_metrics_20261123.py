"""Train R2-F: financials routing by industry, sector metric sets and new SEC metrics (2026-11-23)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from etf_cockpit.analysis.stock_universe import FINANCIAL_INDUSTRY_MISSING, FINANCIAL_SET_NOT_BUILT, financial_route_reason
from etf_cockpit.signals import simple_scores as ss


def _evidence() -> SimpleNamespace:
    part = SimpleNamespace(score_10=8.0, why="generic", source_id="sec_edgar:fundamentals", as_of="2025-01-09", freshness="ok",
                           band_low=None, band_high=None, used=(), inputs=())
    return SimpleNamespace(components={"stock_value": part, "stock_quality": part, "analyst_revision": part}, metrics={})


def _scores(industry: str | None) -> dict[str, float | None]:
    parts = ss._stock_fundamental_components(_evidence(), None, sector="Financial Services", industry=industry)
    return {part.key: part.score_10 for part in parts}


# --- item 1 (F4): fee-based financials are scored, banks and insurers stay out --------------------------------------


@pytest.mark.parametrize("industry", ["Asset Management", "Financial Data & Stock Exchanges", "Insurance Brokers"])
def test_fee_based_financials_use_the_existing_metric_set(industry: str) -> None:
    assert financial_route_reason("Financial Services", industry) is None
    assert _scores(industry)["stock_value"] == 8.0 and _scores(industry)["stock_quality"] == 8.0


@pytest.mark.parametrize("industry", ["Banks - Regional", "Banks - Diversified", "Capital Markets", "Credit Services"])
def test_banks_and_lenders_stay_out_until_their_set_exists(industry: str) -> None:
    assert financial_route_reason("Financial Services", industry) == FINANCIAL_SET_NOT_BUILT
    parts = {p.key: p for p in ss._stock_fundamental_components(_evidence(), None, sector="Financial Services", industry=industry)}
    assert parts["stock_value"].score_10 is None and FINANCIAL_SET_NOT_BUILT in parts["stock_value"].why


@pytest.mark.parametrize("industry", ["Insurance - Life", "Insurance - Property & Casualty", "Insurance - Reinsurance"])
def test_insurers_stay_out_until_their_set_exists(industry: str) -> None:
    assert financial_route_reason("Financials", industry) == FINANCIAL_SET_NOT_BUILT
    assert _scores(industry)["stock_quality"] is None


@pytest.mark.parametrize("industry", [None, "", "  "])
def test_financial_without_industry_fails_closed(industry: str | None) -> None:
    assert financial_route_reason("Financial Services", industry) == FINANCIAL_INDUSTRY_MISSING
    parts = {p.key: p for p in ss._stock_fundamental_components(_evidence(), None, sector="Financial Services", industry=industry)}
    assert parts["stock_value"].score_10 is None and FINANCIAL_INDUSTRY_MISSING in parts["stock_value"].why
    assert parts["analyst_revision"].score_10 == 8.0


def test_non_financial_sector_ignores_industry() -> None:
    assert financial_route_reason("Industrials", None) is None
    assert financial_route_reason("Industrials", "Banks - Regional") is None
