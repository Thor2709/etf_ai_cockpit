from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.analysis.decision.contracts import ScoredMetric
from etf_cockpit.analysis.decision.domains import (
    DomainReference,
    DomainRegistry,
    MetricDefinition,
    build_instrument_assessment,
    load_domain_registry,
    registry_checksum,
)
from etf_cockpit.analysis.peer_cohorts import (
    PeerObservation,
    construct_cohort,
    normalize_peer_metric,
)
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.signals.canonical_scoring import (
    CanonicalComponent,
    build_canonical_score,
    load_score_policy,
)


AS_OF = "2024-06-30T00:00:00Z"
DECISION = "2024-07-02T00:00:00Z"


def _context(instrument_id: str, *, industry: str = "software"):
    values = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": "technology",
        "industry": industry,
        "operating_country": "NO",
        "reporting_currency": "NOK",
        "cap_bucket": "large",
        "business_model_tag": "subscription",
        "entity_id": instrument_id,
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument_id}:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            source="synthetic test",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"synthetic:{instrument_id}:{field}",
            confidence=0.95,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(
        evidence,
        instrument_id=instrument_id,
        effective_at=AS_OF,
        decision_time=DECISION,
    )


def _definition(
    metric_id: str,
    *,
    domain: str = "synthetic_domain",
    subfamily: str = "synthetic_family",
    requirement_class: str = "OPTIONAL",
    metric_shape: str = "higher_is_better",
    comparison_scope: str = "INDUSTRY",
    weight: float = 1.0,
    subfamily_weight: float = 1.0,
) -> MetricDefinition:
    return MetricDefinition(
        metric_id=metric_id,
        domain=domain,
        subfamily=subfamily,
        weight=weight,
        subfamily_weight=subfamily_weight,
        comparison_scope=comparison_scope,
        requirement_class=requirement_class,
        metric_shape=metric_shape,
        rank_authority=True,
    )


def _scored_metric(
    definition: MetricDefinition,
    value: float | None,
    *,
    known_at: str = DECISION,
    status: str = "available",
    reason_code: str = "AVAILABLE",
) -> ScoredMetric:
    return ScoredMetric(
        metric_id=definition.metric_id,
        raw_value=value,
        unit="ratio",
        effective_at=AS_OF,
        known_at=known_at,
        source="synthetic test",
        authority=0.9,
        freshness=0.9,
        business_model="subscription",
        comparison_scope=definition.comparison_scope,
        metric_shape=definition.metric_shape,
        requirement_class=definition.requirement_class,
        rank_authority=True,
        coverage=1.0,
        uncertainty=0.1,
        status=status,
        reason_code=reason_code,
    )


def _observations(
    metric_id: str,
    values: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0),
) -> list[PeerObservation]:
    return [
        PeerObservation(
            instrument_id=f"peer-{metric_id}-{index}",
            context=_context(f"peer-{metric_id}-{index}"),
            metric=metric_id,
            value=value,
            weight=1.0,
            effective_at=AS_OF,
            known_at=DECISION,
        )
        for index, value in enumerate(values)
    ]


def _assessment(
    definitions: tuple[MetricDefinition, ...],
    *,
    metrics: tuple[ScoredMetric, ...] | None = None,
    domain_reference_z: dict[str, tuple[DomainReference, ...]] | None = None,
    minimum_support: int = 3,
):
    evidence = (
        tuple(_scored_metric(item, 2.5) for item in definitions)
        if metrics is None
        else metrics
    )
    observations = [
        observation
        for item in definitions
        for observation in _observations(item.metric_id)
    ]
    return build_instrument_assessment(
        "target",
        "stock",
        "subscription",
        DECISION,
        evidence,
        DomainRegistry("synthetic-v1", "a" * 64, definitions),
        target_context=_context("target"),
        peer_observations=observations,
        domain_reference_z=domain_reference_z,
        minimum_support=minimum_support,
    )


