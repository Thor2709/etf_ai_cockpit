"""Transparent exact-horizon return distributions for ordinary funds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from typing import Literal

from etf_cockpit.analysis.fund_analysis import (
    FundAnalysisRecord,
    FundReturnDecomposition,
    load_fund_analysis_config,
)
from etf_cockpit.analysis.fund_peers import FundPeerCohort
from etf_cockpit.models.calibration import conformal_quantile_adjustment
from etf_cockpit.portfolio import risk_profiles
from etf_cockpit.portfolio.risk_profiles import ProfileEligibilityResult


FUND_RETURN_DISTRIBUTION_CONTRACT = "fund-return-distribution.v1"
FUND_RECOMMENDATION_PROJECTION_CONTRACT = "fund-recommendation-projection.v1"


class FundForecastError(ValueError):
    """Raised when fund-forecast inputs violate their evidence contract."""


@dataclass(frozen=True)
class FundCalibrationEvidence:
    """One out-of-sample nonconformity score for a fund cohort and horizon."""

    evidence_id: str
    evidence_reference: str
    cohort_key: str
    horizon: str
    selected_currency: str
    known_at: datetime
    matured_at: datetime
    nonconformity_score: Decimal
    active_from: datetime | None = None
    active_to: datetime | None = None


@dataclass(frozen=True)
class FundForecastInput:
    analysis_record: FundAnalysisRecord
    economic_strategy_id: str
    dealing_frequency: str | None
    historical_decompositions: tuple[FundReturnDecomposition, ...]
    calibration_evidence: tuple[FundCalibrationEvidence, ...] = ()
    peer_cohort: FundPeerCohort | None = None
    benchmark_return: Decimal | None = None
    after_trade_analysis: object | None = None
    after_trade_snapshot: object | None = None


@dataclass(frozen=True)
class FundReturnDistribution:
    fund_id: str
    share_class_id: str
    economic_strategy_id: str
    decision_time: datetime
    horizon: str
    horizon_days: int | None
    selected_currency: str
    status: Literal["unavailable", "research_only", "calibrated"]
    q05: Decimal | None
    q50: Decimal | None
    q95: Decimal | None
    loss_probability: Decimal | None
    beat_benchmark_probability: Decimal | None
    sample_count: int
    calibration_cohort_key: str | None
    calibration_fallback_path: tuple[str, ...]
    calibration_id: str | None
    reason_codes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    contract_version: str = FUND_RETURN_DISTRIBUTION_CONTRACT
    execution_allowed: bool = False


@dataclass(frozen=True)
class FundRecommendationProjection:
    analysis_id: str
    distribution: FundReturnDistribution
    profile_results: tuple[ProfileEligibilityResult, ...]
    blockers: tuple[str, ...]
    projection_id: str
    contract_version: str = FUND_RECOMMENDATION_PROJECTION_CONTRACT
    execution_allowed: bool = False


def forecast_fund_return(item: FundForecastInput) -> FundReturnDistribution:
    """Build empirical return quantiles and apply point-in-time split conformal."""

    _validate_input(item)
    config = load_fund_analysis_config()
    record = item.analysis_record
    decomposition = record.return_decomposition
    decision = record.decision_time.astimezone(timezone.utc)
    horizon = decomposition.requested_horizon
    selected_currency = decomposition.selected_currency
    horizon_days = dict(config.horizon_days).get(horizon)
    cohort_path = _cohort_hierarchy(item.peer_cohort)
    cohort_key = cohort_path[0] if cohort_path else None
    common = {
        "fund_id": record.fund_id,
        "share_class_id": record.share_class_id,
        "economic_strategy_id": item.economic_strategy_id,
        "decision_time": decision,
        "horizon": horizon,
        "horizon_days": horizon_days,
        "selected_currency": selected_currency,
        "sample_count": 0,
        "calibration_cohort_key": cohort_key,
        "calibration_fallback_path": (),
        "calibration_id": None,
        "evidence_references": (),
    }
    if horizon_days is None:
        return _unavailable(common, "fund_horizon_unsupported")
    frequency = item.dealing_frequency.casefold() if item.dealing_frequency else None
    minimum_horizon_days = dict(config.frequency_minimum_horizon_days).get(frequency)
    if minimum_horizon_days is None:
        return _unavailable(common, "fund_dealing_frequency_unknown")
    if horizon_days < minimum_horizon_days:
        return _unavailable(common, "fund_horizon_below_dealing_frequency")

    baseline = _usable_baseline(item.historical_decompositions, item, decision)
    baseline_values = tuple(row.total_return for row in baseline if row.total_return is not None)
    references = tuple(
        sorted({reference for row in baseline for reference in row.evidence_references})
    )
    common["sample_count"] = len(baseline_values)
    common["evidence_references"] = references
    if len(baseline_values) < config.forecast_minimum_baseline_samples:
        return _unavailable(common, "fund_baseline_insufficient_history")

    levels = dict(config.forecast_quantile_levels)
    q05 = _empirical_quantile(baseline_values, levels["q05"])
    q50 = _empirical_quantile(baseline_values, levels["q50"])
    q95 = _empirical_quantile(baseline_values, levels["q95"])
    reason_codes: list[str] = []
    if record.benchmark_id is None or item.benchmark_return is None:
        reason_codes.append(
            "fund_benchmark_missing"
            if record.benchmark_id is None
            else "fund_benchmark_return_unavailable"
        )

    selected_path: tuple[str, ...] = ()
    selected_evidence: tuple[FundCalibrationEvidence, ...] = ()
    adjustment: Decimal | None = None
    if not cohort_path:
        reason_codes.append("fund_calibration_cohort_unavailable")
    else:
        eligible = _eligible_calibration_evidence(
            item.calibration_evidence,
            decision,
            horizon,
            selected_currency,
        )
        for index, key in enumerate(cohort_path):
            cohort_rows = tuple(row for row in eligible if row.cohort_key == key)
            result = conformal_quantile_adjustment(
                (float(row.nonconformity_score) for row in cohort_rows),
                minimum_matured_samples=config.forecast_minimum_matured_calibration_samples,
                target_coverage=float(config.forecast_target_coverage),
            )
            if result.get("status") == "available" and result.get("adjustment") is not None:
                selected_path = cohort_path[: index + 1]
                selected_evidence = cohort_rows
                adjustment = Decimal(str(result["adjustment"]))
                break
        if adjustment is None:
            reason_codes.append("fund_return_calibration_insufficient_matured_evidence")

    if adjustment is None:
        reason_codes.append("fund_return_calibration_unavailable")
        return FundReturnDistribution(
            **{**common, "calibration_fallback_path": selected_path},
            status="research_only",
            q05=q05,
            q50=q50,
            q95=q95,
            loss_probability=None,
            beat_benchmark_probability=None,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
        )

    evidence_refs = tuple(
        sorted(
            set(references)
            | {row.evidence_reference for row in selected_evidence}
        )
    )
    calibration_id = _hash(
        {
            "contract": FUND_RETURN_DISTRIBUTION_CONTRACT,
            "cohort_key": selected_path[-1],
            "evidence": selected_evidence,
            "decision_time": decision,
            "horizon": horizon,
            "selected_currency": selected_currency,
            "minimum_matured_samples": config.forecast_minimum_matured_calibration_samples,
            "target_coverage": config.forecast_target_coverage,
            "adjustment": adjustment,
        }
    )
    benchmark_probability = (
        Decimal(sum(value > item.benchmark_return for value in baseline_values))
        / Decimal(len(baseline_values))
        if item.benchmark_return is not None and record.benchmark_id is not None
        else None
    )
    return FundReturnDistribution(
        **{
            **common,
            "evidence_references": evidence_refs,
            "calibration_fallback_path": selected_path,
            "calibration_id": calibration_id,
        },
        status="calibrated",
        q05=q05 - adjustment,
        q50=q50,
        q95=q95 + adjustment,
        loss_probability=Decimal(sum(value < 0 for value in baseline_values))
        / Decimal(len(baseline_values)),
        beat_benchmark_probability=benchmark_probability,
        reason_codes=tuple(reason_codes),
    )


def project_fund_recommendation(
    item: FundForecastInput,
) -> FundRecommendationProjection:
    """Project one fund analysis through all five guarded risk-profile presets."""

    distribution = forecast_fund_return(item)
    record = item.analysis_record
    blockers: list[str] = list(record.blockers)
    if record.status != "available" and not blockers:
        blockers.append("fund_analysis_unavailable")
    if record.total_fee_bps is None or record.fee_stack_status != "complete":
        blockers.append("fund_fee_stack_missing")
    if record.benchmark_id is None:
        blockers.append("fund_benchmark_missing")
    blockers.extend(
        reason
        for reason in distribution.reason_codes
        if reason.startswith("fund_benchmark_")
    )
    if distribution.status != "calibrated":
        blockers.extend(distribution.reason_codes)
    blockers = list(dict.fromkeys(blockers))

    policies = risk_profiles.load_risk_profile_presets()
    profile_versions = tuple(
        risk_profiles.risk_profile_preset_version(policy) for policy in policies
    )
    results: list[ProfileEligibilityResult] = []
    profile_projection_ids: list[str | None] = []
    if blockers:
        results.extend(
            _profile_result(profile.profile_id, "blocked", False, tuple(blockers))
            for profile in profile_versions
        )
        profile_projection_ids.extend(None for _ in profile_versions)
    elif item.after_trade_analysis is None or item.after_trade_snapshot is None:
        results.extend(
            _profile_result(
                profile.profile_id,
                "unavailable",
                None,
                ("risk_profile_after_trade_context_unavailable",),
            )
            for profile in profile_versions
        )
        profile_projection_ids.extend(None for _ in profile_versions)
    else:
        for profile in profile_versions:
            try:
                projected = risk_profiles.project_risk_profile(
                    profile,
                    item.after_trade_analysis,
                    item.after_trade_snapshot,
                )
            except ValueError:
                # Keep the fund surface advisory when the shared projection
                # contract cannot interpret ordinary-fund after-trade inputs.
                results.append(
                    _profile_result(
                        profile.profile_id,
                        "unavailable",
                        None,
                        ("risk_profile_fund_context_unavailable",),
                    )
                )
                profile_projection_ids.append(None)
                continue
            eligibility = getattr(projected, "eligibility", None)
            if not isinstance(eligibility, ProfileEligibilityResult):
                results.append(
                    _profile_result(
                        profile.profile_id,
                        "unavailable",
                        None,
                        ("risk_profile_projection_unavailable",),
                    )
                )
                profile_projection_ids.append(None)
                continue
            results.append(eligibility)
            profile_projection_ids.append(getattr(projected, "projection_id", None))

    profile_results = tuple(results)
    projection_blockers = tuple(
        dict.fromkeys(
            blockers
            + [
                reason
                for result in profile_results
                for reason in result.binding_reasons
                if result.status != "eligible"
            ]
        )
    )
    projection_id = _hash(
        {
            "contract": FUND_RECOMMENDATION_PROJECTION_CONTRACT,
            "analysis_id": record.record_id,
            "distribution": distribution,
            "profile_results": profile_results,
            "profile_projection_ids": profile_projection_ids,
            "blockers": projection_blockers,
        }
    )
    return FundRecommendationProjection(
        analysis_id=record.record_id,
        distribution=distribution,
        profile_results=profile_results,
        blockers=projection_blockers,
        projection_id=projection_id,
    )


def _validate_input(item: FundForecastInput) -> None:
    if not isinstance(item, FundForecastInput):
        raise FundForecastError("fund forecast input has the wrong contract")
    if not isinstance(item.economic_strategy_id, str) or not item.economic_strategy_id.strip():
        raise FundForecastError("economic_strategy_id must be non-empty")
    record = item.analysis_record
    if not isinstance(record, FundAnalysisRecord):
        raise FundForecastError("fund analysis record has the wrong contract")
    if record.decision_time.tzinfo is None or record.decision_time.utcoffset() is None:
        raise FundForecastError("fund analysis decision_time must be timezone-aware")
    decomposition = record.return_decomposition
    if (
        decomposition.fund_id != record.fund_id
        or decomposition.share_class_id != record.share_class_id
    ):
        raise FundForecastError("fund analysis and return identities must match")
    if decomposition.decision_time != record.decision_time:
        raise FundForecastError("fund analysis and return decision times must match")
    _currency(decomposition.selected_currency)
    if item.dealing_frequency is not None and not isinstance(item.dealing_frequency, str):
        raise FundForecastError("dealing_frequency must be text when supplied")
    if not isinstance(item.historical_decompositions, tuple):
        raise FundForecastError("historical decompositions must be a tuple")
    if not isinstance(item.calibration_evidence, tuple):
        raise FundForecastError("calibration evidence must be a tuple")
    if any(not isinstance(row, FundCalibrationEvidence) for row in item.calibration_evidence):
        raise FundForecastError("calibration entry has the wrong contract")
    evidence_ids = [row.evidence_id for row in item.calibration_evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise FundForecastError("calibration evidence IDs must be unique")
    if item.benchmark_return is not None and (
        not isinstance(item.benchmark_return, Decimal)
        or not item.benchmark_return.is_finite()
    ):
        raise FundForecastError("benchmark return must be finite")


def _usable_baseline(
    rows: tuple[FundReturnDecomposition, ...],
    item: FundForecastInput,
    decision: datetime,
) -> tuple[FundReturnDecomposition, ...]:
    record = item.analysis_record
    current = record.return_decomposition
    usable: list[FundReturnDecomposition] = []
    for row in rows:
        if not isinstance(row, FundReturnDecomposition):
            raise FundForecastError("historical baseline row has the wrong contract")
        if row.decision_time.tzinfo is None or row.decision_time.utcoffset() is None:
            raise FundForecastError("historical decision_time must be timezone-aware")
        if (
            row.share_class_id != record.share_class_id
            or row.requested_horizon != current.requested_horizon
            or row.selected_currency != current.selected_currency
            or row.decision_time.astimezone(timezone.utc) >= decision
            or row.end_nav_date is None
            or row.end_nav_date > decision.date()
            or row.status != "available"
            or row.total_return is None
            or not isinstance(row.total_return, Decimal)
            or not row.total_return.is_finite()
        ):
            continue
        usable.append(row)
    return tuple(sorted(usable, key=lambda row: (row.end_nav_date, row.decision_time)))


def _eligible_calibration_evidence(
    rows: tuple[FundCalibrationEvidence, ...],
    decision: datetime,
    horizon: str,
    selected_currency: str,
) -> tuple[FundCalibrationEvidence, ...]:
    eligible: list[FundCalibrationEvidence] = []
    for row in rows:
        if not isinstance(row, FundCalibrationEvidence):
            raise FundForecastError("calibration entry has the wrong contract")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (row.evidence_id, row.evidence_reference, row.cohort_key)
        ):
            raise FundForecastError("calibration evidence identity is incomplete")
        if row.selected_currency != selected_currency or row.horizon != horizon:
            continue
        for timestamp in (row.known_at, row.matured_at, row.active_from, row.active_to):
            if timestamp is not None and (timestamp.tzinfo is None or timestamp.utcoffset() is None):
                raise FundForecastError("calibration evidence timestamps must be timezone-aware")
        if (
            not isinstance(row.nonconformity_score, Decimal)
            or not row.nonconformity_score.is_finite()
            or row.nonconformity_score < 0
            or row.matured_at.astimezone(timezone.utc) >= decision
            or row.known_at.astimezone(timezone.utc) > decision
            or (
                row.active_from is not None
                and row.known_at.astimezone(timezone.utc)
                < row.active_from.astimezone(timezone.utc)
            )
            or (
                row.active_to is not None
                and row.matured_at.astimezone(timezone.utc)
                > row.active_to.astimezone(timezone.utc)
            )
        ):
            continue
        eligible.append(row)
    return tuple(sorted(eligible, key=lambda row: (row.matured_at, row.evidence_id)))


def _cohort_hierarchy(cohort: FundPeerCohort | None) -> tuple[str, ...]:
    if cohort is None:
        return ()
    membership = cohort.cohort
    candidates = list(membership.fallback_path)
    if membership.cohort_key:
        candidates.append(membership.cohort_key)
    if membership.parent_cohort_key:
        candidates.append(membership.parent_cohort_key)
    return tuple(dict.fromkeys(value for value in candidates if value))


def _empirical_quantile(values: tuple[Decimal, ...], level: Decimal) -> Decimal:
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * level
    lower_index = int(position.to_integral_value(rounding=ROUND_FLOOR))
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    return ordered[lower_index] + fraction * (ordered[upper_index] - ordered[lower_index])


def _unavailable(common: dict[str, object], reason: str) -> FundReturnDistribution:
    return FundReturnDistribution(
        **{**common, "calibration_fallback_path": ()},
        status="unavailable",
        q05=None,
        q50=None,
        q95=None,
        loss_probability=None,
        beat_benchmark_probability=None,
        reason_codes=(reason,),
    )


def _profile_result(
    profile_id: str,
    status: Literal["blocked", "unavailable"],
    eligible: bool | None,
    reasons: tuple[str, ...],
) -> ProfileEligibilityResult:
    return ProfileEligibilityResult(
        profile_id=profile_id,
        status=status,
        eligible=eligible,
        rank=None,
        recommendation="unavailable",
        binding_reasons=reasons,
        constraints=(),
        execution_allowed=False,
    )


def _currency(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value.upper() != value
    ):
        raise FundForecastError("selected_currency must be an uppercase ISO-style code")
    return value


def _hash(value: object) -> str:
    raw = json.dumps(
        asdict(value) if hasattr(value, "__dataclass_fields__") else value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
