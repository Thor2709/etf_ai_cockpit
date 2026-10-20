"""Canonical v3 scoring contract shared by score and signal surfaces.

The contract deliberately keeps research attractiveness, model expected return,
risk/implementation quality and evidence confidence separate. The legacy
composite remains an explicitly named migration field until downstream readers
move to the separated outputs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Iterable, Mapping

import yaml

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.core.values import finite_float_or_none
from etf_cockpit.models.ensemble import BASELINE_SOURCE_FORECAST, BASELINE_SOURCE_HEURISTIC, effective_ensemble_weights

if TYPE_CHECKING:
    from etf_cockpit.analysis.decision.contracts import CriticalGateResult, ScoreAuthorityFlags


FORMULA_PATH = CONFIG_DIR / "score_engine_v3.yaml"
_BLOCKED_FRESHNESS = {"stale", "stale_block", "unavailable", "missing", "unknown", "not_checked"}
_MODEL_AUTHORITIES = {"model", "model_advisory"}
_LEGACY_WEIGHT_KEYS = {"baseline_ml": "baseline"}


class CanonicalScoreError(ValueError):
    """Raised when the versioned canonical score policy is invalid."""


# S3-02: model forecasts are a separate ``expected_return`` domain. Its weight in any rank is 0 until the #811
# promotion (with the paired #928 test) records an explicit finite weight; the ``expected_return`` group weights in
# ``score_engine_v3.yaml`` size that separate domain's own 0-10 value and are never rank weights.
RANK_DOMAINS = ("attractiveness", "risk_implementation")
FORECAST_DOMAIN = "expected_return"


def rank_domain_weights(
    policy: "ScorePolicy",
    *,
    forecast_promotion: Mapping[str, object] | None = None,
) -> dict[str, float]:
    """Rank weight per domain: the forecast domain is 0.0 unless a promotion record carries an explicit weight.

    Fails closed: a promotion without ``promoted is True``, the paired ``test_id`` and a finite ``weight`` in (0, 1]
    leaves the forecast weight at 0.0. The ranked domains are the policy's own group sums, unchanged.
    """

    weights = {group: float(sum(policy.groups.get(group, {}).values())) for group in RANK_DOMAINS}
    weight = 0.0
    if isinstance(forecast_promotion, Mapping) and forecast_promotion.get("promoted") is True and forecast_promotion.get("test_id"):
        candidate = finite_float_or_none(forecast_promotion.get("weight"))
        if candidate is not None and 0.0 < candidate <= 1.0:
            weight = candidate
    weights[FORECAST_DOMAIN] = weight
    return weights


@dataclass(frozen=True)
class ScorePolicy:
    formula_version: str
    formula_checksum: str
    horizon: str
    asset_type: str
    groups: dict[str, dict[str, float]]
    # Weights of the headline evidence composite (``headline_evidence`` in the yaml, zeros kept); empty when the file has none.
    headline_weights: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "formula_version": self.formula_version,
            "formula_checksum": self.formula_checksum,
            "horizon": self.horizon,
            "asset_type": self.asset_type,
            "groups": self.groups,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class CanonicalComponent:
    key: str
    raw_metric: float | None
    score_role: str
    peer_group: str
    source_id: str | None
    source_authority: str
    freshness_status: str
    uncertainty: str
    status: str
    explanation: str
    source_vintage_hash: str | None = None
    conflict_id: str | None = None
    as_of_date: str | None = None  # evidence date; the critical-evidence gates compare it with the decision date

    @property
    def eligible(self) -> bool:
        if self.raw_metric is None or not math.isfinite(float(self.raw_metric)):
            return False
        if not self.source_id or self.status.casefold() != "ok":
            return False
        if self.freshness_status.casefold() in _BLOCKED_FRESHNESS or self.conflict_id:
            return False
        if self.score_role != "expected_return" and self.source_authority.casefold() in _MODEL_AUTHORITIES:
            return False
        return True

    def as_dict(self, *, weight: float, contribution_raw: float | None) -> dict[str, object]:
        return {
            "key": self.key,
            "raw_metric": self.raw_metric,
            "score_role": self.score_role,
            "peer_group": self.peer_group,
            "source_id": self.source_id,
            "source_authority": self.source_authority,
            "freshness_status": self.freshness_status,
            "uncertainty": self.uncertainty,
            "status": self.status,
            "explanation": self.explanation,
            "source_vintage_hash": self.source_vintage_hash,
            "conflict_id": self.conflict_id,
            "weight": weight,
            "contribution_raw": contribution_raw,
            "score_eligible": self.eligible,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class CanonicalScore:
    instrument_id: str
    asset_type: str
    horizon: str
    decision_time: str
    formula_version: str
    formula_checksum: str
    source_vintage_hash: str
    attractiveness_10: float | None
    expected_return_10: float | None
    risk_implementation_10: float | None
    evidence_confidence_10: float | None
    coverage: float
    legacy_composite_raw: float | None
    components: tuple[dict[str, object], ...]
    contributions: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]
    explanations: tuple[str, ...]
    # Critical-evidence gating (#939); empty/None when the caller did not request gate evaluation.
    critical_gates: tuple["CriticalGateResult", ...] = ()
    insufficient_groups: tuple[str, ...] = ()
    authority: "ScoreAuthorityFlags | None" = None
    unavailable_reason: str | None = None  # "critical_domain_insufficient" | "insufficient_coverage": no 0-10 value shown

    @property
    def gate_failed(self) -> bool:
        return self.unavailable_reason is not None or any(not gate.passed for gate in self.critical_gates)

    @property
    def legacy_composite_10(self) -> float | None:
        if self.legacy_composite_raw is None:
            return None
        return round((_clamp(self.legacy_composite_raw) + 1.0) * 5.0, 1)

    @property
    def decision_distribution(self) -> dict[str, float | None]:
        """Return separated decision inputs for downstream policy consumers."""

        return {
            "attractiveness": _normalise_10(self.attractiveness_10),
            "expected_return": _normalise_10(self.expected_return_10),
            "risk_implementation": _normalise_10(self.risk_implementation_10),
            "evidence_confidence": _normalise_10(self.evidence_confidence_10),
            "coverage": self.coverage,
        }

    def as_dict(self) -> dict[str, object]:
        payload = self._base_dict()
        if self.critical_gates:
            payload["critical_gates"] = [
                {"gate_id": gate.gate_id, "status": gate.status, "missing": list(gate.missing), "reason_code": gate.reason_code}
                for gate in self.critical_gates
            ]
            payload["insufficient_groups"] = list(self.insufficient_groups)
            payload["unavailable_reason"] = self.unavailable_reason
            payload["authority"] = None if self.authority is None else self.authority.as_dict()
        return payload

    def _base_dict(self) -> dict[str, object]:
        return {
            "schema_version": 3,
            "instrument_id": self.instrument_id,
            "asset_type": self.asset_type,
            "horizon": self.horizon,
            "decision_time": self.decision_time,
            "formula_version": self.formula_version,
            "formula_checksum": self.formula_checksum,
            "source_vintage_hash": self.source_vintage_hash,
            "attractiveness_10": self.attractiveness_10,
            "expected_return_10": self.expected_return_10,
            "risk_implementation_10": self.risk_implementation_10,
            "evidence_confidence_10": self.evidence_confidence_10,
            "coverage": self.coverage,
            "legacy_composite_raw": self.legacy_composite_raw,
            "legacy_composite_10": self.legacy_composite_10,
            "decision_distribution": self.decision_distribution,
            "components": list(self.components),
            "contributions": list(self.contributions),
            "warnings": list(self.warnings),
            "explanations": list(self.explanations),
            "execution_allowed": False,
        }


# Asset types that share a configured policy. A plain Certificate is scored like a stock (value and
# quality weights); no other type may silently borrow the ETF policy.
_POLICY_ALIASES: dict[str, str] = {"CERTIFICATE": "STOCK", "EQUITY": "STOCK"}


_STOCK_LIKE_SIGNAL_TYPES = frozenset({"stock", "equity", "certificate", "equity_certificate", "equity certificate", "egenkapitalbevis"})


def resolve_policy_asset_type(asset_type: object) -> str:
    """Return the configured policy key for ``asset_type``; unknown types raise, never fall back to ETF."""

    key = str(asset_type or "").strip().upper()
    return _POLICY_ALIASES.get(key, key)


@lru_cache(maxsize=32)
def _parse_yaml_text(text: str) -> object:
    """Parse one exact policy text once; callers receive private copies."""

    return yaml.safe_load(text)


def load_score_policy(asset_type: str = "ETF", *, path: Path = FORMULA_PATH) -> ScorePolicy:
    if _is_sparebank_ec_asset_type(asset_type):
        raise CanonicalScoreError("EC instruments must use the native Sparebank scorecard")
    try:
        raw_bytes = path.read_bytes()
        normalised_bytes = raw_bytes.replace(b"\r\n", b"\n")
        payload = deepcopy(_parse_yaml_text(normalised_bytes.decode("utf-8"))) or {}
        formula_version = str(payload.get("formula_version") or "").strip()
        horizons = payload.get("horizons") or {}
        horizon = str(horizons.get("primary") or "").strip()
        policies = payload.get("asset_policies") or {}
        policy_key = resolve_policy_asset_type(asset_type)
        selected = policies.get(policy_key) if policy_key else None
        if not formula_version or not horizon:
            raise CanonicalScoreError("score_engine_v3.yaml is missing version or horizon")
        if not isinstance(selected, dict):
            raise CanonicalScoreError(f"no score policy is configured for asset type: {str(asset_type).strip() or 'unknown'}")
        groups: dict[str, dict[str, float]] = {}
        for group in ("attractiveness", "expected_return", "risk_implementation"):
            values = selected.get(group)
            if not isinstance(values, dict):
                raise CanonicalScoreError(f"score policy group is missing: {group}")
            group_weights: dict[str, float] = {}
            for key, value in values.items():
                number = finite_float_or_none(value)
                if number is None:
                    raise CanonicalScoreError("score policy weights must be finite numbers")
                if number > 0:
                    group_weights[str(key)] = number
            groups[group] = group_weights
            if sum(groups[group].values()) <= 0:
                raise CanonicalScoreError(f"score policy group has no positive weights: {group}")
        headline: dict[str, float] = {}
        headline_block = selected.get("headline_evidence")
        if headline_block is not None:
            if not isinstance(headline_block, dict):
                raise CanonicalScoreError("score policy headline_evidence must be a mapping")
            for key, value in headline_block.items():
                number = finite_float_or_none(value)
                if number is None or number < 0 or isinstance(value, bool):
                    raise CanonicalScoreError("score policy headline weights must be finite non-negative numbers")
                headline[str(key)] = number
            if sum(headline.values()) <= 0:
                raise CanonicalScoreError("score policy headline_evidence has no positive weights")
        return ScorePolicy(formula_version, hashlib.sha256(normalised_bytes).hexdigest(), horizon, policy_key, groups, headline)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        if isinstance(exc, CanonicalScoreError):
            raise
        raise CanonicalScoreError(f"could not load canonical score policy: {type(exc).__name__}") from exc


def headline_evidence_weights(policy_key: str, *, path: Path | None = None) -> dict[str, float]:
    """Headline evidence-composite weights of the ``ETF`` or ``STOCK`` policy from the versioned yaml (the only source).

    Fails closed (``CanonicalScoreError``) when the yaml carries no ``headline_evidence`` for the policy.
    """

    key = str(policy_key).strip().upper()
    if key not in {"ETF", "STOCK"}:
        raise CanonicalScoreError(f"no headline weights for policy: {policy_key!r}")
    policy_path = path or FORMULA_PATH
    stat = policy_path.stat()
    return dict(_headline_weights_cached(str(policy_path), stat.st_mtime_ns, stat.st_size, key))


@lru_cache(maxsize=16)
def _headline_weights_cached(path: str, mtime_ns: int, size: int, key: str) -> tuple[tuple[str, float], ...]:
    weights = load_score_policy(key, path=Path(path)).headline_weights
    if not weights:
        raise CanonicalScoreError(f"score policy has no headline_evidence weights for {key}")
    return tuple(weights.items())


def build_canonical_score(
    *,
    instrument_id: str,
    asset_type: str,
    decision_time: str | date,
    components: Iterable[CanonicalComponent],
    legacy_component_weights: Mapping[str, float] | None = None,
    legacy_penalties: Mapping[str, float] | None = None,
    policy: ScorePolicy | None = None,
    source_vintage_hash: str | None = None,
    structure_confidence_cap: float | None = None,
    structure_provenance: Mapping[str, object] | None = None,
    critical_evidence: Iterable[str] | Mapping[str, object] | None = None,
    business_model: str | None = None,
    quality_status: str | None = None,
    forecast_calibrated: bool = False,
    benchmark_eligible: bool = False,
) -> CanonicalScore:
    """Build the canonical score.

    ``critical_evidence`` opts into the score gate (#939; ``None`` is the ungated calculation primitive, every
    score entry point passes it): ids of evidence the caller holds beyond the eligible component keys (for example
    ``market_cap`` or ``identity``), as a mapping to their as-of dates. A group tied to a failed gate is
    ``insufficient_evidence`` (no score), never averaged up from its other inputs; stale or invalid critical
    evidence, coverage below the policy minimum, or no non-price component makes the whole score unavailable. A
    component reported not applicable leaves the group denominator only when the ``business_model`` definition
    forbids it. A ``quality_status`` other than ``complete`` makes ``stock_quality`` partial and score-ineligible.
    """

    if _is_sparebank_ec_asset_type(asset_type):
        raise CanonicalScoreError("EC instruments must use the native Sparebank scorecard")
    selected_policy = policy or load_score_policy(asset_type)
    timestamp = str(decision_time.isoformat() if isinstance(decision_time, date) else decision_time)
    raw_components = tuple(components)
    warnings: list[str] = []
    source_components_list: list[CanonicalComponent] = []
    seen_components: set[tuple[str, str]] = set()
    for component in raw_components:
        identity = (_component_group(component), component.key)
        if identity in seen_components:
            warning = f"duplicate_component:{component.key}"
            if warning not in warnings:
                warnings.append(warning)
            continue
        seen_components.add(identity)
        source_components_list.append(component)
    if quality_status is not None and quality_status != "complete":
        # Below the minimum input count the quality component is partial: it adds no active weight and no coverage.
        source_components_list = [
            replace(component, status="partial")
            if component.key == "stock_quality" and component.status.casefold() == "ok"
            else component
            for component in source_components_list
        ]
    source_components = tuple(source_components_list)
    gates_module = _gates() if (critical_evidence is not None or business_model) else None
    forbidden_inapplicable: frozenset[str] = frozenset()
    if gates_module is not None and business_model:
        forbidden_inapplicable = gates_module.inapplicable_inputs(gates_module.critical_asset_class(asset_type, business_model))
    critical_gates: tuple[Any, ...] = ()
    insufficient: dict[str, tuple[str, ...]] = {}
    unavailable_reason: str | None = None
    if gates_module is not None and critical_evidence is not None:
        held: dict[str, object] = {component.key: component.as_of_date for component in source_components if component.eligible}
        for item, as_of in gates_module.evidence_as_of(critical_evidence).items():
            if as_of is not None or item not in held:
                held[item] = as_of
        decision = gates_module.evaluate_score_gate(
            gates_module.critical_asset_class(asset_type, business_model),
            held,
            decision_time=timestamp,
            coverage=_eligible_coverage(selected_policy, source_components, forbidden_inapplicable, gates_module),
            eligible_components=[component.key for component in source_components if component.eligible],
        )
        critical_gates = decision.gates
        unavailable_reason = decision.unavailable_reason
        insufficient = gates_module.failed_gate_groups(critical_gates)
        for gate in gates_module.failed_gates(critical_gates):
            warnings.append(f"critical_gate:{gate.gate_id}:{gate.reason_code}")
        if unavailable_reason is not None:
            warnings.append(f"score_unavailable:{unavailable_reason}")
    group_results: dict[str, tuple[float | None, float, list[dict[str, object]], list[dict[str, object]]]] = {}
    all_component_rows: list[dict[str, object]] = []
    contributions: list[dict[str, object]] = []
    explanations: list[str] = []
    total_configured = 0.0
    total_active = 0.0
    discarded_keys: set[str] = set()
    for group, weights in selected_policy.groups.items():
        configured = sum(weights.values())
        active_weight = 0.0
        exempt_weight = 0.0
        weighted = 0.0
        group_rows: list[dict[str, object]] = []
        group_contributions: list[dict[str, object]] = []
        for component in source_components:
            if _component_group(component) != group:
                continue
            weight = float(weights.get(component.key, 0.0))
            if weight <= 0:
                continue
            contribution = None
            if (
                not component.eligible
                and component.key in forbidden_inapplicable
                and gates_module is not None
                and gates_module.is_not_applicable(component.status)
            ):
                # The sector definition forbids this metric: it leaves the denominator instead of lowering coverage.
                exempt_weight += weight
                warnings.append(f"not_applicable:{component.key}")
                group_rows.append(component.as_dict(weight=weight, contribution_raw=None))
                continue
            if component.eligible:
                active_weight += weight
                contribution = _clamp(float(component.raw_metric)) * weight
                weighted += contribution
                group_contributions.append({"key": component.key, "group": group, "contribution_raw": contribution})
                explanations.append(f"{component.key}: {component.explanation}")
            group_rows.append(component.as_dict(weight=weight, contribution_raw=contribution))
        configured -= exempt_weight
        score = None if active_weight <= 0 else _score_10(weighted / active_weight)
        if group in insufficient:
            # A failed critical gate: the remaining inputs are never averaged up into an attractive score, and the
            # discarded group's evidence counts neither toward coverage/confidence nor as a contribution.
            score = None
            active_weight = 0.0
            group_contributions = []
            for row in group_rows:
                row["contribution_raw"] = None
                row["score_counted"] = False
            discarded_keys.update(str(row["key"]) for row in group_rows)
            warnings.append(f"{group}_insufficient_evidence:{','.join(insufficient[group])}")
        coverage = active_weight / configured if configured > 0 else 0.0
        if coverage < 1.0:
            warnings.append(f"{group}_coverage:{coverage:.3f}")
        total_configured += configured
        total_active += active_weight
        group_results[group] = (score, coverage, group_rows, group_contributions)
        for contribution in group_contributions:
            contribution["contribution_raw"] = round(float(contribution["contribution_raw"]) / active_weight, 10) if active_weight else None
        all_component_rows.extend(group_rows)
        contributions.extend(group_contributions)
    overall_coverage = total_active / total_configured if total_configured else 0.0
    confidence = _confidence_score([c for c in source_components if c.key not in discarded_keys], overall_coverage)
    if unavailable_reason is not None:
        # An unavailable score shows no 0-10 value, confidence or contribution (never a guessed or shrunk number).
        confidence = None
        contributions = []
        for row in all_component_rows:
            row["contribution_raw"] = None
            row["score_counted"] = False
        group_results = {name: (None, *rest) for name, (_, *rest) in group_results.items()}
    structure_identity = dict(structure_provenance or {})
    if structure_confidence_cap is not None:
        cap = _bounded_structure_cap(structure_confidence_cap)
        confidence = None if confidence is None else round(min(confidence, 10.0 * cap), 1)
        warnings.append(f"structure_confidence_cap:{cap:.3f}")
        structure_identity["structure_confidence_cap"] = cap
    legacy_raw = None if unavailable_reason is not None else _legacy_composite(source_components, legacy_component_weights, legacy_penalties)
    vintage_hash = source_vintage_fingerprint(
        source_components,
        timestamp,
        source_vintage_hash=source_vintage_hash,
        structure_provenance=structure_identity or None,
    )
    authority = None
    if gates_module is not None and critical_gates:
        authority = gates_module.score_authority_flags(
            critical_gates,
            score_present=any(group_results[name][0] is not None for name in group_results)
            and not insufficient
            and unavailable_reason is None,
            quality_status=quality_status,
            forecast_calibrated=forecast_calibrated,
            benchmark_eligible=benchmark_eligible,
        )
    return CanonicalScore(
        instrument_id=str(instrument_id),
        asset_type=str(asset_type).upper(),
        horizon=selected_policy.horizon,
        decision_time=timestamp,
        formula_version=selected_policy.formula_version,
        formula_checksum=selected_policy.formula_checksum,
        source_vintage_hash=vintage_hash,
        attractiveness_10=group_results["attractiveness"][0],
        expected_return_10=group_results["expected_return"][0],
        risk_implementation_10=group_results["risk_implementation"][0],
        evidence_confidence_10=confidence,
        coverage=round(overall_coverage, 6),
        legacy_composite_raw=legacy_raw,
        components=tuple(all_component_rows),
        contributions=tuple(contributions),
        warnings=tuple(dict.fromkeys(warnings)),
        explanations=tuple(dict.fromkeys(explanations)),
        critical_gates=critical_gates,
        insufficient_groups=tuple(insufficient),
        authority=authority,
        unavailable_reason=unavailable_reason,
    )


def apply_structure_confidence_cap(score: CanonicalScore, cap: float) -> CanonicalScore:
    """Cap evidence confidence only; preserve attractiveness and return outputs."""

    bounded = _bounded_structure_cap(cap)
    confidence = None if score.evidence_confidence_10 is None else round(min(score.evidence_confidence_10, 10.0 * bounded), 1)
    warning = f"structure_confidence_cap:{bounded:.3f}"
    return replace(score, evidence_confidence_10=confidence, warnings=tuple(dict.fromkeys((*score.warnings, warning))))


def _canonical_component_from_simple(component: Any) -> CanonicalComponent:
    """The one conversion of a score-component record (simple or signal-row) into a canonical component."""

    return CanonicalComponent(
        key=str(getattr(component, "key", "")),
        raw_metric=_number(getattr(component, "raw_score", None)),
        score_role=_component_group_name(str(getattr(component, "score_role", "evidence"))),
        peer_group=str(getattr(component, "peer_group", None) or "universe"),
        source_id=str(getattr(component, "source_id", "") or "") or None,
        source_authority=str(getattr(component, "source_authority", "unknown") or "unknown"),
        freshness_status=str(getattr(component, "freshness_status", "unknown") or "unknown"),
        uncertainty=_uncertainty(getattr(component, "evidence_quality", None)),
        status="ok" if str(getattr(component, "status", "")).casefold() == "ok" else str(getattr(component, "status", "unavailable")),
        explanation=str(getattr(component, "why", "") or getattr(component, "explanation", "") or "Score component evidence."),
        source_vintage_hash=str(getattr(component, "source_vintage_hash", "") or "") or None,
        conflict_id=str(getattr(component, "conflict_id", "") or "") or None,
        as_of_date=str(getattr(component, "as_of_date", "") or "") or None,
    )


def canonical_score_from_simple_components(
    instrument_id: str,
    asset_type: str,
    decision_time: str,
    components: Iterable[Any],
    *,
    critical_evidence: Iterable[str] | Mapping[str, object] | None = None,
    business_model: str | None = None,
    legacy_component_weights: Mapping[str, float] | None = None,
    legacy_penalties: Mapping[str, float] | None = None,
    structure_confidence_cap: float | None = None,
    structure_provenance: Mapping[str, object] | None = None,
) -> CanonicalScore:
    """Canonical score of score components, always through the score gate (extra ``critical_evidence`` optional).

    The one shared v3 entry point: the simple-score builder and the signal-row builder
    (:func:`canonical_score_from_signal_row`) both end here, so the same components give the same v3 value.
    """

    if _is_sparebank_ec_asset_type(asset_type):
        raise CanonicalScoreError("EC instruments must use the native Sparebank scorecard")
    source = tuple(components)
    converted = tuple(_canonical_component_from_simple(component) for component in source)
    evidence: dict[str, object] = {}
    for original in source:
        for item in getattr(original, "inputs_used", ()) or ():
            if getattr(original, "as_of_date", None) is not None or str(item) not in evidence:
                evidence[str(item)] = getattr(original, "as_of_date", None)
    for item, as_of in _gates().evidence_as_of(critical_evidence or ()).items():
        if as_of is not None or item not in evidence:
            evidence[item] = as_of
    return build_canonical_score(
        instrument_id=instrument_id,
        asset_type=asset_type,
        decision_time=decision_time,
        components=converted,
        critical_evidence=evidence,
        business_model=business_model,
        quality_status=simple_quality_status(source, asset_type, business_model),
        legacy_component_weights=legacy_component_weights,
        legacy_penalties=legacy_penalties,
        structure_confidence_cap=structure_confidence_cap,
        structure_provenance=structure_provenance,
    )


def simple_quality_status(components: Iterable[Any], asset_type: str, business_model: str | None = None) -> str | None:
    """``complete`` / ``partial`` / ``unavailable`` for the stock quality component; ``None`` when there is none (ETFs)."""

    quality = next((component for component in components if getattr(component, "key", None) == "stock_quality"), None)
    if quality is None:
        return None
    gates = _gates()
    configured = tuple(getattr(quality, "inputs_configured", ()) or ())
    if not configured:
        # No per-input detail: completeness cannot be verified, so a numeric quality score is only partial.
        return "partial" if _number(getattr(quality, "raw_score", None)) is not None else "unavailable"
    asset_class = gates.critical_asset_class(asset_type, business_model)
    result = gates.input_completeness(
        configured,
        tuple(getattr(quality, "inputs_used", ()) or ()),
        not_applicable=tuple(getattr(quality, "inputs_not_applicable", ()) or ()),
        asset_class=asset_class,
    )
    return result.status


def canonical_score_from_signal_row(
    row: Mapping[str, object],
    config: AppConfig,
    decision_time: str | date,
    *,
    toto_available: bool = False,
    timesfm_available: bool = False,
    structure_confidence_cap: float | None = None,
    structure_provenance: Mapping[str, object] | None = None,
) -> CanonicalScore:
    if any(
        _is_sparebank_ec_asset_type(row.get(name))
        for name in ("asset_type", "instrument_type", "instrument_subtype", "capital_class")
    ):
        raise CanonicalScoreError("EC instruments must use the native Sparebank scorecard")
    instrument_id = str(row.get("etf_id") or row.get("instrument_id") or "unknown")
    freshness = row.get("price_freshness")
    price_freshness = str(freshness).strip().casefold() if freshness is not None else "unknown"
    if price_freshness in {"", "none", "nan", "<na>"}:
        price_freshness = "unknown"
    source = "yfinance:prices"
    # The row is computed at the signal date: its evidence is dated with it while the price freshness is ok.
    signal_day = str(decision_time.isoformat() if isinstance(decision_time, date) else decision_time)[:10]
    as_of = signal_day if price_freshness == "ok" else None
    # Portfolio drift (score_rebalance) is not a component: an instrument's score never depends on the portfolio.
    baseline_source = row.get("score_baseline_source")
    forecast_baseline = isinstance(baseline_source, str) and baseline_source == BASELINE_SOURCE_FORECAST
    heuristic_baseline = isinstance(baseline_source, str) and baseline_source == BASELINE_SOURCE_HEURISTIC
    baseline_explanation = (
        "Unavailable as a model: price heuristic (momentum/trend fallback, no forecast); shown for display only, "
        "carries no score weight and no coverage."
        if heuristic_baseline
        else "Baseline expected-return evidence."
        if forecast_baseline
        else "Unavailable: missing or unrecognised baseline provenance; explicit forecast provenance is required."
    )
    components = [
        _signal_component("momentum", row.get("score_momentum"), "attractiveness", source, price_freshness, "Momentum evidence.", as_of),
        _signal_component("trend", row.get("score_trend"), "attractiveness", source, price_freshness, "Trend evidence.", as_of),
        _signal_component("relative_strength", row.get("score_relative_strength"), "attractiveness", source, price_freshness, "Relative-strength evidence.", as_of),
        _signal_component("etf_exposure", row.get("score_etf_exposure"), "attractiveness", "yfinance:holdings", price_freshness, "ETF exposure evidence.", as_of),
        _signal_component("risk", row.get("score_risk"), "risk_implementation", source, price_freshness, "Risk quality evidence.", as_of),
        _signal_component("liquidity_cost", _liquidity_quality(row.get("cost_penalty")), "risk_implementation", source, price_freshness, "Configured cost quality.", as_of),
        # A heuristic baseline re-uses price strength: unavailable as expected-return evidence (value kept for display).
        _signal_component(
            "baseline", row.get("score_baseline_ml"), "expected_return",
            "heuristic:momentum_trend" if heuristic_baseline else "model:baseline" if forecast_baseline else "",
            price_freshness, baseline_explanation, as_of, authority="model_advisory",
            status="ok" if forecast_baseline else "unavailable",
        ),
        _signal_component("timesfm", row.get("score_timesfm"), "expected_return", "model:timesfm", price_freshness, "TimesFM challenger expected-return evidence.", as_of, authority="model_advisory", status="ok" if timesfm_available else "unavailable"),
        _signal_component("toto", row.get("score_toto"), "expected_return", "model:toto", price_freshness, "Toto challenger expected-return evidence.", as_of, authority="model_advisory", status="ok" if toto_available else "unavailable"),
        # Optional manual input (action composite only; no v3 group weight): eligible only when a value was supplied.
        _signal_component("chatgpt_thesis", row.get("score_chatgpt_thesis"), "expected_return", "manual:chatgpt_thesis", price_freshness, "Manual ChatGPT thesis input.", as_of, authority="model_advisory"),
    ]
    weights = effective_ensemble_weights(
        config.models.ensemble.get("weights", {}),
        toto_available=toto_available,
        timesfm_available=timesfm_available,
    )
    if not forecast_baseline:
        # Only explicitly forecast-backed values carry legacy action-composite weight.
        weights = {key: value for key, value in weights.items() if key != "baseline_ml"}
    return canonical_score_from_simple_components(
        instrument_id,
        _signal_asset_type(row, config, instrument_id),
        decision_time if isinstance(decision_time, str) else decision_time.isoformat(),
        components,
        legacy_component_weights=_legacy_component_weights(weights),
        legacy_penalties={
            "cost_penalty": _number(row.get("cost_penalty")) or 0.0,
            "turnover_penalty": _number(row.get("turnover_penalty")) or 0.0,
        },
        structure_confidence_cap=structure_confidence_cap,
        structure_provenance=structure_provenance,
        critical_evidence={"identity": None} if instrument_id != "unknown" else (),
    )


def source_vintage_fingerprint(
    components: Iterable[CanonicalComponent],
    decision_time: str,
    *,
    source_vintage_hash: str | None = None,
    structure_provenance: Mapping[str, object] | None = None,
) -> str:
    payload = {
        "decision_time": decision_time,
        "sources": sorted(
            (
                {
                    "source_id": component.source_id,
                    "source_vintage_hash": component.source_vintage_hash,
                }
                for component in components
                if component.source_id
            ),
            key=lambda value: (str(value["source_id"]), str(value["source_vintage_hash"])),
        ),
    }
    if source_vintage_hash is not None:
        payload["source_vintage_hash"] = source_vintage_hash
    if structure_provenance:
        payload["structure_provenance"] = dict(structure_provenance)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _eligible_coverage(
    policy: ScorePolicy,
    components: Iterable[CanonicalComponent],
    forbidden_inapplicable: frozenset[str],
    gates_module: Any,
) -> float:
    """Share of the configured weight held by eligible components, before any gate discards a group."""

    components = tuple(components)
    configured_total = 0.0
    active_total = 0.0
    for group, weights in policy.groups.items():
        configured = sum(weights.values())
        for component in components:
            weight = float(weights.get(component.key, 0.0))
            if _component_group(component) != group or weight <= 0:
                continue
            if component.eligible:
                active_total += weight
            elif component.key in forbidden_inapplicable and gates_module.is_not_applicable(component.status):
                configured -= weight
        configured_total += configured
    return active_total / configured_total if configured_total > 0 else 0.0


def _gates():
    """Late import: the decision package is heavy and imports signal modules."""

    from etf_cockpit.analysis.decision import gates

    return gates


def _component_group(component: CanonicalComponent) -> str:
    role = _component_group_name(component.score_role)
    return role if role in {"attractiveness", "expected_return", "risk_implementation"} else "attractiveness"


def _component_group_name(role: str) -> str:
    value = str(role).casefold()
    if value in {"risk", "risk_friction", "risk_implementation"}:
        return "risk_implementation"
    if value in {"model_confirmation", "expected_return", "forecast"}:
        return "expected_return"
    return "attractiveness"


def _confidence_score(components: Iterable[CanonicalComponent], coverage: float) -> float | None:
    eligible = [component for component in components if component.eligible]
    if not eligible:
        return None
    values = []
    for component in eligible:
        authority = {
            "official_regulator": 1.0,
            "official_filing": 1.0,
            "issuer_document": 0.9,
            "vendor_verified": 0.8,
            "vendor_unofficial": 0.6,
            "model_advisory": 0.25,
        }.get(component.source_authority.casefold(), 0.3)
        freshness = 1.0 if component.freshness_status.casefold() == "ok" else 0.5
        uncertainty = {"low": 1.0, "medium": 0.8, "high": 0.5}.get(component.uncertainty.casefold(), 0.4)
        values.append(authority * freshness * uncertainty)
    return round(max(0.0, min(10.0, 10.0 * (sum(values) / len(values)) * coverage)), 1)


def _bounded_structure_cap(value: object) -> float:
    try:
        cap = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return cap if math.isfinite(cap) and 0.0 <= cap <= 1.0 else 0.0


def _legacy_composite(
    components: Iterable[CanonicalComponent],
    weights: Mapping[str, float] | None,
    penalties: Mapping[str, float] | None,
) -> float | None:
    if not weights:
        return None
    values = {
        component.key: _number(component.raw_metric)
        for component in components
        if component.eligible and _number(component.raw_metric) is not None
    }
    active_weights = {key: float(weight) for key, weight in weights.items() if key in values and float(weight) > 0}
    weight_total = sum(active_weights.values())
    if not values or weight_total <= 0:
        return None
    result = sum(weight * float(values[key]) for key, weight in active_weights.items()) / weight_total
    for key, penalty in (penalties or {}).items():
        result -= max(0.0, float(penalty))
    return round(_clamp(result), 4)


def _legacy_component_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Map ensemble weight keys onto canonical component keys (baseline_ml -> baseline)."""

    mapped: dict[str, float] = {}
    for key, value in weights.items():
        canonical_key = _LEGACY_WEIGHT_KEYS.get(str(key), str(key))
        mapped[canonical_key] = mapped.get(canonical_key, 0.0) + float(value)
    return mapped


