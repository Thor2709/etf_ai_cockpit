"""Typed, local-only REIT, utility and infrastructure evidence adapters."""

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


REAL_ASSET_CONTRACT = "real-asset-adapter.v1"
REAL_ASSET_FORMULA_VERSION = "real-asset-formulas.v1"
_ADAPTERS = {
    "reit": "sector:real_estate",
    "utility": "sector:utilities",
    "infrastructure": "sector:industrials",
}
_COMMON = frozenset(
    {
        "maintenance_capex", "expansion_capex", "distributions", "net_debt",
        "ebitda", "interest_expense",
    }
)
_METRICS = {
    "reit": _COMMON | {
        "net_income", "depreciation_amortisation", "property_sale_gains",
        "ffo", "recurring_adjustments", "affo", "nav", "occupancy_rate",
        "weighted_average_lease_maturity", "loan_to_value",
    },
    "utility": _COMMON | {
        "operating_cash_flow", "rab", "allowed_return", "capex_funding_ratio",
        "tariff_regulatory_exposure",
    },
    "infrastructure": _COMMON | {
        "operating_cash_flow", "regulated_asset_base", "allowed_return",
        "capex_funding_ratio", "tariff_regulatory_exposure",
    },
}
_PROHIBITED = frozenset(
    {"pe_ratio", "generic_pe", "industrial_free_cash_flow", "free_cash_flow", "fcf",
     "industrial_leverage"}
)
_LOWER = frozenset({
    "maintenance_capex", "expansion_capex", "net_debt", "interest_expense",
    "loan_to_value", "tariff_regulatory_exposure",
})
_RATIO_METRICS = frozenset({
    "occupancy_rate", "loan_to_value", "allowed_return", "capex_funding_ratio",
    "tariff_regulatory_exposure",
})


class RealAssetAdapterError(ValueError):
    """Raised when real-asset evidence violates its fail-closed contract."""


@dataclass(frozen=True)
class RealAssetFormulaDefinition:
    metric: str
    business_model: str
    direction: str
    allowed_units: tuple[str, ...]
    definition: str
    missing_policy: str = "unavailable"
    formula_version: str = REAL_ASSET_FORMULA_VERSION
    execution_allowed: bool = False


@dataclass(frozen=True)
class RealAssetMetricEvidence:
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
    execution_allowed: bool = False


@dataclass(frozen=True)
class RealAssetMetricResult:
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
    execution_allowed: bool = False


@dataclass(frozen=True)
class RealAssetCheck:
    check: str
    status: str
    value: float | None
    unit: str
    formula: str
    reason_code: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class RealAssetStress:
    shock: str
    status: str
    impact: float | None
    unit: str
    formula: str
    inputs: Mapping[str, float]
    reason_code: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class RealAssetProjection:
    contract: str
    status: str
    instrument_id: str
    business_model: str
    adapter_id: str
    adapter_version: str
    variant_path: tuple[str, ...]
    parent_fallback: str
    metrics: tuple[RealAssetMetricResult, ...]
    checks: tuple[RealAssetCheck, ...]
    stresses: tuple[RealAssetStress, ...]
    rationale: tuple[str, ...]
    lineage: Mapping[str, object]
    limitations: tuple[str, ...]
    result_hash: str
    execution_allowed: bool = False


def real_asset_adapter_definitions() -> tuple[AdapterDefinition, ...]:
    return tuple(
        AdapterDefinition(adapter, "1", _METRICS[model])
        for model, adapter in sorted(_ADAPTERS.items())
    )


