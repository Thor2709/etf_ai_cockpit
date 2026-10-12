from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.decision.etf import compose_etf_decision
from etf_cockpit.analysis.decision import shadow_run
from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.analysis.peer_cohorts import (
    PeerCohortError,
    PeerObservation,
    construct_cohort,
)
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
_APPLE_ISIN = "US0378331005"


def _context(
    instrument: str,
    *,
    asset_class: str = "equity",
    instrument_type: str = "ETF",
):
    values = {
        "instrument_type": instrument_type,
        "asset_class": asset_class,
        "trading_currency": "USD",
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument}:{field}",
            instrument_id=instrument,
            field=field,
            value=value,
            source="DA-003 test fixture",
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
    tmp_path: Path,
    values: list[float],
    *,
    instrument_id: str,
) -> TotalReturnEvidence:
    dates = pd.bdate_range("2026-01-01", periods=len(values))
    adjustment = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": dates,
                "close": values,
                "instrument_id": instrument_id,
                "currency": "USD",
                "source_id": f"source:{instrument_id}",
                "provenance": "DA-003 synthetic series",
            }
        )
    )
    coverage = CorporateActionCoverage(
        instrument_id=instrument_id,
        coverage_through=str(dates[-1]),
        published_at=str(dates[-1]),
        retrieved_at=str(dates[-1]),
        known_at=str(dates[-1]),
        revision=1,
        source="DA-003 test fixture",
        source_id=f"coverage:{instrument_id}",
        source_checksum="c" * 64,
        status="active",
    )
    with CorporateActionCoverageStore(
        tmp_path / f"coverage-{instrument_id}"
    ) as store:
        trusted_coverage = store.append(coverage)
    return TotalReturnEvidence.from_adjustment_result(
        adjustment,
        instrument_id=instrument_id,
        currency="USD",
        known_at=str(dates[-1]),
        as_of=str(dates[-1]),
        source_id=f"source:{instrument_id}",
        provenance="DA-003 synthetic series",
        corporate_action_coverage=trusted_coverage,
    )


def _economics_report(tmp_path: Path):
    records = [
        {
            "instrument_id": "target",
            "scope": "fund",
            "as_of": "2026-01-04",
            "known_at": "2026-01-04",
            "currency": "USD",
            "benchmark_id": "benchmark",
            "benchmark_currency": "USD",
            "ter": 0.0022,
            "fee_unit": "decimal_fraction",
            "source_id": "fund-economics:target",
            "source_provenance": "DA-003 test fixture",
            "source_checksum": "b" * 64,
        }
    ]
    return calculate_etf_economics(
        "target",
        records,
        fund_total_return=_total_return_series(
            tmp_path, [100.0, 102.0, 104.0, 106.0], instrument_id="target"
        ),
        benchmark_total_return=_total_return_series(
            tmp_path, [100.0, 101.0, 102.0, 103.0], instrument_id="benchmark"
        ),
        as_of=DECISION,
        horizon_days=3,
    )


def _observations(
    metric: str,
    values: tuple[float, ...],
    *,
    prefix: str = "peer",
) -> list[PeerObservation]:
    return [
        PeerObservation(
            instrument_id=f"{prefix}-{metric}-{index}",
            context=_context(f"{prefix}-{metric}-{index}"),
            metric=metric,
            value=value,
            weight=1.0,
            effective_at=EFFECTIVE,
            known_at=DECISION,
        )
        for index, value in enumerate(values)
    ]


