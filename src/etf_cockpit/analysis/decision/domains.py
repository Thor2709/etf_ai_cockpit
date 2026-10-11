"""Metric registry loading and point-in-time peer-relative domain scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from etf_cockpit.analysis.decision.contracts import (
    DecisionDriver,
    DomainSlot,
    EligibilityResult,
    GateResult,
    InstrumentDecisionAssessment,
    MetricShape,
    OpportunitySlot,
    RequirementClass,
    ScoredMetric,
    SubfamilySlot,
)
from etf_cockpit.analysis.peer_cohorts import (
    CohortMembership,
    PeerCohortError,
    PeerNormalizationResult,
    PeerObservation,
    construct_cohort,
    normalize_peer_metric,
    weighted_empirical_cdf,
)
from etf_cockpit.data.classification import InstrumentContextV2


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    domain: str
    subfamily: str
    weight: float
    comparison_scope: str
    requirement_class: RequirementClass
    metric_shape: MetricShape
    rank_authority: bool = False
    band: float | tuple[float, float] | None = None
    subfamily_weight: float = 1.0
    gate_operator: str | None = None
    gate_threshold: float | None = None

    def __post_init__(self) -> None:
        if not all((self.metric_id, self.domain, self.subfamily)):
            raise ValueError("metric_id, domain and subfamily must be non-empty")
        if (
            isinstance(self.weight, bool)
            or not math.isfinite(self.weight)
            or self.weight <= 0
            or isinstance(self.subfamily_weight, bool)
            or not math.isfinite(self.subfamily_weight)
            or self.subfamily_weight <= 0
        ):
            raise ValueError("metric and subfamily weights must be positive")
        if self.requirement_class not in {"CRITICAL", "CONDITIONAL", "OPTIONAL"}:
            raise ValueError("unsupported requirement class")
        if self.metric_shape not in {
            "higher_is_better",
            "lower_is_better",
            "target_band",
            "threshold_or_plateau",
            "gate",
            "context_only",
        }:
            raise ValueError("unsupported metric shape")
        if self.comparison_scope not in {
            "UNIVERSE",
            "SECTOR",
            "INDUSTRY",
            "BUSINESS_MODEL",
            "ETF_CATEGORY",
            "ETF_EXPOSURE_PEERS",
        }:
            raise ValueError("unsupported comparison scope")
        if self.metric_shape in {"target_band", "threshold_or_plateau"} and self.band is None:
            raise ValueError(f"{self.metric_shape} requires a configured band")
        if self.metric_shape == "gate":
            if (
                self.gate_operator not in {"gt", "gte", "lt", "lte", "eq"}
                or self.gate_threshold is None
                or isinstance(self.gate_threshold, bool)
                or not math.isfinite(self.gate_threshold)
            ):
                raise ValueError("gate metrics require a finite threshold and operator")
        elif self.gate_operator is not None or self.gate_threshold is not None:
            raise ValueError("gate threshold and operator only apply to gate metrics")


@dataclass(frozen=True)
class DomainRegistry:
    version: str
    checksum: str
    metrics: tuple[MetricDefinition, ...]

    def __post_init__(self) -> None:
        if not self.version or len(self.checksum) != 64:
            raise ValueError("registry version and SHA-256 checksum are required")
        identifiers = [item.metric_id for item in self.metrics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("metric identifiers must be unique in the registry")
        family_weights: dict[tuple[str, str], float] = {}
        for item in self.metrics:
            family = (item.domain, item.subfamily)
            if (
                family in family_weights
                and family_weights[family] != item.subfamily_weight
            ):
                raise ValueError("a subfamily must have one configured domain weight")
            family_weights[family] = item.subfamily_weight


@dataclass(frozen=True)
class DomainReference:
    instrument: str
    z_score: float
    effective_at: str
    known_at: str

    def __post_init__(self) -> None:
        if (
            not self.instrument.strip()
            or isinstance(self.z_score, bool)
            or not isinstance(self.z_score, (float, int))
            or not math.isfinite(float(self.z_score))
        ):
            raise ValueError("domain reference requires an identity and finite z score")
        _parse_time(self.effective_at)
        _parse_time(self.known_at)


@dataclass(frozen=True)
class _MetricOutcome:
    definition: MetricDefinition
    evidence: ScoredMetric | None
    normalized: PeerNormalizationResult | None
    status: str
    reason_code: str
    inapplicable: bool = False


def registry_checksum(content: bytes | str) -> str:
    """Return the SHA-256 of the complete LF-normalized registry content."""

    data = content.encode("utf-8") if isinstance(content, str) else content
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def load_domain_registry(
    path: str | Path = "configs/decision_domains_v1.yaml",
) -> DomainRegistry:
    registry_path = Path(path)
    return _domain_registry_for_content(registry_path.read_bytes())


@lru_cache(maxsize=8)
def _domain_registry_for_content(content: bytes) -> DomainRegistry:
    """Parse once per distinct file content (frozen result; exceptions are never cached)."""

    parsed = yaml.safe_load(content.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("decision domain registry must be a mapping")
    checksum = registry_checksum(content)
    raw_metrics = parsed.get("metrics")
    if not isinstance(raw_metrics, list):
        raise ValueError("decision domain registry requires a metrics list")
    metrics = tuple(_metric_definition(item) for item in raw_metrics)
    return DomainRegistry(str(parsed.get("version", "")), checksum, metrics)


def build_instrument_assessment(
    instrument: str,
    asset_type: str,
    business_model: str | None,
    decision_time: str,
    metrics: Sequence[ScoredMetric],
    registry: DomainRegistry,
    *,
    target_context: InstrumentContextV2,
    peer_observations: Sequence[PeerObservation],
    comparison_groups: Mapping[str, Mapping[str, str]] | Mapping[str, str] | None = None,
    domain_reference_z: Mapping[str, Sequence[DomainReference]] | None = None,
    eligibility_results: Sequence[EligibilityResult] = (),
    gate_results: Sequence[GateResult] = (),
    minimum_support: int = 3,
) -> InstrumentDecisionAssessment:
    """Build a read-only assessment using only evidence known at decision time."""

    decision = _parse_time(decision_time)
    evidence_by_id: dict[str, ScoredMetric] = {}
    for metric in metrics:
        if metric.metric_id in evidence_by_id:
            raise ValueError(f"duplicate scored metric: {metric.metric_id}")
        evidence_by_id[metric.metric_id] = metric

    cohorts: dict[str, CohortMembership] = {}
    outcomes: list[_MetricOutcome] = []
    drivers: list[DecisionDriver] = []
    output_gates = list(gate_results)
    warnings: set[str] = set()

    for definition in registry.metrics:
        evidence = evidence_by_id.get(definition.metric_id)
        if definition.metric_shape == "gate":
            gate = _gate_result(definition, evidence, decision)
            output_gates.append(gate)
            outcomes.append(
                _MetricOutcome(
                    definition,
                    evidence,
                    None,
                    gate.status,
                    gate.reason_code,
                    gate.status == "N/A",
                )
            )
            drivers.append(
                DecisionDriver(
                    definition.metric_id,
                    gate.status,
                    gate.raw_value,
                    gate.unit,
                    None,
                    gate.reason_code,
                )
            )
            continue
        if definition.metric_shape == "context_only":
            reason = "CONTEXT_ONLY"
            status = "UNAVAILABLE" if evidence is None else evidence.status
            if evidence is not None and evidence.raw_value is not None:
                reason = evidence.reason_code or reason
            outcomes.append(
                _MetricOutcome(definition, evidence, None, status, reason)
            )
            drivers.append(
                DecisionDriver(
                    definition.metric_id,
                    status,
                    None if evidence is None else evidence.raw_value,
                    "" if evidence is None else evidence.unit,
                    None,
                    reason,
                )
            )
            continue

        outcome, cohort, warning = _score_metric(
            definition,
            evidence,
            decision,
            target_context,
            peer_observations,
            comparison_groups,
            minimum_support,
        )
        outcomes.append(outcome)
        if cohort is not None:
            cohorts[definition.metric_id] = cohort
        if warning:
            warnings.add(warning)
        drivers.append(
            DecisionDriver(
                definition.metric_id,
                outcome.status,
                None if evidence is None else evidence.raw_value,
                "" if evidence is None else evidence.unit,
                None if outcome.normalized is None else outcome.normalized.z_score,
                outcome.reason_code,
            )
        )

    references = domain_reference_z or {}
    domain_slots = _aggregate_domains(outcomes, references, decision)
    if not eligibility_results:
        eligibility_results = (
            EligibilityResult("eligible", "UNAVAILABLE", "NOT_PROVIDED"),
        )
    if not output_gates:
        output_gates.append(
            GateResult("UNAVAILABLE", "UNAVAILABLE", None, "", None, "NO_GATE_EVIDENCE")
        )
    source_vintage_hash = _hash(
        [
            _metric_vintage(metric)
            for metric in sorted(metrics, key=lambda item: item.metric_id)
            if _parse_time(metric.known_at) <= decision
            and _parse_time(metric.effective_at) <= decision
        ]
    )
    comparison_universe_hash = _hash(
        {
            "metric_cohorts": {
                metric_id: cohort.cohort_hash
                for metric_id, cohort in sorted(cohorts.items())
            },
            "domain_references": {
                domain: [
                    {
                        "instrument": item.instrument,
                        "z_score": item.z_score,
                        "effective_at": item.effective_at,
                        "known_at": item.known_at,
                    }
                    for item in sorted(values, key=lambda row: row.instrument)
                    if _parse_time(item.known_at) <= decision
                    and _parse_time(item.effective_at) <= decision
                ]
                for domain, values in sorted(references.items())
            },
        }
    )
    return InstrumentDecisionAssessment(
        instrument,
        asset_type,
        business_model,
        decision_time,
        tuple(eligibility_results),
        tuple(output_gates),
        domain_slots,
        (
            OpportunitySlot(
                "opportunity", "UNAVAILABLE", None, "OUT_OF_SCOPE_DA004"
            ),
        ),
        registry.version,
        registry.checksum,
        source_vintage_hash,
        comparison_universe_hash,
        tuple(drivers),
        tuple(sorted(warnings)),
        False,
    )


def _score_metric(
    definition: MetricDefinition,
    evidence: ScoredMetric | None,
    decision: datetime,
    target_context: InstrumentContextV2,
    peer_observations: Sequence[PeerObservation],
    comparison_groups: Mapping[str, Mapping[str, str]] | Mapping[str, str] | None,
    minimum_support: int,
) -> tuple[_MetricOutcome, CohortMembership | None, str | None]:
    if evidence is None:
        return _MetricOutcome(
            definition, None, None, "UNAVAILABLE", "MISSING_INPUT"
        ), None, None
    if evidence.status.upper() in {"N/A", "NA", "NOT_APPLICABLE"} or (
        evidence.reason_code.upper() in {"NOT_APPLICABLE", "METRIC_INAPPLICABLE"}
    ):
        return _MetricOutcome(
            definition, evidence, None, "N/A", "METRIC_INAPPLICABLE", True
        ), None, None
    if _parse_time(evidence.known_at) > decision:
        return _MetricOutcome(
            definition, evidence, None, "UNAVAILABLE", "KNOWN_AFTER_DECISION_TIME"
        ), None, "FUTURE_KNOWN_METRIC_EXCLUDED"
    if _parse_time(evidence.effective_at) > decision:
        return _MetricOutcome(
            definition,
            evidence,
            None,
            "UNAVAILABLE",
            "EFFECTIVE_AFTER_DECISION_TIME",
        ), None, "FUTURE_EFFECTIVE_METRIC_EXCLUDED"
    if (
        evidence.metric_shape != definition.metric_shape
        or evidence.comparison_scope != definition.comparison_scope
        or evidence.requirement_class != definition.requirement_class
    ):
        return _MetricOutcome(
            definition,
            evidence,
            None,
            "UNAVAILABLE",
            "REGISTRY_CONTRACT_MISMATCH",
        ), None, None
    if evidence.raw_value is None or evidence.status.upper() in {
        "UNAVAILABLE",
        "MISSING",
        "BLOCKED",
        "ERROR",
    }:
        return _MetricOutcome(
            definition,
            evidence,
            None,
            "UNAVAILABLE",
            evidence.reason_code or "MISSING_INPUT",
        ), None, None
    if not definition.rank_authority or not evidence.rank_authority:
        return _MetricOutcome(
            definition, evidence, None, "UNAVAILABLE", "RANK_AUTHORITY_NOT_GRANTED"
        ), None, None
    try:
        # The classification context is resolved once at its own effective
        # cutoff (decision time on the shadow path), so the cohort cutoff is
        # that of the context. The metric's own effective period still bounds
        # the peer evidence: only peer observations effective no later than
        # the metric's effective time are comparable (S4-05).
        metric_effective = _parse_time(evidence.effective_at)
        comparable_peers = [
            item
            for item in peer_observations
            if _effective_not_after(item, metric_effective)
        ]
        cohort = construct_cohort(
            target_context,
            comparable_peers,
            metric=definition.metric_id,
            effective_at=target_context.effective_at,
            decision_time=decision.isoformat().replace("+00:00", "Z"),
            minimum_support=minimum_support,
            comparison_scope=definition.comparison_scope,
            comparison_groups=comparison_groups,
        )
        normalized = normalize_peer_metric(
            definition.metric_id,
            evidence.raw_value,
            cohort,
            applicable=True,
            metric_shape=definition.metric_shape,
            comparison_scope=definition.comparison_scope,
            band=definition.band,
        )
    except PeerCohortError as exc:
        return (
            _MetricOutcome(
                definition, evidence, None, "UNAVAILABLE", "PEER_COHORT_UNAVAILABLE"
            ),
            None,
            str(exc),
        )
    return (
        _MetricOutcome(
            definition,
            evidence,
            normalized,
            normalized.status,
            normalized.reason_code,
        ),
        cohort,
        None,
    )


def _aggregate_domains(
    outcomes: Sequence[_MetricOutcome],
    domain_reference_z: Mapping[str, Sequence[DomainReference]],
    decision_time: datetime,
) -> tuple[DomainSlot, ...]:
    domain_names = sorted({item.definition.domain for item in outcomes})
    slots: list[DomainSlot] = []
    for domain in domain_names:
        domain_items = [
            item
            for item in outcomes
            if item.definition.domain == domain
            and item.definition.metric_shape
            not in {"gate", "context_only"}
        ]
        applicable_items = [item for item in domain_items if not item.inapplicable]
        applicable_weight = sum(item.definition.weight for item in applicable_items)
        available_items = [
            item
            for item in applicable_items
            if item.normalized is not None and item.normalized.z_score is not None
        ]
        available_weight = sum(item.definition.weight for item in available_items)
        coverage = available_weight / applicable_weight if applicable_weight else 0.0
        if not applicable_items:
            slots.append(
                DomainSlot(domain, "N/A", None, None, 0.0, 0.0, "NO_APPLICABLE_INPUTS")
            )
            continue
        grouped: dict[str, list[_MetricOutcome]] = {}
        for item in domain_items:
            grouped.setdefault(item.definition.subfamily, []).append(item)
        family_slots: list[SubfamilySlot] = []
        for family, family_all in sorted(grouped.items()):
            family_applicable = [item for item in family_all if not item.inapplicable]
            family_available = [
                item
                for item in family_applicable
                if item.normalized is not None and item.normalized.z_score is not None
            ]
            family_weight = sum(item.definition.weight for item in family_applicable)
            family_coverage = (
                sum(item.definition.weight for item in family_available) / family_weight
                if family_weight
                else 0.0
            )
            critical_missing = any(
                item.definition.requirement_class == "CRITICAL"
                and item not in family_available
                for item in family_applicable
            )
            if not family_applicable:
                family_slots.append(
                    SubfamilySlot(family, "N/A", None, 0.0, 0.0, "NO_APPLICABLE_INPUTS")
                )
                continue
            if critical_missing:
                family_slots.append(
                    SubfamilySlot(
                        family,
                        "INSUFFICIENT_EVIDENCE",
                        None,
                        family_coverage,
                        _confidence(family_coverage, family_available),
                        "CRITICAL_INPUT_UNAVAILABLE",
                    )
                )
                continue
            family_z = _weighted_mean(
                [
                    (float(item.normalized.z_score), item.definition.weight)
                    for item in family_available
                    if item.normalized is not None
                    and item.normalized.z_score is not None
                ]
            )
            family_slots.append(
                SubfamilySlot(
                    family,
                    "AVAILABLE" if family_z is not None else "UNAVAILABLE",
                    family_z,
                    family_coverage,
                    _confidence(family_coverage, family_available),
                    "AVAILABLE" if family_z is not None else "RANK_EVIDENCE_UNAVAILABLE",
                )
            )
        if any(slot.status == "INSUFFICIENT_EVIDENCE" for slot in family_slots):
            slots.append(
                DomainSlot(
                    domain,
                    "INSUFFICIENT_EVIDENCE",
                    None,
                    None,
                    coverage,
                    _confidence(coverage, available_items),
                    "CRITICAL_INPUT_UNAVAILABLE",
                    tuple(family_slots),
                )
            )
            continue
        subfamily_values: list[tuple[float, float]] = []
        family_weights = {
            item.definition.subfamily: item.definition.subfamily_weight
            for item in domain_items
        }
        for family in family_slots:
            if family.z_score is not None:
                subfamily_values.append(
                    (family.z_score, family_weights[family.subfamily])
                )
        z_score = _weighted_mean(subfamily_values)
        if z_score is None:
            slots.append(
                DomainSlot(
                    domain,
                    "UNAVAILABLE",
                    None,
                    None,
                    coverage,
                    0.0,
                    "RANK_EVIDENCE_UNAVAILABLE",
                    tuple(family_slots),
                )
            )
            continue
        reference = [
            item.z_score
            for item in domain_reference_z.get(domain, ())
            if _parse_time(item.known_at) <= decision_time
            and _parse_time(item.effective_at) <= decision_time
        ]
        if reference:
            displayed = 100.0 * weighted_empirical_cdf(
                reference, [1.0] * len(reference), z_score
            )
            slots.append(
                DomainSlot(
                    domain,
                    "AVAILABLE",
                    z_score,
                    displayed,
                    coverage,
                    _confidence(coverage, available_items),
                    "AVAILABLE",
                    tuple(family_slots),
                )
            )
        else:
            slots.append(
                DomainSlot(
                    domain,
                    "UNAVAILABLE",
                    z_score,
                    None,
                    coverage,
                    _confidence(coverage, available_items),
                    "CROSS_SECTIONAL_REFERENCE_UNAVAILABLE",
                    tuple(family_slots),
                )
            )
    return tuple(slots)


def _confidence(
    coverage: float, outcomes: Sequence[_MetricOutcome]
) -> float:
    factors = [
        item.evidence.authority
        * item.evidence.freshness
        * item.evidence.reliability
        for item in outcomes
        if item.evidence is not None
    ]
    return coverage * (sum(factors) / len(factors) if factors else 0.0)


def _gate_result(
    definition: MetricDefinition, evidence: ScoredMetric | None, decision: datetime
) -> GateResult:
    metric_id = definition.metric_id
    if evidence is None:
        return GateResult(metric_id, "UNAVAILABLE", None, "", None, "MISSING_INPUT")
    if evidence.status.upper() in {"N/A", "NA", "NOT_APPLICABLE"}:
        return GateResult(metric_id, "N/A", evidence.raw_value, evidence.unit, None, "METRIC_INAPPLICABLE")
    if (
        _parse_time(evidence.known_at) > decision
        or _parse_time(evidence.effective_at) > decision
    ):
        return GateResult(metric_id, "UNAVAILABLE", None, evidence.unit, None, "FUTURE_EVIDENCE_EXCLUDED")
    if evidence.raw_value is None or evidence.status.upper() == "UNAVAILABLE":
        return GateResult(metric_id, "UNAVAILABLE", None, evidence.unit, None, evidence.reason_code)
    threshold = definition.gate_threshold
    operator = definition.gate_operator
    if threshold is None or operator is None:
        return GateResult(
            metric_id,
            "UNAVAILABLE",
            evidence.raw_value,
            evidence.unit,
            None,
            "GATE_CONFIGURATION_MISSING",
        )
    comparisons = {
        "gt": evidence.raw_value > threshold,
        "gte": evidence.raw_value >= threshold,
        "lt": evidence.raw_value < threshold,
        "lte": evidence.raw_value <= threshold,
        "eq": evidence.raw_value == threshold,
    }
    passed = comparisons[operator]
    return GateResult(
        metric_id,
        "AVAILABLE",
        evidence.raw_value,
        evidence.unit,
        passed,
        "GATE_PASSED" if passed else "GATE_FAILED",
    )


def _metric_definition(raw: object) -> MetricDefinition:
    if not isinstance(raw, dict):
        raise ValueError("registry metric entries must be mappings")
    band = raw.get("band")
    if isinstance(band, list):
        band = tuple(float(value) for value in band)
    return MetricDefinition(
        metric_id=str(raw["metric_id"]),
        domain=str(raw["domain"]),
        subfamily=str(raw["subfamily"]),
        weight=float(raw.get("weight", 1.0)),
        comparison_scope=str(raw["comparison_scope"]),
        requirement_class=str(raw["requirement_class"]),
        metric_shape=str(raw["metric_shape"]),
        rank_authority=bool(raw.get("rank_authority", False)),
        band=band,
        subfamily_weight=float(raw.get("subfamily_weight", 1.0)),
        gate_operator=(
            str(raw["gate_operator"]) if raw.get("gate_operator") is not None else None
        ),
        gate_threshold=(
            float(raw["gate_threshold"])
            if raw.get("gate_threshold") is not None
            else None
        ),
    )


def _metric_vintage(metric: ScoredMetric) -> dict[str, object]:
    return {
        "metric_id": metric.metric_id,
        "effective_at": metric.effective_at,
        "known_at": metric.known_at,
        "source": metric.source,
        "raw_value": metric.raw_value,
        "unit": metric.unit,
        "authority": metric.authority,
        "freshness": metric.freshness,
        "reliability": metric.reliability,
        "coverage": metric.coverage,
        "uncertainty": metric.uncertainty,
        "status": metric.status,
        "reason_code": metric.reason_code,
    }


def _weighted_mean(values: Sequence[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in values if weight > 0)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in values if weight > 0) / total_weight


def _effective_not_after(item: PeerObservation, limit: datetime) -> bool:
    try:
        return _parse_time(item.effective_at) <= limit
    except ValueError:
        # Malformed peer timestamps stay in so the cohort records the exclusion.
        return True


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("timestamps must be ISO formatted") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamps require an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _hash(value: object) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "DomainReference",
    "DomainRegistry",
    "MetricDefinition",
    "build_instrument_assessment",
    "load_domain_registry",
    "registry_checksum",
]
