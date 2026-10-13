"""Critical-evidence gates and separate score-authority flags (#939).

Required evidence per asset class lives in ``configs/decision_domains_v1.yaml`` under ``critical_evidence``.
A failed gate blocks Buy-type labels and makes the dependent score group ``insufficient_evidence``; it never
raises the weight of the remaining inputs, and a coverage shrink can never turn a failed gate into a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
from typing import Collection, Iterable, Mapping

import yaml

from etf_cockpit.analysis.decision.contracts import CriticalGateResult, ScoreAuthorityFlags
from etf_cockpit.core.paths import CONFIG_DIR

POLICY_PATH = CONFIG_DIR / "decision_domains_v1.yaml"
INSUFFICIENT_LABEL = "insufficient_evidence"
_NOT_APPLICABLE_STATUSES = frozenset({"n/a", "na", "not_applicable", "inapplicable"})
_STOCK_TYPES = frozenset({"stock", "equity", "certificate", "stock_like"})
_BANK_MODELS = frozenset({"bank", "sparebank", "savings_bank", "equity_certificate", "ec", "egenkapitalbevis"})


class CriticalEvidenceError(ValueError):
    """Raised when the critical-evidence policy is missing or malformed."""


@dataclass(frozen=True)
class GateDefinition:
    gate_id: str
    evidence_any_of: tuple[str, ...]
    group: str | None = None


@dataclass(frozen=True)
class CriticalEvidencePolicy:
    version: str
    quality_minimum_inputs: int
    quality_configured_inputs: int
    buy_labels: frozenset[str]
    gates: Mapping[str, tuple[GateDefinition, ...]]
    inapplicable_inputs: Mapping[str, frozenset[str]]


@lru_cache(maxsize=8)
def _policy_for_content(content: bytes) -> CriticalEvidencePolicy:
    try:
        parsed = yaml.safe_load(content.replace(b"\r\n", b"\n").decode("utf-8")) or {}
        section = parsed["critical_evidence"]
        minimum = section["quality_minimum_inputs"]
        quality_minimum = int(minimum["minimum"])
        quality_configured = int(minimum["configured"])
        if quality_minimum < 1 or quality_configured < quality_minimum:
            raise CriticalEvidenceError("quality_minimum_inputs must satisfy 1 <= minimum <= configured")
        gates: dict[str, tuple[GateDefinition, ...]] = {}
        inapplicable: dict[str, frozenset[str]] = {}
        for asset_class, body in section["asset_classes"].items():
            definitions = []
            for gate_id, raw in body["gates"].items():
                evidence = tuple(str(item) for item in raw["evidence_any_of"])
                if not evidence:
                    raise CriticalEvidenceError(f"gate {gate_id} lists no evidence ids")
                group = raw.get("group")
                definitions.append(GateDefinition(str(gate_id), evidence, None if group is None else str(group)))
            gates[str(asset_class).upper()] = tuple(definitions)
            inapplicable[str(asset_class).upper()] = frozenset(str(item) for item in body.get("inapplicable_inputs", ()))
        return CriticalEvidencePolicy(
            str(section["version"]),
            quality_minimum,
            quality_configured,
            frozenset(str(item) for item in section["buy_labels"]),
            gates,
            inapplicable,
        )
    except CriticalEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as exc:
        raise CriticalEvidenceError(f"critical_evidence policy is invalid: {type(exc).__name__}") from exc


def load_critical_evidence_policy(path: Path = POLICY_PATH) -> CriticalEvidencePolicy:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise CriticalEvidenceError(f"critical_evidence policy is unreadable: {type(exc).__name__}") from exc
    return _policy_for_content(content)


def critical_asset_class(asset_type: object, business_model: object = None) -> str | None:
    """Map an asset type (and optional business model) to a configured gate class; ``None`` when unmapped."""

    model = str(business_model or "").strip().casefold().replace("-", "_").replace(" ", "_")
    kind = str(asset_type or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if kind in {"equity_certificate", "ec", "egenkapitalbevis"} or model in _BANK_MODELS:
        return "BANK"
    if kind == "etf":
        return "ETF"
    if kind in _STOCK_TYPES:
        return "STOCK"
    return None


def evaluate_critical_gates(
    asset_class: str | None,
    evidence: Iterable[str],
    *,
    policy: CriticalEvidencePolicy | None = None,
) -> tuple[CriticalGateResult, ...]:
    """Evaluate every required-evidence gate; an unmapped asset class fails closed."""

    selected = policy or load_critical_evidence_policy()
    if asset_class is None or asset_class.upper() not in selected.gates:
        return (CriticalGateResult("asset_class", "INSUFFICIENT_EVIDENCE", ("asset_class",), "ASSET_CLASS_UNMAPPED"),)
    present = {str(item) for item in evidence}
    results = []
    for definition in selected.gates[asset_class.upper()]:
        if present & set(definition.evidence_any_of):
            results.append(CriticalGateResult(definition.gate_id, "PASS", (), "EVIDENCE_PRESENT", definition.group))
        else:
            results.append(
                CriticalGateResult(
                    definition.gate_id,
                    "INSUFFICIENT_EVIDENCE",
                    definition.evidence_any_of,
                    "CRITICAL_EVIDENCE_MISSING",
                    definition.group,
                )
            )
    return tuple(results)


def failed_gates(results: Iterable[CriticalGateResult]) -> tuple[CriticalGateResult, ...]:
    return tuple(result for result in results if not result.passed)


def failed_gate_groups(results: Iterable[CriticalGateResult]) -> dict[str, tuple[str, ...]]:
    """Score groups made insufficient by failed gates, with the gate ids responsible."""

    groups: dict[str, list[str]] = {}
    for result in failed_gates(results):
        if result.group:
            groups.setdefault(result.group, []).append(result.gate_id)
    return {group: tuple(ids) for group, ids in groups.items()}


def blocks_buy_label(results: Iterable[CriticalGateResult]) -> bool:
    return bool(failed_gates(results))


def is_buy_label(label: object, *, policy: CriticalEvidencePolicy | None = None) -> bool:
    selected = policy or load_critical_evidence_policy()
    return str(label or "").strip() in selected.buy_labels


def is_not_applicable(status: object) -> bool:
    return str(status or "").strip().casefold() in _NOT_APPLICABLE_STATUSES


def inapplicable_inputs(asset_class: str | None, *, policy: CriticalEvidencePolicy | None = None) -> frozenset[str]:
    """Inputs the sector definition forbids; only these may leave a denominator when not applicable."""

    if asset_class is None:
        return frozenset()
    return (policy or load_critical_evidence_policy()).inapplicable_inputs.get(asset_class.upper(), frozenset())


@dataclass(frozen=True)
class InputCompleteness:
    status: str  # "complete" | "partial" | "unavailable"
    used: int
    applicable: int
    required: int
    coverage: float
    missing: tuple[str, ...]


def input_completeness(
    configured: Collection[str],
    used: Collection[str],
    *,
    not_applicable: Collection[str] = (),
    asset_class: str | None = None,
    minimum: int | None = None,
    policy: CriticalEvidencePolicy | None = None,
) -> InputCompleteness:
    """Completeness of one component's inputs (quality: default 4 of 6, recorded in the policy).

    Inputs reported not applicable leave the denominator only when the sector definition forbids them;
    any other missing input stays in the denominator. Fewer than the minimum is ``partial``, never complete.
    """

    selected = policy or load_critical_evidence_policy()
    forbidden = inapplicable_inputs(asset_class, policy=selected)
    exempt = {item for item in not_applicable if item in forbidden}
    applicable = [item for item in configured if item not in exempt]
    used_set = {item for item in used if item in set(applicable)}
    floor = selected.quality_minimum_inputs if minimum is None else int(minimum)
    required = min(floor, len(applicable))
    coverage = len(used_set) / len(applicable) if applicable else 0.0
    missing = tuple(item for item in applicable if item not in used_set)
    if not used_set or not applicable:
        status = "unavailable"
    elif len(used_set) >= required:
        status = "complete"
    else:
        status = "partial"
    return InputCompleteness(status, len(used_set), len(applicable), required, round(coverage, 6), missing)


def score_authority_flags(
    gates: Iterable[CriticalGateResult],
    *,
    score_present: bool,
    quality_status: str | None = None,
    forecast_calibrated: bool = False,
    benchmark_eligible: bool = False,
) -> ScoreAuthorityFlags:
    """Derive the separate authority flags; unknown inputs stay False (fail closed)."""

    results = tuple(gates)
    gates_pass = bool(results) and all(result.passed for result in results)
    quality_ok = quality_status in (None, "complete")
    rankable = bool(score_present and gates_pass)
    safety = bool(gates_pass and quality_ok and quality_status is not None)
    if not score_present:
        status = INSUFFICIENT_LABEL
    elif not gates_pass:
        status = INSUFFICIENT_LABEL
    elif not quality_ok:
        status = "partial"
    else:
        status = "eligible"
    return ScoreAuthorityFlags(
        score_rankable=rankable,
        financial_safety_verified=safety,
        forecast_calibrated=bool(forecast_calibrated),
        benchmark_eligible=bool(benchmark_eligible),
        research_decision_status=status,
    )


def owner_claim_gate(claim_state: object) -> CriticalGateResult:
    """Sparebank owner-claim gate: the eierbrøk must be confirmed (reported or reconstructed) and the claim resolved."""

    def number(name: str) -> float | None:
        value = claim_state.get(name) if isinstance(claim_state, Mapping) else getattr(claim_state, name, None)
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    status = claim_state.get("claim_status") if isinstance(claim_state, Mapping) else getattr(claim_state, "claim_status", None)
    share = number("reconstructed_eierbrok")
    if share is None:
        share = number("reported_eierbrok")
    confirmed = share is not None and 0.0 < share <= 1.0 and str(status or "") == "resolved"
    if confirmed:
        return CriticalGateResult("owner_claim", "PASS", (), "EVIDENCE_PRESENT", "attractiveness")
    return CriticalGateResult(
        "owner_claim", "INSUFFICIENT_EVIDENCE", ("eierbrok", "equity_certificates"), "OWNER_CLAIM_NOT_CONFIRMED", "attractiveness"
    )


__all__ = [
    "CriticalEvidenceError",
    "CriticalEvidencePolicy",
    "GateDefinition",
    "INSUFFICIENT_LABEL",
    "InputCompleteness",
    "blocks_buy_label",
    "critical_asset_class",
    "evaluate_critical_gates",
    "failed_gate_groups",
    "failed_gates",
    "inapplicable_inputs",
    "input_completeness",
    "is_buy_label",
    "is_not_applicable",
    "load_critical_evidence_policy",
    "owner_claim_gate",
    "score_authority_flags",
]