def _comparison_groups(
    observations: list[PeerObservation],
    *,
    target_group: str = "global_equity",
    unrelated: tuple[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    groups = {item.instrument_id: target_group for item in observations}
    groups["target"] = target_group
    if unrelated is not None:
        groups[unrelated[0]] = unrelated[1]
    return {"ETF_EXPOSURE_PEERS": groups}


def _simple_look_through() -> object:
    holdings = pd.DataFrame(
        [
            {
                "security": "Apple",
                "isin": _APPLE_ISIN,
                "weight": 1.0,
                "issuer": "apple",
                "company": "apple",
                "currency": "USD",
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


def _evidence_record(value: float, source: str) -> dict[str, object]:
    return {
        "value": value,
        "unit": "decimal_fraction",
        "effective_at": EFFECTIVE,
        "known_at": DECISION,
        "source": source,
    }


def test_tracking_metrics_use_canonical_economics_values_and_lower_orientation(tmp_path: Path) -> None:
    economics = _economics_report(tmp_path)
    peers = [
        *_observations("tracking_difference_abs", (0.10, 0.20, 0.30, 0.40)),
        *_observations("tracking_error", (0.10, 0.20, 0.30, 0.40)),
    ]
    groups = _comparison_groups(peers)

    assessment = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        etf_economics=economics,
        peer_observations=peers,
        comparison_groups=groups,
    )
    drivers = {item.metric_id: item for item in assessment.drivers}

    assert economics.tracking_status == "available"
    assert drivers["tracking_difference_abs"].raw_value == pytest.approx(
        abs(economics.tracking_difference)
    )
    assert drivers["tracking_error"].raw_value == pytest.approx(
        economics.tracking_error
    )
    assert drivers["tracking_difference_abs"].z_score > 0
    assert drivers["tracking_error"].z_score > 0


def test_tracking_method_uses_td_without_adding_ter_and_records_fallback(tmp_path: Path) -> None:
    economics = _economics_report(tmp_path)
    look_through = {
        "status": "available",
        "freshness": "current",
        "holdings_date": "2026-01-05",
        "decision_time": DECISION,
        "lineage": {"known_at": DECISION},
        "calculated_metrics": {},
        "fundamental_data_coverage": {},
    }
    liquidity = {
        "status": "available",
        "as_of": EFFECTIVE,
        "source_id": "liquidity:target",
        "estimated_cost_bps": 10.0,
    }
    index_return = _evidence_record(0.12, "index-return:target")
    trading_cost = 10.0 / 10_000
    peers = _observations("expected_etf_return", (0.01, 0.02, 0.03, 0.04))
    groups = _comparison_groups(peers)

    tracking = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        etf_economics=economics,
        liquidity_report=liquidity,
        liquidity_known_at=DECISION,
        look_through=look_through,
        expected_index_return=index_return,
        comparison_groups=groups,
        exposure_peer_observations=peers,
    )
    tracking_drivers = {item.metric_id: item for item in tracking.drivers}
    assert "expected_etf_return" in tracking_drivers, (
        tracking_drivers.get("expected_etf_return_method"),
        tracking.opportunity_slots,
    )
    assert tracking_drivers["expected_etf_return"].raw_value == pytest.approx(
        0.12 + economics.tracking_difference - trading_cost
    )
    assert tracking_drivers["expected_etf_return_method"].reason_code == (
        "INDEX_PLUS_TD_MINUS_TRADING_COSTS"
    )

    without_reliable_td = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        etf_economics=replace(
            economics,
            tracking_status="unavailable",
            tracking_difference=None,
        ),
        liquidity_report=liquidity,
        liquidity_known_at=DECISION,
        look_through=look_through,
        expected_index_return=index_return,
        structural_drag=_evidence_record(0.003, "structural-drag:target"),
        comparison_groups=groups,
        exposure_peer_observations=peers,
    )
    fallback_drivers = {item.metric_id: item for item in without_reliable_td.drivers}
    assert fallback_drivers["expected_etf_return"].raw_value == pytest.approx(
        0.12 - economics.fund_metrics["ter"] - 0.003 - trading_cost
    )
    assert fallback_drivers["expected_etf_return_method"].reason_code == (
        "INDEX_MINUS_TER_MINUS_STRUCTURAL_DRAG_MINUS_TRADING_COSTS"
    )


def test_vehicle_cohort_excludes_non_exposure_peers(tmp_path: Path) -> None:
    economics = _economics_report(tmp_path)
    same_group = _observations("tracking_difference_abs", (0.04, 0.05, 0.06, 0.07))
    unrelated = PeerObservation(
        instrument_id="unrelated-etf",
        context=_context("unrelated-etf", asset_class="fixed_income"),
        metric="tracking_difference_abs",
        value=100.0,
        weight=1.0,
        effective_at=EFFECTIVE,
        known_at=DECISION,
    )
    baseline_groups = _comparison_groups(same_group)
    with_unrelated_groups = _comparison_groups(
        [*same_group, unrelated], unrelated=("unrelated-etf", "bond")
    )

    baseline = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        etf_economics=economics,
        peer_observations=same_group,
        comparison_groups=baseline_groups,
    )
    with_unrelated = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        etf_economics=economics,
        peer_observations=[*same_group, unrelated],
        comparison_groups=with_unrelated_groups,
    )
    base_driver = next(
        item for item in baseline.drivers if item.metric_id == "tracking_difference_abs"
    )
    added_driver = next(
        item for item in with_unrelated.drivers if item.metric_id == "tracking_difference_abs"
    )

    assert base_driver.z_score == pytest.approx(added_driver.z_score)

    small_group = same_group[:2]
    outside_group = _observations(
        "tracking_difference_abs", (0.8, 0.9, 1.0, 1.1), prefix="outside"
    )
    insufficient_groups = _comparison_groups(small_group)
    for item in outside_group:
        insufficient_groups["ETF_EXPOSURE_PEERS"][item.instrument_id] = "other"
    insufficient = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        etf_economics=economics,
        peer_observations=[*small_group, *outside_group],
        comparison_groups=insufficient_groups,
        strict_exposure_peers=True,
    )
    insufficient_driver = next(
        item
        for item in insufficient.drivers
        if item.metric_id == "tracking_difference_abs"
    )
    assert insufficient_driver.status == "UNAVAILABLE"
    assert insufficient_driver.z_score is None


