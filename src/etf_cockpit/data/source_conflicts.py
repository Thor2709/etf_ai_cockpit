"""Deterministic source conflict resolution with an auditable trail."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Iterable, Mapping

from etf_cockpit.data.contracts import SourceAuthority


class MetricResolutionError(ValueError):
    """Raised when metric candidates cannot be compared without inventing context."""


class AmbiguousMetricAvailabilityError(MetricResolutionError):
    """Raised when a point-in-time claim lacks availability evidence."""


@dataclass(frozen=True)
class MetricPolicy:
    policy_name: str
    version: int
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    field_tolerances: Mapping[str, tuple[float, float]] | None = None
    minimum_confidence: float | None = None
    blocked_freshness_statuses: tuple[str, ...] = ("stale", "block", "quarantined", "conflicted")

    def __post_init__(self) -> None:
        if not self.policy_name.strip() or self.version < 1:
            raise MetricResolutionError("metric policy name and positive version are required")
        if self.absolute_tolerance < 0 or self.relative_tolerance < 0:
            raise MetricResolutionError("metric tolerances cannot be negative")
        if self.minimum_confidence is not None and not 0 <= self.minimum_confidence <= 1:
            raise MetricResolutionError("minimum confidence must be between zero and one")
        for value in (self.field_tolerances or {}).values():
            if len(value) != 2 or value[0] < 0 or value[1] < 0:
                raise MetricResolutionError("field tolerances must be non-negative absolute/relative pairs")

    @property
    def policy_id(self) -> str:
        return f"{self.policy_name.strip()}:{self.version}"

    def tolerance_for(self, field: str) -> tuple[float, float]:
        return (self.field_tolerances or {}).get(field, (self.absolute_tolerance, self.relative_tolerance))

    @property
    def sha256(self) -> str:
        payload = {
            "policy_id": self.policy_id,
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
            "field_tolerances": {key: list(value) for key, value in sorted((self.field_tolerances or {}).items())},
            "minimum_confidence": self.minimum_confidence,
            "blocked_freshness_statuses": sorted({item.strip().lower() for item in self.blocked_freshness_statuses}),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MetricReviewDecision:
    conflict_id: str
    selected_source_id: str
    reviewer: str
    reviewed_at: str
    reason: str
    revision: int = 1

    @property
    def decision_id(self) -> str:
        payload = {
            "conflict_id": self.conflict_id,
            "selected_source_id": self.selected_source_id,
            "reviewer": self.reviewer,
            "reviewed_at": _timestamp(self.reviewed_at, "reviewed_at", require_timezone=True),
            "reason": self.reason,
            "revision": self.revision,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MetricClaim:
    instrument_id: str
    field: str
    value: object
    source: str
    authority: SourceAuthority
    source_id: str
    unit: str | None = None
    period: str | None = None
    as_of: str | None = None
    freshness_status: str = "unknown"
    confidence: float | str | None = None
    currency: str | None = None
    restatement_id: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    available_at: str | None = None
    revision: int = 1


@dataclass(frozen=True)
class MetricConflict:
    instrument_id: str
    field: str
    selected_value: object
    values: tuple[object, ...]
    source_ids: tuple[str, ...]
    requires_manual_review: bool
    conflict_id: str = ""
    reason: str = ""
    resolution_status: str = "manual_review"
    evidence_quality: str = "reduced"
    selected_source_id: str = ""
    period: str = "unavailable"
    unit: str = "unavailable"
    currency: str = "unavailable"
    as_of: str = "unavailable"
    valid_from: str = "unavailable"
    valid_to: str = "open"
    restatement_ids: tuple[str, ...] = ()
    reason_code: str = "material_value_conflict"
    state: str = "quarantine"
    policy_id: str = ""
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    decision_id: str = ""
    review_decision_id: str = ""
    policy_sha256: str = ""
    candidate_count: int = 0


@dataclass(frozen=True)
class ConflictResolution:
    selected: dict[str, MetricClaim]
    conflicts: tuple[MetricConflict, ...]
    claims: tuple[MetricClaim, ...] = ()
    requires_manual_review: bool = False
    excluded_claims: tuple[MetricClaim, ...] = ()
    policy_id: str = ""
    decision_id: str = ""
    invalidation_token: str = ""
    state: str = "pass"
    execution_allowed: bool = False
    policy_sha256: str = ""


def resolve_conflicts(
    claims: Iterable[MetricClaim],
    *,
    decision_time: str | datetime | None = None,
    policy: MetricPolicy | None = None,
    review_decisions: Iterable[MetricReviewDecision] = (),
) -> ConflictResolution:
    """Select a canonical claim while retaining every source disagreement.

    Official/issuer claims outrank vendors and context/model sources.  Ties
    are broken by source ID, source name and stable value representation, so
    reversing input order cannot change the result.
    """

    items = tuple(_coerce_claim(item) for item in claims)
    active_policy = policy or MetricPolicy("canonical-metric.v1", 1)
    cutoff = _timestamp(decision_time, "decision_time", require_timezone=True) if decision_time is not None else None
    active, excluded = _point_in_time_candidates(items, cutoff)
    grouped: dict[tuple[str, str, str, str, str, str, str, str], list[MetricClaim]] = {}
    for claim in active:
        if not claim.instrument_id or not claim.field:
            continue
        grouped.setdefault(_context(claim), []).append(claim)
    selected: dict[str, MetricClaim] = {}
    conflicts: list[MetricConflict] = []
    conflict_candidates: dict[str, tuple[str, tuple[MetricClaim, ...]]] = {}
    context_counts: dict[tuple[str, str], int] = {}
    for instrument_id, field, *_comparison_context in grouped:
        context_counts[(instrument_id, field)] = context_counts.get((instrument_id, field), 0) + 1
    one_instrument = len({item.instrument_id for item in active}) <= 1
    for context, field_claims in sorted(grouped.items()):
        instrument_id, field, period, unit, currency, as_of, valid_from, valid_to = context
        ordered = sorted(field_claims, key=_claim_sort_key)
        quality_eligible = [item for item in ordered if _quality_eligible(item, active_policy)]
        quality_rejected = [item for item in ordered if item not in quality_eligible]
        winner = quality_eligible[0] if quality_eligible else ordered[0]
        key = _selection_key(context, one_instrument=one_instrument, context_count=context_counts[(instrument_id, field)])
        if quality_eligible:
            selected[key] = winner
        values = _stable_values(item.value for item in field_claims)
        comparable_values = _stable_values(item.value for item in quality_eligible)
        source_ids = tuple(sorted({item.source_id or "unknown" for item in field_claims}))
        missing_source = any(not item.source_id for item in field_claims)
        missing_context = any(value == "unavailable" for value in (period, unit, currency, as_of, valid_from))
        legacy_unknown_context = cutoff is None and policy is None
        if missing_source or (missing_context and not legacy_unknown_context) or not quality_eligible or len(comparable_values) > 1 or quality_rejected:
            absolute_tolerance, relative_tolerance = active_policy.tolerance_for(field)
            within_tolerance = _within_tolerance(comparable_values, absolute_tolerance, relative_tolerance)
            if missing_source:
                reason_code, state, requires_review = "missing_source_identity", "block", True
            elif missing_context and not legacy_unknown_context:
                reason_code, state, requires_review = "missing_metric_context", "block", True
            elif not quality_eligible:
                reason_code, state, requires_review = "no_quality_eligible_candidate", "block", False
            elif within_tolerance:
                reason_code, state, requires_review = "within_materiality_tolerance", "warn", False
            elif len(comparable_values) > 1:
                reason_code, state, requires_review = "material_value_conflict", "quarantine", True
            else:
                reason_code, state, requires_review = "candidate_quality_reduced", "warn", False
            if state == "block":
                selected.pop(key, None)
            conflict_id = _conflict_id(
                instrument_id,
                field,
                values,
                source_ids,
                context=context,
                policy_id=active_policy.sha256,
                restatement_ids=tuple(sorted({item.restatement_id or "original" for item in field_claims})),
            )
            reason = _reason(winner, field_claims, values, reason_code=reason_code, tolerances=(absolute_tolerance, relative_tolerance))
            conflict_decision_id = _metric_decision_id(
                active_policy.sha256,
                cutoff,
                context,
                field_claims,
                conflict_id,
            )
            conflicts.append(
                MetricConflict(
                    instrument_id=instrument_id,
                    field=field,
                    selected_value=winner.value,
                    values=values,
                    source_ids=source_ids,
                    requires_manual_review=requires_review,
                    conflict_id=conflict_id,
                    reason=reason,
                    resolution_status="manual_review" if requires_review else reason_code,
                    evidence_quality="blocked" if state == "block" else "reduced" if requires_review else "qualified",
                    selected_source_id=winner.source_id,
                    period=period,
                    unit=unit,
                    currency=currency,
                    as_of=as_of,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    restatement_ids=tuple(sorted({item.restatement_id or "original" for item in field_claims})),
                    reason_code=reason_code,
                    state=state,
                    policy_id=active_policy.policy_id,
                    absolute_tolerance=absolute_tolerance,
                    relative_tolerance=relative_tolerance,
                    decision_id=conflict_decision_id,
                    policy_sha256=active_policy.sha256,
                    candidate_count=len(field_claims),
                )
            )
            conflict_candidates[conflict_id] = (key, tuple(field_claims))

    for (instrument_id, field), count in sorted(context_counts.items()):
        if count <= 1:
            continue
        contexts = tuple(sorted(context for context in grouped if context[:2] == (instrument_id, field)))
        context_claims = tuple(item for context in contexts for item in grouped[context])
        values = _stable_values(item.value for item in context_claims)
        source_ids = tuple(sorted({item.source_id or "unknown" for item in context_claims}))
        conflict_id = _conflict_id(
            instrument_id,
            field,
            values,
            source_ids,
            context=(instrument_id, field, "multiple", "multiple", "multiple", "multiple", "multiple", "multiple"),
            policy_id=active_policy.sha256,
            restatement_ids=tuple(sorted({item.restatement_id or "original" for item in context_claims})),
        )
        winner = sorted(context_claims, key=_claim_sort_key)[0]
        conflicts.append(
            MetricConflict(
                instrument_id=instrument_id,
                field=field,
                selected_value=winner.value,
                values=values,
                source_ids=source_ids,
                requires_manual_review=True,
                conflict_id=conflict_id,
                reason="Metric candidates use incompatible period, unit or currency contexts; each context is retained separately and pooled selection is blocked.",
                resolution_status="blocked_incompatible_context",
                evidence_quality="blocked",
                selected_source_id=winner.source_id,
                period="multiple",
                unit="multiple",
                currency="multiple",
                as_of="multiple",
                valid_from="multiple",
                valid_to="multiple",
                restatement_ids=tuple(sorted({item.restatement_id or "original" for item in context_claims})),
                reason_code="incompatible_metric_context",
                state="block",
                policy_id=active_policy.policy_id,
                decision_id=_metric_decision_id(
                    active_policy.sha256,
                    cutoff,
                    (instrument_id, field, "multiple", "multiple", "multiple", "multiple", "multiple", "multiple"),
                    context_claims,
                    conflict_id,
                ),
                policy_sha256=active_policy.sha256,
                candidate_count=len(context_claims),
            )
        )
        conflict_candidates[conflict_id] = ("", context_claims)

    selected, conflicts = _apply_reviews(
        selected,
        conflicts,
        conflict_candidates,
        tuple(review_decisions),
        cutoff=cutoff,
        policy=active_policy,
    )
    ordered_claims = tuple(sorted(active, key=lambda item: (item.instrument_id, item.field, *_claim_sort_key(item))))
    state = _aggregate_state(conflicts, selected)
    decision_id = _resolution_decision_id(active_policy.sha256, cutoff, selected, conflicts)
    invalidation_token = hashlib.sha256(
        json.dumps(
            {
                "decision_id": decision_id,
                "selected": {key: _claim_identity(value) for key, value in sorted(selected.items())},
                "execution_allowed": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ConflictResolution(
        selected=selected,
        conflicts=tuple(conflicts),
        claims=ordered_claims,
        requires_manual_review=any(item.requires_manual_review for item in conflicts),
        excluded_claims=excluded,
        policy_id=active_policy.policy_id,
        decision_id=decision_id,
        invalidation_token=invalidation_token,
        state=state,
        execution_allowed=False,
        policy_sha256=active_policy.sha256,
    )


def _coerce_claim(claim: MetricClaim) -> MetricClaim:
    if not isinstance(claim, MetricClaim):
        raise TypeError("metric claims must be MetricClaim instances")
    try:
        authority = claim.authority if isinstance(claim.authority, SourceAuthority) else SourceAuthority(str(claim.authority).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unknown metric authority: {claim.authority!r}") from exc
    try:
        revision = int(claim.revision)
    except (TypeError, ValueError) as exc:
        raise MetricResolutionError("metric revision must be a positive integer") from exc
    if revision < 1:
        raise MetricResolutionError("metric revision must be a positive integer")
    as_of = _optional_timestamp(claim.as_of, "as_of")
    valid_from = _optional_timestamp(claim.valid_from or as_of, "valid_from")
    valid_to = _optional_timestamp(claim.valid_to, "valid_to")
    available_at = _optional_timestamp(claim.available_at, "available_at", require_timezone=True)
    if valid_from and valid_to and _as_datetime(valid_to) <= _as_datetime(valid_from):
        raise MetricResolutionError("metric valid_to must be later than valid_from")
    return MetricClaim(
        instrument_id=str(claim.instrument_id or "").strip(),
        field=str(claim.field or "").strip(),
        value=claim.value,
        source=str(claim.source or "").strip(),
        authority=authority,
        source_id=str(claim.source_id or "").strip(),
        unit=claim.unit,
        period=claim.period,
        as_of=as_of,
        freshness_status=str(claim.freshness_status or "unknown").strip().lower(),
        confidence=claim.confidence,
        currency=str(claim.currency).strip().upper() if claim.currency else None,
        restatement_id=str(claim.restatement_id).strip() if claim.restatement_id else None,
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at,
        revision=revision,
    )


def _claim_sort_key(claim: MetricClaim) -> tuple[int, int, str, str, str]:
    return (
        -claim.authority.rank,
        -claim.revision,
        claim.source_id or "unknown",
        claim.source.casefold(),
        _stable_repr(claim.value),
    )


def _stable_values(values: Iterable[object]) -> tuple[object, ...]:
    unique: dict[str, object] = {}
    for value in values:
        unique.setdefault(_stable_repr(value), value)
    return tuple(unique[key] for key in sorted(unique))


def _stable_repr(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)


def _reason(
    winner: MetricClaim,
    claims: Iterable[MetricClaim],
    values: tuple[object, ...],
    *,
    reason_code: str,
    tolerances: tuple[float, float],
) -> str:
    authority_names = sorted({item.authority.value for item in claims})
    if reason_code == "within_materiality_tolerance":
        return (
            f"{winner.field} candidates differ within policy tolerance "
            f"(absolute={tolerances[0]}, relative={tolerances[1]}); {winner.source_id or 'unknown'} selected by authority and all candidates retained."
        )
    if reason_code == "missing_metric_context":
        return f"{winner.field} candidates lack complete period, unit or currency context; pooled canonical selection is blocked and all candidates are retained."
    if reason_code == "missing_source_identity":
        return f"{winner.field} includes a candidate without a stable source_id; canonical use is blocked pending source identity review."
    if reason_code == "candidate_quality_reduced":
        return f"{winner.field} selected source {winner.source_id or 'unknown'} after stale or low-confidence candidates were retained but excluded by policy."
    if reason_code == "no_quality_eligible_candidate":
        return f"All {winner.field} candidates are stale, blocked or below the policy confidence floor; canonical use is blocked."
    if len(authority_names) > 1:
        return (
            f"Material {winner.field} disagreement between {', '.join(authority_names)} sources "
            f"({', '.join(map(str, values))}); {winner.authority.value} source {winner.source_id or 'unknown'} "
            "selected by authority and all claims retained for manual review."
        )
    return (
        f"Conflicting {winner.field} values ({', '.join(map(str, values))}); "
        f"source {winner.source_id or 'unknown'} selected deterministically and manual review is required."
    )


def _conflict_id(
    instrument_id: str,
    field: str,
    values: tuple[object, ...],
    source_ids: tuple[str, ...],
    *,
    context: tuple[str, str, str, str, str, str, str, str],
    policy_id: str,
    restatement_ids: tuple[str, ...],
) -> str:
    payload = "|".join(
        (
            instrument_id,
            field,
            *context[2:],
            policy_id,
            *restatement_ids,
            *(_stable_repr(item) for item in values),
            *source_ids,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _context(claim: MetricClaim) -> tuple[str, str, str, str, str, str, str, str]:
    return (
        claim.instrument_id,
        claim.field,
        str(claim.period or "unavailable").strip() or "unavailable",
        str(claim.unit or "unavailable").strip() or "unavailable",
        str(claim.currency or "unavailable").strip().upper() or "unavailable",
        str(claim.as_of or "unavailable").strip() or "unavailable",
        str(claim.valid_from or "unavailable").strip() or "unavailable",
        str(claim.valid_to or "open").strip() or "open",
    )


def _selection_key(
    context: tuple[str, str, str, str, str, str, str, str],
    *,
    one_instrument: bool,
    context_count: int,
) -> str:
    instrument_id, field, period, unit, currency, as_of, valid_from, valid_to = context
    if one_instrument and context_count == 1:
        return field
    prefix = "" if one_instrument else f"{instrument_id}:"
    return (
        f"{prefix}{field}|period={period}|unit={unit}|currency={currency}"
        f"|as_of={as_of}|valid_from={valid_from}|valid_to={valid_to}"
    )


def _point_in_time_candidates(
    items: tuple[MetricClaim, ...],
    cutoff: str | None,
) -> tuple[tuple[MetricClaim, ...], tuple[MetricClaim, ...]]:
    if cutoff is not None:
        for claim in items:
            if claim.available_at is None:
                raise AmbiguousMetricAvailabilityError(
                    f"available_at is required for point-in-time metric claim {claim.source_id or 'unknown'}"
                )
    cutoff_dt = _as_datetime(cutoff) if cutoff else None
    candidates = [
        claim
        for claim in items
        if cutoff_dt is None or _as_datetime(claim.available_at or cutoff) <= cutoff_dt
    ]
    excluded = [claim for claim in items if claim not in candidates]
    latest: dict[tuple[str, str, str, str, str, str, str, str, str], MetricClaim] = {}
    superseded: list[MetricClaim] = []
    unidentified: list[MetricClaim] = []
    for claim in sorted(candidates, key=lambda item: ((item.available_at or ""), item.revision, _claim_sort_key(item))):
        if not claim.source_id:
            unidentified.append(claim)
            continue
        context = _context(claim)
        key = (*context, claim.source_id)
        previous = latest.get(key)
        if previous is not None:
            superseded.append(previous)
        latest[key] = claim
    excluded.extend(superseded)
    active = tuple(
        sorted(
            (*latest.values(), *unidentified),
            key=lambda item: (item.instrument_id, item.field, *_claim_sort_key(item)),
        )
    )
    return active, tuple(sorted(excluded, key=lambda item: (item.instrument_id, item.field, item.available_at or "", item.revision)))


def _within_tolerance(values: tuple[object, ...], absolute: float, relative: float) -> bool:
    if len(values) <= 1:
        return False
    numbers: list[float] = []
    for value in values:
        if isinstance(value, bool):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(number):
            return False
        numbers.append(number)
    spread = max(numbers) - min(numbers)
    limit = max(absolute, relative * max(abs(item) for item in numbers))
    return spread <= limit


def _quality_eligible(claim: MetricClaim, policy: MetricPolicy) -> bool:
    if claim.authority is SourceAuthority.MODEL:
        return False
    blocked = {item.strip().lower() for item in policy.blocked_freshness_statuses}
    if claim.freshness_status in blocked:
        return False
    if policy.minimum_confidence is None:
        return True
    if claim.confidence is None:
        return False
    confidence = claim.confidence
    if isinstance(confidence, str):
        mapped = {"high": 1.0, "medium": 0.5, "low": 0.25, "unknown": 0.0}.get(confidence.strip().lower())
        if mapped is None:
            return False
        confidence_value = mapped
    else:
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            return False
    return math.isfinite(confidence_value) and confidence_value >= policy.minimum_confidence


def _metric_decision_id(
    policy_id: str,
    cutoff: str | None,
    context: tuple[str, str, str, str, str, str, str, str],
    claims: Iterable[MetricClaim],
    conflict_id: str,
) -> str:
    payload = {
        "policy_id": policy_id,
        "decision_time": cutoff or "latest",
        "context": context,
        "claims": [_claim_identity(item) for item in sorted(claims, key=_claim_sort_key)],
        "conflict_id": conflict_id,
        "execution_allowed": False,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _claim_identity(claim: MetricClaim) -> dict[str, object]:
    return {
        "instrument_id": claim.instrument_id,
        "field": claim.field,
        "value": claim.value,
        "source_id": claim.source_id or "unknown",
        "authority": claim.authority.value,
        "period": claim.period or "unavailable",
        "unit": claim.unit or "unavailable",
        "currency": claim.currency or "unavailable",
        "restatement_id": claim.restatement_id,
        "valid_from": claim.valid_from,
        "valid_to": claim.valid_to,
        "available_at": claim.available_at,
        "revision": claim.revision,
        "freshness_status": claim.freshness_status,
        "confidence": claim.confidence,
    }


def _apply_reviews(
    selected: dict[str, MetricClaim],
    conflicts: list[MetricConflict],
    candidates: Mapping[str, tuple[str, tuple[MetricClaim, ...]]],
    decisions: tuple[MetricReviewDecision, ...],
    *,
    cutoff: str | None,
    policy: MetricPolicy,
) -> tuple[dict[str, MetricClaim], list[MetricConflict]]:
    decision_map: dict[str, MetricReviewDecision] = {}
    cutoff_dt = _as_datetime(cutoff) if cutoff else None
    for decision in decisions:
        if not decision.conflict_id or not decision.selected_source_id or not decision.reviewer or not decision.reason or decision.revision < 1:
            raise MetricResolutionError("review decisions require conflict, candidate, reviewer, reason and positive revision")
        reviewed_at = _timestamp(decision.reviewed_at, "reviewed_at", require_timezone=True)
        if cutoff_dt is not None and _as_datetime(reviewed_at) > cutoff_dt:
            continue
        previous = decision_map.get(decision.conflict_id)
        if previous is not None and decision.revision == previous.revision and decision != previous:
            raise MetricResolutionError("metric reviews contain conflicting decisions at the same revision")
        if previous is None or decision.revision > previous.revision:
            decision_map[decision.conflict_id] = decision
    unknown = set(decision_map).difference(candidates)
    if unknown:
        raise MetricResolutionError(f"review decision references unknown conflict: {sorted(unknown)[0]}")
    updated = list(conflicts)
    for index, conflict in enumerate(updated):
        decision = decision_map.get(conflict.conflict_id)
        if decision is None:
            continue
        if conflict.reason_code in {
            "candidate_quality_reduced",
            "incompatible_metric_context",
            "missing_metric_context",
            "missing_source_identity",
            "no_quality_eligible_candidate",
        }:
            raise MetricResolutionError(f"review decision cannot override blocking {conflict.reason_code}")
        key, options = candidates[conflict.conflict_id]
        matching = [item for item in options if item.source_id == decision.selected_source_id]
        if not matching:
            raise MetricResolutionError("review decision selected source is not a retained candidate")
        if not any(_quality_eligible(item, policy) for item in matching):
            raise MetricResolutionError("review decision selected a quality-ineligible retained candidate")
        chosen = sorted((item for item in matching if _quality_eligible(item, policy)), key=_claim_sort_key)[0]
        if key:
            selected[key] = chosen
        updated[index] = replace(
            conflict,
            selected_value=chosen.value,
            selected_source_id=chosen.source_id,
            requires_manual_review=False,
            resolution_status="reviewed",
            evidence_quality="reviewed",
            state="warn",
            review_decision_id=decision.decision_id,
            decision_id=hashlib.sha256(f"{conflict.decision_id}|{decision.decision_id}".encode("utf-8")).hexdigest(),
        )
    return selected, updated


def _aggregate_state(conflicts: Iterable[MetricConflict], selected: Mapping[str, MetricClaim]) -> str:
    if not selected:
        return "block"
    states = {item.state for item in conflicts}
    for state in ("block", "quarantine", "warn"):
        if state in states:
            return state
    return "pass"


def _resolution_decision_id(
    policy_id: str,
    cutoff: str | None,
    selected: Mapping[str, MetricClaim],
    conflicts: Iterable[MetricConflict],
) -> str:
    payload = {
        "policy_id": policy_id,
        "decision_time": cutoff or "latest",
        "selected": {key: _claim_identity(value) for key, value in sorted(selected.items())},
        "conflicts": [
            {
                "conflict_id": item.conflict_id,
                "state": item.state,
                "selected_source_id": item.selected_source_id,
                "review_decision_id": item.review_decision_id,
            }
            for item in sorted(conflicts, key=lambda value: value.conflict_id)
        ],
        "execution_allowed": False,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _optional_timestamp(value: str | datetime | None, field: str, *, require_timezone: bool = False) -> str | None:
    return None if value is None else _timestamp(value, field, require_timezone=require_timezone)


def _timestamp(value: str | datetime, field: str, *, require_timezone: bool = False) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MetricResolutionError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        if require_timezone and "T" in str(value):
            raise AmbiguousMetricAvailabilityError(f"{field} must include a timezone")
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
