from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.decision.etf import compose_etf_decision
from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.analysis.peer_cohorts import PeerObservation
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.etf_economics import (
    TotalReturnEvidence,
    calculate_etf_economics,
)
from etf_cockpit.data.market_adjustments import (
    CorporateActionCoverage,
    CorporateActionCoverageStore,
    apply_total_return_adjustments,
)


DECISION = "2026-01-06T00:00:00Z"
EFFECTIVE = "2026-01-05T00:00:00Z"


def _context(instrument: str):
    values = {
        "instrument_type": "ETF",
        "asset_class": "equity",
        "trading_currency": "USD",
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument}:{field}",
            instrument_id=instrument,
            field=field,
            value=value,
            source="#809 synthetic fixture",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{instrument}:{field}",
            confidence=0.95,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence,
        instrument_id=instrument,
        effective_at=EFFECTIVE,
        decision_time=DECISION,
    )


def _total_return_series(
    tmp_path: Path, instrument: str, values: list[float]
) -> TotalReturnEvidence:
    dates = pd.bdate_range("2026-01-01", periods=len(values))
    source_id = "test"
    adjustment = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": dates,
                "close": values,
                "instrument_id": instrument,
                "currency": "USD",
                "source_id": source_id,
                "provenance": "unit-test",
            }
        )
    )
    coverage = CorporateActionCoverage(
        instrument_id=instrument,
        coverage_through=str(dates[-1]),
        published_at=str(dates[-1]),
        retrieved_at=str(dates[-1]),
        known_at=str(dates[-1]),
        revision=1,
        source="unit-test",
        source_id="coverage-test",
        source_checksum="c" * 64,
    )
    with CorporateActionCoverageStore(tmp_path / instrument) as store:
        trusted_coverage = store.append(coverage)
    return TotalReturnEvidence.from_adjustment_result(
        adjustment,
        instrument_id=instrument,
        currency="USD",
        known_at=str(dates[-1]),
        as_of=str(dates[-1]),
        source_id=source_id,
        provenance="unit-test",
        corporate_action_coverage=trusted_coverage,
    )


def _peer(metric: str, value: float, instrument: str) -> PeerObservation:
    return PeerObservation(
        instrument_id=instrument,
        context=_context(instrument),
        metric=metric,
        value=value,
        weight=1.0,
        effective_at=EFFECTIVE,
        known_at=DECISION,
    )


def _look_through_summary():
    holdings = pd.DataFrame(
        [
            {
                "security": "Apple",
                "isin": "US0378331005",
                "weight": 1.0,
                "issuer": "apple",
                "company": "apple",
                "currency": "USD",
                "factor": "value",
                "exposure_type": "security",
                "instrument_id": "target",
                "as_of": "2026-01-05",
                "source": "issuer",
                "source_id": "holdings:target",
                "known_at": "2026-01-05T12:00:00Z",
                "revision": "revision-1",
            }
        ]
    )
    fundamentals = pd.DataFrame(
        [
            {
                "identity": "apple",
                "pe_ratio": 50.0,
                "roic": 0.01,
                "currency": "USD",
                "as_of_date": "2026-01-04",
                "available_at": "2026-01-05T12:00:00Z",
                "source_id": "fundamental:target",
            }
        ]
    )
    return calculate_look_through(
        holdings,
        instrument_id="target",
        decision_time=DECISION,
        constituent_fundamentals=fundamentals,
    )


def test_canonical_tracking_uses_annualized_mean_active_return(tmp_path: Path) -> None:
    fund_values = [100.0, 102.0, 103.0, 108.0]
    benchmark_values = [100.0, 101.0, 104.0, 105.0]
    active_returns = pd.Series(fund_values).pct_change().iloc[1:] - pd.Series(
        benchmark_values
    ).pct_change().iloc[1:]
    records = [
        {
            "instrument_id": "target",
            "scope": "fund",
            "as_of": "2026-01-05",
            "known_at": "2026-01-05",
            "currency": "USD",
            "benchmark_id": "benchmark",
            "benchmark_currency": "USD",
            "ter": 0.002,
            "fee_unit": "decimal_fraction",
            "source_id": "fund-economics:target",
            "source_provenance": "#809 synthetic fixture",
            "source_checksum": "b" * 64,
        }
    ]

    report = calculate_etf_economics(
        "target",
        records,
        fund_total_return=_total_return_series(tmp_path, "target", fund_values),
        benchmark_total_return=_total_return_series(
            tmp_path, "benchmark", benchmark_values
        ),
        as_of=DECISION,
        horizon_days=3,
    )

    assert report.tracking_status == "available"
    assert report.tracking_difference == round(float(active_returns.mean() * 252), 10)
    assert report.tracking_error == round(
        float(active_returns.std(ddof=1) * (252**0.5)), 10
    )


def test_vehicle_peer_contract_is_strict_by_default() -> None:
    peers = [
        _peer("tracking_difference_abs", 0.01, "peer-a"),
        _peer("tracking_difference_abs", 0.02, "peer-b"),
    ]
    assessment = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        peer_observations=peers,
        minimum_support=3,
        vehicle_metrics={
            "tracking_difference_abs": {
                "value": 0.03,
                "unit": "decimal_fraction",
                "effective_at": EFFECTIVE,
                "known_at": DECISION,
                "source": "#809 synthetic fixture",
            }
        },
    )

    driver = next(
        item
        for item in assessment.drivers
        if item.metric_id == "tracking_difference_abs"
    )
    assert driver.status == "UNAVAILABLE"
    assert driver.raw_value is None
    assert driver.z_score is None


def test_look_through_producer_evidence_reaches_exposure_opportunity() -> None:
    summary = _look_through_summary()
    exposure_peers = [
        *[
            _peer("look_through_pe_ratio", value, f"pe-{index}")
            for index, value in enumerate((20.0, 30.0, 40.0))
        ],
        *[
            _peer("look_through_roic", value, f"roic-{index}")
            for index, value in enumerate((0.1, 0.2, 0.3))
        ],
    ]
    groups = {item.instrument_id: "global_equity" for item in exposure_peers}
    groups["target"] = "global_equity"

    assessment = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        look_through=summary,
        exposure_peer_observations=exposure_peers,
        comparison_groups={"ETF_EXPOSURE_PEERS": groups},
    )

    drivers = {item.metric_id: item for item in assessment.drivers}
    assert summary.exposures.get("factor")
    assert drivers["look_through_pe_ratio"].status.casefold() == "available"
    assert drivers["look_through_pe_ratio"].raw_value == pytest.approx(50.0)
    assert drivers["look_through_roic"].status.casefold() == "available"
    assert drivers["look_through_roic"].raw_value == pytest.approx(0.01)


def test_missing_look_through_evidence_is_unavailable_not_zero() -> None:
    assessment = compose_etf_decision("target", _context("target"), DECISION)

    hhi = next(item for item in assessment.drivers if item.metric_id == "look_through_hhi")
    exposure = next(
        item
        for item in assessment.opportunity_slots
        if item.opportunity == "Exposure Opportunity Rank"
    )
    assert hhi.status == "UNAVAILABLE"
    assert hhi.raw_value is None
    assert exposure.status == "UNAVAILABLE"
    assert exposure.score is None
    assert exposure.reason_code == "LOOK_THROUGH_UNAVAILABLE"
