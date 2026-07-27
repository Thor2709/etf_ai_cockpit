"""Point-in-time peer cohorts and robust, applicability-aware peer statistics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import random
import statistics
from typing import Mapping, Sequence

from etf_cockpit.data.classification import (
    DEFAULT_LEAF_CONFIDENCE,
    InstrumentContextV2,
    sector_adapter_route,
)


PEER_COHORT_CONTRACT = "peer-cohort.v1"
PEER_COHORT_SCHEMA_VERSION = 1
PEER_RULE_VERSION = "peer-rules.v1"
BROAD_STOCK_ADAPTER = "stock:broad"


class PeerCohortError(ValueError):
    """Raised when peer evidence violates the deterministic contract."""


@dataclass(frozen=True)
class AdapterDefinition:
    adapter_id: str
    version: str
    applicable_metrics: frozenset[str]


@dataclass(frozen=True)
class AdapterSelection:
    adapter_id: str
    adapter_version: str
    reason_code: str
    fallback: bool
    applicable_metrics: tuple[str, ...]
    classification_token: str
    lineage_hash: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class PeerObservation:
    instrument_id: str
    context: InstrumentContextV2
    metric: str
    value: float | None
    weight: float
    effective_at: str
    known_at: str
    applicable: bool = True
    economic_strategy_id: str | None = None
    active_from: str | None = None
    active_to: str | None = None
    revision: int = 1


@dataclass(frozen=True)
class CohortMembership:
    cohort_key: str
    fallback_path: tuple[str, ...]
    members: tuple[str, ...]
    exclusions: Mapping[str, str]
    observations: tuple[PeerObservation, ...]
    parent_cohort_key: str | None
    parent_observations: tuple[PeerObservation, ...]
    support: int
    coverage: float
    cohort_hash: str


@dataclass(frozen=True)
class PeerMetricResult:
    metric: str
    applicable: bool
    status: str
    raw_value: float | None
    winsorized_value: float | None
    median: float | None
    mad: float | None
    percentile: float | None
    shrunk_percentile: float | None
    interval: tuple[float, float] | None
    effective_sample_size: float
    support: int
    reason_code: str


@dataclass(frozen=True)
class PeerProjection:
    contract: str
    schema_version: int
    status: str
    instrument_id: str
    effective_at: str
    decision_time: str
    target_context: InstrumentContextV2
    universe: tuple[PeerObservation, ...]
    universe_version: str
    adapter: AdapterSelection
    cohort: CohortMembership
    metric: PeerMetricResult
    rule_version: str
    formula_parameters: Mapping[str, object]
    warnings: tuple[str, ...]
    result_hash: str
    execution_allowed: bool = False


class AdapterRegistry:
    """Small local registry; sector-family algorithms remain downstream work."""

    def __init__(self, adapters: Sequence[AdapterDefinition] = ()) -> None:
        broad = AdapterDefinition(BROAD_STOCK_ADAPTER, "1", frozenset())
        definitions = (broad, *adapters)
        self._adapters = {item.adapter_id: item for item in definitions}
        if len(self._adapters) != len(definitions):
            raise PeerCohortError("adapter identifiers must be unique")

    def select(self, context: InstrumentContextV2) -> AdapterSelection:
        if context.instrument_type != "stock" or context.asset_class != "equity":
            raise PeerCohortError("peer cohort adapters support classified stocks only")
        route = sector_adapter_route(context)
        requested = route.adapter_id if route.allowed else None
        definition = self._adapters.get(str(requested)) if requested else None
        if definition is None:
            definition = self._adapters[BROAD_STOCK_ADAPTER]
            fallback = True
            reason = (
                "BROAD_STOCK_FALLBACK_UNREGISTERED_ADAPTER"
                if route.allowed
                else f"BROAD_STOCK_FALLBACK_{route.reason_code}"
            )
        else:
            fallback = False
            reason = "PRIMARY_SECTOR_ADAPTER"
        lineage = _hash(
            {
                "adapter_id": definition.adapter_id,
                "adapter_version": definition.version,
                "applicable_metrics": sorted(definition.applicable_metrics),
                "classification_token": context.score_invalidation_token,
                "classification_version": context.version_id,
                "rule_version": PEER_RULE_VERSION,
            }
        )
        return AdapterSelection(
            definition.adapter_id,
            definition.version,
            reason,
            fallback,
            tuple(sorted(definition.applicable_metrics)),
            context.score_invalidation_token,
            lineage,
        )


def construct_cohort(
    target: InstrumentContextV2,
    observations: Sequence[PeerObservation],
    *,
    metric: str,
    effective_at: str,
    decision_time: str,
    minimum_support: int = 3,
) -> CohortMembership:
    """Select the first sufficiently supported leaf-to-parent cohort."""

    if minimum_support < 1:
        raise PeerCohortError("minimum_support must be positive")
    effective = _time(effective_at)
    decision = _time(decision_time)
    _validate_context(target, effective, decision, target=True)
    candidates: list[PeerObservation] = []
    exclusions: dict[str, str] = {}
    relevant = [item for item in observations if item.metric == metric]
    eligible_by_instrument: dict[str, list[PeerObservation]] = {}
    for item in relevant:
        if item.instrument_id != item.context.instrument_id:
            exclusions[item.instrument_id] = "classification_identity_mismatch"
            continue
        reason = _exclusion_reason(item, effective, decision)
        if reason is not None:
            exclusions[item.instrument_id] = reason
            continue
        if item.instrument_id == target.instrument_id:
            exclusions[item.instrument_id] = "target_instrument"
            continue
        eligible_by_instrument.setdefault(item.instrument_id, []).append(item)
    for instrument_id, revisions in sorted(eligible_by_instrument.items()):
        selected_revision = max(
            revisions,
            key=lambda row: (
                _time(row.effective_at),
                _time(row.known_at),
                row.revision,
                _observation_hash(row),
            ),
        )
        candidates.append(selected_revision)
        for stale in revisions:
            if stale is not selected_revision:
                exclusions[f"{instrument_id}@revision:{stale.revision}"] = (
                    "superseded_revision"
                )

    levels = _cohort_levels(target)
    selected: list[PeerObservation] = []
    selected_exclusions: dict[str, str] = {}
    parent: list[PeerObservation] = []
    parent_key: str | None = None
    fallback_path: list[str] = []
    selected_key = "stock:broad"
    selected_index = len(levels) - 1
    for index, (label, fields) in enumerate(levels):
        matching = [
            item for item in candidates if _matches(target, item.context, fields)
        ]
        subset, duplicate_exclusions = _deduplicate(matching)
        fallback_path.append(label)
        selected, selected_key = subset, label
        selected_exclusions = duplicate_exclusions
        selected_index = index
        if len(subset) >= minimum_support:
            break
    if selected_index + 1 < len(levels):
        parent_key, parent_fields = levels[selected_index + 1]
        parent, _ = _deduplicate(
            [
                item
                for item in candidates
                if _matches(target, item.context, parent_fields)
            ]
        )
    exclusions.update(selected_exclusions)
    members = tuple(item.instrument_id for item in selected)
    coverage = len(candidates) / len(relevant) if relevant else 0.0
    payload = {
        "target": target.instrument_id,
        "metric": metric,
        "effective_at": _iso(effective),
        "decision_time": _iso(decision),
        "key": selected_key,
        "path": fallback_path,
        "members": members,
        "parent_key": parent_key,
        "parent_members": [item.instrument_id for item in parent],
        "exclusions": exclusions,
        "classification_tokens": {
            item.instrument_id: item.context.score_invalidation_token
            for item in selected
        },
        "rule_version": PEER_RULE_VERSION,
    }
    return CohortMembership(
        selected_key,
        tuple(fallback_path),
        members,
        dict(sorted(exclusions.items())),
        tuple(selected),
        parent_key,
        tuple(parent),
        len(selected),
        coverage,
        _hash(payload),
    )


def calculate_peer_metric(
    metric: str,
    target_value: float | None,
    cohort: CohortMembership,
    *,
    applicable: bool,
    parent_percentile: float = 0.5,
    shrinkage_strength: float = 5.0,
    bootstrap_seed: int = 0,
    bootstrap_samples: int = 400,
    winsor_mad: float = 3.0,
) -> PeerMetricResult:
    """Calculate robust rank evidence; inapplicable metrics never receive a score."""

    if not applicable:
        return PeerMetricResult(
            metric,
            False,
            "N/A",
            target_value,
            None,
            None,
            None,
            None,
            None,
            None,
            0.0,
            0,
            "METRIC_INAPPLICABLE",
        )
    if target_value is None or not _finite(target_value):
        return PeerMetricResult(
            metric,
            True,
            "unavailable",
            target_value,
            None,
            None,
            None,
            None,
            None,
            None,
            0.0,
            0,
            "TARGET_VALUE_INVALID",
        )
    usable = [
        (float(item.value), float(item.weight))
        for item in cohort.observations
        if item.applicable
        and item.value is not None
        and _finite(item.value)
        and _finite(item.weight)
        and item.weight > 0
    ]
    if not usable:
        return PeerMetricResult(
            metric,
            True,
            "unavailable",
            target_value,
            None,
            None,
            None,
            None,
            None,
            None,
            0.0,
            0,
            "PEER_VALUES_UNAVAILABLE",
        )
    values = [value for value, _ in usable]
    weights = [weight for _, weight in usable]
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    if mad == 0:
        clipped = values[:]
        target_clipped = float(target_value)
    else:
        lower, upper = median - winsor_mad * mad, median + winsor_mad * mad
        clipped = [min(max(value, lower), upper) for value in values]
        target_clipped = min(max(float(target_value), lower), upper)
    percentile = weighted_empirical_cdf(clipped, weights, target_clipped)
    ess = effective_sample_size(weights)
    actual_parent_percentile = _parent_percentile(
        cohort.parent_observations,
        float(target_value),
        default=parent_percentile,
        winsor_mad=winsor_mad,
    )
    shrunk = (ess * percentile + shrinkage_strength * actual_parent_percentile) / (
        ess + shrinkage_strength
    )
    interval = bootstrap_percentile_interval(
        clipped,
        weights,
        target_clipped,
        parent_percentile=actual_parent_percentile,
        shrinkage_strength=shrinkage_strength,
        seed=bootstrap_seed,
        samples=bootstrap_samples,
    )
    return PeerMetricResult(
        metric,
        True,
        "available",
        target_value,
        target_clipped,
        median,
        mad,
        percentile,
        shrunk,
        interval,
        ess,
        len(usable),
        "AVAILABLE",
    )


def weighted_empirical_cdf(
    values: Sequence[float], weights: Sequence[float], target: float
) -> float:
    """Mid-rank weighted CDF, giving deterministic and fair treatment to ties."""

    pairs = _valid_pairs(values, weights)
    total = sum(weight for _, weight in pairs)
    below = sum(weight for value, weight in pairs if value < target)
    tied = sum(weight for value, weight in pairs if value == target)
    return (below + 0.5 * tied) / total


def effective_sample_size(weights: Sequence[float]) -> float:
    valid = [
        float(weight) for weight in weights if _finite(weight) and float(weight) > 0
    ]
    if not valid:
        return 0.0
    return sum(valid) ** 2 / sum(weight * weight for weight in valid)


def bootstrap_percentile_interval(
    values: Sequence[float],
    weights: Sequence[float],
    target: float,
    *,
    parent_percentile: float,
    shrinkage_strength: float,
    seed: int,
    samples: int,
) -> tuple[float, float]:
    pairs = _valid_pairs(values, weights)
    if samples < 1:
        raise PeerCohortError("bootstrap samples must be positive")
    rng = random.Random(seed)
    population = list(range(len(pairs)))
    probabilities = [weight for _, weight in pairs]
    draws: list[float] = []
    for _ in range(samples):
        indices = rng.choices(population, weights=probabilities, k=len(pairs))
        sample_values = [pairs[index][0] for index in indices]
        rank = weighted_empirical_cdf(sample_values, [1.0] * len(indices), target)
        n = float(len(indices))
        draws.append(
            (n * rank + shrinkage_strength * parent_percentile)
            / (n + shrinkage_strength)
        )
    draws.sort()
    return draws[int(0.025 * (samples - 1))], draws[int(0.975 * (samples - 1))]


def build_peer_projection(
    target: InstrumentContextV2,
    observations: Sequence[PeerObservation],
    *,
    metric: str,
    target_value: float | None,
    effective_at: str,
    decision_time: str,
    registry: AdapterRegistry,
    applicable: bool,
    minimum_support: int = 3,
    bootstrap_seed: int = 0,
) -> PeerProjection:
    effective = _time(effective_at)
    decision = _time(decision_time)
    _validate_context(target, effective, decision, target=True)
    adapter = registry.select(target)
    cohort = construct_cohort(
        target,
        observations,
        metric=metric,
        effective_at=effective_at,
        decision_time=decision_time,
        minimum_support=minimum_support,
    )
    result = calculate_peer_metric(
        metric,
        target_value,
        cohort,
        applicable=applicable
        and (not adapter.applicable_metrics or metric in adapter.applicable_metrics),
        bootstrap_seed=bootstrap_seed,
    )
    formula_parameters = {
        "minimum_support": minimum_support,
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_samples": 400,
        "winsor_mad": 3.0,
        "shrinkage_strength": 5.0,
        "target_value": target_value,
        "requested_applicable": applicable,
    }
    frozen_universe = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.instrument_id,
                item.revision,
                _observation_hash(item),
            ),
        )
    )
    universe_version = _hash(
        {
            "effective_at": _iso(effective),
            "decision_time": _iso(decision),
            "observations": [asdict(item) for item in frozen_universe],
        }
    )
    warnings = tuple(
        sorted(
            {
                *target.warnings,
                *(
                    warning
                    for item in frozen_universe
                    for warning in item.context.warnings
                ),
            }
        )
    )
    provisional = PeerProjection(
        PEER_COHORT_CONTRACT,
        PEER_COHORT_SCHEMA_VERSION,
        "available",
        target.instrument_id,
        _iso(effective),
        _iso(decision),
        target,
        frozen_universe,
        universe_version,
        adapter,
        cohort,
        result,
        PEER_RULE_VERSION,
        formula_parameters,
        warnings,
        "",
    )
    return PeerProjection(
        **{
            **asdict(provisional),
            "target_context": target,
            "universe": frozen_universe,
            "adapter": adapter,
            "cohort": cohort,
            "metric": result,
            "result_hash": peer_result_hash(provisional),
        }
    )


def projection_payload(projection: PeerProjection) -> dict[str, object]:
    return asdict(projection)


def canonical_peer_result_payload(
    projection: PeerProjection | Mapping[str, object],
) -> dict[str, object]:
    """Return the sole versioned payload authenticated by ``result_hash``."""

    source = (
        asdict(projection)
        if isinstance(projection, PeerProjection)
        else dict(projection)
    )
    source.pop("result_hash", None)
    return _canonical(source)  # type: ignore[return-value]


def peer_result_hash(projection: PeerProjection | Mapping[str, object]) -> str:
    return _hash(canonical_peer_result_payload(projection))


def _cohort_levels(
    context: InstrumentContextV2,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    dimensions: list[tuple[str, str]] = []
    if context.industry:
        dimensions.append(("industry", "industry"))
    if context.sector:
        dimensions.append(("sector", "sector"))
    if context.operating_country:
        dimensions.append(("country", "operating_country"))
    if context.reporting_currency:
        dimensions.append(("currency", "reporting_currency"))
    if context.cap_bucket:
        dimensions.append(("size", "cap_bucket"))
    if context.business_model_tags:
        dimensions.append(("business_subtype", "business_model_tags"))
    levels = []
    fields = tuple(field for _, field in dimensions)
    labels = tuple(label for label, _ in dimensions)
    for index in range(len(fields)):
        levels.append(
            ("+".join(labels[: len(fields) - index]), fields[: len(fields) - index])
        )
    levels.append(("stock:broad", ()))
    return tuple(levels)


def _matches(
    target: InstrumentContextV2, candidate: InstrumentContextV2, fields: Sequence[str]
) -> bool:
    return all(getattr(target, field) == getattr(candidate, field) for field in fields)


def _deduplicate(
    observations: Sequence[PeerObservation],
) -> tuple[list[PeerObservation], dict[str, str]]:
    retained: list[PeerObservation] = []
    exclusions: dict[str, str] = {}
    claimed: dict[str, str] = {}
    for item in sorted(observations, key=lambda row: row.instrument_id):
        strategy = (
            item.economic_strategy_id or item.context.entity_id or item.instrument_id
        )
        if strategy in claimed:
            exclusions[item.instrument_id] = (
                f"economic_strategy_duplicate_of:{claimed[strategy]}"
            )
            continue
        claimed[strategy] = item.instrument_id
        retained.append(item)
    return retained, exclusions


def _parent_percentile(
    observations: Sequence[PeerObservation],
    target: float,
    *,
    default: float,
    winsor_mad: float,
) -> float:
    pairs = [
        (float(item.value), float(item.weight))
        for item in observations
        if item.applicable
        and item.value is not None
        and _finite(item.value)
        and _finite(item.weight)
        and item.weight > 0
    ]
    if not pairs:
        return default
    values = [value for value, _ in pairs]
    weights = [weight for _, weight in pairs]
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    if mad == 0:
        return weighted_empirical_cdf(values, weights, target)
    lower, upper = median - winsor_mad * mad, median + winsor_mad * mad
    clipped = [min(max(value, lower), upper) for value in values]
    return weighted_empirical_cdf(clipped, weights, min(max(target, lower), upper))


def _observation_hash(item: PeerObservation) -> str:
    return _hash(
        {
            "instrument_id": item.instrument_id,
            "metric": item.metric,
            "value": item.value,
            "weight": item.weight,
            "effective_at": _iso(_time(item.effective_at)),
            "known_at": _iso(_time(item.known_at)),
            "revision": item.revision,
            "context_version": item.context.version_id,
        }
    )


def _exclusion_reason(
    item: PeerObservation, effective: datetime, decision: datetime
) -> str | None:
    if isinstance(item.revision, bool) or item.revision < 1:
        return "invalid_revision"
    try:
        if not _context_is_valid(item.context, effective, decision):
            return "classification_cutoff_mismatch"
        if _time(item.known_at) > decision:
            return "future_known"
        if _time(item.effective_at) > effective:
            return "future_effective"
        if item.active_from and _time(item.active_from) > effective:
            return "not_yet_active"
        if item.active_to and _time(item.active_to) <= effective:
            return "inactive_at_cutoff"
    except PeerCohortError:
        return "invalid_timestamp"
    if not item.applicable:
        return "metric_inapplicable"
    if item.value is None or not _finite(item.value):
        return "invalid_value"
    if not _finite(item.weight) or item.weight <= 0:
        return "non_positive_weight"
    return None


def _context_is_valid(
    context: InstrumentContextV2, effective: datetime, decision: datetime
) -> bool:
    try:
        return (
            context.instrument_type == "stock"
            and context.asset_class == "equity"
            and context.classification_status not in {"unresolved", "manual_review"}
            and context.execution_allowed is False
            and _time(context.effective_at) == effective
            and _time(context.decision_time) == decision
            and _hex_digest(context.version_id)
            and _hex_digest(context.score_invalidation_token)
            and sector_adapter_route(context).context_version == context.version_id
            and context.sector_adapter_allowed
            == (
                context.sector is not None
                and float(context.field_confidence.get("sector", 0.0))
                >= DEFAULT_LEAF_CONFIDENCE
            )
        )
    except (AttributeError, PeerCohortError):
        return False


def _validate_context(
    context: InstrumentContextV2,
    effective: datetime,
    decision: datetime,
    *,
    target: bool,
) -> None:
    if not _context_is_valid(context, effective, decision):
        label = "target" if target else "candidate"
        raise PeerCohortError(
            f"{label} classification is invalid at the requested cutoff"
        )


def _valid_pairs(
    values: Sequence[float], weights: Sequence[float]
) -> list[tuple[float, float]]:
    if len(values) != len(weights):
        raise PeerCohortError("values and weights must have equal length")
    pairs = [
        (float(value), float(weight))
        for value, weight in zip(values, weights, strict=True)
        if _finite(value) and _finite(weight) and float(weight) > 0
    ]
    if not pairs:
        raise PeerCohortError(
            "at least one finite value with a positive weight is required"
        )
    return pairs


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PeerCohortError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise PeerCohortError("timestamps require an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in sorted(value.items()):
            name = str(key)
            if name in {
                "effective_at",
                "decision_time",
                "known_at",
                "active_from",
                "active_to",
            } and isinstance(item, str):
                result[name] = _iso(_time(item))
            else:
                result[name] = _canonical(item)
        return result
    if isinstance(value, (set, frozenset)):
        return [_canonical(item) for item in sorted(value, key=str)]
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _hex_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


__all__ = [
    "AdapterDefinition",
    "AdapterRegistry",
    "AdapterSelection",
    "CohortMembership",
    "PeerCohortError",
    "PeerMetricResult",
    "PeerObservation",
    "PeerProjection",
    "build_peer_projection",
    "canonical_peer_result_payload",
    "calculate_peer_metric",
    "construct_cohort",
    "effective_sample_size",
    "projection_payload",
    "peer_result_hash",
    "weighted_empirical_cdf",
]
