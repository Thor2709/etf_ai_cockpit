from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import yaml

from etf_cockpit.analysis.fund_analysis import (
    FUND_ANALYSIS_CONFIG,
    FundAnalysisRecord,
    FundLifecycleRisk,
    FundReturnDecomposition,
    load_fund_analysis_config,
)
from etf_cockpit.analysis.fund_forecasts import (
    FundCalibrationEvidence,
    FundForecastInput,
    forecast_fund_return,
    project_fund_recommendation,
)
from etf_cockpit.analysis.fund_peers import FundPeerCohort
from etf_cockpit.analysis.peer_cohorts import CohortMembership, PeerMetricResult
from etf_cockpit.portfolio import risk_profiles
from etf_cockpit.portfolio.risk_profiles import ProfileEligibilityResult


DECISION = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _decomposition(
    *,
    decision_time: datetime,
    end_nav_date: date | None,
    total_return: str | None,
    share_class_id: str = "class-1",
    horizon: str = "1M",
    currency: str = "EUR",
    status: str = "available",
    evidence_reference: str = "source:return",
) -> FundReturnDecomposition:
    end_date = end_nav_date
    start_date = end_date - timedelta(days=30) if end_date is not None else None
    return FundReturnDecomposition(
        contract_version="fund-return-decomposition.v1",
        fund_id="fund-1",
        share_class_id=share_class_id,
        decision_time=decision_time,
        requested_horizon=horizon,
        status=status,
        nav_currency="EUR",
        selected_currency=currency,
        distribution_policy="accumulating",
        currency_hedge_policy="unhedged",
        hedge_currency=None,
        start_nav_date=start_date,
        end_nav_date=end_date,
        start_nav_per_share=None,
        end_nav_per_share=None,
        nav_change_return=None,
        reinvested_distributions_return=None,
        class_fee_return=None,
        fx_return=None,
        fx_start_rate=None,
        fx_end_rate=None,
        total_return=Decimal(total_return) if total_return is not None else None,
        residual=None,
        reconciliation_tolerance=Decimal("0.000001"),
        reason_codes=(),
        evidence_references=(evidence_reference,),
    )


def _analysis_record(
    *,
    status: str = "available",
    blockers: tuple[str, ...] = (),
    fee_stack_status: str = "complete",
    total_fee_bps: Decimal | None = Decimal("50"),
    benchmark_id: str | None = "benchmark-1",
) -> FundAnalysisRecord:
    current = _decomposition(
        decision_time=DECISION,
        end_nav_date=date(2026, 5, 30),
        total_return="0.1",
    )
    return FundAnalysisRecord(
        contract_version="fund-analysis.v1",
        record_id="analysis-1",
        fund_id="fund-1",
        share_class_id="class-1",
        decision_time=DECISION,
        status=status,
        benchmark_id=benchmark_id,
        total_fee_bps=total_fee_bps,
        fee_stack_status=fee_stack_status,
        return_decomposition=current,
        lifecycle_risk=FundLifecycleRisk(
            contract_version="fund-lifecycle-risk.v1",
            closure_risk=None,
            merger_risk=None,
            manager_change=None,
            benchmark_change=None,
            fee_change=None,
            evidence_references=(),
        ),
        metric_applicability=(),
        blockers=blockers,
        assumptions=(),
        evidence_references=(),
    )


def _history(count: int = 30) -> tuple[FundReturnDecomposition, ...]:
    start = date(2026, 3, 1)
    return tuple(
        _decomposition(
            decision_time=datetime.combine(start + timedelta(days=index + 1), datetime.min.time(), timezone.utc),
            end_nav_date=start + timedelta(days=index),
            total_return=f"{index / 100:.2f}",
            evidence_reference=f"source:return:{index}",
        )
        for index in range(count)
    )


