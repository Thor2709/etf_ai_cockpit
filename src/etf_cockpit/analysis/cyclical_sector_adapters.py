"""Typed, local-only energy, materials and industrial cyclical adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
_RATIO = frozenset({"spot_cycle_margin", "normalised_margin", "hedge_ratio", "book_to_bill", "backlog_quality", "aftermarket_mix", "utilisation", "capital_intensity", "customer_concentration", "project_concentration", "cycle_adjusted_ev_to_earnings", "trough_interest_coverage"})
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
}


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
    model = _model(context)
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
        available = item.value is not None and _finite(item.value)
        item_limits = tuple(sorted({*item.limitations, *(() if available else ("missing_value",))}))
        limitations.update(f"{item.metric}:{value}" for value in item_limits)
        results.append(CyclicalMetricResult(
            metric=item.metric, status="available" if available else "unavailable",
            value=float(item.value) if available else None, unit=item.unit,
            direction=formula.direction, period=item.period,
            reporting_standard=item.reporting_standard, jurisdiction=item.jurisdiction,
            business_model=model, source_id=item.source_id,
            source_authority=item.source_authority.value, as_of=_iso(_time(item.as_of)),
            known_at=_iso(_time(item.known_at)), definition=formula.definition,
            missing_policy=formula.missing_policy, limitations=item_limits,
            commodity_id=item.commodity_id,
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
    adequate = len({row.cycle_id for row in history}) >= 2
    if not adequate:
        limitations.add("cycle_history:insufficient_distinct_cycles")
    available = [row for row in results if row.status == "available"]
    confidence = min(1.0, len(available) / max(1, len(results))) if results else 0.0
    if not adequate:
        confidence *= 0.6
    confidence = round(confidence, 6)
    scenario_results = tuple(_scenario(name, scenarios.get(name)) for name in ("commodity_price", "input_cost", "demand_rate"))
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
        "status": "available" if available and len(available) == len(results) and adequate else "partial" if available else "unavailable",
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


def verify_cyclical_projection(value: CyclicalProjection | Mapping[str, object]) -> dict[str, object]:
    payload = projection_payload(value) if isinstance(value, CyclicalProjection) else dict(value)
    if (set(payload) != set(CyclicalProjection.__dataclass_fields__) or payload.get("contract") != CYCLICAL_CONTRACT
            or payload.get("execution_allowed") is not False or _has_authority(payload)
            or payload.get("result_hash") != cyclical_result_hash(payload)):
        raise CyclicalAdapterError("cyclical projection verification failed")
    return payload


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
    if (item.execution_allowed or item.business_model != model or not item.period.strip()
            or not item.reporting_standard.strip() or not item.jurisdiction.strip()
            or not item.source_id.strip() or _time(item.as_of) > decision or _time(item.known_at) > decision):
        raise CyclicalAdapterError("cyclical metric lineage is invalid")
    if item.metric in _OPERATIONAL and item.source_authority not in {SourceAuthority.OFFICIAL, SourceAuthority.ISSUER}:
        raise CyclicalAdapterError("operational metric requires issuer or official evidence")
    if model in {"energy", "materials"} and item.metric in _COMMODITY_SENSITIVE and not (item.commodity_id or "").strip():
        raise CyclicalAdapterError("commodity-sensitive metric requires an explicit commodity mapping")


def _checks(results: Sequence[CyclicalMetricResult]) -> tuple[CyclicalCheck, ...]:
    values = {row.metric: row.value for row in results if row.status == "available"}

    def check(name: str, threshold: float, direction: str, formula: str) -> CyclicalCheck:
        value = values.get(name)
        if value is None:
            return CyclicalCheck(name, "unavailable", None, "ratio", threshold, direction, formula, "required_cycle_evidence_unavailable")
        passed = value <= threshold if direction == "lower_is_better" else value >= threshold
        return CyclicalCheck(name, "available" if passed else "failed", value, "ratio", threshold, direction, formula, "threshold_satisfied" if passed else "cycle_distress_threshold_breached")

    return (
        check("cycle_adjusted_ev_to_earnings", 12.0, "lower_is_better", "cycle-adjusted enterprise value / normalised operating earnings"),
        check("trough_interest_coverage", 2.0, "higher_is_better", "trough operating earnings / interest expense"),
    )


def _history(rows: Sequence[CycleHistoryEvidence], decision: datetime) -> tuple[CycleHistoryResult, ...]:
    seen: set[str] = set()
    output: list[CycleHistoryResult] = []
    for row in sorted(rows, key=lambda item: (item.cycle_id, item.start_at, item.source_id)):
        start, end, known = _time(row.start_at), _time(row.end_at), _time(row.known_at)
        if (row.execution_allowed or not row.cycle_id.strip() or row.cycle_id in seen or not row.phase.strip()
                or not row.source_id.strip() or row.source_authority not in {SourceAuthority.OFFICIAL, SourceAuthority.ISSUER}
                or start > end or end > decision or known > decision):
            raise CyclicalAdapterError("cycle-history lineage is invalid")
        seen.add(row.cycle_id)
        output.append(CycleHistoryResult(row.cycle_id, row.phase, _iso(start), _iso(end), _iso(known), row.source_id, row.source_authority.value))
    return tuple(output)


def _scenario(name: str, value: object) -> CyclicalScenario:
    formula = "shock_rate * exposed_amount / portfolio_base"
    if not isinstance(value, Mapping):
        return CyclicalScenario(name, "unavailable", None, "ratio", formula, {}, "required_inputs_unavailable")
    try:
        inputs = {key: float(value[key]) for key in ("shock_rate", "exposed_amount", "portfolio_base")}
    except (KeyError, TypeError, ValueError):
        return CyclicalScenario(name, "unavailable", None, "ratio", formula, {}, "required_inputs_unavailable")
    if not all(_finite(number) for number in inputs.values()) or inputs["portfolio_base"] <= 0:
        return CyclicalScenario(name, "unavailable", None, "ratio", formula, {}, "invalid_inputs")
    impact = inputs["shock_rate"] * inputs["exposed_amount"] / inputs["portfolio_base"]
    return CyclicalScenario(name, "available", impact, "ratio", formula, inputs, "deterministic_scenario")


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
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


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