def real_asset_formula_registry() -> tuple[RealAssetFormulaDefinition, ...]:
    definitions = {
        "ffo": "net income + depreciation/amortisation - property sale gains",
        "affo": "FFO - maintenance capex + recurring adjustments; expansion capex excluded",
        "maintenance_capex": "recurring spend required to sustain current asset cash flows",
        "expansion_capex": "growth spend that expands capacity; never deducted as maintenance",
        "nav": "issuer-supported property fair value less liabilities; no proxy fallback",
        "rab": "regulator-certified regulatory asset base; no proxy fallback",
        "regulated_asset_base": "regulator-certified regulated asset base; no proxy fallback",
        "occupancy_rate": "occupied lettable area divided by available lettable area",
        "weighted_average_lease_maturity": "contracted lease term weighted by rent",
        "loan_to_value": "net debt divided by reliable property value",
        "allowed_return": "regulator-authorised return on the regulated asset base",
        "capex_funding_ratio": "identified funding divided by committed capital expenditure",
        "tariff_regulatory_exposure": "share of cash flow exposed to regulated tariffs",
    }
    return tuple(
        RealAssetFormulaDefinition(
            metric=metric,
            business_model=model,
            direction="lower_is_better" if metric in _LOWER else "higher_is_better",
            allowed_units=(
                ("ratio", "percent") if metric in _RATIO_METRICS
                else ("years",) if metric == "weighted_average_lease_maturity"
                else ("currency",)
            ),
            definition=definitions.get(metric, "reported sector-specific statement measure"),
        )
        for model, metrics in sorted(_METRICS.items())
        for metric in sorted(metrics)
    )


