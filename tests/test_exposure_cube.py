from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.portfolio.exposure_cube import build_portfolio_exposure_cube
from etf_cockpit.application.portfolio_views import load_portfolio_exposure_projection


_DECISION_TIME = datetime(2026, 7, 18, 10, tzinfo=timezone.utc)


def _row(instrument_id: str, **values: object) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "as_of": "2026-07-01",
        "known_at": "2026-07-02T00:00:00Z",
        "source_id": f"{instrument_id.lower()}-issuer",
        "authority": "issuer",
        "completeness": "full",
        **values,
    }


def _apple_holding(instrument_id: str = "ETF-A") -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(
                instrument_id,
                security="Apple Inc.",
                isin="US0378331005",
                weight=1.0,
                exposure_type="security",
                issuer="Apple Inc.",
                sector="Information Technology",
                country="US",
                currency="USD",
            )
        ]
    )


def test_every_dimension_totals_100_percent_including_unknown() -> None:
    cube = build_portfolio_exposure_cube(
        _apple_holding(),
        {"ETF-A": 1.0},
        decision_time=_DECISION_TIME,
        reporting_currency="EUR",
    )

    assert cube.dimensions
    for dimension in cube.dimensions:
        assert sum(segment.percentage for segment in dimension.segments) == pytest.approx(100.0, abs=1e-7)
        assert any(segment.bucket == "Unknown/Unmapped" for segment in dimension.segments)
        assert dimension.mapped_weight + dimension.stale_weight + dimension.unmapped_weight == pytest.approx(1.0)


def test_partial_coverage_has_unknown_segment_and_coverage_below_100_percent() -> None:
    holdings = pd.DataFrame(
        [
            _row(
                "ETF-A",
                security="Apple Inc.",
                isin="US0378331005",
                weight=0.6,
                exposure_type="security",
                sector="Information Technology",
            ),
            _row("ETF-A", security="Unidentified holding", isin="", weight=0.4),
        ]
    )

    cube = build_portfolio_exposure_cube(
        holdings,
        {"ETF-A": 1.0},
        decision_time=_DECISION_TIME,
    )
    sector = next(item for item in cube.dimensions if item.dimension == "sector")

    assert sector.coverage_fraction == pytest.approx(0.6)
    assert sector.unmapped_weight == pytest.approx(0.4)
    unknown = next(item for item in sector.segments if item.bucket == "Unknown/Unmapped")
    assert unknown.amount == pytest.approx(0.4)
    assert unknown.percentage == pytest.approx(40.0)
    assert unknown.reasons


def test_foreign_holding_distinguishes_trading_reporting_and_economic_currency() -> None:
    cube = build_portfolio_exposure_cube(
        _apple_holding(),
        {"ETF-A": 1.0},
        decision_time=_DECISION_TIME,
        position_metadata={"ETF-A": {"trading_currency": "EUR"}},
        reporting_currency="GBP",
    )

    buckets = {
        item.dimension: {segment.bucket for segment in item.segments if segment.bucket != "Unknown/Unmapped"}
        for item in cube.dimensions
    }
    assert buckets["trading_currency"] == {"EUR"}
    assert buckets["reporting_currency"] == {"GBP"}
    assert buckets["economic_currency"] == {"USD"}


def test_facade_projection_returns_chart_segments_and_coverage() -> None:
    projection = load_portfolio_exposure_projection(
        {"ETF-A": 1.0},
        decision_time=_DECISION_TIME,
        holdings=_apple_holding(),
        reporting_currency="EUR",
    )

    assert projection["status"] == "available"
    assert projection["execution_allowed"] is False
    assert projection["dimensions"]["sector"][0]["name"] == "Information Technology"
    assert projection["coverage"]["sector"]["coverage_fraction"] == pytest.approx(1.0)