def _cohort() -> FundPeerCohort:
    membership = CohortMembership(
        cohort_key="leaf",
        fallback_path=("leaf", "parent"),
        members=(),
        exclusions={},
        observations=(),
        parent_cohort_key="parent",
        parent_observations=(),
        support=0,
        coverage=0.0,
        cohort_hash="cohort-hash",
    )
    metric = PeerMetricResult(
        metric="total_return",
        applicable=True,
        status="unavailable",
        raw_value=None,
        winsorized_value=None,
        median=None,
        mad=None,
        percentile=None,
        shrunk_percentile=None,
        interval=None,
        effective_sample_size=0.0,
        support=0,
        reason_code="INSUFFICIENT_SUPPORT",
    )
    return FundPeerCohort(
        contract_version="fund-peer-cohort.v1",
        status="unavailable",
        cohort=membership,
        peer_metric=metric,
        collapsed_share_classes=(),
        peer_lifecycle_risks=(),
        abstention_reason="insufficient_peer_support",
    )


def _calibration(
    count: int,
    cohort_key: str = "leaf",
    *,
    matured_at: datetime | None = None,
    start_index: int = 0,
    active_from: datetime | None = None,
    active_to: datetime | None = None,
) -> tuple[FundCalibrationEvidence, ...]:
    maturity = matured_at or (DECISION - timedelta(seconds=1))
    return tuple(
        FundCalibrationEvidence(
            evidence_id=f"cal-{cohort_key}-{start_index + index}",
            evidence_reference=f"source:cal:{cohort_key}:{start_index + index}",
            cohort_key=cohort_key,
            horizon="1M",
            selected_currency="EUR",
            known_at=DECISION - timedelta(days=5),
            matured_at=maturity,
            nonconformity_score=Decimal("0.01"),
            active_from=active_from,
            active_to=active_to,
        )
        for index in range(count)
    )


def _input(
    *,
    analysis_record: FundAnalysisRecord | None = None,
    frequency: str | None = "monthly",
    history: tuple[FundReturnDecomposition, ...] | None = None,
    calibration: tuple[FundCalibrationEvidence, ...] = (),
    cohort: FundPeerCohort | None = None,
    after_trade_analysis: object | None = None,
    after_trade_snapshot: object | None = None,
) -> FundForecastInput:
    return FundForecastInput(
        analysis_record=analysis_record or _analysis_record(),
        economic_strategy_id="strategy-1",
        dealing_frequency=frequency,
        historical_decompositions=history or _history(),
        calibration_evidence=calibration,
        peer_cohort=cohort,
        benchmark_return=Decimal("0.10"),
        after_trade_analysis=after_trade_analysis,
        after_trade_snapshot=after_trade_snapshot,
    )


def test_baseline_quantiles_filter_future_end_dates_and_require_minimum_samples() -> None:
    future = _decomposition(
        decision_time=DECISION - timedelta(days=1),
        end_nav_date=DECISION.date() + timedelta(days=1),
        total_return="0.99",
        evidence_reference="source:return:future",
    )
    mismatched = _decomposition(
        decision_time=DECISION - timedelta(days=10),
        end_nav_date=date(2026, 5, 10),
        total_return="0.88",
        share_class_id="other-class",
    )
    unavailable = _decomposition(
        decision_time=DECISION - timedelta(days=10),
        end_nav_date=date(2026, 5, 11),
        total_return="0.87",
        status="unavailable",
    )
    mismatched_horizon = _decomposition(
        decision_time=DECISION - timedelta(days=10),
        end_nav_date=date(2026, 5, 12),
        total_return="0.86",
        horizon="3M",
    )
    mismatched_currency = _decomposition(
        decision_time=DECISION - timedelta(days=10),
        end_nav_date=date(2026, 5, 13),
        total_return="0.85",
        currency="USD",
    )
    distribution = forecast_fund_return(
        _input(
            history=(
                *_history(),
                future,
                mismatched,
                unavailable,
                mismatched_horizon,
                mismatched_currency,
            )
        )
    )

    assert distribution.status == "research_only"
    assert distribution.sample_count == 30
    assert distribution.q05 == Decimal("0.0145")
    assert distribution.q50 == Decimal("0.145")
    assert distribution.q95 == Decimal("0.2755")
    assert "source:return:future" not in distribution.evidence_references

    insufficient = forecast_fund_return(_input(history=_history(29)))
    assert insufficient.status == "unavailable"
    assert insufficient.reason_codes == ("fund_baseline_insufficient_history",)
    assert insufficient.sample_count == 29