def _signal_asset_type(row: Mapping[str, object], config: object, instrument_id: str) -> str:
    """Resolve the scoring policy from the row, else the configured instrument; default ETF."""

    declared = next(
        (value for value in (row.get("asset_type"), row.get("instrument_type")) if isinstance(value, str) and value.strip()),
        None,
    )
    if declared is None:
        universe = getattr(config, "universe", None)
        lookup = getattr(universe, "by_id", None)
        identity = lookup().get(instrument_id) if callable(lookup) else None
        declared = getattr(identity, "instrument_type", None)
    text = str(declared or "").strip()
    if not text:
        return "ETF"  # undeclared rows are the ETF universe; a declared unknown type raises in load_score_policy
    if text.casefold() in _STOCK_LIKE_SIGNAL_TYPES:
        return "STOCK"  # price-signal path only: certificates and ECs are stock-like, never ETF-weighted
    return "ETF" if text.casefold() == "etf" else text


def _signal_component(key: str, raw: object, role: str, source_id: str, freshness: str, explanation: str, as_of: str | None, *, authority: str = "vendor_unofficial", status: str = "ok") -> SimpleNamespace:
    """A signal-row score input in the record shape :func:`canonical_score_from_simple_components` converts."""

    return SimpleNamespace(
        key=key, raw_score=raw, score_role=role, peer_group="configured-universe", source_id=source_id,
        source_authority=authority, freshness_status=freshness, evidence_quality=5.0, status=status,
        why=explanation, as_of_date=as_of,
    )


def _liquidity_quality(value: object) -> float | None:
    penalty = _number(value)
    return None if penalty is None else _clamp(1.0 - penalty / 0.08)


def _uncertainty(value: object) -> str:
    try:
        quality = float(value)
    except (TypeError, ValueError):
        return "high"
    return "low" if quality >= 8 else "medium" if quality >= 5 else "high"


def _number(value: object) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def _score_10(value: float) -> float:
    return round((_clamp(value) + 1.0) * 5.0, 1)


def _normalise_10(value: float | None) -> float | None:
    return None if value is None else round(max(0.0, min(1.0, float(value) / 10.0)), 6)


def _is_sparebank_ec_asset_type(value: object) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return normalized in {"ec", "equity_certificate", "egenkapitalbevis"}