def test_orientation_lower_is_better_inverts() -> None:
    target = _context("target")
    observations = _observations("valuation_ratio")
    cohort = construct_cohort(
        target,
        observations,
        metric="valuation_ratio",
        effective_at=AS_OF,
        decision_time=DECISION,
        comparison_scope="INDUSTRY",
    )
    higher = normalize_peer_metric(
        "valuation_ratio",
        2.5,
        cohort,
        applicable=True,
        metric_shape="higher_is_better",
        comparison_scope="INDUSTRY",
    )
    lower = normalize_peer_metric(
        "valuation_ratio",
        2.5,
        cohort,
        applicable=True,
        metric_shape="lower_is_better",
        comparison_scope="INDUSTRY",
    )

    assert lower.percentile == pytest.approx(1.0 - higher.percentile)
    assert lower.shrunk_percentile == pytest.approx(1.0 - higher.shrunk_percentile)
    assert lower.z_score == pytest.approx(-higher.z_score)

    target_band = normalize_peer_metric(
        "valuation_ratio",
        2.0,
        cohort,
        applicable=True,
        metric_shape="target_band",
        comparison_scope="INDUSTRY",
        band=(1.8, 2.2),
    )
    plateau_at_four = normalize_peer_metric(
        "valuation_ratio",
        4.0,
        cohort,
        applicable=True,
        metric_shape="threshold_or_plateau",
        comparison_scope="INDUSTRY",
        band=3.0,
    )
    plateau_above_four = normalize_peer_metric(
        "valuation_ratio",
        8.0,
        cohort,
        applicable=True,
        metric_shape="threshold_or_plateau",
        comparison_scope="INDUSTRY",
        band=3.0,
    )
    category_cohort = construct_cohort(
        target,
        observations,
        metric="valuation_ratio",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=1,
        comparison_scope="ETF_CATEGORY",
        comparison_groups={
            "target": "category-a",
            "peer-valuation_ratio-0": "category-a",
            "peer-valuation_ratio-1": "category-a",
            "peer-valuation_ratio-2": "category-b",
            "peer-valuation_ratio-3": "category-b",
        },
    )

    assert target_band.percentile > 0.5
    assert plateau_at_four.percentile == pytest.approx(plateau_above_four.percentile)
    assert category_cohort.cohort_key == "ETF_CATEGORY"
    assert category_cohort.support == 2


def test_family_dedup_equal_voting() -> None:
    ratios = tuple(
        _definition(f"synthetic_ratio_{index}", domain="value", subfamily="ratios")
        for index in range(6)
    )
    quality = _definition("synthetic_quality", domain="value", subfamily="quality")
    family_set = _assessment(
        (*ratios, quality),
        metrics=tuple(_scored_metric(item, 4.0 if item is quality else 2.5) for item in (*ratios, quality)),
        domain_reference_z={"value": _domain_references("value", (-1.0, 0.0, 1.0))},
    ).domain_slots[0]
    single_family = _assessment(
        (ratios[0], quality),
        metrics=tuple(
            _scored_metric(item, 4.0 if item is quality else 2.5)
            for item in (ratios[0], quality)
        ),
        domain_reference_z={"value": _domain_references("value", (-1.0, 0.0, 1.0))},
    ).domain_slots[0]

    family_z = next(
        item.z_score for item in family_set.subfamilies if item.subfamily == "ratios"
    )
    assert family_z == pytest.approx(
        next(item.z_score for item in single_family.subfamilies if item.subfamily == "ratios")
    )
    assert family_set.z_score == pytest.approx(single_family.z_score)


def test_missing_evidence_gates_critical_lowers_optional_coverage_and_skips_na() -> None:
    definitions = (
        _definition("critical", requirement_class="CRITICAL", subfamily="critical"),
        _definition("optional_missing", subfamily="optional_missing"),
        _definition("optional_available", subfamily="optional_available"),
        _definition(
            "conditional_na",
            requirement_class="CONDITIONAL",
            subfamily="conditional",
            weight=5.0,
        ),
    )
    supplied = (
        _scored_metric(definitions[2], 2.5),
        _scored_metric(
            definitions[3], None, status="N/A", reason_code="METRIC_INAPPLICABLE"
        ),
    )

    domain = _assessment(definitions, metrics=supplied).domain_slots[0]

    assert domain.status == "INSUFFICIENT_EVIDENCE"
    assert domain.coverage == pytest.approx(1.0 / 3.0)
    assert next(
        item for item in domain.subfamilies if item.subfamily == "conditional"
    ).status == "N/A"


def test_missing_slots_are_unavailable_not_zero_or_fifty() -> None:
    definition = _definition("critical", requirement_class="CRITICAL")
    domain = _assessment((definition,), metrics=()).domain_slots[0]
    assessment = _assessment((definition,), metrics=())

    assert domain.status == "INSUFFICIENT_EVIDENCE"
    assert domain.z_score is None
    assert domain.displayed_score is None
    assert domain.displayed_score not in {0.0, 50.0}
    assert assessment.opportunity_slots[0].status == "UNAVAILABLE"
    assert assessment.opportunity_slots[0].score is None


