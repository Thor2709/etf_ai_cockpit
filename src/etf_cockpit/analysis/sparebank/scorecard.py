"""Pure, coverage-aware Sparebank scorecard over the native analysis contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Mapping

import yaml

from etf_cockpit.core.paths import CONFIG_DIR

from .models import SparebankScorecard, UNAVAILABLE


SCORECARD_CONFIG_PATH = CONFIG_DIR / "sparebank_scorecard_v1.yaml"


class SparebankScorecardError(ValueError):
    """Raised when the versioned Sparebank scoring policy is invalid."""


@dataclass(frozen=True)
class SparebankScorecardPolicy:
    formula_version: str
    formula_checksum: str
    judgement_version: str
    judgement_status: str
    judgement_source: str
    horizons: Mapping[str, str]
    hard_gates: Mapping[str, object]
    scorecard: Mapping[str, object]
    axes: Mapping[str, object]
    # Assumptions (not evidence) the book itself uses in its worked examples; labelled wherever shown.
    valuation_defaults: Mapping[str, object] = field(default_factory=dict)


def load_sparebank_scorecard_policy(path: Path = SCORECARD_CONFIG_PATH) -> SparebankScorecardPolicy:
    """Load the dedicated scorecard config and hash its LF-normalised bytes."""

    try:
        normalized = path.read_bytes().replace(b"\r\n", b"\n")
        payload = yaml.safe_load(normalized.decode("utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SparebankScorecardError(f"could not load Sparebank scorecard policy: {type(exc).__name__}") from exc
    judgement = payload.get("judgement")
    scorecard = payload.get("scorecard", {})
    axes = payload.get("axes")
    if (
        not isinstance(payload, Mapping)
        or not str(payload.get("formula_version") or "").strip()
        or not isinstance(judgement, Mapping)
        or not isinstance(scorecard, Mapping)
        or not isinstance(axes, Mapping)
        or not isinstance(payload.get("hard_gates"), Mapping)
    ):
        raise SparebankScorecardError("Sparebank scorecard policy is missing versioned rules")
    for axis_id, definition in axes.items():
        if not isinstance(definition, Mapping) or not isinstance(definition.get("inputs"), list):
            raise SparebankScorecardError(f"invalid Sparebank scorecard axis: {axis_id}")
        for item in definition["inputs"]:
            if not isinstance(item, Mapping) or not isinstance(item.get("anchors"), list) or len(item["anchors"]) < 2:
                raise SparebankScorecardError(f"invalid Sparebank scorecard anchors: {axis_id}")
    return SparebankScorecardPolicy(
        formula_version=str(payload["formula_version"]),
        formula_checksum=hashlib.sha256(normalized).hexdigest(),
        judgement_version=str(judgement.get("version") or ""),
        judgement_status=str(judgement.get("status") or ""),
        judgement_source=str(judgement.get("source") or ""),
        horizons=dict(payload.get("horizons") or {}),
        hard_gates=dict(payload["hard_gates"]),
        scorecard=dict(scorecard),
        axes=dict(axes),
        valuation_defaults=dict(payload.get("valuation_defaults") or {}),
    )


def build_sparebank_scorecard(
    analysis: object,
    *,
    decision_time: str | datetime | None,
    decision_price: object = None,
    valuation_assumptions: Mapping[str, object] | None = None,
    tactical_evidence: Mapping[str, object] | None = None,
    policy: SparebankScorecardPolicy | None = None,
) -> SparebankScorecard:
    """Rate only supplied analysis evidence; tactical evidence never enters ratings."""

    selected = policy or load_sparebank_scorecard_policy()
    route = _field(analysis, "routing")
    if not bool(_field(route, "applies", False)):
        reasons = _field(route, "reason_codes", ())
        route_reasons = tuple(str(reason) for reason in reasons) or ("SPAREBANK_ROUTE_NOT_APPLICABLE",)
        return _empty_scorecard(selected, route_reasons)

    claim = _field(analysis, "claim_state")
    bank = _field(analysis, "bank_economics")
    valuation = _field(analysis, "valuation")
    events = _field(analysis, "events")
    assumptions = dict(valuation_assumptions or {})
    price = _number(decision_price)
    reasons: list[str] = []

    if str(_field(claim, "claim_status", "partial")).casefold() != "resolved":
        reasons.append("OWNER_CLAIM_UNRESOLVED")
    pit_status, pit_reason = _pit_check(_field(claim, "known_at"), decision_time)
    if pit_status is not True:
        reasons.append(pit_reason)
    if decision_price is not None and price is None:
        reasons.append("INVALID_VALUATION_DENOMINATOR")
    elif price is not None and price <= 0:
        reasons.append("INVALID_VALUATION_DENOMINATOR")

    context = {
        "analysis": analysis,
        "claim_state": claim,
        "bank_economics": bank,
        "claim": claim,
        "bank": bank,
        "valuation": valuation,
        "events": events,
        "assumptions": assumptions,
        "decision_price": price,
    }
    axes: dict[str, object] = {}
    raw_values: dict[str, float | None] = {}
    for axis_id, definition in selected.axes.items():
        axis = dict(definition)
        rated_inputs: list[dict[str, object]] = []
        for input_rule in axis.get("inputs", []):
            row = dict(input_rule)
            value = _input_value(row, context)
            scored = not bool(row.get("display_only"))
            rating = None if value is None or not scored else _rating(value, row["anchors"])
            bank_reasons = _field(bank, "reasons", {})
            reason_text = None
            if value is None:
                reason_text = (bank_reasons.get(str(row["id"])) if isinstance(bank_reasons, Mapping) else None) or row.get("missing_reason")
            row.update(
                value=value,
                rating_10=rating,
                scored=scored,
                status=("rated" if scored else "shown") if value is not None else "UNAVAILABLE",
                reason_code=None if value is not None else "SCORECARD_INPUT_UNAVAILABLE",
                reason=reason_text,
            )
            rated_inputs.append(row)
            raw_values[str(row["id"])] = value
        scored_inputs = [row for row in rated_inputs if row["scored"]]
        available = [row for row in scored_inputs if row["rating_10"] is not None]
        defined_count = len(scored_inputs)
        coverage = len(available) / defined_count if defined_count else 0.0
        rating = None if not available else round(sum(float(row["rating_10"]) for row in available) / len(available), 6)
        axis.update(
            status="UNAVAILABLE" if not available else "partial" if coverage < 1.0 else "rated",
            rating_10=rating,
            coverage=coverage,
            inputs=tuple(rated_inputs),
            missing_inputs=tuple(str(row["id"]) for row in scored_inputs if row["rating_10"] is None),
            calculation_ids=tuple(dict.fromkeys(str(row["calculation_id"]) for row in rated_inputs)),
            rule_version=selected.judgement_version,
            threshold_label="judgement",
            critical=bool(axis.get("critical")),
        )
        if axis_id == "owner_claim_integrity" and (
            str(_field(claim, "claim_status", "partial")).casefold() != "resolved"
            or "KOMPENSASJONSFOND_NOT_REPORTED" in _field(claim, "reason_codes", ())
        ):
            claim_coverage = _number(_field(claim, "coverage"))
            axis["coverage"] = min(coverage, claim_coverage) if claim_coverage is not None else 0.0
            axis["status"] = "partial"
        if axis_id == "owner_claim_integrity" and "KOMPENSASJONSFOND_NOT_REPORTED" in _field(claim, "reason_codes", ()):
            axis["partial_reason"] = "kompensasjonsfond not reported"
        axes[str(axis_id)] = axis

    coverage_values = [float(_field(axis, "coverage", 0.0)) for axis in axes.values()]
    overall_coverage = sum(coverage_values) / len(selected.axes) if selected.axes else 0.0
    weights = _axis_weights(selected)
    total_weight = sum(weights.values())
    composite_coverage = (
        sum(weights[axis_id] * float(_field(axis, "coverage", 0.0)) for axis_id, axis in axes.items()) / total_weight
        if total_weight > 0
        else 0.0
    )
    missing_axes = tuple(
        axis_id for axis_id, axis in axes.items()
        if float(_field(axis, "coverage", 0.0)) < 1.0
    )
    critical_axes = tuple(axis_id for axis_id, definition in selected.axes.items() if definition.get("critical"))
    rated = [
        (weights[axis_id], float(_field(axis, "rating_10")))
        for axis_id, axis in axes.items()
        if _field(axis, "rating_10") is not None and weights[axis_id] > 0
    ]
    minimum_coverage = _number(_field(selected.scorecard, "min_coverage_for_composite", 0.25))
    if minimum_coverage is None or not 0.0 <= minimum_coverage <= 1.0:
        raise SparebankScorecardError("min_coverage_for_composite must be between 0 and 1")
    if composite_coverage < minimum_coverage:
        reasons.append("MINIMUM_COMPOSITE_COVERAGE_NOT_MET")
    before_cap = (
        round(sum(weight * rating for weight, rating in rated) / sum(weight for weight, _ in rated), 6)
        if composite_coverage >= minimum_coverage and rated
        else None
    )
    caps: list[tuple[float, str]] = []
    if before_cap is not None:
        headroom = raw_values.get("cet1_headroom_pp")
        lcr = raw_values.get("lcr_pct")
        nsfr = raw_values.get("nsfr_pct")
        days = raw_values.get("days_to_trade")
        gates = selected.hard_gates
        if headroom is not None and headroom < float(gates["cet1_headroom_minimum_pp"]):
            caps.append((float(gates["cap_headroom_below_requirement"]), "CET1_HEADROOM_BELOW_REQUIREMENT"))
        if lcr is not None and lcr < float(gates["lcr_minimum_pct"]):
            caps.append((float(gates["cap_lcr_below_minimum"]), "LCR_BELOW_MINIMUM"))
        if nsfr is not None and nsfr < float(gates["nsfr_minimum_pct"]):
            caps.append((float(gates["cap_nsfr_below_minimum"]), "NSFR_BELOW_MINIMUM"))
        if days is not None and days > float(gates["days_to_trade_limit"]):
            caps.append((float(gates["cap_days_to_trade_above_limit"]), "DAYS_TO_TRADE_ABOVE_LIMIT"))
        for gate_name, reason in (
            ("unresolved_claim", "OWNER_CLAIM_UNRESOLVED"),
            ("failed_pit_check", "PIT_CHECK_FAILED"),
            ("invalid_valuation_denominator", "INVALID_VALUATION_DENOMINATOR"),
        ):
            cap = _number(gates.get(gate_name))
            if cap is not None:
                caps.append((cap, reason))
    selected_cap = min((cap for cap, _ in caps), default=None)
    final_composite = None if before_cap is None else round(min(before_cap, selected_cap) if selected_cap is not None else before_cap, 6)
    gate_reasons = tuple(dict.fromkeys((*reasons, *(reason for _, reason in caps))))
    scorecard_status = "complete" if final_composite is not None and composite_coverage == 1.0 else "partial"
    underwriting = {
        "label": "Underwriting",
        "horizon": selected.horizons.get("underwriting", "multi-year owner economics"),
        "status": "rated" if final_composite is not None else "partial",
        "composite_10": final_composite,
        "composite_before_gate_cap_10": before_cap,
        "gate_cap_10": selected_cap,
        "overall_coverage": round(overall_coverage, 6),
        "composite_coverage": round(composite_coverage, 6),
        "missing_axes": missing_axes,
        "critical_axes": critical_axes,
        "gate_reasons": gate_reasons,
        "execution_allowed": False,
    }
    tactical = {
        "label": "Tactical",
        "horizon": selected.horizons.get("tactical", "1-3 months"),
        "status": "available" if tactical_evidence else "UNAVAILABLE",
        "evidence": dict(tactical_evidence or {}),
        "affects_underwriting": False,
        "execution_allowed": False,
    }
    return SparebankScorecard(
        status=scorecard_status,
        formula_version=selected.formula_version,
        formula_checksum=selected.formula_checksum,
        judgement_version=selected.judgement_version,
        judgement_status=selected.judgement_status,
        judgement_source=selected.judgement_source,
        axes=axes,
        composite_10=final_composite,
        composite_before_gate_cap_10=before_cap,
        gate_cap_10=selected_cap,
        overall_coverage=round(overall_coverage, 6),
        composite_coverage=round(composite_coverage, 6),
        missing_axes=missing_axes,
        gate_reasons=gate_reasons,
        underwriting=underwriting,
        tactical=tactical,
        execution_allowed=False,
    )


def _empty_scorecard(policy: SparebankScorecardPolicy, reasons: tuple[str, ...]) -> SparebankScorecard:
    tactical = {
        "label": "Tactical",
        "horizon": policy.horizons.get("tactical", "1-3 months"),
        "status": "UNAVAILABLE",
        "evidence": {},
        "affects_underwriting": False,
        "execution_allowed": False,
    }
    underwriting = {
        "label": "Underwriting",
        "horizon": policy.horizons.get("underwriting", "multi-year owner economics"),
        "status": "UNAVAILABLE",
        "composite_10": None,
        "overall_coverage": 0.0,
        "composite_coverage": 0.0,
        "missing_axes": tuple(policy.axes),
        "gate_reasons": reasons,
        "execution_allowed": False,
    }
    return SparebankScorecard(
        status="BLOCKED",
        formula_version=policy.formula_version,
        formula_checksum=policy.formula_checksum,
        judgement_version=policy.judgement_version,
        judgement_status=policy.judgement_status,
        judgement_source=policy.judgement_source,
        axes={},
        composite_10=None,
        composite_before_gate_cap_10=None,
        gate_cap_10=None,
        overall_coverage=0.0,
        composite_coverage=0.0,
        missing_axes=tuple(policy.axes),
        gate_reasons=reasons,
        underwriting=underwriting,
        tactical=tactical,
        execution_allowed=False,
    )


def _axis_weights(policy: SparebankScorecardPolicy) -> dict[str, float]:
    configured = _field(policy.scorecard, "axis_weights", {})
    if not isinstance(configured, Mapping):
        raise SparebankScorecardError("scorecard.axis_weights must be a mapping")
    result: dict[str, float] = {}
    for axis_id in policy.axes:
        weight = _number(configured.get(axis_id, 1.0))
        if weight is None or weight < 0:
            raise SparebankScorecardError(f"scorecard weight is invalid: {axis_id}")
        result[str(axis_id)] = weight
    if not any(result.values()):
        raise SparebankScorecardError("scorecard axis weights must have a positive total")
    return result


def _input_value(rule: Mapping[str, object], context: Mapping[str, object]) -> float | None:
    transform = str(rule.get("transform") or "")
    value = None
    if transform == "coverage_x10":
        value = _path(context, str(rule["source"]))
        number = _number(value)
        return None if number is None else number * 10.0
    if transform == "headroom_percentage_points":
        resilience = _path(context, str(rule["source"]))
        explicit = _first_number(resilience, "headroom_pp", "cet1_headroom_pp")
        if explicit is not None:
            return explicit
        closing = _first_number(resilience, "closing_ratio", "cet1_ratio")
        target = _first_number(resilience, "target_ratio", "requirement_ratio")
        if closing is not None and target is not None:
            return (closing - target) * 100.0
        amount = _first_number(resilience, "headroom_nok")
        rwa = _first_number(resilience, "rwa")
        return amount / rwa * 100.0 if amount is not None and rwa not in (None, 0.0) else None
    if transform == "normalised_roe_spread_percentage_points":
        roe = _number(_path(context, str(rule["source"])))
        assumptions = context.get("assumptions")
        cost_pct = _first_number(assumptions, "cost_of_equity_pct")
        cost_ratio = _first_number(assumptions, "cost_of_equity")
        if roe is None:
            return None
        if cost_pct is not None:
            return roe * 100.0 - cost_pct
        return None if cost_ratio is None else (roe - cost_ratio) * 100.0
    if transform == "owner_value_vs_decision_price_percent":
        owner_value = _number(_path(context, "valuation.central_owner_value_per_ec"))
        if owner_value is None:
            owner_value = _first_number(_path(context, "valuation.central_owner_value_per_ec"), "value", "value_per_ec")
        if owner_value is None:
            owner_value = _first_number(context.get("assumptions"), "central_owner_value_per_ec", "owner_value_per_ec")
        price = _number(context.get("decision_price"))
        return None if owner_value is None or price is None or price == 0 else (owner_value / price - 1.0) * 100.0
    if transform == "event_value_accretion_percent":
        event_analysis = context.get("events")
        event_rows = _field(event_analysis, "events", ())
        if not isinstance(event_rows, (tuple, list)):
            return None
        for event in event_rows:
            explicit = _first_number(event, "owner_value_accretion_pct", "value_accretion_pct")
            if explicit is not None:
                return explicit
            value = _first_number(event, "value_per_legacy_ec", "owner_value_per_ec")
            pre_event = _first_number(event, "credible_standalone", "pre_event_value_per_ec")
            if value is not None and pre_event not in (None, 0.0):
                return (value / pre_event - 1.0) * 100.0
        return None
    if transform == "days_to_trade":
        value = _path(context, "valuation.marketability.days_to_trade")
        if value is None:
            value = _path(context, "assumptions.marketability.days_to_trade")
        if value is None:
            value = _path(context, "valuation.implementation.days_to_trade")
        return _number(value)
    value = _path(context, str(rule.get("source") or ""))
    if value is None and str(rule.get("source") or "") == "valuation.marketability.median_volume_60d":
        value = _path(context, "assumptions.marketability.median_volume_60d")
    number = _number(value)
    if number is None:
        return None
    if transform == "ratio_to_percent":
        return number * 100.0
    if transform == "ratio_to_basis_points":
        return number * 10000.0
    return number


def _path(context: object, path: str) -> object:
    value = context
    for part in path.split("."):
        value = _field(value, part)
        if value is None:
            return None
    return value


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    if value is None or value == UNAVAILABLE:
        return default
    return getattr(value, name, default)


def _first_number(value: object, *names: str) -> float | None:
    for name in names:
        number = _number(_field(value, name))
        if number is not None:
            return number
    return None


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or (isinstance(value, str) and value.casefold() == "unavailable"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rating(value: float, anchors: object) -> float:
    points = sorted(
        ((_number(_field(anchor, "value")), _number(_field(anchor, "rating"))) for anchor in anchors),
        key=lambda pair: float(pair[1] if pair[1] is not None else 0.0),
    )
    valid = [(float(x), float(y)) for x, y in points if x is not None and y is not None]
    if len(valid) < 2:
        raise SparebankScorecardError("scorecard input needs at least two finite anchors")
    low_x = min(valid, key=lambda point: point[0])
    high_x = max(valid, key=lambda point: point[0])
    if value <= low_x[0]:
        return round(max(0.0, min(10.0, low_x[1])), 6)
    if value >= high_x[0]:
        return round(max(0.0, min(10.0, high_x[1])), 6)
    for (x1, y1), (x2, y2) in zip(valid, valid[1:]):
        if min(x1, x2) <= value <= max(x1, x2):
            rating = y1 + (value - x1) * (y2 - y1) / (x2 - x1)
            return round(max(0.0, min(10.0, rating)), 6)
    return 0.0


def _pit_check(known_at: object, decision_time: str | datetime | None) -> tuple[bool | None, str]:
    if known_at is None or decision_time is None:
        return None, "PIT_CHECK_UNVERIFIED"
    known, decision = _timestamp(known_at), _timestamp(decision_time)
    if known is None or decision is None:
        return None, "PIT_CHECK_UNVERIFIED"
    if known > decision:
        return False, "PIT_CHECK_FAILED"
    return True, ""


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "SparebankScorecardError",
    "SparebankScorecardPolicy",
    "build_sparebank_scorecard",
    "load_sparebank_scorecard_policy",
]
