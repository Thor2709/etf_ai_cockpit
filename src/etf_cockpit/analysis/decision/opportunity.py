"""Cross-sectional opportunity ranks over point-in-time domain evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from etf_cockpit.core.paths import CONFIG_DIR

from etf_cockpit.analysis.decision.contracts import (
    DecisionDriver,
    OpportunityBenchmarkRank,
    OpportunityResult,
)


_DEFAULT_CONFIG = CONFIG_DIR / "decision_opportunity_v1.yaml"
_RANKER_NAMES = ("v3", "Q", "V", "M", "R", "QV", "QVM", "five_factor")


@dataclass(frozen=True)
class OpportunityPolicy:
    version: str
    checksum: str
    minimum_universe_support: int
    minimum_peer_support: int
    minimum_exposure_peer_sector_share: float
    high_opportunity_percentile: float
    attractive_percentile: float
    fair_mixed_percentile: float
    low_percentile: float
    supportive_momentum_percentile: float
    adverse_momentum_percentile: float


def load_opportunity_policy(path: str | Path = _DEFAULT_CONFIG) -> OpportunityPolicy:
    """Load typed conservative defaults; a missing policy fails closed.

    The v1 defaults require three observations, label the upper decile High,
    the top quartile Attractive, 40th-percentile and above Fair/Mixed, the
    25th-percentile through below the 40th Low, and use the top/bottom
    momentum quartiles for timing. ETF exposure
    peers require a dominant sector weight of at least 35 percent. These cutoffs
    are policy choices, not estimated thresholds.
    """

    content = Path(path).read_bytes()
    parsed = yaml.safe_load(content.decode("utf-8"))
    if not isinstance(parsed, Mapping) or parsed.get("schema_version") != 1:
        raise ValueError("opportunity policy requires schema_version 1")
    labels = parsed.get("labels")
    timing = parsed.get("timing")
    if not isinstance(labels, Mapping) or not isinstance(timing, Mapping):
        raise ValueError("opportunity policy requires labels and timing mappings")
    minimum_universe_support = _positive_int(parsed.get("minimum_universe_support"))
    minimum_peer_support = _positive_int(parsed.get("minimum_peer_support"))
    exposure_peer_sector_share = _fraction(
        parsed.get("minimum_exposure_peer_sector_share")
    )
    thresholds = {
        name: _percentile(labels.get(name))
        for name in (
            "high_opportunity_percentile",
            "attractive_percentile",
            "fair_mixed_percentile",
            "low_percentile",
        )
    }
    timing_thresholds = {
        name: _percentile(timing.get(name))
        for name in (
            "supportive_momentum_percentile",
            "adverse_momentum_percentile",
        )
    }
    if not (
        thresholds["high_opportunity_percentile"]
        > thresholds["attractive_percentile"]
        > thresholds["fair_mixed_percentile"]
        > thresholds["low_percentile"]
        >= 0.0
    ):
        raise ValueError("opportunity label percentiles must be strictly descending")
    if timing_thresholds["supportive_momentum_percentile"] <= timing_thresholds[
        "adverse_momentum_percentile"
    ]:
        raise ValueError("supportive timing percentile must exceed adverse percentile")
    checksum = hashlib.sha256(
        content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    ).hexdigest()
    version = str(parsed.get("version", "")).strip()
    if not version:
        raise ValueError("opportunity policy version is required")
    return OpportunityPolicy(
        version,
        checksum,
        minimum_universe_support,
        minimum_peer_support,
        exposure_peer_sector_share,
        **thresholds,
        **timing_thresholds,
    )


def build_opportunity_results(
    candidates: Sequence[Mapping[str, object]],
    *,
    decision_time: str,
    config_path: str | Path = _DEFAULT_CONFIG,
) -> dict[str, OpportunityResult]:
    """Calculate equal-weight domain baselines and empirical mid-rank percentiles.

    Percentiles use ``(members below + half the ties) / support``. The configured
    minimum support is applied without widening or reweighting either cohort.
    """

    policy = load_opportunity_policy(config_path)
    _validate_decision_time(decision_time)
    states: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        instrument = str(candidate.get("instrument", "")).strip()
        if not instrument or instrument in states:
            raise ValueError("opportunity candidates require unique instrument identities")
        state = _candidate_state(candidate, decision_time, policy)
        states[instrument] = state

    eligible = {
        instrument: float(state["baseline_z"])
        for instrument, state in states.items()
        if state["rankable"] and _finite(state.get("baseline_z")) is not None
    }
    universe_hash = _hash(
        {
            "decision_time": decision_time,
            "members": [
                {"instrument": name, "baseline_z": eligible[name]}
                for name in sorted(eligible)
            ],
        }
    )
    universe_supported = len(eligible) >= policy.minimum_universe_support
    universe_percentiles = (
        _percentiles(eligible) if universe_supported else {}
    )
    universe_ranks = _ranks(eligible) if universe_supported else {}
    peer_groups: dict[str, dict[str, float]] = {}
    for instrument, state in states.items():
        peer_id = str(state.get("peer_id") or "unavailable")
        score = _finite(state.get("baseline_z"))
        if state["rankable"] and score is not None and peer_id != "unavailable":
            peer_groups.setdefault(peer_id, {})[instrument] = score
    peer_percentiles = {
        peer_id: _percentiles(values)
        for peer_id, values in peer_groups.items()
        if len(values) >= policy.minimum_peer_support
    }
    peer_ranks = {
        peer_id: _ranks(values)
        for peer_id, values in peer_groups.items()
        if len(values) >= policy.minimum_peer_support
    }

    benchmark_values = {
        instrument: _benchmark_scores(state)
        for instrument, state in states.items()
        if state["rankable"]
    }
    benchmark_percentiles: dict[str, dict[str, float]] = {}
    for name in _RANKER_NAMES:
        values = {
            instrument: score
            for instrument, scores in benchmark_values.items()
            if (score := _finite(scores.get(name))) is not None
        }
        if len(values) >= policy.minimum_universe_support:
            benchmark_percentiles[name] = _percentiles(values)

    results: dict[str, OpportunityResult] = {}
    for instrument, state in states.items():
        baseline_z = _finite(state.get("baseline_z"))
        percentile = universe_percentiles.get(instrument)
        universe_rank = universe_ranks.get(instrument)
        peer_id = str(state.get("peer_id") or "unavailable")
        peer_percentile = peer_percentiles.get(peer_id, {}).get(instrument)
        peer_rank = peer_ranks.get(peer_id, {}).get(instrument)
        if state["status"]:
            label = str(state["status"])
            reason = str(state["reason_code"])
        elif not universe_supported:
            label = "Insufficient Evidence"
            reason = "UNIVERSE_SUPPORT_BELOW_MINIMUM"
        elif percentile is None:
            label = "Insufficient Evidence"
            reason = "BASELINE_SCORE_UNAVAILABLE"
        else:
            label = _opportunity_label(percentile, policy)
            reason = "AVAILABLE"

        rankers: list[OpportunityBenchmarkRank] = []
        scores = benchmark_values.get(instrument, {})
        for name in _RANKER_NAMES:
            value = _finite(scores.get(name))
            rank_percentile = benchmark_percentiles.get(name, {}).get(instrument)
            if value is None:
                rankers.append(
                    OpportunityBenchmarkRank(
                        name,
                        None,
                        None,
                        "UNAVAILABLE",
                        _benchmark_reason(name, scores),
                    )
                )
            elif rank_percentile is None:
                rankers.append(
                    OpportunityBenchmarkRank(
                        name,
                        value,
                        None,
                        "UNAVAILABLE",
                        "BENCHMARK_UNIVERSE_SUPPORT_BELOW_MINIMUM",
                    )
                )
            else:
                rankers.append(
                    OpportunityBenchmarkRank(
                        name, value, rank_percentile, "AVAILABLE", "AVAILABLE"
                    )
                )
        momentum_percentile = next(
            (item.percentile for item in rankers if item.ranker == "M"), None
        )
        if momentum_percentile is None:
            timing = "Insufficient"
            timing_reason = "MOMENTUM_EVIDENCE_UNAVAILABLE"
        elif momentum_percentile >= policy.supportive_momentum_percentile:
            timing = "Supportive"
            timing_reason = "MOMENTUM_PERCENTILE_SUPPORTIVE"
        elif momentum_percentile <= policy.adverse_momentum_percentile:
            timing = "Adverse"
            timing_reason = "MOMENTUM_PERCENTILE_ADVERSE"
        else:
            timing = "Neutral"
            timing_reason = "MOMENTUM_PERCENTILE_NEUTRAL"

        results[instrument] = OpportunityResult(
            instrument=instrument,
            asset_type=str(state["asset_type"]),
            decision_time=decision_time,
            status=label,
            baseline_z=baseline_z,
            percentile=percentile,
            universe_rank=universe_rank,
            universe_support=len(eligible),
            peer_percentile=peer_percentile,
            peer_rank=peer_rank,
            peer_support=len(peer_groups.get(peer_id, {})),
            domain_scores=tuple(state["domain_scores"]),
            confidence=_finite(state.get("confidence")),
            coverage=_finite(state.get("coverage")),
            positive_drivers=tuple(state["positive_drivers"]),
            negative_drivers=tuple(state["negative_drivers"]),
            explanation=str(state["explanation"]),
            timing=timing,
            timing_reason_code=timing_reason,
            benchmark_rankers=tuple(rankers),
            universe_hash=universe_hash,
            peer_id=peer_id,
            config_hash=policy.checksum,
            source_vintage_hash=str(state.get("source_vintage_hash") or "unavailable"),
            reason_code=reason,
            execution_allowed=False,
        )
    return results


def opportunity_result_payload(result: OpportunityResult) -> dict[str, object]:
    payload = asdict(result)
    payload["schema_version"] = 1
    payload["formula_version"] = load_opportunity_policy().version
    return payload


def _candidate_state(
    candidate: Mapping[str, object], decision_time: str, policy: OpportunityPolicy
) -> dict[str, object]:
    instrument = str(candidate["instrument"])
    asset_type = str(candidate.get("asset_type", "ETF"))
    assessment = candidate.get("assessment")
    domains = _candidate_domains(candidate, assessment)
    domain_scores: list[tuple[str, float | None]] = []
    available_domains: list[tuple[str, float]] = []
    labels: dict[str, str] = {}
    supplied_labels = candidate.get("domain_labels")
    supplied_labels = supplied_labels if isinstance(supplied_labels, Mapping) else {}
    for slot in domains:
        name = str(_member(slot, "domain", ""))
        value = _finite(_member(slot, "z_score"))
        status = str(_member(slot, "status", "UNAVAILABLE")).upper()
        domain_scores.append((name, value if status == "AVAILABLE" else None))
        if status == "AVAILABLE" and value is not None:
            available_domains.append((name, value))
        labels[name] = str(supplied_labels.get(name, _member(slot, "label", name)))

    critical_domains = set(
        str(value)
        for value in candidate.get("critical_domains", _member(assessment, "critical_domains", ())) or ()
    )
    by_name = {str(_member(slot, "domain", "")): slot for slot in domains}
    gate_reason = _gate_reason(candidate, assessment)
    insufficient_domain = any(
        str(_member(by_name.get(name), "status", "UNAVAILABLE")).upper()
        in {"INSUFFICIENT_EVIDENCE", "UNAVAILABLE", "BLOCKED"}
        for name in critical_domains
    )

    if gate_reason:
        status, reason_code = "Blocked", gate_reason
    elif insufficient_domain:
        status, reason_code = "Insufficient Evidence", "CRITICAL_DOMAIN_INSUFFICIENT"
    else:
        status, reason_code = "", ""

    baseline_z, baseline_reason = _baseline(candidate, assessment, asset_type)
    if not status and baseline_z is None:
        status, reason_code = "Insufficient Evidence", baseline_reason
    if not status and len(available_domains) == 0:
        status, reason_code = "Insufficient Evidence", "DOMAIN_EVIDENCE_UNAVAILABLE"

    drivers = _drivers(candidate, assessment)
    positives = tuple(
        sorted(
            (item for item in drivers if _driver_z(item) is not None and _driver_z(item) > 0),
            key=lambda item: (-float(_driver_z(item)), item.metric_id),
        )[:3]
    )
    negatives = tuple(
        sorted(
            (item for item in drivers if _driver_z(item) is not None and _driver_z(item) < 0),
            key=lambda item: (float(_driver_z(item)), item.metric_id),
        )[:3]
    )
    if available_domains:
        strongest = max(available_domains, key=lambda item: (item[1], item[0]))
        explanation = f"Strongest domain: {labels.get(strongest[0], strongest[0])}."
    else:
        explanation = "Domain evidence is unavailable."
    confidence_values = [
        value
        for slot in domains
        if str(_member(slot, "status", "")).upper() == "AVAILABLE"
        and (value := _finite(_member(slot, "confidence"))) is not None
    ]
    coverage_values = [
        value
        for slot in domains
        if (value := _finite(_member(slot, "coverage"))) is not None
    ]
    confidence = _finite(candidate.get("confidence"))
    if confidence is None:
        confidence = _mean(confidence_values)
    coverage = _finite(candidate.get("coverage"))
    if coverage is None:
        coverage = _mean(coverage_values)
    return {
        "instrument": instrument,
        "asset_type": asset_type,
        "assessment": assessment,
        "domains": domains,
        "domain_scores": domain_scores,
        "available_domains": available_domains,
        "status": status,
        "reason_code": reason_code,
        "baseline_z": baseline_z,
        "baseline_reason": baseline_reason,
        "rankable": not status and baseline_z is not None,
        "peer_id": _peer_identity(candidate),
        "confidence": confidence,
        "coverage": coverage,
        "positive_drivers": positives,
        "negative_drivers": negatives,
        "explanation": explanation,
        "source_vintage_hash": _member(assessment, "source_vintage_hash", candidate.get("source_vintage_hash", "unavailable")),
        "candidate": candidate,
        "policy": policy,
        "decision_time": decision_time,
    }


def _baseline(
    candidate: Mapping[str, object], assessment: object, asset_type: str
) -> tuple[float | None, str]:
    is_stock = asset_type.casefold() in {"stock", "equity", "equity_certificate"}
    if is_stock:
        underwriting = _finite(candidate.get("underwriting_z_score"))
        valuation = _finite(candidate.get("valuation_z_score"))
        if underwriting is None or valuation is None:
            return None, "STOCK_QV_BASELINE_INPUT_UNAVAILABLE"
        return 0.5 * underwriting + 0.5 * valuation, "AVAILABLE"
    vehicle = _finite(candidate.get("vehicle_z_score"))
    exposure = _finite(candidate.get("exposure_z_score"))
    if vehicle is None or exposure is None:
        opportunity_slots = _member(assessment, "opportunity_slots", ()) or ()
        scores = {
            str(_member(item, "opportunity", "")): _finite(_member(item, "score"))
            for item in opportunity_slots
        }
        vehicle = vehicle if vehicle is not None else scores.get("Vehicle Rank")
        exposure = exposure if exposure is not None else scores.get("Exposure Opportunity Rank")
    if vehicle is None or exposure is None:
        return None, "ETF_VEHICLE_OR_EXPOSURE_BASELINE_UNAVAILABLE"
    return 0.5 * vehicle + 0.5 * exposure, "AVAILABLE"


def _candidate_domains(
    candidate: Mapping[str, object], assessment: object
) -> tuple[object, ...]:
    values: list[object] = []
    for key in ("underwriting_domains", "domain_slots"):
        current = candidate.get(key)
        if isinstance(current, (tuple, list)):
            values.extend(current)
    valuation = candidate.get("valuation_domain")
    if valuation is not None:
        values.append(valuation)
    exposure = candidate.get("exposure_domain_slots") or _member(
        assessment, "exposure_domain_slots", ()
    )
    if isinstance(exposure, (tuple, list)):
        values.extend(exposure)
    if not values:
        current = _member(assessment, "domain_slots", ())
        if isinstance(current, (tuple, list)):
            values.extend(current)
    return tuple(values)


def _gate_reason(candidate: Mapping[str, object], assessment: object) -> str:
    eligibility = candidate.get("eligibility_results") or _member(
        assessment, "eligibility_results", ()
    ) or ()
    for item in eligibility:
        status = str(_member(item, "status", "")).upper()
        if status in {"BLOCKED", "INELIGIBLE"}:
            return str(_member(item, "reason_code", "ELIGIBILITY_BLOCKED"))
    gates = candidate.get("gate_results") or _member(assessment, "gate_results", ()) or ()
    for item in gates:
        status = str(_member(item, "status", "")).upper()
        passed = _member(item, "passed")
        if status == "BLOCKED" or passed is False:
            return str(_member(item, "reason_code", "GATE_BLOCKED"))
    return ""


def _drivers(candidate: Mapping[str, object], assessment: object) -> tuple[DecisionDriver, ...]:
    raw = candidate.get("drivers") or _member(assessment, "drivers", ()) or ()
    result = []
    for item in raw:
        if isinstance(item, DecisionDriver):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(
                DecisionDriver(
                    str(item.get("metric_id", "")),
                    str(item.get("status", "UNAVAILABLE")),
                    _finite(item.get("raw_value")),
                    str(item.get("unit", "")),
                    _finite(item.get("z_score")),
                    str(item.get("reason_code", "")),
                )
            )
    return tuple(result)


def _benchmark_scores(state: Mapping[str, object]) -> dict[str, float | None]:
    candidate = state["candidate"]
    assert isinstance(candidate, Mapping)
    assessment = state.get("assessment")
    signal = candidate.get("signal")
    q = _finite(candidate.get("underwriting_z_score"))
    if q is None:
        q = _finite(candidate.get("vehicle_z_score"))
    if q is None:
        slots = _member(assessment, "opportunity_slots", ()) or ()
        q = next(
            (
                value
                for item in slots
                if "vehicle" in str(_member(item, "opportunity", "")).casefold()
                and (value := _finite(_member(item, "score"))) is not None
            ),
            None,
        )
    v = _finite(candidate.get("valuation_z_score"))
    m = _canonical_factor(signal, "momentum")
    r = _canonical_factor(signal, "risk")
    is_stock = str(state.get("asset_type", "")).casefold() in {
        "stock",
        "equity",
        "equity_certificate",
    }
    g = _canonical_factor(signal, "growth") if is_stock else None
    canonical = _member(signal, "canonical_score")
    v3 = _finite(_member(canonical, "legacy_composite_raw"))
    qv = None if q is None or v is None else (q + v) / 2.0
    qvm = None if q is None or v is None or m is None else (q + v + m) / 3.0
    five = (
        None
        if any(value is None for value in (v, g, q, m, r))
        else (float(v) + float(g) + float(q) + float(m) + float(r)) / 5.0
    )
    return {
        "v3": v3,
        "Q": q,
        "V": v,
        "M": m,
        "R": r,
        "G": g,
        "QV": qv,
        "QVM": qvm,
        "five_factor": five,
    }


def _benchmark_reason(name: str, scores: Mapping[str, object]) -> str:
    required = {
        "v3": ("v3",),
        "Q": ("Q",),
        "V": ("V",),
        "M": ("M",),
        "R": ("R",),
        "QV": ("Q", "V"),
        "QVM": ("Q", "V", "M"),
        "five_factor": ("V", "G", "Q", "M", "R"),
    }[name]
    missing = [key for key in required if _finite(scores.get(key)) is None]
    return "UNAVAILABLE_INPUTS:" + ",".join(missing) if missing else "UNAVAILABLE"


def _canonical_factor(signal: object, key: str) -> float | None:
    # SignalResult.components is the public v3 score-column contract. Momentum
    # and risk in CanonicalScore.components are raw evidence fields, so prefer
    # the already-scored v3 values and keep an explicitly missing score absent.
    score_components = _member(signal, "components")
    if key in {"momentum", "risk"} and score_components is not None:
        return _finite(_member(score_components, key))
    canonical = _member(signal, "canonical_score")
    for component in _member(canonical, "components", ()) or ():
        if str(_member(component, "key", "")) == key:
            eligible = _member(component, "score_eligible")
            if eligible is None:
                eligible = _member(component, "eligible")
            if eligible is True:
                return _finite(_member(component, "raw_metric"))
    return None


def _peer_identity(candidate: Mapping[str, object]) -> str:
    raw = candidate.get("peer_id")
    return str(raw).strip() if isinstance(raw, str) and raw.strip() else "unavailable"


def _opportunity_label(percentile: float, policy: OpportunityPolicy) -> str:
    if percentile >= policy.high_opportunity_percentile:
        return "High Opportunity"
    if percentile >= policy.attractive_percentile:
        return "Attractive"
    if percentile >= policy.fair_mixed_percentile:
        return "Fair/Mixed"
    if percentile >= policy.low_percentile:
        return "Low"
    return "Unattractive"


def _percentiles(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(values.values())
    count = len(ordered)
    return {
        name: 100.0
        * (
            sum(value < score for value in ordered)
            + 0.5 * sum(value == score for value in ordered)
        )
        / count
        for name, score in values.items()
    }


def _ranks(values: Mapping[str, float]) -> dict[str, int]:
    """Assign competition ranks with rank 1 as the highest score and tied values."""

    return {
        name: 1 + sum(other > score for other in values.values())
        for name, score in values.items()
    }


def _driver_z(driver: DecisionDriver) -> float | None:
    return _finite(driver.z_score) if driver.status.upper() == "AVAILABLE" else None


def _member(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("opportunity support thresholds must be positive integers")
    return value


def _percentile(value: object) -> float:
    number = _finite(value)
    if number is None or not 0.0 <= number <= 100.0:
        raise ValueError("opportunity percentiles must be finite values in [0, 100]")
    return number


def _fraction(value: object) -> float:
    number = _finite(value)
    if number is None or not 0.0 <= number <= 1.0:
        raise ValueError("opportunity fractions must be finite values in [0, 1]")
    return number


def _validate_decision_time(value: str) -> None:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("decision_time requires an explicit timezone")


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "OpportunityPolicy",
    "build_opportunity_results",
    "load_opportunity_policy",
    "opportunity_result_payload",
]
