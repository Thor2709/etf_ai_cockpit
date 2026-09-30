"""ETF vehicle and equity-exposure decision composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
from pathlib import Path

import yaml

from etf_cockpit.analysis.decision.contracts import (
    DecisionDriver,
    InstrumentDecisionAssessment,
    OpportunitySlot,
    ScoredMetric,
)
from etf_cockpit.analysis.decision.domains import (
    DomainRegistry,
    MetricDefinition,
    build_instrument_assessment,
    registry_checksum,
)
from etf_cockpit.analysis.etf_tax_context import build_currency_context
from etf_cockpit.analysis.look_through import LookThroughSummary
from etf_cockpit.analysis.peer_cohorts import (
    PeerCohortError,
    PeerObservation,
    construct_cohort,
)
from etf_cockpit.data.classification import InstrumentContextV2


_DEFAULT_REGISTRY_PATH = Path("configs/decision_domains_v1.yaml")
_DOMAIN_LABELS = {
    "tracking": "Tracking",
    "cost_implementation": "Cost/Implementation",
    "diversification": "Diversification",
    "structural_risk": "Structural risk",
}
_TD_METHOD = "INDEX_PLUS_TD_MINUS_TRADING_COSTS"
_FALLBACK_METHOD = "INDEX_MINUS_TER_MINUS_STRUCTURAL_DRAG_MINUS_TRADING_COSTS"
_LOW_CONFIDENCE = {"high": 0.85, "medium": 0.65, "low": 0.35}


def compose_etf_decision(
    instrument: str,
    target_context: InstrumentContextV2,
    decision_time: str,
    *,
    etf_economics: object | None = None,
    liquidity_report: object | None = None,
    liquidity_known_at: str | None = None,
    look_through: LookThroughSummary | Mapping[str, object] | None = None,
    expected_index_return: Mapping[str, object] | None = None,
    structural_drag: Mapping[str, object] | None = None,
    structural_metrics: Mapping[str, object] | None = None,
    vehicle_metrics: Mapping[str, object] | None = None,
    peer_observations: Sequence[PeerObservation] = (),
    exposure_peer_observations: Sequence[PeerObservation] = (),
    comparison_groups: Mapping[str, Mapping[str, str]] | Mapping[str, str] | None = None,
    registry_path: str | Path = _DEFAULT_REGISTRY_PATH,
    minimum_support: int = 3,
    strict_exposure_peers: bool = False,
) -> InstrumentDecisionAssessment:
    """Compose an ETF assessment from canonical local evidence.

    Generic metric records in ``vehicle_metrics``, ``expected_index_return`` and
    ``structural_drag`` require ``value``, ``unit``, ``effective_at``,
    ``known_at`` and ``source``. The exposure and vehicle rankings use the
    supplied ``ETF_EXPOSURE_PEERS`` comparison groups independently.
    """

    if target_context.instrument_id != instrument:
        raise ValueError("instrument identity must match the resolved context")
    decision = _timestamp(decision_time)
    if decision is None:
        raise ValueError("decision_time must be an ISO timestamp")

    vehicle_registry, exposure_registry, checksum = _load_etf_registries(registry_path)
    vehicle_metrics = dict(vehicle_metrics or {})
    structural_metrics = dict(structural_metrics or {})
    vehicle_evidence = _vehicle_scored_metrics(
        vehicle_registry,
        etf_economics,
        liquidity_report,
        liquidity_known_at,
        look_through,
        structural_metrics,
        vehicle_metrics,
        target_context,
        decision,
    )
    if strict_exposure_peers and vehicle_evidence:
        definitions = {item.metric_id: item for item in vehicle_registry.metrics}
        unsupported: set[str] = set()
        for item in vehicle_evidence:
            definition = definitions.get(item.metric_id)
            if definition is not None and definition.comparison_scope == "ETF_EXPOSURE_PEERS":
                try:
                    construct_cohort(
                        target_context,
                        peer_observations,
                        metric=item.metric_id,
                        effective_at=decision_time,
                        decision_time=decision_time,
                        minimum_support=minimum_support,
                        comparison_scope="ETF_EXPOSURE_PEERS",
                        comparison_groups=comparison_groups,
                        strict_mode=True,
                    )
                except PeerCohortError:
                    unsupported.add(item.metric_id)
        vehicle_evidence = [
            item for item in vehicle_evidence if item.metric_id not in unsupported
        ]
    expected_record, selected_method = _expected_return_record(
        exposure_registry,
        etf_economics,
        liquidity_report,
        liquidity_known_at,
        expected_index_return,
        structural_drag,
        vehicle_metrics,
        decision,
    )
    exposure_evidence = _exposure_scored_metrics(
        exposure_registry, look_through, decision
    )
    if strict_exposure_peers and exposure_evidence:
        definitions = {item.metric_id: item for item in exposure_registry.metrics}
        unsupported = set()
        for item in exposure_evidence:
            definition = definitions.get(item.metric_id)
            if definition is not None and definition.comparison_scope == "ETF_EXPOSURE_PEERS":
                try:
                    construct_cohort(
                        target_context,
                        exposure_peer_observations,
                        metric=item.metric_id,
                        effective_at=decision_time,
                        decision_time=decision_time,
                        minimum_support=minimum_support,
                        comparison_scope="ETF_EXPOSURE_PEERS",
                        comparison_groups=comparison_groups,
                        strict_mode=True,
                    )
                except PeerCohortError:
                    unsupported.add(item.metric_id)
        exposure_evidence = [
            item for item in exposure_evidence if item.metric_id not in unsupported
        ]
    if expected_record is not None:
        exposure_evidence.append(expected_record)

    asset_type = target_context.instrument_type or "ETF"
    vehicle = build_instrument_assessment(
        instrument,
        asset_type,
        None,
        decision_time,
        vehicle_evidence,
        vehicle_registry,
        target_context=target_context,
        peer_observations=peer_observations,
        comparison_groups=comparison_groups,
        minimum_support=minimum_support,
    )
    vehicle_domains = tuple(
        replace(item, domain=_domain_label(item.domain))
        for item in vehicle.domain_slots
    )
    vehicle_rank = _rank_slot("Vehicle Rank", vehicle.domain_slots)
    vehicle_critical_domains = tuple(
        sorted(
            {
                _domain_label(item.domain)
                for item in vehicle_registry.metrics
                if item.requirement_class == "CRITICAL"
            }
        )
    )

    exposure: InstrumentDecisionAssessment | None = None
    exposure_reason: str | None = None
    exposure_domains = ()
    exposure_critical_domains = tuple(
        sorted(
            {
                _domain_label(item.domain)
                for item in exposure_registry.metrics
                if item.requirement_class == "CRITICAL"
            }
        )
    )
    if not _is_equity_etf(target_context):
        exposure_reason = "EXPOSURE_ADAPTER_NOT_IMPLEMENTED"
    elif look_through is None or not _look_through_usable(look_through, decision):
        exposure_reason = "LOOK_THROUGH_UNAVAILABLE"
    else:
        exposure = build_instrument_assessment(
            instrument,
            asset_type,
            None,
            decision_time,
            exposure_evidence,
            exposure_registry,
            target_context=target_context,
            peer_observations=exposure_peer_observations,
            comparison_groups=comparison_groups,
            minimum_support=minimum_support,
        )
        exposure_domains = exposure.domain_slots

    if exposure is None:
        exposure_rank = OpportunitySlot(
            "Exposure Opportunity Rank", "UNAVAILABLE", None, exposure_reason or "MISSING_INPUT"
        )
    else:
        exposure_rank = _rank_slot(
            "Exposure Opportunity Rank", exposure.domain_slots
        )
        if exposure_rank.status == "UNAVAILABLE":
            exposure_rank = replace(
                exposure_rank, reason_code="EXPOSURE_PEER_COHORT_UNAVAILABLE"
            )

    method_driver = DecisionDriver(
        "expected_etf_return_method",
        "AVAILABLE",
        None,
        "method",
        None,
        selected_method,
    )
    drivers = [*vehicle.drivers, *(() if exposure is None else exposure.drivers)]
    if expected_record is not None and not any(
        item.metric_id == expected_record.metric_id for item in drivers
    ):
        drivers.append(
            DecisionDriver(
                expected_record.metric_id,
                "AVAILABLE",
                expected_record.raw_value,
                expected_record.unit,
                None,
                "EXPECTED_RETURN_METHOD_RECORDED",
            )
        )
    drivers.append(method_driver)
    warnings = set(vehicle.warnings)
    if exposure is not None:
        warnings.update(exposure.warnings)

    combined_vintage = _combined_hash(
        vehicle.source_vintage_hash,
        None if exposure is None else exposure.source_vintage_hash,
    )
    combined_cohort = _combined_hash(
        vehicle.comparison_universe_hash,
        None if exposure is None else exposure.comparison_universe_hash,
    )
    return replace(
        vehicle,
        domain_slots=vehicle_domains,
        opportunity_slots=(vehicle_rank, exposure_rank),
        exposure_domain_slots=tuple(
            replace(item, domain=_domain_label(item.domain))
            for item in exposure_domains
        ),
        critical_domains=tuple(
            sorted(
                {
                    *vehicle_critical_domains,
                    *exposure_critical_domains,
                }
            )
        ),
        formula_checksum=checksum,
        source_vintage_hash=combined_vintage,
        comparison_universe_hash=combined_cohort,
        drivers=tuple(drivers),
        warnings=tuple(sorted(warnings)),
        execution_allowed=False,
    )


def _load_etf_registries(
    path: str | Path,
) -> tuple[DomainRegistry, DomainRegistry, str]:
    content = Path(path).read_bytes()
    parsed = yaml.safe_load(content.decode("utf-8"))
    graph = parsed.get("etf_decision_graph") if isinstance(parsed, Mapping) else None
    if not isinstance(graph, Mapping):
        raise ValueError("decision domain registry requires etf_decision_graph")
    version = str(graph.get("version", ""))
    checksum = registry_checksum(content)
    vehicle = _definitions(graph.get("vehicle_metrics"), "vehicle_metrics")
    exposure = _definitions(graph.get("exposure_metrics"), "exposure_metrics")
    return (
        DomainRegistry(version, checksum, vehicle),
        DomainRegistry(version, checksum, exposure),
        checksum,
    )


def _definitions(value: object, field_name: str) -> tuple[MetricDefinition, ...]:
    if not isinstance(value, list):
        raise ValueError(f"ETF decision registry requires {field_name}")
    result = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError(f"ETF {field_name} rows must be mappings")
        result.append(
            MetricDefinition(
                metric_id=str(raw.get("metric_id", "")),
                domain=str(raw.get("domain", "")),
                subfamily=str(raw.get("subfamily", "")),
                weight=float(raw.get("weight", 1.0)),
                subfamily_weight=float(raw.get("subfamily_weight", 1.0)),
                comparison_scope=str(raw.get("comparison_scope", "")),
                requirement_class=str(raw.get("requirement_class", "OPTIONAL")),  # type: ignore[arg-type]
                metric_shape=str(raw.get("metric_shape", "higher_is_better")),  # type: ignore[arg-type]
                rank_authority=raw.get("rank_authority") is True,
            )
        )
    return tuple(result)


def _vehicle_scored_metrics(
    registry: DomainRegistry,
    economics: object | None,
    liquidity: object | None,
    liquidity_known_at: str | None,
    look_through: LookThroughSummary | Mapping[str, object] | None,
    structural: Mapping[str, object],
    supplied: Mapping[str, object],
    context: InstrumentContextV2,
    decision: datetime,
) -> list[ScoredMetric]:
    definitions = {item.metric_id: item for item in registry.metrics}
    evidence: dict[str, ScoredMetric] = {}
    _add_tracking_metrics(evidence, definitions, economics)
    _add_fee_metric(evidence, definitions, economics)
    _add_liquidity_metrics(evidence, definitions, liquidity, liquidity_known_at)
    _add_closure_metric(evidence, definitions, economics)
    _add_look_through_vehicle_metrics(evidence, definitions, look_through)
    _add_currency_metric(evidence, definitions, look_through, context)
    _add_structural_stress_metrics(evidence, definitions, structural)
    _add_record_metrics(evidence, definitions, supplied)
    return [evidence[key] for key in sorted(evidence)]


def _exposure_scored_metrics(
    registry: DomainRegistry,
    look_through: LookThroughSummary | Mapping[str, object] | None,
    decision: datetime,
) -> list[ScoredMetric]:
    if look_through is None or not _look_through_usable(look_through, decision):
        return []
    definitions = {item.metric_id: item for item in registry.metrics}
    metrics: list[ScoredMetric] = []
    calculated = _mapping(_member(look_through, "calculated_metrics"))
    coverage = _mapping(_member(look_through, "fundamental_data_coverage"))
    lineage = _mapping(_member(look_through, "lineage"))
    holdings_known_at = lineage.get("known_at")
    holdings_date = _member(look_through, "holdings_date")
    lineage_authority = _fraction(lineage.get("authority"))
    lineage_confidence = _fraction(lineage.get("confidence"))
    for output_name, metric_id in (
        ("pe_ratio", "look_through_pe_ratio"),
        ("roic", "look_through_roic"),
    ):
        record = _mapping(calculated.get(output_name))
        contributors = record.get("contributors")
        if str(record.get("status", "")).casefold() != "available" or not isinstance(contributors, (tuple, list)) or not contributors:
            continue
        effective_values = [holdings_date]
        known_values = [holdings_known_at]
        for contributor in contributors:
            if not isinstance(contributor, Mapping):
                continue
            effective_values.append(contributor.get("as_of_date"))
            known_values.append(contributor.get("available_at"))
        effective = _max_timestamp(effective_values)
        known = _max_timestamp(known_values)
        value = _finite(record.get("value"))
        coverage_record = _mapping(coverage.get(output_name))
        metric_coverage = _fraction(coverage_record.get("coverage_fraction"))
        if metric_id in definitions and effective is not None and known is not None and value is not None:
            metrics.append(
                _metric(
                    definitions[metric_id],
                    value,
                    unit="ratio",
                    effective_at=effective,
                    known_at=known,
                    source={
                        "source": "analysis.look_through",
                        "holdings_source_id": _member(look_through, "source_id"),
                        "holdings_date": holdings_date,
                        "contributors": contributors,
                        "calculation": record.get("method"),
                    },
                    coverage=metric_coverage if metric_coverage is not None else 0.0,
                    authority=0.35 if lineage_authority is None else lineage_authority,
                    reliability=0.35 if lineage_confidence is None else lineage_confidence,
                )
            )
    return metrics


def _add_tracking_metrics(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    economics: object | None,
) -> None:
    if economics is None:
        return
    td = _finite(_member(economics, "tracking_difference"))
    te = _finite(_member(economics, "tracking_error"))
    known = _max_timestamp(
        (
            _member(economics, "fund_total_return_selected_known_at"),
            _member(economics, "benchmark_total_return_selected_known_at"),
        )
    )
    effective = _timestamp(_member(economics, "matched_end"))
    if str(_member(economics, "tracking_status", "")).casefold() != "available" or known is None or effective is None:
        return
    provenance = {
        "source": "data.etf_economics.calculate_etf_economics",
        "fund_source_id": _member(economics, "fund_source_id"),
        "benchmark_source_id": _member(economics, "benchmark_source_id"),
        "matched_start": _member(economics, "matched_start"),
        "matched_end": _member(economics, "matched_end"),
        "td_definition": "td_definition: compounded (canonical etf_economics)",
        "te_definition": "sqrt(A) * sigma(a), from canonical etf_economics",
    }
    if td is not None and "tracking_difference_abs" in definitions:
        evidence["tracking_difference_abs"] = _metric(
            definitions["tracking_difference_abs"],
            abs(td),
            unit="decimal_fraction",
            effective_at=effective,
            known_at=known,
            source={**provenance, "canonical_tracking_difference": td},
            coverage=1.0 if _tracking_history_reliable(economics) else 0.0,
            authority=0.85,
            reliability=1.0 if _tracking_history_reliable(economics) else 0.35,
        )
    if te is not None and "tracking_error" in definitions:
        evidence["tracking_error"] = _metric(
            definitions["tracking_error"],
            te,
            unit="decimal_fraction",
            effective_at=effective,
            known_at=known,
            source=provenance,
            coverage=1.0 if _tracking_history_reliable(economics) else 0.0,
            authority=0.85,
            reliability=1.0 if _tracking_history_reliable(economics) else 0.35,
        )


def _tracking_history_reliable(economics: object) -> bool:
    horizon = _finite(_member(economics, "horizon_days"))
    rows = _finite(_member(economics, "matched_rows"))
    coverage = _finite(_member(economics, "coverage_ratio"))
    return (
        str(_member(economics, "tracking_status", "")).casefold() == "available"
        and coverage == 1.0
        and horizon is not None
        and rows == horizon + 1
    )


def _add_fee_metric(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    economics: object | None,
) -> None:
    if economics is None or "ter" not in definitions:
        return
    fund = _mapping(_member(economics, "fund_metrics"))
    fee = _finite(fund.get("ter"))
    effective = _timestamp(fund.get("evidence_as_of"))
    known = _timestamp(fund.get("evidence_known_at"))
    if fee is None or effective is None or known is None:
        return
    if fund.get("fee_unit") != "decimal_fraction":
        return
    evidence["ter"] = _metric(
        definitions["ter"],
        fee,
        unit="decimal_fraction",
        effective_at=effective,
        known_at=known,
        source={
            "source": fund.get("source_id"),
            "provenance": fund.get("source_provenance"),
            "checksum": fund.get("source_checksum"),
        },
    )


def _add_liquidity_metrics(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    liquidity: object | None,
    known_at: str | None,
) -> None:
    if liquidity is None:
        return
    effective = _timestamp(_member(liquidity, "as_of"))
    known = _timestamp(known_at)
    if effective is None or known is None:
        return
    source = {
        "source": _member(liquidity, "source_id"),
        "model_id": _member(liquidity, "model_id"),
        "as_of": _member(liquidity, "as_of"),
        "known_at": known.isoformat().replace("+00:00", "Z"),
    }
    trading_cost = _finite(_member(liquidity, "estimated_cost_bps"))
    if trading_cost is not None and "estimated_trading_cost" in definitions:
        evidence["estimated_trading_cost"] = _metric(
            definitions["estimated_trading_cost"],
            trading_cost / 10_000.0,
            unit="decimal_fraction",
            effective_at=effective,
            known_at=known,
            source={**source, "original_value_bps": trading_cost},
        )
    premium = _finite(_member(liquidity, "premium_discount_bps"))
    if premium is not None and "premium_discount_abs" in definitions:
        evidence["premium_discount_abs"] = _metric(
            definitions["premium_discount_abs"],
            abs(premium),
            unit="basis_points",
            effective_at=effective,
            known_at=known,
            source=source,
        )
    for metric_id, field, unit in (
        ("spread_proxy_bps", "spread_proxy_bps", "basis_points"),
        ("spread_p95_bps", "spread_p95_bps", "basis_points"),
        ("order_to_daily_turnover", "order_to_daily_turnover", "ratio"),
    ):
        value = _finite(_member(liquidity, field))
        if value is not None and metric_id in definitions:
            evidence[metric_id] = _metric(
                definitions[metric_id],
                value,
                unit=unit,
                effective_at=effective,
                known_at=known,
                source=source,
            )


def _add_closure_metric(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    economics: object | None,
) -> None:
    if economics is None or "closure_risk_score" not in definitions:
        return
    closure = _mapping(_member(economics, "closure_risk_proxy"))
    if str(closure.get("status", "")).casefold() != "available":
        return
    value = _finite(closure.get("score"))
    fund = _mapping(_member(economics, "fund_metrics"))
    interval = _mapping(closure.get("policy_interval"))
    effective = _timestamp(_member(economics, "as_of"))
    known = _max_timestamp((fund.get("evidence_known_at"), interval.get("known_at")))
    if value is None or effective is None or known is None:
        return
    evidence["closure_risk_score"] = _metric(
        definitions["closure_risk_score"],
        value,
        unit="risk_proxy",
        effective_at=effective,
        known_at=known,
        source=closure,
        coverage=_fraction(_mapping(closure.get("factor_coverage")).get("ratio")) or 0.0,
        reliability=0.65,
    )


def _add_look_through_vehicle_metrics(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    look_through: LookThroughSummary | Mapping[str, object] | None,
) -> None:
    if look_through is None:
        return
    lineage = _mapping(_member(look_through, "lineage"))
    effective = _timestamp(_member(look_through, "holdings_date"))
    known = _timestamp(lineage.get("known_at"))
    if effective is None or known is None:
        return
    concentration = _mapping(_member(look_through, "concentration"))
    provider_coverage = _fraction(_member(look_through, "provider_coverage"))
    mapped = _finite(_member(look_through, "mapped_weight"))
    total = _finite(_member(look_through, "reported_total_weight"))
    lineage_authority = _fraction(lineage.get("authority"))
    lineage_confidence = _fraction(lineage.get("confidence"))
    mapped_coverage = min(1.0, max(0.0, mapped / total)) if mapped is not None and total is not None and total > 0 else 0.0
    source = {
        "source": "analysis.look_through",
        "source_id": _member(look_through, "source_id"),
        "holdings_date": _member(look_through, "holdings_date"),
    }
    for metric_id, name, coverage in (
        ("look_through_hhi", "hhi", mapped_coverage),
        ("look_through_top_10_share", "top_10_share", mapped_coverage),
        ("unresolved_exposure_weight", "unresolved_weight", provider_coverage or 0.0),
    ):
        value = _finite(concentration.get(name)) if name != "unresolved_weight" else _finite(_member(look_through, name))
        if metric_id in definitions and value is not None and (mapped or 0.0) > 0.0:
            evidence[metric_id] = _metric(
                definitions[metric_id],
                value,
                unit="fraction",
                effective_at=effective,
                known_at=known,
                source=source,
                coverage=coverage,
                authority=0.35 if lineage_authority is None else lineage_authority,
                reliability=0.35 if lineage_confidence is None else lineage_confidence,
            )


def _add_currency_metric(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    look_through: LookThroughSummary | Mapping[str, object] | None,
    context: InstrumentContextV2,
) -> None:
    if look_through is None or "currency_mismatch" not in definitions:
        return
    lineage = _mapping(_member(look_through, "lineage"))
    effective = _timestamp(_member(look_through, "holdings_date"))
    known = _timestamp(lineage.get("known_at"))
    exposures = _mapping(_member(look_through, "exposures"))
    currency_weights = _mapping(exposures.get("currency"))
    if effective is None or known is None or not currency_weights:
        return
    result = build_currency_context(context.trading_currency, currency_weights)
    differs = result.trading_currency_differs_from_economic
    if differs is None:
        return
    evidence["currency_mismatch"] = _metric(
        definitions["currency_mismatch"],
        1.0 if differs else 0.0,
        unit="boolean",
        effective_at=effective,
        known_at=known,
        source={
            "source": "analysis.etf_tax_context.build_currency_context",
            "economic_currency_weights": currency_weights,
            "trading_currency": context.trading_currency,
        },
    )


def _add_structural_stress_metrics(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    structural: Mapping[str, object],
) -> None:
    stress = _mapping(structural.get("stress"))
    if str(stress.get("status", "")).casefold() != "available":
        return
    provenance = _mapping(stress.get("provenance"))
    values = [item for item in provenance.values() if isinstance(item, Mapping)]
    effective = _max_timestamp(
        [item.get("effective_at", item.get("as_of")) for item in values]
    )
    known = _max_timestamp([item.get("known_at") for item in values])
    if effective is None or known is None:
        return
    source = {
        "source": structural.get("contract"),
        "structure_provenance_hash": _mapping(structural.get("structure_identity")).get("structure_provenance_hash"),
        "stress": stress,
    }
    for metric_id, field in (
        ("unsecured_counterparty_exposure", "unsecured_pct_nav"),
        ("collateral_concentration_stress", "concentration_pct_nav"),
    ):
        value = _finite(stress.get(field))
        if metric_id in definitions and value is not None:
            evidence[metric_id] = _metric(
                definitions[metric_id],
                value,
                unit="fraction_of_nav",
                effective_at=effective,
                known_at=known,
                source=source,
            )


def _add_record_metrics(
    evidence: dict[str, ScoredMetric],
    definitions: Mapping[str, MetricDefinition],
    supplied: Mapping[str, object],
) -> None:
    for metric_id, record in supplied.items():
        definition = definitions.get(metric_id)
        if definition is None or metric_id in evidence or not isinstance(record, Mapping):
            continue
        metric = _metric_from_record(definition, record)
        if metric is not None:
            evidence[metric_id] = metric


def _expected_return_record(
    registry: DomainRegistry,
    economics: object | None,
    liquidity: object | None,
    liquidity_known_at: str | None,
    expected_index_return: Mapping[str, object] | None,
    structural_drag: Mapping[str, object] | None,
    vehicle_metrics: Mapping[str, object],
    decision: datetime,
) -> tuple[ScoredMetric | None, str]:
    definitions = {item.metric_id: item for item in registry.metrics}
    definition = definitions.get("expected_etf_return")
    use_tracking = (
        economics is not None
        and _tracking_history_reliable(economics)
        and _tracking_record(economics, decision) is not None
    )
    method = _TD_METHOD if use_tracking else _FALLBACK_METHOD
    if definition is None:
        return None, method
    index = _validated_record(expected_index_return, decision)
    trading = _validated_record(_record_metric(vehicle_metrics.get("estimated_trading_cost")), decision)
    if trading is None:
        trading = _trading_cost_record(liquidity, liquidity_known_at, decision)
    components: list[tuple[str, dict[str, object]]] = []
    if index is None or trading is None:
        return None, method
    if index.get("unit") != "decimal_fraction" or trading.get("unit") != "decimal_fraction":
        return None, method
    components.extend((("expected_index_return", index), ("trading_cost", trading)))

    if use_tracking:
        td = _tracking_record(economics, decision)
        if td is None:
            return None, method
        if td.get("unit") != "decimal_fraction":
            return None, method
        components.append(("canonical_tracking_difference", td))
        value = float(index["value"]) + float(td["value"]) - float(trading["value"])
    else:
        ter = _ter_record(economics, decision)
        drag = _validated_record(structural_drag, decision)
        if ter is None or drag is None:
            return None, method
        if ter.get("unit") != "decimal_fraction" or drag.get("unit") != "decimal_fraction":
            return None, method
        components.extend((("ter", ter), ("structural_drag", drag)))
        value = float(index["value"]) - float(ter["value"]) - float(drag["value"]) - float(trading["value"])

    effective = _max_timestamp([item.get("effective_at") for _, item in components])
    known = _max_timestamp([item.get("known_at") for _, item in components])
    if effective is None or known is None:
        return None, method
    metric = _metric(
        definition,
        value,
        unit="decimal_fraction",
        effective_at=effective,
        known_at=known,
        source={
            "expected_return_method": method,
            "calculation": method,
            "components": {name: item.get("provenance") for name, item in components},
            "td_definition": "td_definition: compounded (canonical etf_economics)" if use_tracking else None,
        },
        authority=min(float(item.get("authority", 0.35)) for _, item in components),
        reliability=min(float(item.get("reliability", 0.35)) for _, item in components),
        coverage=min(float(item.get("coverage", 1.0)) for _, item in components),
    )
    return metric, method


def _tracking_record(economics: object, decision: datetime) -> dict[str, object] | None:
    value = _finite(_member(economics, "tracking_difference"))
    effective = _timestamp(_member(economics, "matched_end"))
    known = _max_timestamp((
        _member(economics, "fund_total_return_selected_known_at"),
        _member(economics, "benchmark_total_return_selected_known_at"),
    ))
    if value is None or effective is None or known is None or effective > decision or known > decision:
        return None
    return {
        "value": value,
        "unit": "decimal_fraction",
        "effective_at": effective,
        "known_at": known,
        "authority": 0.85,
        "reliability": 1.0,
        "coverage": 1.0,
        "provenance": {
            "source": "data.etf_economics.calculate_etf_economics",
            "td_definition": "td_definition: compounded (canonical etf_economics)",
        },
    }


def _ter_record(economics: object | None, decision: datetime) -> dict[str, object] | None:
    if economics is None:
        return None
    fund = _mapping(_member(economics, "fund_metrics"))
    record = {
        "value": fund.get("ter"),
        "effective_at": fund.get("evidence_as_of"),
        "known_at": fund.get("evidence_known_at"),
        "unit": fund.get("fee_unit"),
        "source": fund.get("source_id"),
        "authority": 0.35,
        "reliability": 0.35,
        "provenance": {
            "source_id": fund.get("source_id"),
            "source_provenance": fund.get("source_provenance"),
            "source_checksum": fund.get("source_checksum"),
        },
    }
    return _validated_record(record, decision)


def _trading_cost_record(
    liquidity: object | None,
    known_at: str | None,
    decision: datetime,
) -> dict[str, object] | None:
    if liquidity is None:
        return None
    value = _finite(_member(liquidity, "estimated_cost_bps"))
    effective = _timestamp(_member(liquidity, "as_of"))
    known = _timestamp(known_at)
    if value is None or effective is None or known is None:
        return None
    return _validated_record(
        {
            "value": value / 10_000.0,
            "unit": "decimal_fraction",
            "effective_at": effective,
            "known_at": known,
            "source": _member(liquidity, "source_id"),
            "authority": 0.35,
            "reliability": 0.35,
            "coverage": 1.0,
            "provenance": {
                "source_id": _member(liquidity, "source_id"),
                "source_model": _member(liquidity, "model_id"),
                "original_value_bps": value,
            },
        },
        decision,
    )


def _record_metric(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _validated_record(
    value: Mapping[str, object] | None,
    decision: datetime,
) -> dict[str, object] | None:
    if value is None:
        return None
    raw = _finite(value.get("value"))
    effective = _timestamp(value.get("effective_at"))
    known = _timestamp(value.get("known_at"))
    source = value.get("source")
    unit = value.get("unit")
    if (
        raw is None
        or effective is None
        or known is None
        or not isinstance(source, str)
        or not source.strip()
        or not isinstance(unit, str)
        or not unit.strip()
    ):
        return None
    if effective > decision or known > decision:
        return None
    return {
        "value": raw,
        "unit": unit,
        "effective_at": effective,
        "known_at": known,
        "authority": _quality(value.get("authority", value.get("confidence")), 0.35),
        "reliability": _quality(value.get("reliability", value.get("confidence")), 0.35),
        "coverage": _fraction(value.get("coverage")) if value.get("coverage") is not None else 1.0,
        "provenance": value.get("provenance", {"source": source}),
    }


def _metric_from_record(
    definition: MetricDefinition,
    record: Mapping[str, object],
) -> ScoredMetric | None:
    validated = _validated_record(record, datetime.max.replace(tzinfo=timezone.utc))
    if validated is None:
        return None
    return _metric(
        definition,
        float(validated["value"]),
        unit=str(validated["unit"]),
        effective_at=validated["effective_at"],
        known_at=validated["known_at"],
        source=validated["provenance"],
        authority=float(validated["authority"]),
        reliability=float(validated["reliability"]),
        coverage=float(validated["coverage"]),
    )


def _metric(
    definition: MetricDefinition,
    value: float,
    *,
    unit: str,
    effective_at: datetime,
    known_at: datetime,
    source: object,
    authority: float = 0.35,
    reliability: float = 0.35,
    coverage: float = 1.0,
) -> ScoredMetric:
    authority = _quality(authority, 0.35)
    reliability = _quality(reliability, 0.35)
    coverage = _fraction(coverage) or 0.0
    return ScoredMetric(
        metric_id=definition.metric_id,
        raw_value=value,
        unit=unit,
        effective_at=_iso(effective_at),
        known_at=_iso(known_at),
        source=json.dumps(source, sort_keys=True, separators=(",", ":"), default=str),
        authority=authority,
        freshness=1.0,
        reliability=reliability,
        business_model=None,
        comparison_scope=definition.comparison_scope,  # type: ignore[arg-type]
        metric_shape=definition.metric_shape,  # type: ignore[arg-type]
        requirement_class=definition.requirement_class,  # type: ignore[arg-type]
        rank_authority=definition.rank_authority,
        coverage=coverage,
        uncertainty=1.0 - authority,
        status="AVAILABLE",
        reason_code="AVAILABLE",
    )


def _rank_slot(name: str, domains: Sequence[object]) -> OpportunitySlot:
    scores = [
        score
        for domain in domains
        if (score := _finite(_member(domain, "z_score"))) is not None
    ]
    if not scores:
        return OpportunitySlot(name, "UNAVAILABLE", None, "NO_RANKABLE_DOMAIN_EVIDENCE")
    return OpportunitySlot(
        name,
        "AVAILABLE",
        math.fsum(scores) / len(scores),
        "MEAN_DOMAIN_Z_SCORE",
    )


def _domain_label(domain: str) -> str:
    """Keep established vehicle labels and render configured exposure ids plainly."""

    return _DOMAIN_LABELS.get(domain, domain.replace("_", " ").title())


def _is_equity_etf(context: InstrumentContextV2) -> bool:
    instrument_type = (context.instrument_type or "").casefold()
    asset_class = (context.asset_class or "").casefold()
    return "etf" in instrument_type and asset_class in {"equity", "equities"}


def _look_through_usable(
    summary: LookThroughSummary | Mapping[str, object],
    decision: datetime,
) -> bool:
    status = str(_member(summary, "status", "")).casefold()
    effective = _timestamp(_member(summary, "holdings_date"))
    decision_time = _timestamp(_member(summary, "decision_time"))
    return (
        status in {"available", "partial"}
        and effective is not None
        and effective <= decision
        and decision_time is not None
        and decision_time <= decision
        and str(_member(summary, "freshness", "current")).casefold() != "stale"
    )


def _combined_hash(first: str, second: str | None) -> str:
    return hashlib.sha256(json.dumps((first, second), separators=(",", ":")).encode()).hexdigest()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _member(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _fraction(value: object) -> float | None:
    result = _finite(value)
    return result if result is not None and 0.0 <= result <= 1.0 else None


def _quality(value: object, default: float) -> float:
    if isinstance(value, str):
        value = _LOW_CONFIDENCE.get(value.casefold())
    parsed = _fraction(value)
    return default if parsed is None else parsed


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) == 10:
        try:
            return datetime.combine(date.fromisoformat(text), time.min, tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _max_timestamp(values: Sequence[object] | object) -> datetime | None:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        values = (values,)
    parsed = [_timestamp(item) for item in values]
    if not parsed or any(item is None for item in parsed):
        return None
    return max(item for item in parsed if item is not None)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["compose_etf_decision"]
