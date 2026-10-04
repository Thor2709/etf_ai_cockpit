"""Stock underwriting composition over canonical producer evidence.

This module performs no valuation or accounting calculations. It binds
producer-owned metrics to the versioned stock decision map and delegates
peer-relative underwriting scoring to the shared decision-domain engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import yaml

from etf_cockpit.analysis.decision.contracts import (
    DomainSlot,
    ScoredMetric,
)
from etf_cockpit.analysis.decision.domains import (
    DomainReference,
    DomainRegistry,
    MetricDefinition,
    build_instrument_assessment,
    load_domain_registry,
    registry_checksum,
)
from etf_cockpit.analysis.financial_sector_adapters import (
    FINANCIAL_ADAPTER_CONTRACT,
    FINANCIAL_ADAPTER_ID,
    financial_adapter_definition,
)
from etf_cockpit.analysis.peer_cohorts import (
    AdapterRegistry,
    PeerObservation,
    PeerCohortError,
)
from etf_cockpit.analysis.sparebank.claim import routing as route_sparebank_ec
from etf_cockpit.analysis.sparebank.models import CONTRACT_ID as SPAREBANK_ANALYSIS_CONTRACT
from etf_cockpit.core.values import mapping_or_attribute as _projection_member
from etf_cockpit.data.classification import InstrumentContextV2


_DEFAULT_REGISTRY_PATH = Path("configs/decision_domains_v1.yaml")
_FINANCIAL_CONTEXT_LABELS = frozenset(
    {
        "bank",
        "banks",
        "banking",
        "financial",
        "financials",
        "financial_institution",
        "financial institution",
        "insurance",
        "insurer",
    }
)
_EC_TOKENS = frozenset({"ec", "equity_certificate", "certificate", "egenkapitalbevis"})


@dataclass(frozen=True)
class StockDecisionMap:
    registry: DomainRegistry
    domains: tuple[Mapping[str, object], ...]
    stock_sources: Mapping[str, str]
    financial_sources: Mapping[str, str]
    financial_shapes: Mapping[str, str]
    financial_unscored_reasons: Mapping[str, str]
    rank_authority: bool


def load_stock_decision_map(
    path: str | Path = _DEFAULT_REGISTRY_PATH,
) -> StockDecisionMap:
    """Load the stock-specific mapping from the canonical decision registry."""

    registry_path = Path(path)
    content = registry_path.read_bytes()
    parsed = yaml.safe_load(content.decode("utf-8"))
    if not isinstance(parsed, Mapping):
        raise ValueError("decision registry must be a mapping")
    stock = parsed.get("stock_decision")
    if not isinstance(stock, Mapping) or stock.get("schema_version") != 1:
        raise ValueError("decision registry requires stock_decision schema_version 1")
    raw_domains = stock.get("subdomains")
    if not isinstance(raw_domains, list) or len(raw_domains) != 6:
        raise ValueError("stock decision mapping requires exactly six underwriting domains")

    definitions: list[MetricDefinition] = []
    stock_sources: dict[str, str] = {}
    financial_sources: dict[str, str] = {}
    financial_shapes: dict[str, str] = {}
    financial_unscored_reasons: dict[str, str] = {}
    seen_domains: set[str] = set()
    domain_rows: list[Mapping[str, object]] = []
    for raw_domain in raw_domains:
        if not isinstance(raw_domain, Mapping):
            raise ValueError("stock decision domains must be mappings")
        domain_id = str(raw_domain.get("domain", ""))
        if not domain_id or domain_id in seen_domains:
            raise ValueError("stock decision domain identifiers must be unique")
        seen_domains.add(domain_id)
        weight = _finite(raw_domain.get("weight"))
        if weight is None or weight <= 0:
            raise ValueError("stock decision domain weights must be positive")
        raw_metrics = raw_domain.get("metrics")
        if not isinstance(raw_metrics, list) or not raw_metrics:
            raise ValueError(f"stock decision domain {domain_id!r} requires metrics")
        domain_rows.append(raw_domain)
        for raw_metric in raw_metrics:
            if not isinstance(raw_metric, Mapping):
                raise ValueError("stock decision metrics must be mappings")
            definition = _definition_from_map(
                {
                    **raw_metric,
                    "rank_authority": raw_metric.get(
                        "rank_authority", stock.get("rank_authority", False)
                    ),
                },
                domain_id,
            )
            if definition.metric_id in stock_sources:
                raise ValueError("stock decision metric identifiers must be unique")
            definitions.append(definition)
            stock_sources[definition.metric_id] = str(raw_metric["source"])
        raw_financial = raw_domain.get("financial_metrics", [])
        if not isinstance(raw_financial, list):
            raise ValueError("financial metric maps must be lists")
        for raw_metric in raw_financial:
            if not isinstance(raw_metric, Mapping):
                raise ValueError("financial stock mappings must be mappings")
            financial_name = str(raw_metric.get("metric", ""))
            if not financial_name:
                raise ValueError("financial stock mapping requires a source metric")
            metric_id = f"financial:{domain_id}:{financial_name}"
            shape = str(raw_metric.get("metric_shape", "higher_is_better"))
            financial_shapes[metric_id] = shape
            if shape == "threshold_or_plateau" and raw_metric.get("band") is None:
                if metric_id in financial_sources:
                    raise ValueError("financial stock metric identifiers must be unique")
                financial_sources[metric_id] = financial_name
                financial_unscored_reasons[metric_id] = (
                    "VERSIONED_PLATEAU_THRESHOLD_UNAVAILABLE"
                )
                continue
            definition = _definition_from_map(
                {
                    **raw_metric,
                    "metric_id": metric_id,
                    "subfamily": str(raw_metric.get("subfamily", financial_name)),
                    "source": financial_name,
                    "comparison_scope": "BUSINESS_MODEL",
                    "requirement_class": "CONDITIONAL",
                    "rank_authority": raw_metric.get(
                        "rank_authority", stock.get("rank_authority", False)
                    ),
                },
                domain_id,
            )
            if metric_id in financial_sources:
                raise ValueError("financial stock metric identifiers must be unique")
            definitions.append(definition)
            financial_sources[metric_id] = financial_name
    if len(seen_domains) != 6:
        raise ValueError("stock decision map must name six distinct domains")
    stock_map = StockDecisionMap(
        registry=DomainRegistry(
            str(stock.get("version", "")),
            registry_checksum(content),
            tuple(definitions),
        ),
        domains=tuple(domain_rows),
        stock_sources=stock_sources,
        financial_sources=financial_sources,
        financial_shapes=financial_shapes,
        financial_unscored_reasons=financial_unscored_reasons,
        rank_authority=stock.get("rank_authority") is True,
    )
    return stock_map


def compose_stock_decision(
    instrument: str,
    target_context: InstrumentContextV2,
    decision_time: str,
    stock_research: Mapping[str, object],
    *,
    capital_allocation: Mapping[str, object] | None = None,
    financial_projection: object | None = None,
    native_spbk_result: object | None = None,
    peer_observations: Sequence[PeerObservation] = (),
    domain_reference_z: Mapping[str, Sequence[DomainReference]] | None = None,
    tactical_evidence: Mapping[str, object] | None = None,
    registry_path: str | Path = _DEFAULT_REGISTRY_PATH,
    minimum_support: int = 3,
) -> dict[str, object]:
    """Compose stock underwriting, valuation, expectations and tactical evidence.

    Confirmed Norwegian equity certificates are delegated to the native SPBK
    result and cannot fall through into generic stock ranking. Classified
    financial institutions use only their financial-sector projection.
    """

    if target_context.instrument_id != instrument:
        raise ValueError("instrument identity must match the resolved context")
    route_evidence = {
        "jurisdiction": tuple(
            value
            for value in (target_context.legal_domicile, target_context.regulatory_country)
            if value
        ),
        "legal_form": target_context.issuer_type,
        "instrument_subtype": target_context.instrument_subtype,
    }
    ec_route = route_sparebank_ec(route_evidence)
    valuation_output = _valuation_components(stock_research)
    expectations_output = _copy_path(stock_research, "expectations")
    tactical_output = _tactical_components(tactical_evidence)
    valuation_assessment = None
    if ec_route.applies:
        native_valid = _is_native_spbk_result(native_spbk_result)
        assessment = native_spbk_result if native_valid else None
        route = "norwegian_ec_native_spbk"
        route_status = "available" if native_valid else "unavailable"
        route_reason = (
            ""
            if native_valid
            else "NATIVE_SPBK_RESULT_MISSING"
            if native_spbk_result is None
            else "NATIVE_SPBK_RESULT_INVALID"
        )
        valuation_output, expectations_output, tactical_output = _native_spbk_components(
            native_spbk_result if native_valid else None
        )
        generic_assessment = None
        input_evidence: dict[str, object] = {}
        domains: tuple[DomainSlot, ...] = ()
        stock_map = load_stock_decision_map(registry_path)
    elif _looks_like_ec(target_context):
        return _route_failure(
            instrument,
            decision_time,
            stock_research,
            "norwegian_ec_unconfirmed",
            "EC_CLASSIFICATION_UNCONFIRMED",
            None,
            None,
        )
    else:
        valuation_output = _valuation_components(stock_research)
        expectations_output = _copy_path(stock_research, "expectations")
        tactical_output = _tactical_components(tactical_evidence)
        stock_map = load_stock_decision_map(registry_path)
        financial = _is_financial_institution(target_context)
        if financial:
            adapter_registry = AdapterRegistry((financial_adapter_definition(),))
            try:
                adapter = adapter_registry.select(target_context)
            except PeerCohortError:
                adapter = None
            if (
                adapter is None
                or adapter.adapter_id != FINANCIAL_ADAPTER_ID
                or adapter.fallback
            ):
                return _route_failure(
                    instrument,
                    decision_time,
                    stock_research,
                    "financial_adapter_unavailable",
                    "FINANCIAL_ADAPTER_ROUTE_NOT_CONFIRMED",
                    financial_projection,
                    tactical_evidence,
                )
            route = "financial_sector_adapter"
            route_status = (
                "available"
                if _is_financial_projection(financial_projection, instrument)
                else "unavailable"
            )
            route_reason = (
                "" if route_status == "available" else "FINANCIAL_ADAPTER_RESULT_UNAVAILABLE"
            )
            definitions = [item for item in stock_map.registry.metrics if item.metric_id in stock_map.financial_sources]
            registry = DomainRegistry(
                stock_map.registry.version,
                stock_map.registry.checksum,
                tuple(definitions),
            )
            scored, input_evidence = _financial_scored_metrics(
                financial_projection if route_status == "available" else None,
                target_context,
                stock_map,
            )
        else:
            route = "generic_stock"
            route_status = "available"
            route_reason = ""
            registry = DomainRegistry(
                stock_map.registry.version,
                stock_map.registry.checksum,
                tuple(
                    item
                    for item in stock_map.registry.metrics
                    if item.metric_id in stock_map.stock_sources
                ),
            )
            scored, input_evidence = _stock_scored_metrics(
                stock_research,
                capital_allocation or {},
                stock_map,
            )
        generic_assessment = build_instrument_assessment(
            instrument,
            "stock",
            _business_model(target_context),
            decision_time,
            scored,
            registry,
            target_context=target_context,
            peer_observations=peer_observations,
            domain_reference_z=domain_reference_z,
            minimum_support=minimum_support,
        )
        assessment = generic_assessment
        domains_by_name = {
            item.domain: item for item in generic_assessment.domain_slots
        }
        domains = tuple(
            domains_by_name[str(item["domain"])]
            for item in stock_map.domains
            if str(item["domain"]) in domains_by_name
        )
        valuation_registry = load_domain_registry(registry_path)
        valuation_definitions = tuple(
            item for item in valuation_registry.metrics if item.domain == "valuation"
        )
        valuation_assessment = build_instrument_assessment(
            instrument,
            "stock",
            _business_model(target_context),
            decision_time,
            _valuation_scored_metrics(
                stock_research,
                valuation_definitions,
                target_context,
            ),
            DomainRegistry(
                valuation_registry.version,
                valuation_registry.checksum,
                valuation_definitions,
            ),
            target_context=target_context,
            peer_observations=peer_observations,
            domain_reference_z=domain_reference_z,
            minimum_support=minimum_support,
        )
        valuation_domain = valuation_assessment.domain_slots[0]

    return {
        "instrument": instrument,
        "decision_time": decision_time,
        "route": route,
        "route_status": route_status,
        "route_reason": route_reason,
        "assessment": assessment,
        "underwriting": generic_assessment,
        "underwriting_domains": domains,
        "underwriting_domain_labels": {
            str(item["domain"]): str(item["label"])
            for item in stock_map.domains
        },
        "underwriting_baseline_weights": _domain_weights(stock_map.domains),
        "underwriting_z_score": _weighted_domain_z(domains, _domain_weights(stock_map.domains)),
        "critical_underwriting_domains": tuple(
            sorted(
                {
                    item.domain
                    for item in stock_map.registry.metrics
                    if item.requirement_class == "CRITICAL"
                }
            )
        ),
        "underwriting_input_evidence": input_evidence,
        "valuation_domain": valuation_domain if generic_assessment is not None else DomainSlot(
            "valuation", "UNAVAILABLE", None, None, 0.0, 0.0,
            "NATIVE_VALUATION_DOMAIN_UNAVAILABLE", (),
        ),
        "valuation_z_score": (
            valuation_domain.z_score
            if generic_assessment is not None and valuation_domain.status == "AVAILABLE"
            else None
        ),
        "valuation_drivers": (
            tuple(valuation_assessment.drivers)
            if valuation_assessment is not None
            else ()
        ),
        "valuation": valuation_output,
        "expectations": expectations_output,
        "tactical": tactical_output,
        "execution_allowed": False,
    }


def _valuation_scored_metrics(
    stock_research: Mapping[str, object],
    definitions: Sequence[MetricDefinition],
    context: InstrumentContextV2,
) -> list[ScoredMetric]:
    valuation = stock_research.get("valuation")
    relative = valuation.get("relative_metrics") if isinstance(valuation, Mapping) else None
    if not isinstance(relative, Mapping):
        return []
    return [
        metric
        for definition in definitions
        if (
            metric := _make_scored_metric(
                definition.metric_id,
                relative.get(definition.metric_id),
                definition,
                rank_authority=definition.rank_authority,
                context=context,
            )
        )
        is not None
    ]


def _weighted_domain_z(
    domains: Sequence[DomainSlot], weights: Mapping[str, float]
) -> float | None:
    by_domain = {item.domain: item for item in domains}
    if not weights or any(
        domain not in by_domain
        or by_domain[domain].status != "AVAILABLE"
        or by_domain[domain].z_score is None
        for domain in weights
    ):
        return None
    total = sum(weights.values())
    if total <= 0:
        return None
    return sum(
        float(by_domain[domain].z_score) * weight
        for domain, weight in weights.items()
    ) / total


def _definition_from_map(raw: Mapping[str, object], domain_id: str) -> MetricDefinition:
    weight = _finite(raw.get("weight", 1.0))
    subfamily_weight = _finite(raw.get("subfamily_weight", 1.0))
    if weight is None or subfamily_weight is None:
        raise ValueError("stock decision metric weights must be finite numbers")
    raw_band = raw.get("band")
    band: float | tuple[float, float] | None
    if isinstance(raw_band, (tuple, list)) and len(raw_band) == 2:
        low, high = (_finite(raw_band[0]), _finite(raw_band[1]))
        band = None if low is None or high is None else (low, high)
    else:
        band = _finite(raw_band)
    return MetricDefinition(
        metric_id=str(raw.get("metric_id", "")),
        domain=domain_id,
        subfamily=str(raw.get("subfamily", "core")),
        weight=weight,
        comparison_scope=str(raw.get("comparison_scope", "INDUSTRY")),
        requirement_class=str(raw.get("requirement_class", "CONDITIONAL")),  # type: ignore[arg-type]
        metric_shape=str(raw.get("metric_shape", "higher_is_better")),  # type: ignore[arg-type]
        rank_authority=raw.get("rank_authority") is True,
        band=band,
        subfamily_weight=subfamily_weight,
    )


def _domain_weights(domains: Sequence[Mapping[str, object]]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for item in domains:
        weight = _finite(item.get("weight"))
        if weight is None:
            raise ValueError("stock decision domain weights must be finite numbers")
        weights[str(item["domain"])] = weight
    return weights


def _stock_scored_metrics(
    stock_research: Mapping[str, object],
    capital_allocation: Mapping[str, object],
    stock_map: StockDecisionMap,
) -> tuple[list[ScoredMetric], dict[str, object]]:
    source_roots = {
        "profitability": stock_research.get("profitability"),
        "balance_sheet": stock_research.get("balance_sheet"),
        "capital_efficiency": stock_research.get("capital_efficiency"),
        "capital_allocation": capital_allocation,
    }
    scored: list[ScoredMetric] = []
    evidence: dict[str, object] = {}
    definitions = {
        item.metric_id: item
        for item in stock_map.registry.metrics
        if item.metric_id in stock_map.stock_sources
    }
    for metric_id, source_path in stock_map.stock_sources.items():
        definition = definitions[metric_id]
        root_name, _, subpath = source_path.partition(".")
        raw = _mapping_path(source_roots.get(root_name), subpath)
        input_record = _evidence_record(raw, source_path)
        evidence[metric_id] = input_record
        metric = _make_scored_metric(
            metric_id,
            raw,
            definition,
            rank_authority=stock_map.rank_authority,
        )
        if metric is not None:
            scored.append(metric)
    return scored, evidence


def _financial_scored_metrics(
    projection: object | None,
    context: InstrumentContextV2,
    stock_map: StockDecisionMap,
) -> tuple[list[ScoredMetric], dict[str, object]]:
    raw_metrics = _projection_member(projection, "metrics", ())
    if isinstance(raw_metrics, Mapping):
        metric_rows = list(raw_metrics.items())
    elif isinstance(raw_metrics, (tuple, list)):
        metric_rows = [(_projection_member(item, "metric"), item) for item in raw_metrics]
    else:
        metric_rows = []
    by_name = {
        str(_projection_member(item, "metric", name)): item
        for name, item in metric_rows
    }
    scored: list[ScoredMetric] = []
    evidence: dict[str, object] = {}
    definitions = {
        item.metric_id: item
        for item in stock_map.registry.metrics
        if item.metric_id in stock_map.financial_sources
    }
    for metric_id, producer_name in stock_map.financial_sources.items():
        raw = by_name.get(producer_name)
        metric_evidence = _evidence_record(raw, f"financial_projection.{producer_name}")
        if metric_id in stock_map.financial_unscored_reasons:
            metric_evidence.update(
                metric_shape=stock_map.financial_shapes[metric_id],
                decision_status="UNAVAILABLE",
                reason_code=stock_map.financial_unscored_reasons[metric_id],
            )
            evidence[metric_id] = metric_evidence
            continue
        evidence[metric_id] = metric_evidence
        definition = definitions[metric_id]
        direction = _projection_member(raw, "direction")
        if direction in {"higher_is_better", "lower_is_better"} and direction != definition.metric_shape:
            definition = MetricDefinition(
                definition.metric_id,
                definition.domain,
                definition.subfamily,
                definition.weight,
                definition.comparison_scope,
                definition.requirement_class,
                direction,
                rank_authority=definition.rank_authority,
                band=definition.band,
                subfamily_weight=definition.subfamily_weight,
            )
        metric = _make_scored_metric(
            metric_id,
            raw,
            definition,
            rank_authority=stock_map.rank_authority,
            context=context,
        )
        if metric is not None:
            scored.append(metric)
    return scored, evidence


def _make_scored_metric(
    metric_id: str,
    raw: object,
    definition: MetricDefinition,
    *,
    rank_authority: bool,
    context: InstrumentContextV2 | None = None,
) -> ScoredMetric | None:
    if not isinstance(raw, Mapping) and raw is None:
        return None
    value = _finite(_projection_member(raw, "value"))
    status = str(_projection_member(raw, "status", "unavailable"))
    if status.casefold() in {"not_applicable", "n/a", "na"}:
        return None
    timing_status = _projection_member(raw, "source_timing_status")
    if timing_status is not None and str(timing_status).casefold() != "available":
        return None
    provenance = _provenance_from_metric(raw)
    if not _provenance_complete(provenance):
        return None
    timestamps = [(_time(item["effective_at"]), _time(item["known_at"])) for item in provenance]
    effective_at = max((item[0] for item in timestamps)).isoformat().replace("+00:00", "Z")
    known_at = max((item[1] for item in timestamps)).isoformat().replace("+00:00", "Z")
    confidence = _finite(_projection_member(raw, "confidence"))
    if confidence is None:
        confidence = {"high": 0.85, "medium": 0.65, "low": 0.35}.get(
            str(_projection_member(raw, "confidence", "low")).casefold(), 0.35
        )
    unit = str(_projection_member(raw, "unit", "ratio") or "ratio")
    business_model = _projection_member(raw, "business_model")
    if not isinstance(business_model, str) or not business_model.strip():
        business_model = _business_model(context)
    source = json.dumps(provenance, sort_keys=True, separators=(",", ":"))
    return ScoredMetric(
        metric_id=metric_id,
        raw_value=value,
        unit=unit,
        effective_at=effective_at,
        known_at=known_at,
        source=source,
        authority=max(0.0, min(1.0, confidence)),
        freshness=1.0,
        reliability=max(0.0, min(1.0, confidence)),
        business_model=business_model,
        comparison_scope=definition.comparison_scope,  # type: ignore[arg-type]
        metric_shape=definition.metric_shape,
        requirement_class=definition.requirement_class,
        rank_authority=rank_authority,
        coverage=1.0,
        uncertainty=1.0 - max(0.0, min(1.0, confidence)),
        status=status.upper(),
        reason_code=(
            "AVAILABLE"
            if value is not None and status.casefold() not in {"missing", "unavailable"}
            else "MISSING_INPUT"
        ),
    )


def _evidence_record(raw: object, source_path: str) -> dict[str, object]:
    if raw is None:
        return {"source": source_path, "status": "UNAVAILABLE", "reason_code": "MISSING_INPUT"}
    provenance = _provenance_from_metric(raw)
    status = str(_projection_member(raw, "status", "unavailable")).upper()
    value = _finite(_projection_member(raw, "value"))
    timing_status = _projection_member(raw, "source_timing_status")
    if timing_status is None and _provenance_complete(provenance):
        timing_status = "available"
    timing_available = timing_status == "available"
    metric_available = value is not None and status.casefold() not in {
        "missing",
        "unavailable",
        "not_applicable",
        "n/a",
        "na",
        "quarantined",
    }
    if not timing_available:
        reason = "EXACT_SOURCE_TIMING_UNAVAILABLE"
    elif not metric_available:
        reason = str(
            _projection_member(raw, "limitation", "")
            or _projection_member(raw, "reason", "")
            or "METRIC_VALUE_UNAVAILABLE"
        )
    else:
        reason = str(_projection_member(raw, "limitation", "") or "")
    return {
        "source": source_path,
        "value": value,
        "status": status,
        "decision_status": "AVAILABLE" if timing_available and metric_available else "UNAVAILABLE",
        "reason_code": reason or "AVAILABLE",
        "source_provenance": provenance,
    }


def _provenance_from_metric(raw: object) -> list[dict[str, object]]:
    explicit = _projection_member(raw, "source_provenance")
    if isinstance(explicit, (tuple, list)):
        return [dict(item) for item in explicit if isinstance(item, Mapping)]
    source_id = _projection_member(raw, "source_id")
    effective_at = _projection_member(raw, "effective_at", _projection_member(raw, "as_of"))
    known_at = _projection_member(raw, "known_at")
    if source_id is None and effective_at is None and known_at is None:
        return []
    return [
        {
            "source_id": source_id,
            "effective_at": effective_at,
            "known_at": known_at,
        }
    ]


def _provenance_complete(provenance: Sequence[Mapping[str, object]]) -> bool:
    if not provenance:
        return False
    try:
        return all(
            str(item.get("source_id", "")).strip()
            and _parse_time(str(item.get("effective_at", "")))
            and _known_at(str(item.get("known_at", "")))
            for item in provenance
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _known_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("known_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("known_at requires an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if len(value) == 10:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            raise ValueError("source timing requires an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("source timing must be an ISO string")
    return _parse_time(value)


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result is not None and math.isfinite(result) else None


def _mapping_path(value: object, path: str) -> object:
    current = value
    for name in path.split(".") if path else ():
        if not isinstance(current, Mapping):
            return None
        current = current.get(name)
    return current


def _copy_path(value: Mapping[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    return dict(item) if isinstance(item, Mapping) else {"status": "unavailable"}


def _valuation_components(stock_research: Mapping[str, object]) -> dict[str, object]:
    raw = stock_research.get("valuation")
    if not isinstance(raw, Mapping):
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "reason_code": "NO_VALUATION_PRODUCER_OUTPUT",
            "execution_allowed": False,
        }
    components = {
        "relative_metrics": raw.get("relative_metrics", {}),
        "dcf": raw.get("intrinsic_value", {}),
        "residual_income": raw.get("residual_income", {}),
        "reverse_dcf": raw.get("reverse_dcf", {}),
        "reverse_dcf_gap": raw.get("reverse_dcf_gap", {"status": "unavailable"}),
        "normalized_mid_cycle": raw.get("normalized_mid_cycle", {"status": "unavailable"}),
        "model_disagreement": raw.get("model_disagreement", {"status": "unavailable"}),
        "margin_of_safety": raw.get("margin_of_safety", {"status": "unavailable"}),
    }
    available = any(_has_valuation_evidence(value) for value in components.values())
    return {
        "status": "AVAILABLE" if available else "INSUFFICIENT_EVIDENCE",
        "reason_code": "AVAILABLE" if available else "NO_DEFENSIBLE_VALUATION_COMPONENT",
        **components,
        "execution_allowed": False,
    }


def _has_valuation_evidence(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    status = str(value.get("status", "")).casefold()
    if status in {"available", "resolved", "observed"}:
        for name in (
            "value",
            "per_share",
            "implied_growth",
            "owner_pb",
            "owner_pe",
            "owner_book_per_ec",
            "owner_eps",
        ):
            if _finite(value.get(name)) is not None:
                return True
        raw_range = value.get("range")
        if isinstance(raw_range, (tuple, list)) and any(
            _finite(item) is not None for item in raw_range
        ):
            return True
        scenarios = value.get("scenarios")
        if isinstance(scenarios, Mapping) and any(
            isinstance(item, Mapping) and _finite(item.get("per_share")) is not None
            for item in scenarios.values()
        ):
            return True
        models = value.get("models")
        if isinstance(models, Mapping) and any(
            isinstance(item, Mapping)
            and str(item.get("status", "")).casefold() == "available"
            and _finite(item.get("value")) is not None
            for item in models.values()
        ):
            return True
    return any(_has_valuation_evidence(item) for item in value.values())


def _tactical_components(evidence: Mapping[str, object] | None) -> dict[str, object]:
    raw = evidence or {}
    members = {
        name: raw.get(name, {"status": "unavailable"})
        for name in ("momentum", "trend", "relative_strength")
    }
    return {
        "price_family": {
            "status": "available" if any(_available(item) for item in members.values()) else "unavailable",
            "vote_count": 1,
            "members": members,
            "combined_value": None,
            "execution_allowed": False,
        },
        "earnings_momentum": raw.get("earnings_momentum", {"status": "unavailable"}),
        "model_evidence": raw.get("model_evidence", {"status": "unavailable"}),
        "execution_allowed": False,
    }


def _available(value: object) -> bool:
    return isinstance(value, Mapping) and str(value.get("status", "")).casefold() in {
        "available",
        "observed",
    }


def _looks_like_ec(context: InstrumentContextV2) -> bool:
    labels = (
        *(context.business_model_tags or ()),
        *(context.special_structures or ()),
        context.instrument_subtype or "",
        context.share_class_id or "",
    )
    normalized = {
        str(value).casefold().replace("-", "_").replace(" ", "_")
        for value in labels
        if value
    }
    return any(
        label in _EC_TOKENS
        or any(token in label for token in _EC_TOKENS if token != "ec")
        for label in normalized
    )


def _is_financial_institution(context: InstrumentContextV2) -> bool:
    labels = (context.sector or "", context.issuer_sector or "", context.issuer_type or "")
    return any(str(value).casefold().strip() in _FINANCIAL_CONTEXT_LABELS for value in labels)


def _business_model(context: InstrumentContextV2 | None) -> str | None:
    if context is None:
        return None
    return next(iter(context.business_model_tags), None)


def _is_financial_projection(projection: object | None, instrument: str) -> bool:
    return (
        _projection_member(projection, "status") == "available"
        and _projection_member(projection, "contract") == FINANCIAL_ADAPTER_CONTRACT
        and _projection_member(projection, "adapter_id") == FINANCIAL_ADAPTER_ID
        and _projection_member(projection, "instrument_id") == instrument
        and _projection_member(projection, "execution_allowed") is False
    )


def _is_native_spbk_result(result: object | None) -> bool:
    routing = _projection_member(result, "routing")
    return (
        _projection_member(result, "contract") == SPAREBANK_ANALYSIS_CONTRACT
        and _projection_member(result, "execution_allowed") is False
        and _projection_member(routing, "applies") is True
    )


def _native_spbk_components(
    result: object | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    unavailable_expectations = {
        "status": "unavailable",
        "reason_code": "NATIVE_SPBK_EXPECTATIONS_NOT_EXPOSED",
        "execution_allowed": False,
    }
    if not _is_native_spbk_result(result):
        unavailable = {
            "status": "unavailable",
            "reason_code": "NATIVE_SPBK_COMPONENT_UNAVAILABLE",
            "execution_allowed": False,
        }
        return unavailable, unavailable_expectations, unavailable
    raw_valuation = _projection_member(result, "valuation")
    valuation = (
        dict(raw_valuation)
        if isinstance(raw_valuation, Mapping)
        else {
            "status": "unavailable",
            "reason_code": "NATIVE_SPBK_VALUATION_UNAVAILABLE",
            "execution_allowed": False,
        }
    )
    scorecard = _projection_member(result, "scorecard")
    raw_tactical = _projection_member(scorecard, "tactical")
    tactical = (
        dict(raw_tactical)
        if isinstance(raw_tactical, Mapping)
        else {
            "status": "unavailable",
            "reason_code": "NATIVE_SPBK_TACTICAL_UNAVAILABLE",
            "execution_allowed": False,
        }
    )
    return valuation, unavailable_expectations, tactical


def _route_failure(
    instrument: str,
    decision_time: str,
    stock_research: Mapping[str, object],
    route: str,
    reason: str,
    native_result: object | None,
    tactical_evidence: Mapping[str, object] | None,
) -> dict[str, object]:
    if route.startswith("norwegian_ec"):
        valuation, expectations, tactical = _native_spbk_components(native_result)
    else:
        valuation = _valuation_components(stock_research)
        expectations = _copy_path(stock_research, "expectations")
        tactical = _tactical_components(tactical_evidence)
    return {
        "instrument": instrument,
        "route": route,
        "route_status": "unavailable",
        "route_reason": reason,
        "assessment": native_result,
        "underwriting": None,
        "underwriting_domains": (),
        "underwriting_baseline_weights": {},
        "underwriting_input_evidence": {},
        "valuation": valuation,
        "expectations": expectations,
        "tactical": tactical,
        "decision_time": decision_time,
        "execution_allowed": False,
    }


__all__ = [
    "StockDecisionMap",
    "compose_stock_decision",
    "load_stock_decision_map",
]