def test_small_cohort_shrinks_toward_its_parent() -> None:
    target = _context("target")
    observations = [
        PeerObservation(
            instrument_id=f"peer-{index}",
            context=_context(
                f"peer-{index}",
                industry="software" if index < 2 else "hardware",
            ),
            metric="profitability",
            value=float(index + 1),
            weight=1.0,
            effective_at=AS_OF,
            known_at=DECISION,
        )
        for index in range(5)
    ]
    cohort = construct_cohort(
        target,
        observations,
        metric="profitability",
        effective_at=AS_OF,
        decision_time=DECISION,
        minimum_support=1,
        comparison_scope="INDUSTRY",
    )
    result = normalize_peer_metric(
        "profitability",
        1.5,
        cohort,
        applicable=True,
        metric_shape="higher_is_better",
        comparison_scope="INDUSTRY",
    )

    assert cohort.support == 2
    assert cohort.parent_observations
    assert abs(result.shrunk_percentile - 0.1) < abs(result.percentile - 0.1)


def test_known_at_after_decision_time_is_invisible() -> None:
    definition = _definition("future_metric")
    future_metric = _scored_metric(
        definition, 2.5, known_at="2024-07-03T00:00:00Z"
    )
    peers = _observations("future_metric")
    peers.append(
        PeerObservation(
            instrument_id="future-peer",
            context=_context("future-peer"),
            metric="future_metric",
            value=99.0,
            weight=1.0,
            effective_at=AS_OF,
            known_at="2024-07-03T00:00:00Z",
        )
    )
    cohort = construct_cohort(
        _context("target"),
        peers,
        metric="future_metric",
        effective_at=AS_OF,
        decision_time=DECISION,
        comparison_scope="INDUSTRY",
    )
    assessment = build_instrument_assessment(
        "target",
        "stock",
        "subscription",
        DECISION,
        (future_metric,),
        DomainRegistry("synthetic-v1", "a" * 64, (definition,)),
        target_context=_context("target"),
        peer_observations=peers,
    )

    assert "future-peer" not in cohort.members
    assert cohort.exclusions["future-peer"] == "future_known"
    assert assessment.drivers[0].status == "UNAVAILABLE"
    assert assessment.drivers[0].reason_code == "KNOWN_AFTER_DECISION_TIME"


def test_legacy_v3_hash_and_reference_score_are_unchanged() -> None:
    policy = load_score_policy("ETF")
    score = build_canonical_score(
        instrument_id="ETF-1",
        asset_type="ETF",
        decision_time="2026-07-10",
        components=[
            _component("momentum", 0.8),
            _component("trend", 0.4),
            _component("relative_strength", 0.2),
            _component("risk", 0.6, "risk_implementation"),
            _component("liquidity_cost", 0.5, "risk_implementation"),
            _component("baseline", 0.3, "expected_return", "model_advisory"),
            _component("timesfm", -0.2, "expected_return", "model_advisory"),
        ],
    )

    assert policy.formula_checksum == "a95569c117e14009c55da187ce67059a6670ff96fe90b97b80017cf53dc80a55"
    assert score.attractiveness_10 == pytest.approx(7.5, abs=1e-12)


def test_registry_hash_is_stable_across_crlf_and_lf() -> None:
    content = Path("configs/decision_domains_v1.yaml").read_bytes()
    crlf_content = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    registry = load_domain_registry()

    assert registry.checksum == registry_checksum(content)
    assert registry_checksum(content) == registry_checksum(crlf_content)


def _component(
    key: str,
    raw: float,
    role: str = "attractiveness",
    authority: str = "vendor_unofficial",
) -> CanonicalComponent:
    return CanonicalComponent(
        key=key,
        raw_metric=raw,
        score_role=role,
        peer_group="synthetic",
        source_id=f"source:{key}",
        source_authority=authority,
        freshness_status="ok",
        uncertainty="low",
        status="ok",
        explanation=f"{key} synthetic reference",
    )


def _domain_references(
    domain: str, values: tuple[float, ...]
) -> tuple[DomainReference, ...]:
    return tuple(
        DomainReference(f"reference-{index}", value, AS_OF, DECISION)
        for index, value in enumerate(values)
    )