def build_real_asset_projection(
    context: InstrumentContextV2,
    evidence: Sequence[RealAssetMetricEvidence],
    *,
    registry: AdapterRegistry,
    decision_time: str,
    shocks: Mapping[str, object],
) -> RealAssetProjection:
    model = _model(context)
    decision = _time(decision_time)
    try:
        selection = registry.select(context)
    except PeerCohortError as exc:
        raise RealAssetAdapterError(str(exc)) from exc
    if selection.adapter_id != _ADAPTERS[model]:
        raise RealAssetAdapterError("real-asset classification route is incompatible")
    if context.instrument_type != "stock" or context.asset_class != "equity":
        raise RealAssetAdapterError("real-asset adapter requires a classified equity security")
    if (context.execution_allowed or _time(context.decision_time) != decision
            or context.classification_status in {"unresolved", "manual_review"}):
        raise RealAssetAdapterError("real-asset classification must match the exact decision cutoff")
    formulas = {
        row.metric: row for row in real_asset_formula_registry()
        if row.business_model == model
    }
    results: list[RealAssetMetricResult] = []
    limitations: set[str] = set()
    seen: set[str] = set()
    for item in sorted(evidence, key=lambda row: (row.metric, row.known_at, row.source_id)):
        _validate(item, model, decision)
        if item.metric in _PROHIBITED:
            raise RealAssetAdapterError(f"generic fallback {item.metric!r} is forbidden")
        if item.metric not in formulas or item.metric in seen:
            raise RealAssetAdapterError("real-asset metric is invalid or duplicated")
        seen.add(item.metric)
        formula = formulas[item.metric]
        if item.unit not in formula.allowed_units or (
            item.direction is not None and item.direction != formula.direction
        ):
            raise RealAssetAdapterError("real-asset metric unit or direction is incompatible")
        available = item.value is not None and _finite(item.value)
        item_limits = tuple(sorted({*item.limitations, *(() if available else ("missing_value",))}))
        limitations.update(f"{item.metric}:{value}" for value in item_limits)
        results.append(RealAssetMetricResult(
            metric=item.metric, status="available" if available else "unavailable",
            value=float(item.value) if available else None, unit=item.unit,
            direction=formula.direction, period=item.period,
            reporting_standard=item.reporting_standard, jurisdiction=item.jurisdiction,
            business_model=model, source_id=item.source_id,
            source_authority=item.source_authority.value, as_of=_iso(_time(item.as_of)),
            known_at=_iso(_time(item.known_at)), definition=formula.definition,
            missing_policy=formula.missing_policy, limitations=item_limits,
        ))
    results.extend(_derived_reit_results(model, results))
    results.sort(key=lambda row: (row.metric, row.known_at, row.source_id))
    values = {row.metric: row.value for row in results if row.status == "available"}
    checks = _checks(model, values)
    protected_metrics = (
        {"nav"} if model == "reit"
        else {"rab"} if model == "utility"
        else {"regulated_asset_base"}
    )
    for protected in protected_metrics:
        if protected not in values:
            limitations.add(f"{protected}:required_inputs_unavailable")
            formula = formulas[protected]
            results.append(RealAssetMetricResult(
                metric=protected, status="unavailable", value=None, unit="currency",
                direction=formula.direction, period="unavailable",
                reporting_standard="unavailable", jurisdiction="unavailable",
                business_model=model, source_id="unavailable",
                source_authority="unavailable", as_of=_iso(decision),
                known_at=_iso(decision), definition=formula.definition,
                missing_policy=formula.missing_policy,
                limitations=("required_reliable_inputs_unavailable",),
            ))
    for check in checks:
        if check.status == "failed":
            limitations.add(f"{check.check}:{check.reason_code}")
    stress_results = tuple(
        _stress(name, shocks.get(name))
        for name in ("rate", "inflation", "refinancing", "nav_sensitivity")
    )
    country = context.operating_country or context.regulatory_country or "global"
    variant_path = (f"real_assets:{model}:{country.lower()}", f"real_assets:{model}", "real_assets")
    available = [row for row in results if row.status == "available"]
    protected_available = all(metric in values for metric in protected_metrics)
    reconciliation_failed = any(row.status == "failed" for row in checks)
    lineage = {
        "classification_version": context.version_id,
        "classification_token": context.score_invalidation_token,
        "adapter_lineage": selection.lineage_hash,
        "formula_version": REAL_ASSET_FORMULA_VERSION,
        "decision_time": _iso(decision),
        "sources": tuple(sorted({row.source_id for row in results})),
    }
    provisional = {
        "contract": REAL_ASSET_CONTRACT,
        "status": (
            "available"
            if available and len(available) == len(results)
            and protected_available and not reconciliation_failed
            else "partial" if available else "unavailable"
        ),
        "instrument_id": context.instrument_id, "business_model": model,
        "adapter_id": selection.adapter_id, "adapter_version": selection.adapter_version,
        "variant_path": variant_path, "parent_fallback": "real_assets",
        "metrics": tuple(results), "checks": checks, "stresses": stress_results,
        "rationale": (
            "REIT FFO/AFFO and maintenance versus expansion capex stay distinct" if model == "reit"
            else "regulated cash flow, payout, leverage and coverage use statement evidence",
            "NAV/RAB remain unavailable without reliable required inputs; generic P/E/FCF/leverage fallbacks forbidden",
        ),
        "lineage": lineage, "limitations": tuple(sorted(limitations)),
        "execution_allowed": False,
    }
    return RealAssetProjection(**provisional, result_hash=_hash(provisional))


def unavailable_real_asset_projection(instrument_id: str, reason_code: str = "real_asset_evidence_unavailable") -> dict[str, object]:
    return {
        "contract": REAL_ASSET_CONTRACT, "status": "unavailable",
        "instrument_id": str(instrument_id), "reason_code": reason_code,
        "metrics": (), "checks": (), "stresses": (), "rationale": (), "lineage": {},
        "limitations": ("local real-asset evidence unavailable",), "execution_allowed": False,
    }


def projection_payload(projection: RealAssetProjection) -> dict[str, object]:
    return asdict(projection)


def real_asset_result_hash(value: RealAssetProjection | Mapping[str, object]) -> str:
    payload = asdict(value) if isinstance(value, RealAssetProjection) else dict(value)
    payload.pop("result_hash", None)
    return _hash(payload)


