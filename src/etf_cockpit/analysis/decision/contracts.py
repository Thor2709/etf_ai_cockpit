"""Immutable value contracts for decision architecture v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Literal


MetricShape = Literal[
    "higher_is_better",
    "lower_is_better",
    "target_band",
    "threshold_or_plateau",
    "gate",
    "context_only",
]
RequirementClass = Literal["CRITICAL", "CONDITIONAL", "OPTIONAL"]
ComparisonScope = Literal[
    "UNIVERSE",
    "SECTOR",
    "INDUSTRY",
    "BUSINESS_MODEL",
    "ETF_CATEGORY",
    "ETF_EXPOSURE_PEERS",
]

_METRIC_SHAPES = {
    "higher_is_better",
    "lower_is_better",
    "target_band",
    "threshold_or_plateau",
    "gate",
    "context_only",
}
_REQUIREMENT_CLASSES = {"CRITICAL", "CONDITIONAL", "OPTIONAL"}
_COMPARISON_SCOPES = {
    "UNIVERSE",
    "SECTOR",
    "INDUSTRY",
    "BUSINESS_MODEL",
    "ETF_CATEGORY",
    "ETF_EXPOSURE_PEERS",
}


@dataclass(frozen=True)
class ScoredMetric:
    """Canonical calculation evidence with explicit timing and quality factors."""

    metric_id: str
    raw_value: float | None
    unit: str
    effective_at: str
    known_at: str
    source: str
    authority: float
    freshness: float
    reliability: float
    business_model: str | None
    comparison_scope: ComparisonScope
    metric_shape: MetricShape
    requirement_class: RequirementClass
    rank_authority: bool = False
    coverage: float = 0.0
    uncertainty: float = 1.0
    status: str = "UNAVAILABLE"
    reason_code: str = "MISSING_INPUT"

    def __post_init__(self) -> None:
        if not self.metric_id.strip():
            raise ValueError("metric_id must be non-empty")
        if self.metric_shape not in _METRIC_SHAPES:
            raise ValueError(f"unsupported metric_shape: {self.metric_shape!r}")
        if self.requirement_class not in _REQUIREMENT_CLASSES:
            raise ValueError(
                f"unsupported requirement_class: {self.requirement_class!r}"
            )
        if self.comparison_scope not in _COMPARISON_SCOPES:
            raise ValueError(
                f"unsupported comparison_scope: {self.comparison_scope!r}"
            )
        if not self.unit.strip() or not self.source.strip():
            raise ValueError("unit and source must be non-empty")
        if not isinstance(self.rank_authority, bool):
            raise ValueError("rank_authority must be boolean")
        for field_name in (
            "authority",
            "freshness",
            "reliability",
            "coverage",
            "uncertainty",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ValueError(f"{field_name} must be a finite value in [0, 1]")
        if self.raw_value is not None and (
            isinstance(self.raw_value, bool)
            or not isinstance(self.raw_value, (float, int))
            or not math.isfinite(float(self.raw_value))
        ):
            raise ValueError("raw_value must be finite or None")
        _aware_datetime(self.effective_at, "effective_at")
        _aware_datetime(self.known_at, "known_at")


@dataclass(frozen=True)
class EligibilityResult:
    name: str
    status: str
    reason_code: str


@dataclass(frozen=True)
class GateResult:
    metric_id: str
    status: str
    raw_value: float | None
    unit: str
    passed: bool | None
    reason_code: str


@dataclass(frozen=True)
class SubfamilySlot:
    subfamily: str
    status: str
    z_score: float | None
    coverage: float
    confidence: float
    reason_code: str


@dataclass(frozen=True)
class DomainSlot:
    domain: str
    status: str
    z_score: float | None
    displayed_score: float | None
    coverage: float
    confidence: float
    reason_code: str
    subfamilies: tuple[SubfamilySlot, ...] = ()


@dataclass(frozen=True)
class OpportunitySlot:
    opportunity: str
    status: str
    score: float | None
    reason_code: str


@dataclass(frozen=True)
class DecisionDriver:
    metric_id: str
    status: str
    raw_value: float | None
    unit: str
    z_score: float | None
    reason_code: str


@dataclass(frozen=True)
class InstrumentDecisionAssessment:
    instrument: str
    asset_type: str
    business_model: str | None
    decision_time: str
    eligibility_results: tuple[EligibilityResult, ...]
    gate_results: tuple[GateResult, ...]
    domain_slots: tuple[DomainSlot, ...]
    opportunity_slots: tuple[OpportunitySlot, ...]
    formula_version: str
    formula_checksum: str
    source_vintage_hash: str
    comparison_universe_hash: str
    drivers: tuple[DecisionDriver, ...]
    warnings: tuple[str, ...]
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if self.execution_allowed:
            raise ValueError("decision assessments never authorize execution")
        if not self.instrument.strip() or not self.asset_type.strip():
            raise ValueError("instrument and asset_type must be non-empty")
        _aware_datetime(self.decision_time, "decision_time")


def _aware_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} requires an explicit timezone")
    return parsed