def test_horizon_must_meet_known_dealing_frequency_minimum() -> None:
    weekly_record = _analysis_record()
    weekly_record = replace(
        weekly_record,
        return_decomposition=replace(
            weekly_record.return_decomposition, requested_horizon="1W"
        ),
    )
    weekly = forecast_fund_return(
        _input(analysis_record=weekly_record, frequency="monthly")
    )
    assert weekly.status == "unavailable"
    assert weekly.reason_codes == ("fund_horizon_below_dealing_frequency",)

    daily = forecast_fund_return(_input(frequency="daily"))
    assert daily.status == "research_only"
    assert "fund_horizon_below_dealing_frequency" not in daily.reason_codes

    unknown = forecast_fund_return(_input(frequency="unknown"))
    assert unknown.status == "unavailable"
    assert unknown.reason_codes == ("fund_dealing_frequency_unknown",)

    unsupported_record = _analysis_record()
    unsupported_record = replace(
        unsupported_record,
        return_decomposition=replace(
            unsupported_record.return_decomposition, requested_horizon="10Y"
        ),
    )
    unsupported = forecast_fund_return(
        _input(analysis_record=unsupported_record, frequency="daily")
    )
    assert unsupported.status == "unavailable"
    assert unsupported.reason_codes == ("fund_horizon_unsupported",)


def test_conformal_calibration_is_point_in_time_and_falls_back_to_parent() -> None:
    no_evidence = forecast_fund_return(_input(history=_history()))
    assert no_evidence.status == "research_only"
    assert no_evidence.loss_probability is None
    assert no_evidence.beat_benchmark_probability is None

    calibrated = forecast_fund_return(
        _input(
            cohort=_cohort(),
            calibration=_calibration(20),
        )
    )
    assert calibrated.status == "calibrated"
    assert calibrated.q05 == Decimal("0.0045")
    assert calibrated.q95 == Decimal("0.2855")
    assert calibrated.loss_probability == Decimal("0")
    assert calibrated.beat_benchmark_probability == Decimal("0.6333333333333333333333333333")
    assert calibrated.calibration_fallback_path == ("leaf",)
    assert calibrated.calibration_id

    active_window = forecast_fund_return(
        _input(
            cohort=_cohort(),
            calibration=_calibration(
                20,
                active_from=DECISION - timedelta(days=365),
                active_to=DECISION - timedelta(milliseconds=500),
            ),
        )
    )
    assert active_window.status == "calibrated"
    assert active_window.sample_count == 30
    assert len([ref for ref in active_window.evidence_references if ":cal:" in ref]) == 20

    parent_fallback = forecast_fund_return(
        _input(
            cohort=_cohort(),
            calibration=(*_calibration(3), *_calibration(20, "parent")),
        )
    )
    assert parent_fallback.status == "calibrated"
    assert parent_fallback.calibration_cohort_key == "leaf"
    assert parent_fallback.calibration_fallback_path == ("leaf", "parent")
    assert all("parent" in ref for ref in parent_fallback.evidence_references if ":cal:" in ref)

    matured_at_decision = forecast_fund_return(
        _input(
            cohort=_cohort(),
            calibration=(
                *_calibration(19),
                *_calibration(1, matured_at=DECISION, start_index=19),
            ),
        )
    )
    assert matured_at_decision.status == "research_only"
    assert matured_at_decision.loss_probability is None