def verify_real_asset_projection(value: RealAssetProjection | Mapping[str, object]) -> dict[str, object]:
    payload = projection_payload(value) if isinstance(value, RealAssetProjection) else dict(value)
    required = set(RealAssetProjection.__dataclass_fields__)
    if (set(payload) != required or payload.get("contract") != REAL_ASSET_CONTRACT
            or payload.get("execution_allowed") is not False
            or payload.get("result_hash") != real_asset_result_hash(payload)
            or _has_authority(payload)):
        raise RealAssetAdapterError("real-asset projection verification failed")
    return payload


def _model(context: InstrumentContextV2) -> str:
    tags = {tag.casefold() for tag in context.business_model_tags}
    matches = [model for model, aliases in {
        "reit": {"reit", "real_estate_investment_trust"},
        "utility": {"utility", "regulated_utility"},
        "infrastructure": {"infrastructure", "infrastructure_operator"},
    }.items() if tags & aliases]
    if len(matches) != 1:
        raise RealAssetAdapterError("business model must resolve to REIT, utility or infrastructure")
    return matches[0]


def _validate(item: RealAssetMetricEvidence, model: str, decision: datetime) -> None:
    if (item.execution_allowed or item.business_model != model or not item.period.strip()
            or not item.reporting_standard.strip() or not item.jurisdiction.strip()
            or not item.source_id.strip() or _time(item.as_of) > decision
            or _time(item.known_at) > decision
            or (decision - _time(item.as_of)).days > 550):
        raise RealAssetAdapterError("real-asset metric lineage is invalid")
    if item.metric in {"nav", "rab", "regulated_asset_base"} and item.source_authority not in {
        SourceAuthority.OFFICIAL, SourceAuthority.ISSUER,
    }:
        raise RealAssetAdapterError("NAV/RAB requires reliable issuer or official evidence")


def _derived_reit_results(
    model: str, results: Sequence[RealAssetMetricResult]
) -> list[RealAssetMetricResult]:
    if model != "reit":
        return []
    by_metric = {row.metric: row for row in results}
    derived: list[RealAssetMetricResult] = []

    def make(metric: str, inputs: tuple[str, ...], formula: str) -> RealAssetMetricResult:
        rows = [by_metric.get(name) for name in inputs]
        available = all(row is not None and row.status == "available" for row in rows)
        value: float | None = None
        if available:
            numbers = {name: by_metric[name].value for name in inputs}
            if metric == "ffo":
                value = (
                    numbers["net_income"]
                    + numbers["depreciation_amortisation"]
                    - numbers["property_sale_gains"]
                )  # type: ignore[operator]
            else:
                value = (
                    numbers["ffo"]
                    - numbers["maintenance_capex"]
                    + numbers["recurring_adjustments"]
                )  # type: ignore[operator]
        reference = next((row for row in rows if row is not None), None)
        return RealAssetMetricResult(
            metric=metric, status="available" if available else "unavailable",
            value=float(value) if value is not None else None, unit="currency",
            direction="higher_is_better",
            period=reference.period if reference else "unavailable",
            reporting_standard=reference.reporting_standard if reference else "unavailable",
            jurisdiction=reference.jurisdiction if reference else "unavailable",
            business_model=model, source_id=f"derived:{metric}",
            source_authority="derived_statement_evidence",
            as_of=max((row.as_of for row in rows if row is not None), default="unavailable"),
            known_at=max((row.known_at for row in rows if row is not None), default="unavailable"),
            definition=f"derived from statement evidence: {formula}",
            missing_policy="unavailable",
            limitations=() if available else ("required_statement_inputs_unavailable",),
        )

    if "ffo" not in by_metric:
        ffo = make(
            "ffo",
            ("net_income", "depreciation_amortisation", "property_sale_gains"),
            "net income + depreciation/amortisation - property sale gains",
        )
        derived.append(ffo)
        by_metric["ffo"] = ffo
    if "affo" not in by_metric:
        derived.append(make(
            "affo",
            ("ffo", "maintenance_capex", "recurring_adjustments"),
            "FFO - maintenance capex + recurring adjustments; expansion capex excluded",
        ))
    return derived


