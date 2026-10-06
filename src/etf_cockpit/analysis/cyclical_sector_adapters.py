"""Typed, local-only energy, materials and industrial cyclical adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Mapping, Sequence

from etf_cockpit.analysis.peer_cohorts import AdapterDefinition, AdapterRegistry, PeerCohortError
from etf_cockpit.data.classification import InstrumentContextV2
from etf_cockpit.data.contracts import SourceAuthority


CYCLICAL_CONTRACT = "cyclical-sector-adapter.v1"
CYCLICAL_FORMULA_VERSION = "cyclical-sector-formulas.v1"
_CYCLICAL_SOURCE_CONTRACT = "cyclical-sector-source.v1"
_CYCLICAL_SOURCE_SCHEMA_VERSION = 1
_SCENARIO_NAMES = ("commodity_price", "input_cost", "demand_rate")
_SCENARIO_INPUTS = ("shock_rate", "exposed_amount", "portfolio_base")
_ADAPTERS = {"energy": "sector:energy", "materials": "sector:materials", "industrials": "sector:industrials"}
_COMMON = frozenset({
    "spot_cycle_margin", "normalised_margin", "capital_intensity",
    "cycle_adjusted_ev_to_earnings", "trough_interest_coverage",
})
_METRICS = {
    "energy": _COMMON | {"production", "unit_cost", "reserves", "resource_life", "realised_price", "hedge_ratio", "sustaining_capex", "decommissioning"},
    "materials": _COMMON | {"production", "unit_cost", "reserves", "resource_life", "realised_price", "hedge_ratio", "sustaining_capex", "decommissioning", "inventory"},
    "industrials": _COMMON | {"order_backlog", "book_to_bill", "backlog_quality", "aftermarket_mix", "utilisation", "working_capital", "customer_concentration", "project_concentration"},
}
_LOWER = frozenset({"unit_cost", "capital_intensity", "decommissioning", "working_capital", "customer_concentration", "project_concentration", "cycle_adjusted_ev_to_earnings"})
_RATIO = frozenset({"spot_cycle_margin", "normalised_margin", "hedge_ratio", "backlog_quality", "aftermarket_mix", "utilisation", "capital_intensity", "customer_concentration", "project_concentration"})
_OPERATIONAL = frozenset().union(*_METRICS.values()) - {"spot_cycle_margin", "normalised_margin"}
_PROHIBITED = frozenset({"pe_ratio", "generic_pe", "free_cash_flow", "fcf", "industrial_leverage"})
_COMMODITY_SENSITIVE = frozenset({
    "production", "unit_cost", "reserves", "resource_life",
    "realised_price", "hedge_ratio", "inventory",
})
_UNITS = {
    "production": ("quantity",), "reserves": ("quantity",), "inventory": ("quantity",),
    "unit_cost": ("currency_per_quantity",), "realised_price": ("currency_per_quantity",),
    "resource_life": ("years",),
    "book_to_bill": ("multiple",),
    "cycle_adjusted_ev_to_earnings": ("multiple",),
    "trough_interest_coverage": ("multiple",),
}
_BOUNDED_RATIOS = frozenset({"hedge_ratio", "backlog_quality", "aftermarket_mix", "utilisation", "customer_concentration", "project_concentration"})
_FATAL_LIMITATIONS = frozenset({"stale", "conflicted", "invalid", "unsupported", "missing_value"})


class CyclicalAdapterError(ValueError):
    """Raised when cyclical evidence violates its fail-closed contract."""


@dataclass(frozen=True)
class CyclicalFormulaDefinition:
    metric: str
    business_model: str
    direction: str
    allowed_units: tuple[str, ...]
    definition: str
    formula_version: str = CYCLICAL_FORMULA_VERSION
    missing_policy: str = "unavailable"
    execution_allowed: bool = False


@dataclass(frozen=True)
class CyclicalMetricEvidence:
    metric: str
    value: float | None
    unit: str
    period: str
    reporting_standard: str
    jurisdiction: str
    business_model: str
    source_id: str
    source_authority: SourceAuthority
    as_of: str
    known_at: str
    direction: str | None = None
    limitations: tuple[str, ...] = ()
    commodity_id: str | None = None
    normalisation_cycle_ids: tuple[str, ...] = ()
    applicable: bool = True
    execution_allowed: bool = False


@dataclass(frozen=True)
class CycleHistoryEvidence:
    cycle_id: str
    phase: str
    start_at: str
    end_at: str
    known_at: str
    source_id: str
    source_authority: SourceAuthority
    execution_allowed: bool = False


@dataclass(frozen=True)
class CyclicalMetricResult:
    metric: str
    status: str
    value: float | None
    unit: str
    direction: str
    period: str
    reporting_standard: str
    jurisdiction: str
    business_model: str
    source_id: str
    source_authority: str
    as_of: str
    known_at: str
    definition: str
    missing_policy: str
    limitations: tuple[str, ...]
    commodity_id: str | None = None
    normalisation_cycle_ids: tuple[str, ...] = ()
    formula_version: str = CYCLICAL_FORMULA_VERSION
    execution_allowed: bool = False


@dataclass(frozen=True)
class CycleHistoryResult:
    cycle_id: str
    phase: str
    start_at: str
    end_at: str
    known_at: str
    source_id: str
    source_authority: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class CyclicalScenario:
    scenario: str
    status: str
    portfolio_impact: float | None
    unit: str
    formula: str
    inputs: Mapping[str, float]
    direction: str
    exposure_unit: str
    basis_unit: str
    reason_code: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class CyclicalCheck:
    check: str
    status: str
    value: float | None
    unit: str
    threshold: float
    direction: str
    formula: str
    reason_code: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class CyclicalProjection:
    contract: str
    status: str
    instrument_id: str
    business_model: str
    adapter_id: str
    adapter_version: str
    variant_path: tuple[str, ...]
    parent_fallback: str
    metrics: tuple[CyclicalMetricResult, ...]
    cycle_history: tuple[CycleHistoryResult, ...]
    cycle_history_adequate: bool
    aggregate_confidence: float
    scenarios: tuple[CyclicalScenario, ...]
    checks: tuple[CyclicalCheck, ...]
    rationale: tuple[str, ...]
    lineage: Mapping[str, object]
    limitations: tuple[str, ...]
    source_payload: Mapping[str, object]
    result_hash: str
    execution_allowed: bool = False


def cyclical_adapter_definitions() -> tuple[AdapterDefinition, ...]:
    return tuple(AdapterDefinition(adapter, "1", _METRICS[model]) for model, adapter in sorted(_ADAPTERS.items()))


def cyclical_formula_registry() -> tuple[CyclicalFormulaDefinition, ...]:
    definitions = {
        "spot_cycle_margin": "current reported operating margin at the observed cycle point",
        "normalised_margin": "through-cycle margin supported by distinct historical cycles",
        "resource_life": "reported reserves divided by current annual production",
        "book_to_bill": "orders received divided by recognised revenue",
        "backlog_quality": "supported executable backlog divided by total reported backlog",
    }
    return tuple(
        CyclicalFormulaDefinition(
            metric, model, "lower_is_better" if metric in _LOWER else "higher_is_better",
            _UNITS.get(metric, ("ratio", "percent") if metric in _RATIO else ("currency",)),
            definitions.get(metric, "issuer-reported sector-specific operational measure"),
        )
        for model, metrics in sorted(_METRICS.items()) for metric in sorted(metrics)
    )


def build_cyclical_projection(
    context: InstrumentContextV2,
    evidence: Sequence[CyclicalMetricEvidence],
    *,
    cycle_history: Sequence[CycleHistoryEvidence],
    registry: AdapterRegistry,
    decision_time: str,
    scenarios: Mapping[str, object],
) -> CyclicalProjection:
    decision = _time(decision_time)
    _validate_context_source_fields(asdict(context))
    model = _model(context)
    source = _source_payload(context, evidence, cycle_history, decision, scenarios)
    if context.instrument_type != "stock" or context.asset_class != "equity":
        raise CyclicalAdapterError("cyclical adapter requires a classified equity security")
    if (context.execution_allowed or _time(context.decision_time) != decision
            or _time(context.effective_at) > decision
            or context.classification_status in {"unresolved", "manual_review"}):
        raise CyclicalAdapterError("classification must match the exact decision cutoff")
    try:
        selection = registry.select(context)
    except PeerCohortError as exc:
        raise CyclicalAdapterError(str(exc)) from exc
    if selection.adapter_id != _ADAPTERS[model] or selection.fallback:
        raise CyclicalAdapterError("cyclical classification route is incompatible")
    formulas = {row.metric: row for row in cyclical_formula_registry() if row.business_model == model}
    results: list[CyclicalMetricResult] = []
    seen: set[str] = set()
    limitations: set[str] = set()
    for item in sorted(evidence, key=lambda row: (row.metric, row.known_at, row.source_id)):
        _validate_metric(item, model, decision)
        if item.metric in _PROHIBITED:
            raise CyclicalAdapterError(f"generic fallback {item.metric!r} is forbidden")
        if item.metric not in formulas or item.metric in seen:
            raise CyclicalAdapterError("cyclical metric is invalid or duplicated")
        seen.add(item.metric)
        formula = formulas[item.metric]
        if item.unit not in formula.allowed_units or (item.direction is not None and item.direction != formula.direction):
            raise CyclicalAdapterError("cyclical metric unit or direction is incompatible")
        fatal = any(
            value.casefold().split(":", 1)[0].split("_", 1)[0] in _FATAL_LIMITATIONS
            for value in item.limitations
        )
        inapplicable = not item.applicable
        available = not inapplicable and not fatal and item.value is not None and _finite(item.value)
        item_limits = tuple(sorted({*item.limitations, *(() if available or inapplicable else ("missing_value",))}))
        limitations.update(f"{item.metric}:{value}" for value in item_limits)
        results.append(CyclicalMetricResult(
            metric=item.metric, status="inapplicable" if inapplicable else "available" if available else "unavailable",
            value=float(item.value) if available else None, unit=item.unit,
            direction=formula.direction, period=item.period,
            reporting_standard=item.reporting_standard, jurisdiction=item.jurisdiction,
            business_model=model, source_id=item.source_id,
            source_authority=item.source_authority.value, as_of=_iso(_time(item.as_of)),
            known_at=_iso(_time(item.known_at)), definition=formula.definition,
            missing_policy=formula.missing_policy, limitations=item_limits,
            commodity_id=item.commodity_id,
            normalisation_cycle_ids=tuple(sorted(item.normalisation_cycle_ids)),
        ))
    for metric in sorted(set(formulas) - seen):
        formula = formulas[metric]
        results.append(CyclicalMetricResult(
            metric=metric, status="unavailable", value=None,
            unit=formula.allowed_units[0], direction=formula.direction,
            period="unavailable", reporting_standard="unavailable",
            jurisdiction="unavailable", business_model=model, source_id="unavailable",
            source_authority="unavailable", as_of=_iso(decision), known_at=_iso(decision),
            definition=formula.definition, missing_policy=formula.missing_policy,
            limitations=("not_disclosed",), commodity_id=None,
        ))
        limitations.add(f"{metric}:not_disclosed")
    results.sort(key=lambda row: row.metric)
    history = _history(cycle_history, decision)
    adequate = len(history) >= 2
    history_ids = tuple(sorted(row.cycle_id for row in history))
    linked = next((row.normalisation_cycle_ids for row in results if row.metric == "normalised_margin"), ())
    normalisation_linked = tuple(sorted(linked)) == history_ids
    if not adequate or not normalisation_linked:
        limitations.add("cycle_history:insufficient_distinct_cycles")
        results = [
            replace(
                row,
                status="unavailable",
                value=None,
                limitations=tuple(sorted({*row.limitations, "insufficient_or_unlinked_cycle_history"})),
            )
            if row.metric == "normalised_margin"
            else row
            for row in results
        ]
        limitations.add("normalised_margin:insufficient_or_unlinked_cycle_history")
    applicable_results = [row for row in results if row.status != "inapplicable"]
    available = [row for row in applicable_results if row.status == "available"]
    confidence = min(1.0, len(available) / max(1, len(applicable_results))) if applicable_results else 0.0
    if not adequate:
        confidence *= 0.6
    confidence = round(confidence, 6)
    scenario_results = tuple(_scenario(name, scenarios.get(name)) for name in ("commodity_price", "input_cost", "demand_rate"))
    scenarios_complete = all(row.status == "available" for row in scenario_results)
    if not scenarios_complete:
        limitations.add("scenarios:required_scenario_unavailable")
        confidence *= 0.8
        confidence = round(confidence, 6)
    checks = _checks(results)
    lineage = {
        "classification_version": context.version_id,
        "classification_token": context.score_invalidation_token,
        "adapter_lineage": selection.lineage_hash,
        "formula_version": CYCLICAL_FORMULA_VERSION,
        "decision_time": _iso(decision),
        "sources": tuple(sorted(
            {row.source_id for row in results if row.source_id != "unavailable"}
            | {row.source_id for row in history}
        )),
    }
    provisional = {
        "contract": CYCLICAL_CONTRACT,
        "status": "available" if available and len(available) == len(applicable_results) and adequate and normalisation_linked and scenarios_complete else "partial" if available else "unavailable",
        "instrument_id": context.instrument_id, "business_model": model,
        "adapter_id": selection.adapter_id, "adapter_version": selection.adapter_version,
        "variant_path": (f"cyclicals:{model}:{(context.operating_country or 'global').lower()}", f"cyclicals:{model}", "cyclicals"),
        "parent_fallback": "cyclicals", "metrics": tuple(results),
        "cycle_history": history, "cycle_history_adequate": adequate,
        "aggregate_confidence": confidence, "scenarios": scenario_results, "checks": checks,
        "rationale": (
            "spot-cycle and normalised margins remain separate",
            "operational measures require issuer or official point-in-time lineage",
            "insufficient distinct-cycle history reduces confidence",
        ),
        "lineage": lineage, "limitations": tuple(sorted(limitations)),
        "source_payload": source,
        "execution_allowed": False,
    }
    return CyclicalProjection(**provisional, result_hash=_hash(provisional))


def unavailable_cyclical_projection(instrument_id: str, reason_code: str = "cyclical_evidence_unavailable") -> dict[str, object]:
    return {
        "contract": CYCLICAL_CONTRACT, "status": "unavailable", "instrument_id": str(instrument_id),
        "reason_code": reason_code, "metrics": (), "cycle_history": (),
        "cycle_history_adequate": False, "aggregate_confidence": 0.0, "scenarios": (), "checks": (),
        "rationale": (), "lineage": {}, "limitations": ("local cyclical evidence unavailable",),
        "execution_allowed": False,
    }


def projection_payload(projection: CyclicalProjection) -> dict[str, object]:
    return asdict(projection)


def cyclical_result_hash(value: CyclicalProjection | Mapping[str, object]) -> str:
    payload = asdict(value) if isinstance(value, CyclicalProjection) else dict(value)
    payload.pop("result_hash", None)
    return _hash(payload)


def cyclical_source_digest(source_payload: Mapping[str, object]) -> str:
    """Hash canonical source evidence supplied separately from its projection."""

    if not isinstance(source_payload, Mapping):
        raise CyclicalAdapterError("cyclical source payload must be a mapping")
    return _hash(source_payload)


def verify_cyclical_projection(
    value: CyclicalProjection | Mapping[str, object],
    *,
    expected_source_digest: str,
) -> dict[str, object]:
    payload = projection_payload(value) if isinstance(value, CyclicalProjection) else dict(value)
    if (set(payload) != set(CyclicalProjection.__dataclass_fields__) or payload.get("contract") != CYCLICAL_CONTRACT
            or payload.get("execution_allowed") is not False or _has_authority(payload)
            or payload.get("result_hash") != cyclical_result_hash(payload)):
        raise CyclicalAdapterError("cyclical projection verification failed")
    try:
        if (not _digest(expected_source_digest)
                or expected_source_digest != cyclical_source_digest(payload["source_payload"])):  # type: ignore[arg-type]
            raise ValueError
        expected = projection_payload(_replay_source_payload(payload["source_payload"]))
        expected_hash = expected.pop("result_hash")
        actual = dict(payload)
        actual_hash = actual.pop("result_hash")
        if _hash(actual) != _hash(expected) or actual_hash != expected_hash:
            raise ValueError
    except (KeyError, TypeError, ValueError, CyclicalAdapterError) as exc:
        raise CyclicalAdapterError("cyclical projection semantic verification failed") from exc
    return payload


def _source_payload(
    context: InstrumentContextV2,
    evidence: Sequence[CyclicalMetricEvidence],
    cycle_history: Sequence[CycleHistoryEvidence],
    decision: datetime,
    scenarios: Mapping[str, object],
) -> dict[str, object]:
    return {
        "contract": _CYCLICAL_SOURCE_CONTRACT,
        "schema_version": _CYCLICAL_SOURCE_SCHEMA_VERSION,
        "context": asdict(context),
        "evidence": tuple(_metric_source(item) for item in sorted(evidence, key=lambda row: (row.metric, row.known_at, row.source_id))),
        "cycle_history": tuple(_history_source(item) for item in sorted(cycle_history, key=lambda row: (row.cycle_id, row.start_at, row.source_id))),
        "decision_time": _iso(decision),
        "scenarios": {name: _scenario_source(scenarios.get(name)) for name in _SCENARIO_NAMES},
    }


def _metric_source(item: CyclicalMetricEvidence) -> dict[str, object]:
    value = asdict(item)
    value["source_authority"] = item.source_authority.value
    return value


def _history_source(item: CycleHistoryEvidence) -> dict[str, object]:
    value = asdict(item)
    value["source_authority"] = item.source_authority.value
    return value


def _scenario_source(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    output: dict[str, object] = {}
    for key in _SCENARIO_INPUTS:
        if key not in value:
            continue
        try:
            number = float(value[key])
        except OverflowError:
            output[key] = {"kind": "invalid", "value": "numeric_overflow"}
        except (TypeError, ValueError):
            output[key] = {"kind": "invalid", "value": str(value[key])}
        else:
            output[key] = number if math.isfinite(number) else {"kind": "non_finite", "value": repr(number)}
    return output


def _replay_source_payload(source: object) -> CyclicalProjection:
    if not isinstance(source, Mapping) or set(source) != {"contract", "schema_version", "context", "evidence", "cycle_history", "decision_time", "scenarios"}:
        raise ValueError
    if source["contract"] != _CYCLICAL_SOURCE_CONTRACT or source["schema_version"] != _CYCLICAL_SOURCE_SCHEMA_VERSION:
        raise ValueError
    context = _context_from_source(source["context"])
    evidence = tuple(_metric_from_source(item) for item in _source_rows(source["evidence"]))
    cycle_history = tuple(_history_from_source(item) for item in _source_rows(source["cycle_history"]))
    decision = _time(str(source["decision_time"]))
    scenarios = _scenarios_from_source(source["scenarios"])
    if _hash(source) != _hash(_source_payload(context, evidence, cycle_history, decision, scenarios)):
        raise ValueError
    return build_cyclical_projection(
        context,
        evidence,
        cycle_history=cycle_history,
        registry=AdapterRegistry(cyclical_adapter_definitions()),
        decision_time=_iso(decision),
        scenarios=scenarios,
    )


def _source_rows(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError
    return tuple(value)  # type: ignore[arg-type]


def _context_from_source(value: object) -> InstrumentContextV2:
    if not isinstance(value, Mapping) or set(value) != set(InstrumentContextV2.__dataclass_fields__):
        raise ValueError
    fields = dict(value)
    _validate_context_source_fields(fields)
    for name in ("strategy_labels", "business_model_tags", "revenue_regions", "asset_regions", "special_structures", "fallback_path", "evidence_ids", "excluded_evidence_ids", "override_ids", "source_ids", "invalidated_score_keys", "warnings"):
        fields[name] = tuple(fields[name])
    fields["alternatives"] = {key: tuple(values) for key, values in fields["alternatives"].items()}
    return InstrumentContextV2(**fields)


def _validate_context_source_fields(fields: Mapping[str, object]) -> None:
    sequences = {
        "strategy_labels", "business_model_tags", "revenue_regions", "asset_regions",
        "special_structures", "fallback_path", "evidence_ids", "excluded_evidence_ids",
        "override_ids", "source_ids", "invalidated_score_keys", "warnings",
    }
    mappings = {"field_confidence", "alternatives"}
    booleans = {"dependent_scores_invalidated", "sector_adapter_allowed", "execution_allowed"}
    for name, item in fields.items():
        if name in sequences:
            if not isinstance(item, (list, tuple)) or not all(isinstance(element, str) for element in item):
                raise ValueError
        elif name == "field_confidence":
            if (not isinstance(item, Mapping)
                    or not all(isinstance(key, str) and _finite(number) for key, number in item.items())):
                raise ValueError
        elif name == "alternatives":
            if (not isinstance(item, Mapping)
                    or not all(isinstance(key, str) and isinstance(values, (list, tuple))
                               and all(isinstance(element, str) for element in values)
                               for key, values in item.items())):
                raise ValueError
        elif name in mappings:
            raise ValueError
        elif name in booleans:
            if not isinstance(item, bool):
                raise ValueError
        elif name == "schema_version":
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError
        elif name == "classification_confidence":
            if not _finite(item):
                raise ValueError
        elif item is not None and not isinstance(item, str):
            raise ValueError
    if fields.get("execution_allowed") is not False:
        raise ValueError


def _metric_from_source(value: Mapping[str, object]) -> CyclicalMetricEvidence:
    if set(value) != set(CyclicalMetricEvidence.__dataclass_fields__):
        raise ValueError
    fields = dict(value)
    try:
        fields["source_authority"] = SourceAuthority(str(fields["source_authority"]))
    except (KeyError, ValueError) as exc:
        raise ValueError from exc
    for name in ("limitations", "normalisation_cycle_ids"):
        if (not isinstance(fields.get(name), (list, tuple))
                or not all(isinstance(item, str) for item in fields[name])):
            raise ValueError
        fields[name] = tuple(fields[name])
    for name in ("metric", "unit", "period", "reporting_standard", "jurisdiction", "business_model", "source_id", "as_of", "known_at"):
        if not isinstance(fields.get(name), str):
            raise ValueError
    for name in ("direction", "commodity_id"):
        if fields.get(name) is not None and not isinstance(fields[name], str):
            raise ValueError
    if (fields.get("value") is not None and not _finite(fields["value"])) or not all(
        isinstance(fields.get(name), bool) for name in ("applicable", "execution_allowed")
    ):
        raise ValueError
    return CyclicalMetricEvidence(**fields)


def _history_from_source(value: Mapping[str, object]) -> CycleHistoryEvidence:
    if set(value) != set(CycleHistoryEvidence.__dataclass_fields__):
        raise ValueError
    fields = dict(value)
    try:
        fields["source_authority"] = SourceAuthority(str(fields["source_authority"]))
    except (KeyError, ValueError) as exc:
        raise ValueError from exc
    if (not all(isinstance(fields.get(name), str) for name in ("cycle_id", "phase", "start_at", "end_at", "known_at", "source_id"))
            or not isinstance(fields.get("execution_allowed"), bool)):
        raise ValueError
    return CycleHistoryEvidence(**fields)


def _scenarios_from_source(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(_SCENARIO_NAMES):
        raise ValueError
    output: dict[str, object] = {}
    for name in _SCENARIO_NAMES:
        raw = value[name]
        if raw is None:
            output[name] = None
            continue
        if not isinstance(raw, Mapping) or not set(raw) <= set(_SCENARIO_INPUTS):
            raise ValueError
        restored: dict[str, object] = {}
        for key, item in raw.items():
            if isinstance(item, Mapping) and set(item) == {"kind", "value"}:
                if (item["kind"] == "non_finite" and isinstance(item["value"], str)
                        and item["value"] in {"nan", "inf", "-inf"}):
                    restored[key] = float(item["value"])
                elif item["kind"] == "invalid" and isinstance(item["value"], str):
                    restored[key] = item["value"]
                else:
                    raise ValueError
            else:
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise ValueError
                try:
                    number = float(item)
                except OverflowError as exc:
                    raise ValueError from exc
                if not math.isfinite(number):
                    raise ValueError
                restored[key] = number
        output[name] = restored
    return output


def _model(context: InstrumentContextV2) -> str:
    tags = {tag.casefold() for tag in context.business_model_tags}
    aliases = {
        "energy": {"energy", "oil_gas", "energy_producer"},
        "materials": {"materials", "mining", "miner"},
        "industrials": {"industrials", "industrial", "capital_goods"},
    }
    matches = [model for model, values in aliases.items() if tags & values]
    if len(matches) != 1:
        raise CyclicalAdapterError("business model must resolve to exactly one cyclical family")
    if "infrastructure" in tags or "infrastructure_operator" in tags:
        raise CyclicalAdapterError("infrastructure industrials use the real-asset adapter")
    return matches[0]


def _validate_metric(item: CyclicalMetricEvidence, model: str, decision: datetime) -> None:
    as_of, known = _time(item.as_of), _time(item.known_at)
    if (item.execution_allowed or item.business_model != model or not item.period.strip()
            or not item.reporting_standard.strip() or not item.jurisdiction.strip()
            or not item.source_id.strip() or as_of > known or known > decision):
        raise CyclicalAdapterError("cyclical metric lineage is invalid")
    if item.metric in _OPERATIONAL and item.source_authority not in {SourceAuthority.OFFICIAL, SourceAuthority.ISSUER}:
        raise CyclicalAdapterError("operational metric requires issuer or official evidence")
    if model in {"energy", "materials"} and item.metric in _COMMODITY_SENSITIVE and not (item.commodity_id or "").strip():
        raise CyclicalAdapterError("commodity-sensitive metric requires an explicit commodity mapping")
    if item.value is not None and item.metric in _BOUNDED_RATIOS and not 0 <= item.value <= 1:
        raise CyclicalAdapterError("cyclical ratio is outside canonical bounds")
    if item.value is not None and item.metric in {"book_to_bill", "cycle_adjusted_ev_to_earnings", "trough_interest_coverage"} and item.value < 0:
        raise CyclicalAdapterError("cyclical multiple cannot be negative")


def _checks(results: Sequence[CyclicalMetricResult]) -> tuple[CyclicalCheck, ...]:
    values = {row.metric: row.value for row in results if row.status == "available"}

    def check(name: str, threshold: float, direction: str, formula: str) -> CyclicalCheck:
        value = values.get(name)
        if value is None:
            return CyclicalCheck(name, "unavailable", None, "multiple", threshold, direction, formula, "required_cycle_evidence_unavailable")
        passed = value <= threshold if direction == "lower_is_better" else value >= threshold
        return CyclicalCheck(name, "available" if passed else "failed", value, "multiple", threshold, direction, formula, "threshold_satisfied" if passed else "cycle_distress_threshold_breached")

    return (
        check("cycle_adjusted_ev_to_earnings", 12.0, "lower_is_better", "cycle-adjusted enterprise value / normalised operating earnings"),
        check("trough_interest_coverage", 2.0, "higher_is_better", "trough operating earnings / interest expense"),
    )


def _history(rows: Sequence[CycleHistoryEvidence], decision: datetime) -> tuple[CycleHistoryResult, ...]:
    seen: set[str] = set()
    output: list[CycleHistoryResult] = []
    for row in sorted(rows, key=lambda item: (item.cycle_id, item.start_at, item.source_id)):
        start, end, known = _time(row.start_at), _time(row.end_at), _time(row.known_at)
        if (row.execution_allowed or not row.cycle_id.strip() or row.cycle_id in seen or row.phase not in {"trough_to_peak", "peak_to_trough", "completed_cycle"}
                or not row.source_id.strip() or row.source_authority not in {SourceAuthority.OFFICIAL, SourceAuthority.ISSUER}
                or start >= end or end > known or known > decision):
            raise CyclicalAdapterError("cycle-history lineage is invalid")
        seen.add(row.cycle_id)
        output.append(CycleHistoryResult(row.cycle_id, row.phase, _iso(start), _iso(end), _iso(known), row.source_id, row.source_authority.value))
    by_start = sorted(output, key=lambda row: row.start_at)
    if any(previous.end_at >= current.start_at for previous, current in zip(by_start, by_start[1:])):
        raise CyclicalAdapterError("cycle-history periods must be genuinely distinct and non-overlapping")
    return tuple(output)


def _scenario(name: str, value: object) -> CyclicalScenario:
    sign = -1.0 if name == "input_cost" else 1.0
    direction = "adverse_positive_is_negative" if name == "input_cost" else "signed_shock_flows_to_impact"
    formula = f"{sign:g} * shock_rate * exposed_amount / portfolio_base"
    if not isinstance(value, Mapping):
        return CyclicalScenario(name, "unavailable", None, "ratio", formula, {}, direction, "portfolio_currency", "portfolio_currency", "required_inputs_unavailable")
    try:
        inputs = {key: float(value[key]) for key in ("shock_rate", "exposed_amount", "portfolio_base")}
    except (KeyError, OverflowError, TypeError, ValueError):
        return CyclicalScenario(name, "unavailable", None, "ratio", formula, {}, direction, "portfolio_currency", "portfolio_currency", "required_inputs_unavailable")
    if (not all(_finite(number) for number in inputs.values()) or inputs["exposed_amount"] < 0
            or inputs["portfolio_base"] <= 0 or abs(inputs["shock_rate"]) > 1):
        return CyclicalScenario(name, "unavailable", None, "ratio", formula, {}, direction, "portfolio_currency", "portfolio_currency", "invalid_inputs")
    impact = sign * inputs["shock_rate"] * inputs["exposed_amount"] / inputs["portfolio_base"]
    return CyclicalScenario(name, "available", impact, "ratio", formula, inputs, direction, "portfolio_currency", "portfolio_currency", "deterministic_scenario")


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CyclicalAdapterError("timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise CyclicalAdapterError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _hash(value: object) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=lambda item: asdict(item)).encode()
    except (TypeError, ValueError) as exc:
        raise CyclicalAdapterError("projection is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _has_authority(value: object) -> bool:
    if isinstance(value, Mapping):
        return value.get("execution_allowed") is True or any(_has_authority(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_authority(item) for item in value)
    return False
