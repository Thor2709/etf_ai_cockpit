"""Local-only software, semiconductor, healthcare and biotech adapters.

The adapter deliberately models disclosed operating evidence rather than
trying to turn sector-specific businesses into a generic P/E or leverage
score.  Missing disclosures remain rows in the projection, and milestone
outcomes are context-only low-authority evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Mapping, Sequence

from etf_cockpit.analysis.peer_cohorts import (
    AdapterDefinition,
    AdapterRegistry,
    PeerCohortError,
)
from etf_cockpit.data.classification import InstrumentContextV2
from etf_cockpit.data.contracts import SourceAuthority


INNOVATION_CONTRACT = "innovation-sector-adapter.v1"
INNOVATION_FORMULA_VERSION = "innovation-sector-formulas.v1"
_SOURCE_CONTRACT = "innovation-sector-source.v1"
_SOURCE_SCHEMA_VERSION = 1

_ADAPTERS = {
    "software": "sector:technology",
    "semiconductors": "sector:technology",
    "healthcare_pharma": "sector:healthcare",
    "biotech": "sector:healthcare",
}
_MODEL_SECTORS = {"software": "technology", "semiconductors": "technology", "healthcare_pharma": "healthcare", "biotech": "healthcare"}
_METRICS = {
    "software": frozenset({
        "recurring_revenue", "recurring_revenue_growth", "net_revenue_retention",
        "gross_margin", "free_cash_flow", "stock_compensation", "basic_shares",
        "diluted_shares", "dilution_rate",
    }),
    "semiconductors": frozenset({
        "inventory", "inventory_days", "utilisation", "capex", "gross_margin",
        "customer_concentration", "end_market_concentration", "cycle_phase",
    }),
    "healthcare_pharma": frozenset({
        "product_concentration", "patent_exclusivity_years", "r_and_d",
        "reimbursement_exposure",
    }),
    "biotech": frozenset({
        "cash_balance", "operating_cash_burn", "cash_runway_months",
        "shares_outstanding", "potential_dilution_shares", "dilution_rate",
    }),
}
_LOWER_IS_BETTER = frozenset({
    "stock_compensation", "dilution_rate", "inventory", "inventory_days",
    "capex", "customer_concentration", "end_market_concentration",
    "product_concentration", "r_and_d", "reimbursement_exposure",
    "operating_cash_burn", "potential_dilution_shares",
})
_RATIO_METRICS = frozenset({
    "recurring_revenue_growth", "net_revenue_retention", "gross_margin",
    "utilisation", "customer_concentration", "end_market_concentration",
    "product_concentration", "reimbursement_exposure", "dilution_rate",
})
_SIGNED_METRICS = frozenset({"free_cash_flow", "recurring_revenue_growth"})
_BOUNDED_METRICS = frozenset({
    "gross_margin", "utilisation", "customer_concentration", "end_market_concentration",
    "product_concentration", "reimbursement_exposure", "dilution_rate",
})
_UNITS = {
    "recurring_revenue": ("currency",), "recurring_revenue_growth": ("ratio", "percent"),
    "net_revenue_retention": ("ratio", "percent"), "gross_margin": ("ratio", "percent"),
    "free_cash_flow": ("currency",), "stock_compensation": ("currency",),
    "basic_shares": ("shares",), "diluted_shares": ("shares",), "dilution_rate": ("ratio", "percent"),
    "inventory": ("currency", "quantity"), "inventory_days": ("days",),
    "utilisation": ("ratio", "percent"), "capex": ("currency",),
    "customer_concentration": ("ratio", "percent"), "end_market_concentration": ("ratio", "percent"),
    "cycle_phase": ("label",), "product_concentration": ("ratio", "percent"),
    "patent_exclusivity_years": ("years",), "r_and_d": ("currency",),
    "reimbursement_exposure": ("ratio", "percent"), "cash_balance": ("currency",),
    "operating_cash_burn": ("currency_per_month", "currency_per_year"),
    "cash_runway_months": ("months",), "shares_outstanding": ("shares",),
    "potential_dilution_shares": ("shares",),
}
_DEFINITIONS = {
    "recurring_revenue": "issuer-disclosed recurring or subscription revenue",
    "net_revenue_retention": "issuer-disclosed revenue retention, only when disclosed",
    "cash_runway_months": "cash balance divided by normalised operating cash burn",
    "dilution_rate": "prospective incremental shares divided by pre-dilution shares",
    "cycle_phase": "issuer-described semiconductor demand or supply cycle phase",
}
_GENERIC_FALLBACKS = frozenset({"pe_ratio", "generic_pe", "leverage", "enterprise_value_to_ebitda", "fcf_yield"})
_ALLOWED_AUTHORITIES = frozenset({SourceAuthority.OFFICIAL, SourceAuthority.ISSUER, SourceAuthority.MANUAL})
_EVENT_TYPES = frozenset({
    "pipeline_stage", "trial_milestone", "regulatory_milestone", "patent_exclusivity",
    "product_concentration", "reimbursement_decision",
})


class InnovationAdapterError(ValueError):
    """Raised when sector evidence violates the fail-closed contract."""


@dataclass(frozen=True)
class InnovationFormulaDefinition:
    metric: str
    business_model: str
    direction: str
    allowed_units: tuple[str, ...]
    definition: str
    formula_version: str = INNOVATION_FORMULA_VERSION
    missing_policy: str = "unavailable_not_disclosed"
    parent_fallback: str = "stock:broad"
    execution_allowed: bool = False


@dataclass(frozen=True)
class InnovationMetricEvidence:
    metric: str
    value: float | str | None
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
    applicable: bool = True
    execution_allowed: bool = False


@dataclass(frozen=True)
class InnovationEventEvidence:
    event_id: str
    event_type: str
    title: str
    stage: str | None
    event_date: str
    period: str
    source_id: str
    source_authority: SourceAuthority
    as_of: str
    known_at: str
    concentration: float | None = None
    outcome_probability: float | None = None
    limitations: tuple[str, ...] = ()
    execution_allowed: bool = False


@dataclass(frozen=True)
class InnovationMetricResult:
    metric: str
    status: str
    value: float | str | None
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
    formula_version: str = INNOVATION_FORMULA_VERSION
    execution_allowed: bool = False


@dataclass(frozen=True)
class InnovationEventResult:
    event_id: str
    event_type: str
    title: str
    stage: str | None
    event_date: str
    period: str
    source_id: str
    source_authority: str
    as_of: str
    known_at: str
    concentration: float | None
    outcome_probability: None
    probability_status: str
    limitations: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class InnovationCheck:
    check: str
    status: str
    value: float | None
    unit: str
    formula: str
    reason_code: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class InnovationProjection:
    contract: str
    status: str
    instrument_id: str
    business_model: str
    adapter_id: str
    adapter_version: str
    variant_path: tuple[str, ...]
    parent_fallback: str
    metrics: tuple[InnovationMetricResult, ...]
    events: tuple[InnovationEventResult, ...]
    checks: tuple[InnovationCheck, ...]
    aggregate_confidence: float
    valuation_status: str
    rationale: tuple[str, ...]
    concentration_timeline: tuple[Mapping[str, object], ...]
    milestone_timeline: tuple[Mapping[str, object], ...]
    lineage: Mapping[str, object]
    limitations: tuple[str, ...]
    source_payload: Mapping[str, object]
    result_hash: str
    execution_allowed: bool = False


def innovation_adapter_definitions() -> tuple[AdapterDefinition, ...]:
    """Register sector parents once; business-model variants remain local."""

    return (
        AdapterDefinition("sector:technology", "1", frozenset().union(*(_METRICS["software"], _METRICS["semiconductors"]))),
        AdapterDefinition("sector:healthcare", "1", frozenset().union(*(_METRICS["healthcare_pharma"], _METRICS["biotech"]))),
    )


def innovation_formula_registry() -> tuple[InnovationFormulaDefinition, ...]:
    return tuple(
        InnovationFormulaDefinition(
            metric=metric,
            business_model=model,
            direction="lower_is_better" if metric in _LOWER_IS_BETTER else "higher_is_better",
            allowed_units=_UNITS.get(metric, ("currency",)),
            definition=_DEFINITIONS.get(metric, "issuer-reported sector-specific operating measure"),
            parent_fallback=f"sector:{_MODEL_SECTORS[model]}",
        )
        for model in sorted(_METRICS)
        for metric in sorted(_METRICS[model])
    )


def build_innovation_projection(
    context: InstrumentContextV2,
    evidence: Sequence[InnovationMetricEvidence],
    *,
    events: Sequence[InnovationEventEvidence] = (),
    registry: AdapterRegistry,
    decision_time: str,
) -> InnovationProjection:
    decision = _time(decision_time)
    effective = _time(context.effective_at)
    model = _model(context)
    if context.instrument_type != "stock" or context.asset_class != "equity":
        raise InnovationAdapterError("innovation adapter requires a classified equity security")
    if context.execution_allowed or context.classification_status in {"unresolved", "manual_review"}:
        raise InnovationAdapterError("classification must be resolved and non-executable")
    if _time(context.decision_time) != decision or effective > decision:
        raise InnovationAdapterError("classification must match the exact decision cutoff")
    try:
        selection = registry.select(context)
    except PeerCohortError as exc:
        raise InnovationAdapterError(str(exc)) from exc
    expected_adapter = _ADAPTERS[model]
    if selection.adapter_id != expected_adapter or selection.fallback:
        raise InnovationAdapterError("innovation classification route is incompatible")
    formulas = {row.metric: row for row in innovation_formula_registry() if row.business_model == model}
    source = _source_payload(context, evidence, events, decision)
    results: list[InnovationMetricResult] = []
    seen: set[str] = set()
    limitations: set[str] = set()
    for item in sorted(evidence, key=lambda row: (row.metric, row.known_at, row.source_id)):
        if item.metric in _GENERIC_FALLBACKS:
            raise InnovationAdapterError(f"generic valuation fallback {item.metric!r} is forbidden")
        _validate_metric(item, model, formulas, decision, effective)
        if item.metric in seen:
            raise InnovationAdapterError("duplicate innovation metric evidence")
        seen.add(item.metric)
        formula = formulas[item.metric]
        if item.unit not in formula.allowed_units or (item.direction is not None and item.direction != formula.direction):
            raise InnovationAdapterError("innovation metric unit or direction is incompatible")
        fatal = any(value.casefold().split(":", 1)[0] in {"stale", "conflicted", "invalid", "unsupported"} for value in item.limitations)
        available = item.applicable and not fatal and item.value is not None and _valid_value(item.value, item.unit, item.metric)
        item_limits = tuple(sorted({*item.limitations, *(() if available or not item.applicable else ("missing_value",))}))
        if item_limits:
            limitations.update(f"{item.metric}:{value}" for value in item_limits)
        results.append(_metric_result(item, formula, model, available, item_limits))
    for metric in sorted(set(formulas) - seen):
        formula = formulas[metric]
        results.append(InnovationMetricResult(
            metric, "unavailable", None, formula.allowed_units[0], formula.direction,
            "unavailable", "unavailable", "unavailable", model, "unavailable", "unavailable",
            _iso(decision), _iso(decision), formula.definition, formula.missing_policy,
            ("not_disclosed",),
        ))
        limitations.add(f"{metric}:not_disclosed")
    results = _derived_sector_metrics(model, results, limitations)
    event_results = _event_results(events, decision, effective, limitations)
    checks = _checks(model, results, limitations)
    concentration = tuple(
        {"event_id": row.event_id, "event_date": row.event_date, "event_type": row.event_type, "concentration": row.concentration, "source_id": row.source_id, "source_authority": row.source_authority}
        for row in event_results if row.concentration is not None
    )
    milestones = tuple(
        {"event_id": row.event_id, "event_date": row.event_date, "event_type": row.event_type, "title": row.title, "stage": row.stage, "source_id": row.source_id, "source_authority": row.source_authority, "probability_status": row.probability_status}
        for row in event_results if row.event_type in {"pipeline_stage", "trial_milestone", "regulatory_milestone", "patent_exclusivity", "reimbursement_decision"}
    )
    available = [row for row in results if row.status == "available"]
    applicable = [row for row in results if row.status != "inapplicable"]
    confidence = round(len(available) / max(1, len(applicable)), 6)
    if any(row.status in {"partial", "unavailable"} for row in checks):
        confidence = round(confidence * 0.8, 6)
    if any(row.outcome_probability is None and row.probability_status != "not_applicable" for row in event_results):
        limitations.add("event_outcomes:low_authority_not_used")
        confidence = round(confidence * 0.9, 6)
    status = "available" if applicable and len(available) == len(applicable) and all(row.status == "available" for row in checks) else "partial" if available else "unavailable"
    lineage = {
        "classification_version": context.version_id,
        "classification_token": context.score_invalidation_token,
        "adapter_lineage": selection.lineage_hash,
        "formula_version": INNOVATION_FORMULA_VERSION,
        "decision_time": _iso(decision),
        "sources": tuple(sorted({row.source_id for row in results if row.source_id != "unavailable"} | {row.source_id for row in event_results})),
    }
    provisional = {
        "contract": INNOVATION_CONTRACT, "status": status, "instrument_id": context.instrument_id,
        "business_model": model, "adapter_id": selection.adapter_id, "adapter_version": selection.adapter_version,
        "variant_path": (f"innovation:{model}:{(context.operating_country or 'global').lower()}", f"innovation:{model}", "innovation"),
        "parent_fallback": f"sector:{_MODEL_SECTORS[model]}", "metrics": tuple(sorted(results, key=lambda row: row.metric)),
        "events": tuple(event_results), "checks": tuple(checks), "aggregate_confidence": confidence,
        "valuation_status": "confidence_capped_inapplicable",
        "rationale": _rationale(model), "concentration_timeline": concentration,
        "milestone_timeline": milestones, "lineage": lineage,
        "limitations": tuple(sorted(limitations)), "source_payload": source, "execution_allowed": False,
    }
    return InnovationProjection(**provisional, result_hash=_hash(provisional))


def unavailable_innovation_projection(instrument_id: str, reason_code: str = "innovation_evidence_unavailable") -> dict[str, object]:
    return {"contract": INNOVATION_CONTRACT, "status": "unavailable", "instrument_id": str(instrument_id), "reason_code": reason_code, "metrics": (), "events": (), "checks": (), "concentration_timeline": (), "milestone_timeline": (), "rationale": (), "lineage": {}, "limitations": ("local innovation evidence unavailable",), "execution_allowed": False}


def projection_payload(projection: InnovationProjection | Mapping[str, object]) -> dict[str, object]:
    return asdict(projection) if isinstance(projection, InnovationProjection) else dict(projection)


def innovation_result_hash(value: InnovationProjection | Mapping[str, object]) -> str:
    payload = projection_payload(value)
    payload.pop("result_hash", None)
    return _hash(payload)


def innovation_source_digest(value: Mapping[str, object]) -> str:
    return _hash(value)


def verify_innovation_projection(value: InnovationProjection | Mapping[str, object], *, expected_source_digest: str) -> dict[str, object]:
    payload = projection_payload(value)
    if not isinstance(payload, dict) or payload.get("contract") != INNOVATION_CONTRACT or payload.get("execution_allowed") is not False:
        raise InnovationAdapterError("innovation projection verification failed")
    if payload.get("result_hash") != innovation_result_hash(payload) or innovation_source_digest(payload.get("source_payload", {})) != expected_source_digest:
        raise InnovationAdapterError("innovation projection digest verification failed")
    _verify_source_consistency(payload)
    if _has_authority(payload):
        raise InnovationAdapterError("innovation projection contains execution authority")
    return payload


def _metric_result(item: InnovationMetricEvidence, formula: InnovationFormulaDefinition, model: str, available: bool, limitations: tuple[str, ...]) -> InnovationMetricResult:
    value = item.value if available else None
    if isinstance(value, float) and not math.isfinite(value):
        value = None
    return InnovationMetricResult(
        item.metric, "available" if available else "inapplicable" if not item.applicable else "unavailable", value,
        item.unit, formula.direction, item.period, item.reporting_standard, item.jurisdiction, model,
        item.source_id, item.source_authority.value, _iso(_time(item.as_of)), _iso(_time(item.known_at)),
        formula.definition, formula.missing_policy, limitations,
    )


def _derived_sector_metrics(model: str, rows: list[InnovationMetricResult], limitations: set[str]) -> list[InnovationMetricResult]:
    if model == "software":
        return _derived_software_metrics(rows, limitations)
    if model != "biotech":
        return rows
    by_metric = {row.metric: row for row in rows}
    cash, burn, runway = by_metric["cash_balance"], by_metric["operating_cash_burn"], by_metric["cash_runway_months"]
    if cash.status == "available" and burn.status == "available" and isinstance(cash.value, (int, float)) and isinstance(burn.value, (int, float)) and float(burn.value) > 0:
        monthly = float(burn.value) if burn.unit == "currency_per_month" else float(burn.value) / 12
        derived = float(cash.value) / monthly
        if runway.status == "available" and isinstance(runway.value, (int, float)) and not math.isclose(float(runway.value), derived, rel_tol=0.1, abs_tol=0.25):
            limitations.add("cash_runway_reconciliation:statement_mismatch")
            rows[rows.index(runway)] = replace(runway, status="unavailable", value=None, limitations=tuple(sorted({*runway.limitations, "statement_mismatch"})))
        elif runway.status != "available":
            rows[rows.index(runway)] = replace(runway, status="available", value=round(derived, 6), unit="months", source_id="derived:cash_runway", source_authority="derived_statement_evidence", as_of=max(cash.as_of, burn.as_of), known_at=max(cash.known_at, burn.known_at), limitations=("derived_from_cash_and_burn",))
    else:
        limitations.add("cash_runway_reconciliation:inputs_missing")
    shares = by_metric["shares_outstanding"]
    potential = by_metric["potential_dilution_shares"]
    dilution = by_metric["dilution_rate"]
    if shares.status == "available" and potential.status == "available" and isinstance(shares.value, (int, float)) and isinstance(potential.value, (int, float)) and float(shares.value) > 0 and float(potential.value) >= 0:
        derived_rate = float(potential.value) / float(shares.value)
        if dilution.status == "available" and isinstance(dilution.value, (int, float)) and not math.isclose(float(dilution.value), derived_rate, rel_tol=0.1, abs_tol=0.005):
            limitations.add("dilution_reconciliation:statement_mismatch")
            rows[rows.index(dilution)] = replace(dilution, status="unavailable", value=None, limitations=tuple(sorted({*dilution.limitations, "statement_mismatch"})))
        elif dilution.status != "available":
            rows[rows.index(dilution)] = replace(dilution, status="available", value=round(derived_rate, 6), unit="ratio", source_id="derived:dilution_rate", source_authority="derived_statement_evidence", as_of=max(shares.as_of, potential.as_of), known_at=max(shares.known_at, potential.known_at), limitations=("derived_from_share_counts",))
    else:
        limitations.add("dilution_reconciliation:inputs_missing")
    return rows


def _derived_software_metrics(rows: list[InnovationMetricResult], limitations: set[str]) -> list[InnovationMetricResult]:
    by_metric = {row.metric: row for row in rows}
    basic, diluted, dilution = (
        by_metric["basic_shares"], by_metric["diluted_shares"], by_metric["dilution_rate"]
    )
    if (
        basic.status == "available" and diluted.status == "available"
        and isinstance(basic.value, (int, float)) and isinstance(diluted.value, (int, float))
        and float(basic.value) > 0 and float(diluted.value) >= float(basic.value)
    ):
        derived_rate = (float(diluted.value) - float(basic.value)) / float(basic.value)
        if (
            dilution.status == "available"
            and isinstance(dilution.value, (int, float))
            and not math.isclose(float(dilution.value), derived_rate, rel_tol=0.1, abs_tol=0.005)
        ):
            limitations.add("dilution_reconciliation:statement_mismatch")
            rows[rows.index(dilution)] = replace(
                dilution, status="unavailable", value=None,
                limitations=tuple(sorted({*dilution.limitations, "statement_mismatch"})),
            )
        elif dilution.status != "available":
            rows[rows.index(dilution)] = replace(
                dilution, status="available", value=round(derived_rate, 6), unit="ratio",
                source_id="derived:dilution_rate", source_authority="derived_share_counts",
                as_of=max(basic.as_of, diluted.as_of), known_at=max(basic.known_at, diluted.known_at),
                limitations=("derived_from_share_counts",),
            )
    elif basic.status == "available" and diluted.status == "available":
        limitations.add("dilution_reconciliation:invalid_share_order")
        rows[rows.index(dilution)] = replace(
            dilution, status="unavailable", value=None,
            limitations=tuple(sorted({*dilution.limitations, "invalid_share_order"})),
        )
    else:
        limitations.add("dilution_reconciliation:inputs_missing")
    return rows


def _checks(model: str, rows: Sequence[InnovationMetricResult], limitations: set[str]) -> tuple[InnovationCheck, ...]:
    if model == "software":
        dilution = {row.metric: row for row in rows}["dilution_rate"]
        reconciled = dilution.status == "available" and not any(
            item.startswith("dilution_reconciliation:")
            for item in limitations
        )
        return (InnovationCheck(
            "dilution_reconciliation", "available" if reconciled else "partial",
            float(dilution.value) if isinstance(dilution.value, (int, float)) else None,
            "ratio", "(diluted_shares - basic_shares) / basic_shares",
            "reconciled" if reconciled else "inputs_missing_or_mismatch",
        ),)
    if model != "biotech":
        return ()
    by_metric = {row.metric: row for row in rows}
    checks = []
    runway = by_metric["cash_runway_months"]
    runway_reconciled = runway.status == "available" and not any(
        item.startswith("cash_runway_reconciliation:") for item in limitations
    )
    checks.append(InnovationCheck("cash_runway_reconciliation", "available" if runway_reconciled else "partial", float(runway.value) if isinstance(runway.value, (int, float)) else None, "months", "cash_balance / monthly_operating_cash_burn", "reconciled" if runway_reconciled else "inputs_missing_or_mismatch"))
    dilution = by_metric["dilution_rate"]
    dilution_reconciled = dilution.status == "available" and not any(
        item.startswith("dilution_reconciliation:") for item in limitations
    )
    checks.append(InnovationCheck("dilution_reconciliation", "available" if dilution_reconciled else "partial", float(dilution.value) if isinstance(dilution.value, (int, float)) else None, "ratio", "potential_dilution_shares / shares_outstanding", "reconciled" if dilution_reconciled else "inputs_missing_or_mismatch"))
    return tuple(checks)


def _event_results(events: Sequence[InnovationEventEvidence], decision: datetime, effective: datetime, limitations: set[str]) -> tuple[InnovationEventResult, ...]:
    results = []
    seen: set[str] = set()
    for item in sorted(events, key=lambda row: (row.event_date, row.event_id)):
        if item.event_id in seen or not item.event_id.strip() or item.event_type not in _EVENT_TYPES:
            raise InnovationAdapterError("innovation event is invalid or duplicated")
        seen.add(item.event_id)
        _validate_event(item, decision, effective)
        probability_status = "low_authority_not_used" if item.outcome_probability is not None else "not_applicable"
        if item.outcome_probability is not None:
            limitations.add(f"{item.event_id}:low_authority_outcome_probability")
        event_limits = {*item.limitations}
        if item.outcome_probability is not None:
            event_limits.add("outcome_probability_not_used")
        results.append(InnovationEventResult(item.event_id, item.event_type, item.title.strip(), item.stage, _iso(_time(item.event_date)), item.period, item.source_id, item.source_authority.value, _iso(_time(item.as_of)), _iso(_time(item.known_at)), item.concentration, None, probability_status, tuple(sorted(event_limits))))
    return tuple(results)


def _validate_metric(item: InnovationMetricEvidence, model: str, formulas: Mapping[str, InnovationFormulaDefinition], decision: datetime, effective: datetime) -> None:
    if item.business_model != model or item.metric not in formulas or not item.period.strip() or not item.reporting_standard.strip() or not item.jurisdiction.strip() or not item.source_id.strip() or item.execution_allowed or item.source_authority not in _ALLOWED_AUTHORITIES:
        raise InnovationAdapterError("innovation metric lineage or authority is invalid")
    if _time(item.known_at) > decision or _time(item.as_of) > effective:
        raise InnovationAdapterError("innovation metric is future-known or future-effective")
    if item.metric in _GENERIC_FALLBACKS:
        raise InnovationAdapterError("generic valuation fallback is forbidden")


def _validate_event(item: InnovationEventEvidence, decision: datetime, effective: datetime) -> None:
    if not item.title.strip() or not item.period.strip() or not item.source_id.strip() or item.execution_allowed or item.source_authority not in _ALLOWED_AUTHORITIES:
        raise InnovationAdapterError("innovation event lineage or authority is invalid")
    _time(item.event_date)
    if _time(item.known_at) > decision or _time(item.as_of) > effective:
        raise InnovationAdapterError("innovation event is future-known or future-effective")
    if item.outcome_probability is not None and (not math.isfinite(float(item.outcome_probability)) or not 0 <= float(item.outcome_probability) <= 1):
        raise InnovationAdapterError("event outcome probability is invalid")
    if item.concentration is not None and (not math.isfinite(float(item.concentration)) or not 0 <= float(item.concentration) <= 1):
        raise InnovationAdapterError("event concentration is invalid")


def _model(context: InstrumentContextV2) -> str:
    sector = (context.sector or "").casefold().replace("&", "and")
    tags = " ".join((*context.business_model_tags, *context.strategy_labels, context.industry or "")).casefold()
    if sector == "technology":
        return "semiconductors" if any(token in tags for token in ("semiconductor", "semis", "chip", "foundry")) else "software" if any(token in tags for token in ("software", "saas", "cloud")) else (_raise_model("technology business model"))
    if sector == "healthcare":
        return "biotech" if any(token in tags for token in ("biotech", "biotechnology", "biopharma")) else "healthcare_pharma" if any(token in tags for token in ("pharma", "healthcare", "therapeutic", "medical")) else (_raise_model("healthcare business model"))
    raise InnovationAdapterError("innovation adapter requires technology or healthcare classification")


def _raise_model(message: str) -> str:
    raise InnovationAdapterError(message)


def _rationale(model: str) -> tuple[str, ...]:
    return {
        "software": ("recurring economics and retention are shown only when issuer-disclosed", "gross margin, free cash flow, stock compensation and dilution remain separate", "generic valuation is confidence-capped as inapplicable"),
        "semiconductors": ("inventory, utilisation, capex and gross margin are cycle-aware operating evidence", "customer and end-market concentration remain dated disclosures", "cycle phase is descriptive and does not authorize execution"),
        "healthcare_pharma": ("product concentration, patent/exclusivity, R&D and reimbursement are source-linked", "milestone and concentration timelines remain contextual evidence", "generic valuation is confidence-capped as inapplicable"),
        "biotech": ("cash runway and prospective dilution reconcile to disclosed inputs when possible", "pipeline, trial and regulatory timing remain dated context-only milestones", "event outcome probabilities are explicitly low authority and excluded from scores"),
    }[model]


def _source_payload(context: InstrumentContextV2, evidence: Sequence[InnovationMetricEvidence], events: Sequence[InnovationEventEvidence], decision: datetime) -> dict[str, object]:
    return {"contract": _SOURCE_CONTRACT, "schema_version": _SOURCE_SCHEMA_VERSION, "context": asdict(context), "decision_time": _iso(decision), "evidence": tuple(asdict(item) for item in sorted(evidence, key=lambda row: (row.metric, row.known_at, row.source_id))), "events": tuple(asdict(item) for item in sorted(events, key=lambda row: (row.event_date, row.event_id)))}


def _verify_source_consistency(payload: Mapping[str, object]) -> None:
    source = payload.get("source_payload")
    if not isinstance(source, Mapping) or source.get("contract") != _SOURCE_CONTRACT:
        raise InnovationAdapterError("innovation source payload is invalid")
    source_rows = {
        str(row.get("metric")): row
        for row in source.get("evidence", ())
        if isinstance(row, Mapping) and row.get("metric")
    }
    for row in payload.get("metrics", ()):
        if not isinstance(row, Mapping):
            raise InnovationAdapterError("innovation metric payload is invalid")
        if row.get("status") != "available":
            if row.get("value") is not None:
                raise InnovationAdapterError("unavailable innovation metric contains a value")
            continue
        source_row = source_rows.get(str(row.get("metric")))
        if str(row.get("source_id", "")).startswith("derived:"):
            continue
        if source_row is None or any(source_row.get(field) != row.get(field) for field in ("source_id", "unit", "period", "as_of", "known_at")) or source_row.get("value") != row.get("value"):
            raise InnovationAdapterError("innovation projection does not match detached source evidence")


def _valid_value(value: float | str, unit: str, metric: str) -> bool:
    if unit == "label":
        return isinstance(value, str) and bool(value.strip())
    try:
        number = float(value)
        if not math.isfinite(number):
            return False
        if metric in _BOUNDED_METRICS:
            return 0 <= number <= (1 if unit == "ratio" else 100)
        if metric not in _SIGNED_METRICS and number < 0:
            return False
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise InnovationAdapterError("innovation timestamps are invalid") from exc
    if parsed.tzinfo is None:
        raise InnovationAdapterError("innovation timestamps require timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: object) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=lambda item: item.value if isinstance(item, SourceAuthority) else asdict(item)).encode()
    except (TypeError, ValueError) as exc:
        raise InnovationAdapterError("innovation projection is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _has_authority(value: object) -> bool:
    if isinstance(value, Mapping):
        return value.get("execution_allowed") is True or any(_has_authority(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_authority(item) for item in value)
    return False


__all__ = [
    "INNOVATION_CONTRACT", "INNOVATION_FORMULA_VERSION", "InnovationAdapterError",
    "InnovationEventEvidence", "InnovationEventResult", "InnovationFormulaDefinition",
    "InnovationMetricEvidence", "InnovationMetricResult", "InnovationProjection",
    "build_innovation_projection", "innovation_adapter_definitions", "innovation_formula_registry",
    "innovation_result_hash", "innovation_source_digest", "projection_payload",
    "unavailable_innovation_projection", "verify_innovation_projection",
]
