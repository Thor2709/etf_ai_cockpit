"""Point-in-time model drift and net-of-cost performance monitoring.

Drift uses the same chronological half-window standardized mean shift as
Forecast Lab. The 1.0 alert boundary and four-observation minimum match its
existing ``_drift`` rule, so monitoring stays comparable across reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import math
from statistics import fmean, pstdev
from typing import Literal
from uuid import uuid4


@dataclass(frozen=True)
class DatedValue:
    """One dated model expectation used for drift monitoring."""

    observed_at: datetime | date
    value: float | None


@dataclass(frozen=True)
class DatedReturn:
    """One matured realized return and its round-trip cost."""

    observed_at: datetime | date
    realized_return: float | None
    round_trip_cost_bps: float | None


@dataclass(frozen=True)
class DriftAlert:
    """Typed warning emitted when a model's expected-return distribution drifts."""

    alert_id: str
    model_id: str
    score: float
    threshold: float
    earlier_mean: float
    recent_mean: float
    observation_count: int
    first_observation_at: datetime
    last_observation_at: datetime
    as_of: datetime
    reason: str
    review_required: bool = True
    execution_allowed: bool = False


@dataclass(frozen=True)
class DriftAssessment:
    """Drift result; unavailable inputs remain unavailable with a reason."""

    model_id: str
    status: Literal["stable", "warning", "unavailable"]
    score: float | None
    reason: str | None
    alert: DriftAlert | None
    execution_allowed: bool = False


@dataclass(frozen=True)
class PerformanceComparison:
    """Paired realized performance after transaction costs."""

    model_id: str
    baseline_id: str
    status: Literal["available", "unavailable"]
    paired_observations: int
    model_net_mean: float | None
    baseline_net_mean: float | None
    excess_net_mean: float | None
    as_of: datetime
    reason: str | None
    execution_allowed: bool = False


def assess_drift(
    model_id: str,
    observations: tuple[DatedValue, ...] | list[DatedValue],
    *,
    as_of: datetime | date,
) -> DriftAssessment:
    """Assess only observations available at ``as_of`` in chronological order.

    A score at or above the existing Forecast Lab boundary of 1.0 creates a
    warning alert. The caller may create a review request but must never
    promote a challenger from this result.
    """

    cutoff = _utc(as_of)
    dated: list[tuple[datetime, float]] = []
    for item in observations:
        observed_at = _utc(item.observed_at)
        if observed_at > cutoff:
            continue
        if item.value is None or not _finite(item.value):
            return DriftAssessment(model_id, "unavailable", None, "drift observation is missing or non-finite", None)
        dated.append((observed_at, float(item.value)))
    dated.sort(key=lambda item: item[0])
    if len({item[0] for item in dated}) != len(dated):
        return DriftAssessment(model_id, "unavailable", None, "drift observation timestamps are not unique", None)
    if len(dated) < 4:
        return DriftAssessment(model_id, "unavailable", None, "at least four point-in-time observations are required", None)

    values = [item[1] for item in dated]
    scale = pstdev(values)
    if not math.isfinite(scale) or scale == 0.0:
        return DriftAssessment(model_id, "unavailable", None, "drift scale is unavailable", None)
    midpoint = max(1, len(values) // 2)
    earlier_mean = fmean(values[:midpoint])
    recent_mean = fmean(values[midpoint:])
    score = abs(recent_mean - earlier_mean) / scale
    if not math.isfinite(score):
        return DriftAssessment(model_id, "unavailable", None, "drift score is non-finite", None)
    if score < 1.0:
        return DriftAssessment(model_id, "stable", score, None, None)

    alert = DriftAlert(
        alert_id=f"drift_{uuid4().hex}",
        model_id=model_id,
        score=score,
        threshold=1.0,
        earlier_mean=earlier_mean,
        recent_mean=recent_mean,
        observation_count=len(values),
        first_observation_at=dated[0][0],
        last_observation_at=dated[-1][0],
        as_of=cutoff,
        reason="standardized expected-return shift reached the Forecast Lab monitoring boundary",
    )
    return DriftAssessment(model_id, "warning", score, alert.reason, alert)


def compare_net_performance(
    model_id: str,
    model_returns: tuple[DatedReturn, ...] | list[DatedReturn],
    baseline_id: str,
    baseline_returns: tuple[DatedReturn, ...] | list[DatedReturn],
    *,
    baseline_is_deterministic: bool,
    as_of: datetime | date,
) -> PerformanceComparison:
    """Compare paired matured returns after each model's round-trip costs.

    The baseline must be explicitly identified as deterministic. Both samples
    must have the same point-in-time dates and complete return/cost inputs;
    missing costs are never treated as zero.
    """

    cutoff = _utc(as_of)
    if not baseline_is_deterministic:
        return _unavailable_comparison(model_id, baseline_id, cutoff, "comparison baseline is not deterministic")
    if not model_id.strip() or not baseline_id.strip():
        return _unavailable_comparison(model_id, baseline_id, cutoff, "model and baseline identifiers are required")

    candidate = _net_returns(model_returns, cutoff)
    baseline = _net_returns(baseline_returns, cutoff)
    if isinstance(candidate, str):
        return _unavailable_comparison(model_id, baseline_id, cutoff, candidate)
    if isinstance(baseline, str):
        return _unavailable_comparison(model_id, baseline_id, cutoff, baseline)
    if not candidate or not baseline:
        return _unavailable_comparison(model_id, baseline_id, cutoff, "no matured paired returns are available")
    if set(candidate) != set(baseline):
        return _unavailable_comparison(model_id, baseline_id, cutoff, "model and baseline return windows do not match")

    paired_dates = sorted(candidate)
    model_mean = fmean(candidate[item] for item in paired_dates)
    baseline_mean = fmean(baseline[item] for item in paired_dates)
    return PerformanceComparison(
        model_id=model_id,
        baseline_id=baseline_id,
        status="available",
        paired_observations=len(paired_dates),
        model_net_mean=model_mean,
        baseline_net_mean=baseline_mean,
        excess_net_mean=model_mean - baseline_mean,
        as_of=cutoff,
        reason=None,
    )


def _net_returns(observations: tuple[DatedReturn, ...] | list[DatedReturn], cutoff: datetime) -> dict[datetime, float] | str:
    result: dict[datetime, float] = {}
    for item in observations:
        observed_at = _utc(item.observed_at)
        if observed_at > cutoff:
            continue
        if item.realized_return is None or item.round_trip_cost_bps is None:
            return "realized return or round-trip cost is unavailable"
        if not _finite(item.realized_return) or not _finite(item.round_trip_cost_bps):
            return "realized return or round-trip cost is non-finite"
        if float(item.round_trip_cost_bps) < 0.0:
            return "round-trip cost cannot be negative"
        if observed_at in result:
            return "return observation timestamps are not unique"
        result[observed_at] = float(item.realized_return) - float(item.round_trip_cost_bps) / 10_000.0
    return result


def _unavailable_comparison(model_id: str, baseline_id: str, as_of: datetime, reason: str) -> PerformanceComparison:
    return PerformanceComparison(model_id, baseline_id, "unavailable", 0, None, None, None, as_of, reason)


def _utc(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


__all__ = [
    "DatedReturn",
    "DatedValue",
    "DriftAlert",
    "DriftAssessment",
    "PerformanceComparison",
    "assess_drift",
    "compare_net_performance",
]