def test_nested_fund_and_direct_position_aggregate_same_security_once() -> None:
    holdings = pd.DataFrame(
        [
            _row(
                "ROOT",
                security="Alpha",
                isin="GB0002634946",
                weight=0.3,
                exposure_type="security",
                issuer="Alpha Issuer",
                sector="Technology",
                country="GB",
                currency="GBP",
            ),
            _row(
                "ROOT",
                security="Nested ETF",
                identity_type="fund",
                identity_namespace="canonical",
                identity_value="NESTED",
                nested_instrument_id="NESTED",
                weight=0.5,
                exposure_type="fund",
            ),
            _row("ROOT", security="Cash", weight=0.1, exposure_type="cash", currency="EUR"),
            _row(
                "ROOT",
                security="Future",
                identity_type="derivative",
                identity_namespace="issuer",
                identity_value="future-1",
                weight=0.1,
                exposure_type="derivative",
            ),
            _row(
                "NESTED",
                security="Alpha renamed",
                isin="GB0002634946",
                weight=0.4,
                exposure_type="security",
                issuer="Alpha Issuer",
            ),
            _row(
                "NESTED",
                security="Index future",
                identity_type="derivative",
                identity_namespace="issuer",
                identity_value="future-2",
                underlying_identity="index:canonical:world",
                weight=0.2,
                exposure_type="derivative",
            ),
        ]
    )
    cube = build_portfolio_exposure_cube(
        holdings,
        {"ROOT": 0.8, "GB0002634946": 0.2},
        decision_time=_DECISION_TIME,
        position_metadata={
            "GB0002634946": {
                "exposure_type": "security",
                "asset_class": "equity",
                "issuer": "Alpha Issuer",
                "sector": "Technology",
                "economic_country": "GB",
                "economic_currency": "GBP",
            }
        },
    )
    security = next(item for item in cube.dimensions if item.dimension == "security")
    alpha = [item for item in security.segments if item.bucket == "isin:GB0002634946"]

    assert len(alpha) == 1
    assert alpha[0].amount == pytest.approx(0.6)
    assert alpha[0].direct_weight == pytest.approx(0.44)
    assert alpha[0].indirect_weight == pytest.approx(0.16)
    assert sum(item.percentage for item in security.segments) == pytest.approx(100.0)


def test_future_holding_metadata_is_unknown_at_decision_time() -> None:
    cube = build_portfolio_exposure_cube(
        _apple_holding(),
        {"ETF-A": 1.0},
        decision_time=_DECISION_TIME,
        holding_metadata={
            "isin:US0378331005": {
                "asset_class": "equity",
                "known_at": "2099-01-01T00:00:00Z",
            }
        },
    )
    asset_class = next(item for item in cube.dimensions if item.dimension == "asset_class")
    unknown = next(item for item in asset_class.segments if item.bucket == "Unknown/Unmapped")

    assert asset_class.mapped_weight == 0.0
    assert unknown.amount == pytest.approx(1.0)
    assert any("unavailable at decision time" in reason for reason in unknown.reasons)


def test_stale_holdings_are_reported_as_stale_not_mapped() -> None:
    holdings = _apple_holding()
    holdings["as_of"] = "2026-01-01"
    holdings["known_at"] = "2026-01-02T00:00:00Z"

    cube = build_portfolio_exposure_cube(
        holdings,
        {"ETF-A": 1.0},
        decision_time=_DECISION_TIME,
    )
    sector = next(item for item in cube.dimensions if item.dimension == "sector")

    assert sector.mapped_weight == 0.0
    assert sector.stale_weight == pytest.approx(1.0)
    assert sector.unmapped_weight == 0.0
    assert sector.coverage_fraction == 0.0
    assert next(item for item in cube.sources if item.instrument_id == "ETF-A").freshness == "stale"


def test_future_classification_metadata_cannot_replace_look_through() -> None:
    cube = build_portfolio_exposure_cube(
        _apple_holding(),
        {"ETF-A": 1.0},
        decision_time=_DECISION_TIME,
        position_metadata={"ETF-A": {"exposure_type": "security", "known_at": "2099-01-01T00:00:00Z"}},
    )
    security = next(item for item in cube.dimensions if item.dimension == "security")
    buckets = {item.bucket: item.amount for item in security.segments}

    assert not any("ETF-A" in bucket for bucket in buckets)
    assert any("US0378331005" in bucket and amount == pytest.approx(1.0) for bucket, amount in buckets.items())