def test_vehicle_rank_and_expensive_exposure_rank_are_separate(tmp_path: Path) -> None:
    economics = _economics_report(tmp_path)
    look_through = _simple_look_through()
    assert look_through.status in {"available", "partial"}, look_through.status
    assert look_through.freshness != "stale", look_through.freshness
    assert look_through.holdings_date is not None
    assert look_through.decision_time is not None
    vehicle_peers = [
        *_observations("tracking_difference_abs", (0.10, 0.20, 0.30, 0.40)),
        *_observations("ter", (0.02, 0.03, 0.04, 0.05)),
    ]
    exposure_peers = [
        *_observations("look_through_pe_ratio", (15.0, 20.0, 25.0, 30.0)),
        *_observations("look_through_roic", (0.10, 0.15, 0.20, 0.25)),
    ]
    all_peers = [*vehicle_peers, *exposure_peers]
    assessment = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        etf_economics=economics,
        look_through=look_through,
        peer_observations=vehicle_peers,
        exposure_peer_observations=exposure_peers,
        comparison_groups=_comparison_groups(all_peers),
    )
    ranks = {item.opportunity: item for item in assessment.opportunity_slots}

    assert ranks["Vehicle Rank"].score > 0
    assert ranks["Exposure Opportunity Rank"].status == "AVAILABLE", (
        ranks["Exposure Opportunity Rank"],
        (
            look_through.status,
            look_through.freshness,
            look_through.holdings_date,
            look_through.decision_time,
            look_through.lineage,
        ),
        [
            (item.metric_id, item.status, item.reason_code, item.raw_value)
            for item in assessment.drivers
            if item.metric_id.startswith("look_through_")
        ],
    )
    assert ranks["Exposure Opportunity Rank"].score < 0
    assert {item.domain for item in assessment.domain_slots} == {
        "Tracking",
        "Cost/Implementation",
        "Diversification",
        "Structural risk",
    }


def test_bond_etf_exposure_is_unavailable_without_stock_fallback() -> None:
    assessment = compose_etf_decision(
        "target",
        _context("target", asset_class="fixed_income"),
        DECISION,
    )
    exposure = next(
        item
        for item in assessment.opportunity_slots
        if item.opportunity == "Exposure Opportunity Rank"
    )

    assert exposure.status == "UNAVAILABLE"
    assert exposure.score is None
    assert exposure.reason_code == "EXPOSURE_ADAPTER_NOT_IMPLEMENTED"
    assert assessment.business_model is None
    assert not any(item.metric_id == "roic" for item in assessment.drivers)


def test_missing_look_through_reduces_coverage_without_zero_filling() -> None:
    assessment = compose_etf_decision("target", _context("target"), DECISION)
    diversification = next(
        item for item in assessment.domain_slots if item.domain == "Diversification"
    )
    hhi = next(item for item in assessment.drivers if item.metric_id == "look_through_hhi")
    exposure = next(
        item
        for item in assessment.opportunity_slots
        if item.opportunity == "Exposure Opportunity Rank"
    )

    assert diversification.coverage < 1.0
    assert hhi.status == "UNAVAILABLE"
    assert hhi.raw_value is None
    assert exposure.status == "UNAVAILABLE"
    assert exposure.reason_code == "LOOK_THROUGH_UNAVAILABLE"