def _checks(model: str, values: Mapping[str, float | None]) -> tuple[RealAssetCheck, ...]:
    def ratio(name: str, numerator: str, denominator: str, formula: str) -> RealAssetCheck:
        top, bottom = values.get(numerator), values.get(denominator)
        if top is None or bottom is None or bottom == 0:
            return RealAssetCheck(name, "unavailable", None, "ratio", formula, "required_statement_inputs_unavailable")
        return RealAssetCheck(name, "available", float(top / bottom), "ratio", formula, "reconciled_to_statement_evidence")
    checks = [
        ratio("payout", "distributions", "affo" if model == "reit" else "operating_cash_flow",
              "distributions / sector cash-flow denominator"),
        ratio("leverage", "net_debt", "ebitda", "net debt / EBITDA"),
        ratio("interest_coverage", "ebitda", "interest_expense", "EBITDA / interest expense"),
    ]
    if model == "reit":
        required = ("net_income", "depreciation_amortisation", "property_sale_gains", "ffo")
        if all(values.get(key) is not None for key in required):
            expected = values["net_income"] + values["depreciation_amortisation"] - values["property_sale_gains"]  # type: ignore[operator]
            checks.append(RealAssetCheck("ffo_reconciliation", "available" if math.isclose(expected, values["ffo"] or 0.0) else "failed", values["ffo"], "currency", "net income + D&A - property sale gains", "reconciled" if math.isclose(expected, values["ffo"] or 0.0) else "statement_mismatch"))
        else:
            checks.append(RealAssetCheck("ffo_reconciliation", "unavailable", None, "currency", "net income + D&A - property sale gains", "required_statement_inputs_unavailable"))
        required_affo = ("ffo", "maintenance_capex", "recurring_adjustments", "affo")
        if all(values.get(key) is not None for key in required_affo):
            expected = values["ffo"] - values["maintenance_capex"] + values["recurring_adjustments"]  # type: ignore[operator]
            checks.append(RealAssetCheck("affo_reconciliation", "available" if math.isclose(expected, values["affo"] or 0.0) else "failed", values["affo"], "currency", "FFO - maintenance capex + recurring adjustments; expansion capex excluded", "reconciled" if math.isclose(expected, values["affo"] or 0.0) else "statement_mismatch"))
        else:
            checks.append(RealAssetCheck("affo_reconciliation", "unavailable", None, "currency", "FFO - maintenance capex + recurring adjustments; expansion capex excluded", "required_statement_inputs_unavailable"))
    return tuple(checks)


def _stress(name: str, value: object) -> RealAssetStress:
    formula = "shock_rate * exposed_amount / base_amount"
    if not isinstance(value, Mapping):
        return RealAssetStress(name, "unavailable", None, "ratio", formula, {}, "required_inputs_unavailable")
    try:
        inputs = {key: float(value[key]) for key in ("shock_rate", "exposed_amount", "base_amount")}
    except (KeyError, TypeError, ValueError):
        return RealAssetStress(name, "unavailable", None, "ratio", formula, {}, "required_inputs_unavailable")
    if not all(_finite(number) for number in inputs.values()) or inputs["base_amount"] <= 0:
        return RealAssetStress(name, "unavailable", None, "ratio", formula, {}, "invalid_inputs")
    return RealAssetStress(name, "available", inputs["shock_rate"] * inputs["exposed_amount"] / inputs["base_amount"], "ratio", formula, inputs, "deterministic_scenario")


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RealAssetAdapterError("timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise RealAssetAdapterError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _hash(value: object) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=lambda item: asdict(item)).encode()
    except (TypeError, ValueError) as exc:
        raise RealAssetAdapterError("projection is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _has_authority(value: object) -> bool:
    if isinstance(value, Mapping):
        return value.get("execution_allowed") is True or any(_has_authority(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_authority(item) for item in value)
    return False
