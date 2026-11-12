"""Independent position-size ceilings for Sparebank opportunities (#718, scope 5).

Every ceiling is a separate, named upper bound on the invested weight.  The
feasible range is their minimum; the optimiser chooses *inside* it.  A
specialist ``maximum_allowed`` is only one ceiling and is never a target weight.
Missing or non-finite required inputs make the whole result ``unavailable``
instead of dropping a ceiling (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

CEILING_POLICY_VERSION = "sbi-ceilings.v1"
CONFIDENCE_ORDER = ("OBSERVED", "HIGH", "MEDIUM", "LOW")


@dataclass(frozen=True)
class CeilingPolicy:
    """Conservative documented defaults; owner settings and score weights are never touched here."""

    loss_budget_nav: float = 0.01  # bear-case loss one name may cost, as a NAV fraction
    event_failure_budget_nav: float = 0.0075  # loss if a binary event fails
    max_days_to_liquidate: float = 5.0
    max_participation: float = 0.20  # of average daily traded value
    max_free_float_ownership: float = 0.02  # of the practically tradable float (market cap x effective free float)
    single_name_cap: float = 0.05
    sector_heat_cap: float = 0.15  # financial-sector / region heat incl. the candidate
    confidence_factor: Mapping[str, float] = field(default_factory=lambda: {"OBSERVED": 1.0, "HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.25})
    degraded_factor: float = 0.5
    min_bear_loss_fraction: float = 0.05  # floor so a bear case at/above price cannot imply an unbounded loss-budget ceiling

    def to_payload(self) -> dict[str, object]:
        return {
            "version": CEILING_POLICY_VERSION, "loss_budget_nav": self.loss_budget_nav,
            "event_failure_budget_nav": self.event_failure_budget_nav, "max_days_to_liquidate": self.max_days_to_liquidate,
            "max_participation": self.max_participation, "max_free_float_ownership": self.max_free_float_ownership,
            "single_name_cap": self.single_name_cap, "sector_heat_cap": self.sector_heat_cap,
            "confidence_factor": dict(sorted(self.confidence_factor.items())), "degraded_factor": self.degraded_factor,
            "min_bear_loss_fraction": self.min_bear_loss_fraction,
        }


@dataclass(frozen=True)
class CeilingInputs:
    portfolio_value: float | None  # base currency
    bear_case_loss_fraction: float | None  # position loss in the bear case, 0..1
    adv_value: float | None  # average daily traded value, base currency
    market_cap: float | None  # base currency
    effective_free_float: float | None  # 0..1, after foundation/strategic/treasury holders
    sector_exposure_excluding_candidate: float | None  # weight
    scenario_confidences: tuple[tuple[float, str], ...] = ()  # (probability, confidence class)
    event_failure_loss_fraction: float | None = None  # only when a binary event is decision-relevant
    event_relevant: bool = False
    specialist_maximum: float | None = None  # model-side maximum, a ceiling only
    degraded: bool = False


@dataclass(frozen=True)
class CeilingResult:
    status: str  # available | unavailable
    ceiling: float | None
    components: Mapping[str, float]
    binding: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    confidence_factor: float | None = None

    def to_payload(self) -> dict[str, object]:
        return {"status": self.status, "ceiling": self.ceiling, "components": dict(sorted(self.components.items())),
                "binding": list(self.binding), "reasons": list(self.reasons), "confidence_factor": self.confidence_factor}


def _ok(value: object, *, low: float = 0.0, strict: bool = False) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and (value > low if strict else value >= low)


def confidence_factor(pairs: tuple[tuple[float, str], ...], factors: Mapping[str, float]) -> float | None:
    """Probability-weighted evidence-confidence shrinkage; unknown class or empty evidence is unavailable."""

    if not pairs or any(conf not in factors for _, conf in pairs):
        return None
    total = sum(p for p, _ in pairs)
    if not math.isfinite(total) or total <= 0:
        return None
    return sum(p * factors[conf] for p, conf in pairs) / total


def compute_ceilings(inputs: CeilingInputs, policy: CeilingPolicy | None = None) -> CeilingResult:
    policy = policy or CeilingPolicy()
    reasons: list[str] = []
    if not _ok(inputs.portfolio_value, strict=True):
        reasons.append("portfolio_value_missing")
    if not _ok(inputs.bear_case_loss_fraction) or inputs.bear_case_loss_fraction > 1.0:
        reasons.append("bear_case_loss_missing")
    if not _ok(inputs.adv_value, strict=True):
        reasons.append("liquidity_adv_missing")
    if not _ok(inputs.market_cap, strict=True) or not _ok(inputs.effective_free_float, strict=True) or inputs.effective_free_float > 1.0:
        reasons.append("free_float_capacity_missing")
    if not _ok(inputs.sector_exposure_excluding_candidate):
        reasons.append("sector_exposure_missing")
    if inputs.event_relevant and not _ok(inputs.event_failure_loss_fraction, strict=True):
        reasons.append("event_failure_exposure_missing")
    factor = confidence_factor(inputs.scenario_confidences, policy.confidence_factor)
    if factor is None:
        reasons.append("confidence_evidence_missing")
    if inputs.specialist_maximum is not None and not (_ok(inputs.specialist_maximum) and inputs.specialist_maximum <= 1.0):
        reasons.append("specialist_maximum_invalid")
    if reasons:
        return CeilingResult("unavailable", None, {}, (), tuple(reasons))

    components: dict[str, float] = {
        "single_name": policy.single_name_cap,
        "loss_budget": policy.loss_budget_nav / max(inputs.bear_case_loss_fraction, policy.min_bear_loss_fraction),
        "liquidity_days": inputs.adv_value * policy.max_participation * policy.max_days_to_liquidate / inputs.portfolio_value,
        "free_float_capacity": inputs.market_cap * inputs.effective_free_float * policy.max_free_float_ownership / inputs.portfolio_value,
        "sector_heat": max(0.0, policy.sector_heat_cap - inputs.sector_exposure_excluding_candidate),
        "confidence": policy.single_name_cap * factor,
    }
    if inputs.event_relevant:
        components["event_failure"] = policy.event_failure_budget_nav / inputs.event_failure_loss_fraction
    if inputs.specialist_maximum is not None:
        components["specialist_maximum"] = inputs.specialist_maximum
    if inputs.degraded:
        components["degraded_treatment"] = policy.single_name_cap * policy.degraded_factor
    ceiling = min(components.values())
    binding = tuple(sorted(name for name, value in components.items() if math.isclose(value, ceiling, rel_tol=1e-12, abs_tol=1e-15)))
    return CeilingResult("available", ceiling, components, binding, confidence_factor=factor)


def apply_ceiling(desired_weight: float, result: CeilingResult) -> tuple[float, bool]:
    """Clamp a desired weight to the feasible range; unavailable ceilings allow nothing."""

    if result.status != "available" or result.ceiling is None or not math.isfinite(desired_weight):
        return 0.0, True
    final = max(0.0, min(float(desired_weight), result.ceiling))
    return final, final < desired_weight


__all__ = [
    "CEILING_POLICY_VERSION",
    "CeilingInputs",
    "CeilingPolicy",
    "CeilingResult",
    "apply_ceiling",
    "compute_ceilings",
    "confidence_factor",
]