def test_etf_composer_exposes_per_domain_exposure_scores() -> None:
    look_through = _simple_look_through()
    exposure_peers = [
        *_observations("look_through_pe_ratio", (15.0, 20.0, 25.0, 30.0)),
        *_observations("look_through_roic", (0.10, 0.15, 0.20, 0.25)),
    ]
    assessment = compose_etf_decision(
        "target",
        _context("target"),
        DECISION,
        look_through=look_through,
        exposure_peer_observations=exposure_peers,
        comparison_groups=_comparison_groups(exposure_peers),
    )

    assert assessment.exposure_domain_slots
    assert all(slot.domain for slot in assessment.exposure_domain_slots)


def test_exposure_cohort_falls_back_by_default_and_can_be_strict() -> None:
    peers = _observations("look_through_roic", (0.1, 0.2))
    groups = _comparison_groups(peers)
    arguments = {
        "metric": "look_through_roic",
        "effective_at": EFFECTIVE,
        "decision_time": DECISION,
        "minimum_support": 3,
        "comparison_scope": "ETF_EXPOSURE_PEERS",
        "comparison_groups": groups,
    }

    fallback = construct_cohort(_context("target"), peers, **arguments)

    assert fallback.cohort_key == "UNIVERSE"
    assert len(fallback.members) == 2
    with pytest.raises(PeerCohortError):
        construct_cohort(
            _context("target"), peers, **arguments, strict_mode=True
        )


def test_shadow_etf_liquidity_reaches_composer_and_missing_value_has_reason(
    monkeypatch,
) -> None:
    liquidity = {
        "as_of": EFFECTIVE,
        "source_id": "liquidity:target",
        "model_id": "local-test",
        "estimated_cost_bps": 10.0,
    }
    prepared_inputs: dict[str, object] = {}
    composed_inputs: dict[str, object] = {}
    monkeypatch.setattr(
        shadow_run, "calculate_etf_economics", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        shadow_run, "_look_through", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        shadow_run, "_load_etf_registries", lambda *args, **kwargs: (object(), object(), "hash")
    )

    def prepare_vehicle(
        registry,
        economics,
        liquidity_report,
        liquidity_known_at,
        look_through,
        structural,
        supplied,
        context,
        decision,
    ):
        prepared_inputs["liquidity_report"] = liquidity_report
        prepared_inputs["liquidity_known_at"] = liquidity_known_at
        return []

    monkeypatch.setattr(shadow_run, "_vehicle_scored_metrics", prepare_vehicle)
    monkeypatch.setattr(shadow_run, "_exposure_scored_metrics", lambda *args: [])
    monkeypatch.setattr(shadow_run, "_exposure_peer_id", lambda *args: "unavailable")
    prepared = shadow_run._prepare_etf_candidate(
        "target",
        _context("target"),
        pd.Timestamp(DECISION),
        (),
        None,
        liquidity_report=liquidity,
        liquidity_known_at=DECISION,
        latest_features={"date": EFFECTIVE},
    )
    assessment = SimpleNamespace(
        domain_slots=(),
        exposure_domain_slots=(),
        opportunity_slots=(),
        critical_domains=(),
        source_vintage_hash="source:test",
    )

    def compose(*args, **kwargs):
        composed_inputs.update(kwargs)
        return assessment

    monkeypatch.setattr(shadow_run, "compose_etf_decision", compose)
    shadow_run._compose_etf_candidate(
        prepared,
        pd.Timestamp(DECISION),
        (),
        (),
        {},
        minimum_support=3,
    )

    assert prepared_inputs["liquidity_report"] == liquidity
    assert prepared_inputs["liquidity_known_at"] == DECISION
    assert composed_inputs["liquidity_report"] == liquidity
    assert composed_inputs["liquidity_known_at"] == DECISION
    assert composed_inputs["strict_exposure_peers"] is True

    missing_assessment = compose_etf_decision("target", _context("target"), DECISION)
    missing_liquidity = next(
        item
        for item in missing_assessment.drivers
        if item.metric_id == "estimated_trading_cost"
    )
    assert missing_liquidity.status == "UNAVAILABLE"
    assert missing_liquidity.reason_code