def test_missing_fee_benchmark_and_blocked_analysis_block_each_profile() -> None:
    fully_calibrated = _input(
        cohort=_cohort(), calibration=_calibration(20)
    )
    cases = (
        (
            replace(fully_calibrated.analysis_record, total_fee_bps=None, fee_stack_status="fee_stack_incomplete"),
            "fund_fee_stack_missing",
        ),
        (
            replace(fully_calibrated.analysis_record, benchmark_id=None),
            "fund_benchmark_missing",
        ),
        (
            replace(fully_calibrated.analysis_record, status="blocked", blockers=("blocked_analysis_input",)),
            "blocked_analysis_input",
        ),
    )
    for record, reason in cases:
        result = project_fund_recommendation(
            replace(fully_calibrated, analysis_record=record)
        )
        assert len(result.profile_results) == 5
        assert all(profile.status == "blocked" for profile in result.profile_results)
        assert all(reason in profile.binding_reasons for profile in result.profile_results)
        if reason == "fund_benchmark_missing":
            assert result.distribution.loss_probability is not None
            assert result.distribution.beat_benchmark_probability is None

    uncalibrated = project_fund_recommendation(
        replace(fully_calibrated, calibration_evidence=())
    )
    assert all(profile.status == "blocked" for profile in uncalibrated.profile_results)
    assert all(
        "fund_return_calibration_unavailable" in profile.binding_reasons
        for profile in uncalibrated.profile_results
    )


def test_profile_projection_requires_after_trade_context_and_calls_once_per_preset(monkeypatch) -> None:
    calibrated_input = _input(cohort=_cohort(), calibration=_calibration(20))
    no_context = project_fund_recommendation(calibrated_input)
    assert len(no_context.profile_results) == 5
    assert all(
        profile.binding_reasons == ("risk_profile_after_trade_context_unavailable",)
        for profile in no_context.profile_results
    )

    calls: list[str] = []

    def fake_project(profile, analysis, snapshot):
        calls.append(profile.profile_id)
        return SimpleNamespace(
            eligibility=ProfileEligibilityResult(
                profile_id=profile.profile_id,
                status="unavailable",
                eligible=None,
                rank=None,
                recommendation="unavailable",
                binding_reasons=("test_projection_unavailable",),
                constraints=(),
            ),
            projection_id=f"projection-{profile.profile_id}",
        )

    monkeypatch.setattr(risk_profiles, "project_risk_profile", fake_project)
    with_context = project_fund_recommendation(
        replace(
            calibrated_input,
            after_trade_analysis=object(),
            after_trade_snapshot=object(),
        )
    )
    assert len(calls) == 5
    assert tuple(calls) == tuple(profile.profile_id for profile in with_context.profile_results)
    assert all(
        profile.binding_reasons == ("test_projection_unavailable",)
        for profile in with_context.profile_results
    )


def test_projection_hash_config_fail_closed_and_no_etf_only_metrics(tmp_path) -> None:
    item = _input(cohort=_cohort(), calibration=_calibration(20))
    first = project_fund_recommendation(item)
    second = project_fund_recommendation(item)
    assert first.projection_id == second.projection_id
    rendered = repr(asdict(first)).casefold()
    assert "premium_discount" not in rendered
    assert "exchange_spread" not in rendered

    raw = yaml.safe_load(FUND_ANALYSIS_CONFIG.read_text(encoding="utf-8"))
    missing_forecast = dict(raw)
    missing_forecast.pop("forecast")
    missing_path = tmp_path / "missing_forecast.yaml"
    missing_path.write_text(yaml.safe_dump(missing_forecast), encoding="utf-8")
    with pytest.raises(ValueError):
        load_fund_analysis_config(missing_path)

    malformed_forecast = dict(raw)
    malformed_forecast["forecast"] = dict(raw["forecast"])
    malformed_forecast["forecast"]["target_coverage"] = "1.0"
    malformed_path = tmp_path / "malformed_forecast.yaml"
    malformed_path.write_text(yaml.safe_dump(malformed_forecast), encoding="utf-8")
    with pytest.raises(ValueError):
        load_fund_analysis_config(malformed_path)
