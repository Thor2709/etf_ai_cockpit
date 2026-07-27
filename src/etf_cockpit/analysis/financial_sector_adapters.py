"""Typed, local-only financial-institution metrics and deterministic stresses."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


FINANCIAL_ADAPTER_CONTRACT = "financial-institution-adapter.v1"
FINANCIAL_FORMULA_VERSION = "financial-formulas.v1"
FINANCIAL_ADAPTER_ID = "sector:financials"
_PROHIBITED = frozenset(
    {
        "industrial_leverage",
        "free_cash_flow",
        "fcf",
        "dcf_value",
        "dcf",
        "altman_z",
        "altman_score",
        "pe_ratio",
        "generic_pe",
    }
)
_METRICS = {
    "bank": frozenset(
        {
            "cet1_ratio",
            "total_capital_ratio",
            "tangible_book_value",
            "net_interest_margin",
            "cost_income_ratio",
            "loan_growth",
            "deposit_growth",
            "loan_deposit_ratio",
            "npl_ratio",
            "provision_ratio",
            "npl_coverage_ratio",
            "liquidity_coverage_ratio",
            "rote",
        }
    ),
    "insurer": frozenset(
        {
            "combined_ratio",
            "loss_ratio",
            "expense_ratio",
            "solvency_capital_ratio",
            "reserve_adequacy",
            "premium_growth",
            "investment_yield",
            "reinsurance_exposure",
        }
    ),
    "diversified": frozenset(
        {
            "funding_cost",
            "credit_loss_ratio",
            "capital_ratio",
            "fee_income_mix",
            "interest_income_mix",
        }
    ),
}
_DIRECTIONS = {
    "cost_income_ratio": "lower_is_better",
    "loan_deposit_ratio": "lower_is_better",
    "npl_ratio": "lower_is_better",
    "combined_ratio": "lower_is_better",
    "loss_ratio": "lower_is_better",
    "expense_ratio": "lower_is_better",
    "reinsurance_exposure": "lower_is_better",
    "funding_cost": "lower_is_better",
    "credit_loss_ratio": "lower_is_better",
}
_REGULATORY = frozenset(
    {
        "cet1_ratio",
        "total_capital_ratio",
        "liquidity_coverage_ratio",
        "solvency_capital_ratio",
        "capital_ratio",
    }
)


class FinancialAdapterError(ValueError):
    """Raised when financial evidence or classification is incompatible."""


@dataclass(frozen=True)
class FinancialFormulaDefinition:
    metric: str
    business_model: str
    direction: str
    allowed_units: tuple[str, ...]
    formula_version: str = FINANCIAL_FORMULA_VERSION
    missing_policy: str = "unavailable"
    execution_allowed: bool = False


@dataclass(frozen=True)
class FinancialMetricEvidence:
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
    limitations: tuple[str, ...] = ()
    direction: str | None = None
    execution_allowed: bool = False


@dataclass(frozen=True)
class FinancialMetricResult:
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
    confidence: float
    authority_label: str
    limitations: tuple[str, ...]
    formula_version: str = FINANCIAL_FORMULA_VERSION
    execution_allowed: bool = False


@dataclass(frozen=True)
class FinancialStressResult:
    shock: str
    status: str
    shock_size: float | None
    capital_impact: float | None
    unit: str
    formula: str
    inputs: Mapping[str, float]
    reason_code: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class FinancialInstitutionProjection:
    contract: str
    status: str
    instrument_id: str
    business_model: str
    adapter_id: str
    adapter_version: str
    variant_path: tuple[str, ...]
    parent_fallback: str
    aggregate_confidence: float
    authority_status: str
    metrics: tuple[FinancialMetricResult, ...]
    stresses: tuple[FinancialStressResult, ...]
    solvency_asset_quality_history: tuple[Mapping[str, object], ...]
    rationale: tuple[str, ...]
    lineage: Mapping[str, object]
    limitations: tuple[str, ...]
    result_hash: str
    execution_allowed: bool = False


def financial_adapter_definition() -> AdapterDefinition:
    return AdapterDefinition(
        FINANCIAL_ADAPTER_ID,
        "1",
        frozenset().union(*_METRICS.values()),
    )


def financial_formula_registry() -> tuple[FinancialFormulaDefinition, ...]:
    """Return the complete typed and versioned formula/applicability registry."""

    return tuple(
        FinancialFormulaDefinition(
            metric=metric,
            business_model=model,
            direction=_DIRECTIONS.get(metric, "higher_is_better"),
            allowed_units=(
                ("currency_per_share",)
                if metric == "tangible_book_value"
                else ("ratio", "percent")
            ),
        )
        for model, metrics in sorted(_METRICS.items())
        for metric in sorted(metrics)
    )


def build_financial_institution_projection(
    context: InstrumentContextV2,
    evidence: Sequence[FinancialMetricEvidence],
    *,
    registry: AdapterRegistry,
    decision_time: str,
    shocks: Mapping[str, object],
) -> FinancialInstitutionProjection:
    """Build reproducible evidence without generic industrial substitutions."""

    model = _business_model(context)
    try:
        selection = registry.select(context)
    except PeerCohortError as exc:
        raise FinancialAdapterError(str(exc)) from exc
    if context.sector != "financials" or selection.adapter_id != FINANCIAL_ADAPTER_ID:
        raise FinancialAdapterError("financial adapter requires classified financials")
    decision = _time(decision_time)
    if (
        context.execution_allowed
        or _time(context.decision_time) != decision
        or context.classification_status in {"unresolved", "manual_review"}
    ):
        raise FinancialAdapterError(
            "financial classification must match the exact decision cutoff"
        )
    formulas = {
        item.metric: item
        for item in financial_formula_registry()
        if item.business_model == model
    }
    allowed = frozenset(formulas)
    results: list[FinancialMetricResult] = []
    limitations: set[str] = set()
    seen: set[str] = set()
    for item in sorted(
        evidence, key=lambda row: (row.metric, row.known_at, row.source_id)
    ):
        _validate_evidence(item, model, decision)
        if item.metric in _PROHIBITED:
            limitations.add(f"{item.metric}:inapplicable")
            continue
        if item.metric not in allowed:
            raise FinancialAdapterError(
                f"metric {item.metric!r} is invalid for {model}"
            )
        if item.metric in seen:
            raise FinancialAdapterError("duplicate financial metric evidence")
        seen.add(item.metric)
        formula = formulas[item.metric]
        if item.unit not in formula.allowed_units or (
            item.direction is not None and item.direction != formula.direction
        ):
            raise FinancialAdapterError(
                f"metric {item.metric!r} unit or direction is incompatible"
            )
        confidence = min(1.0, item.source_authority.rank / 100)
        if item.metric in _REGULATORY and item.source_authority not in {
            SourceAuthority.OFFICIAL,
            SourceAuthority.ISSUER,
        }:
            confidence = min(confidence, 0.55)
            limitations.add(f"{item.metric}:weak_regulatory_authority")
        available = item.value is not None and _finite(item.value)
        item_limitations = tuple(
            sorted(
                {
                    *item.limitations,
                    *(() if available else ("missing_value",)),
                }
            )
        )
        limitations.update(f"{item.metric}:{value}" for value in item_limitations)
        results.append(
            FinancialMetricResult(
                metric=item.metric,
                status="available" if available else "unavailable",
                value=float(item.value) if available else None,
                unit=item.unit,
                direction=formula.direction,
                period=item.period,
                reporting_standard=item.reporting_standard,
                jurisdiction=item.jurisdiction,
                business_model=model,
                source_id=item.source_id,
                source_authority=item.source_authority.value,
                as_of=_iso(_time(item.as_of)),
                known_at=_iso(_time(item.known_at)),
                confidence=confidence,
                authority_label=(
                    "high"
                    if confidence >= 0.8
                    and item.source_authority
                    in {SourceAuthority.OFFICIAL, SourceAuthority.ISSUER}
                    else "limited"
                ),
                limitations=item_limitations,
            )
        )
    missing = sorted(allowed - seen)
    limitations.update(f"{metric}:missing" for metric in missing)
    stress_results = tuple(
        _stress(name, shocks.get(name)) for name in ("credit_loss", "funding", "market")
    )
    available_results = [item for item in results if item.status == "available"]
    critical = {
        "bank": {"cet1_ratio", "total_capital_ratio"},
        "insurer": {"solvency_capital_ratio"},
        "diversified": {"capital_ratio"},
    }[model]
    critical_results = [item for item in results if item.metric in critical]
    critical_usable = [
        item
        for item in critical_results
        if item.status == "available" and item.authority_label == "high"
    ]
    aggregate_confidence = (
        sum(item.confidence for item in available_results) / len(available_results)
        if available_results
        else 0.0
    )
    if not critical_usable:
        aggregate_confidence = min(
            aggregate_confidence, 0.55 if critical_results else 0.45
        )
    authority_status = (
        "high" if aggregate_confidence >= 0.8 and critical_usable else "limited"
    )
    country = context.operating_country or context.regulatory_country or "global"
    variant_path = (
        f"financials:{model}:{country.lower()}",
        f"financials:{model}",
        "financials",
    )
    history = tuple(
        {
            "metric": item.metric,
            "value": item.value,
            "unit": item.unit,
            "as_of": item.as_of,
            "known_at": item.known_at,
            "source_id": item.source_id,
        }
        for item in results
        if item.metric in _REGULATORY
        or item.metric
        in {"npl_ratio", "npl_coverage_ratio", "combined_ratio", "reserve_adequacy"}
    )
    rationale = (
        f"{model} formulas only; industrial leverage/FCF/DCF/Altman/P-E are N/A",
        f"variant={variant_path[0]}; parent fallback stays within financials",
    )
    lineage = {
        "classification_version": context.version_id,
        "classification_token": context.score_invalidation_token,
        "adapter_lineage": selection.lineage_hash,
        "formula_version": FINANCIAL_FORMULA_VERSION,
        "decision_time": _iso(decision),
        "sources": tuple(sorted({item.source_id for item in results})),
    }
    provisional = {
        "contract": FINANCIAL_ADAPTER_CONTRACT,
        "status": (
            "available"
            if available_results and len(available_results) == len(results)
            else "partial"
            if available_results
            else "unavailable"
        ),
        "instrument_id": context.instrument_id,
        "business_model": model,
        "adapter_id": selection.adapter_id,
        "adapter_version": selection.adapter_version,
        "variant_path": variant_path,
        "parent_fallback": variant_path[-1],
        "aggregate_confidence": aggregate_confidence,
        "authority_status": authority_status,
        "metrics": tuple(results),
        "stresses": stress_results,
        "solvency_asset_quality_history": history,
        "rationale": rationale,
        "lineage": lineage,
        "limitations": tuple(sorted(limitations)),
        "execution_allowed": False,
    }
    return FinancialInstitutionProjection(
        **provisional,
        result_hash=_hash(provisional),
    )


def unavailable_financial_projection(
    instrument_id: str, reason_code: str = "financial_evidence_unavailable"
) -> dict[str, object]:
    return {
        "contract": FINANCIAL_ADAPTER_CONTRACT,
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_code": reason_code,
        "aggregate_confidence": 0.0,
        "authority_status": "unavailable",
        "metrics": (),
        "stresses": (),
        "solvency_asset_quality_history": (),
        "rationale": (),
        "lineage": {},
        "limitations": ("local financial evidence unavailable",),
        "execution_allowed": False,
    }


def projection_payload(
    projection: FinancialInstitutionProjection,
) -> dict[str, object]:
    return asdict(projection)


def financial_result_hash(
    value: FinancialInstitutionProjection | Mapping[str, object],
) -> str:
    payload = (
        asdict(value)
        if isinstance(value, FinancialInstitutionProjection)
        else dict(value)
    )
    payload.pop("result_hash", None)
    return _hash(payload)


def verify_financial_projection(
    value: FinancialInstitutionProjection | Mapping[str, object],
) -> dict[str, object]:
    payload = (
        projection_payload(value)
        if isinstance(value, FinancialInstitutionProjection)
        else dict(value)
    )
    required = {
        item.name
        for item in FinancialInstitutionProjection.__dataclass_fields__.values()
    }
    if (
        set(payload) != required
        or payload.get("contract") != FINANCIAL_ADAPTER_CONTRACT
        or payload.get("execution_allowed") is not False
        or payload.get("result_hash") != financial_result_hash(payload)
        or _has_execution_authority(payload)
    ):
        raise FinancialAdapterError("financial projection verification failed")
    return payload


def _has_execution_authority(value: object) -> bool:
    if isinstance(value, Mapping):
        if value.get("execution_allowed") is True:
            return True
        return any(_has_execution_authority(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_has_execution_authority(item) for item in value)
    return False


def _business_model(context: InstrumentContextV2) -> str:
    tags = {item.casefold() for item in context.business_model_tags}
    matches = [
        model
        for model, aliases in {
            "bank": {"bank", "banking", "deposit_taking"},
            "insurer": {"insurer", "insurance"},
            "diversified": {"diversified", "diversified_financials"},
        }.items()
        if tags.intersection(aliases)
    ]
    if len(matches) != 1:
        raise FinancialAdapterError(
            "financial business model must resolve to bank, insurer, or diversified"
        )
    return matches[0]


def _validate_evidence(
    item: FinancialMetricEvidence, model: str, decision: datetime
) -> None:
    if (
        item.execution_allowed
        or item.business_model != model
        or not item.unit.strip()
        or not item.period.strip()
        or not item.reporting_standard.strip()
        or not item.jurisdiction.strip()
        or not item.source_id.strip()
        or _time(item.known_at) > decision
        or _time(item.as_of) > decision
    ):
        raise FinancialAdapterError("financial metric lineage is invalid")


def _stress(name: str, value: object) -> FinancialStressResult:
    formula = "-(abs(shock_rate) * exposed_amount / capital_base)"
    if not isinstance(value, Mapping):
        return FinancialStressResult(
            name,
            "unavailable",
            None,
            None,
            "ratio",
            formula,
            {},
            "SHOCK_INPUT_MISSING",
        )
    try:
        rate = float(value["shock_rate"])
        exposure = float(value["exposed_amount"])
        capital = float(value["capital_base"])
    except (KeyError, TypeError, ValueError):
        return FinancialStressResult(
            name,
            "unavailable",
            None,
            None,
            "ratio",
            formula,
            {},
            "SHOCK_BASIS_MISSING",
        )
    inputs = {
        "shock_rate": rate,
        "exposed_amount": exposure,
        "capital_base": capital,
    }
    if (
        not all(_finite(item) for item in inputs.values())
        or exposure < 0
        or capital <= 0
    ):
        return FinancialStressResult(
            name,
            "unavailable",
            None,
            None,
            "ratio",
            formula,
            {},
            "SHOCK_BASIS_INVALID",
        )
    impact = -(abs(rate) * exposure / capital)
    return FinancialStressResult(
        name,
        "available",
        rate,
        impact,
        "ratio",
        formula,
        inputs,
        "DETERMINISTIC_CAPITAL_IMPACT",
    )


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialAdapterError("financial timestamps are invalid") from exc
    if parsed.tzinfo is None:
        raise FinancialAdapterError("financial timestamps require timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            default=lambda item: (
                asdict(item)
                if hasattr(item, "__dataclass_fields__")
                else item.value
                if isinstance(item, SourceAuthority)
                else str(item)
            ),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
