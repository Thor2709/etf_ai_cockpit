"""Fund-specific identity and point-in-time decision rules.

Fund facts remain linked to the canonical identity graph.  This module adds
typed fund relationships and conservative availability checks without
introducing another identity resolver or storage backend.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.instrument_identity import IdentityClaim, IdentityConflict, IdentityObject


class FundIdentityError(ValueError):
    """Raised when a fund identity fact is malformed or unauditable."""


class FundStructure(StrEnum):
    ETF = "etf"
    ORDINARY_FUND = "ordinary_fund"


class FundLifecycleStatus(StrEnum):
    LAUNCHED = "launched"
    CLOSED = "closed"
    MERGED = "merged"
    LIQUIDATED = "liquidated"


class FundEvidencePeriod(StrEnum):
    NORMAL = "normal"
    INCUBATED = "incubated"
    BACKFILLED = "backfilled"


class FundMetricState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class FundSubFund:
    sub_fund_id: str
    umbrella_id: str | None
    structure: FundStructure | None
    source_ids: tuple[str, ...]
    structure_source_id: str | None = None


@dataclass(frozen=True)
class FundShareClass:
    share_class_id: str
    sub_fund_id: str | None
    distribution_policy: str | None
    source_ids: tuple[str, ...]
    distribution_policy_source_id: str | None = None


@dataclass(frozen=True)
class FundHierarchy:
    sub_funds: tuple[FundSubFund, ...]
    share_classes: tuple[FundShareClass, ...]


def fund_hierarchy(
    objects: Iterable[IdentityObject],
    *,
    conflicts: Iterable[IdentityConflict] = (),
) -> FundHierarchy:
    """Project typed fund links while preserving missing parent links as unknown."""

    items = tuple(objects)
    subfund_objects = tuple(
        item for item in items if item.object_type.casefold() in {"subfund", "sub_fund"}
    )
    subfund_ids = {item.object_id for item in subfund_objects}
    conflicted_structure_ids = {
        item.object_id for item in conflicts if item.field == "fund_structure"
    }
    sub_funds = tuple(
        FundSubFund(
            sub_fund_id=item.object_id,
            umbrella_id=item.parent_object_id,
            structure=(
                None
                if item.object_id in conflicted_structure_ids
                or not item.field_source_ids.get("fund_structure")
                else _fund_structure(item.fields.get("fund_structure"))
            ),
            source_ids=item.source_ids,
            structure_source_id=(
                item.field_source_ids.get("fund_structure")
                if item.object_id not in conflicted_structure_ids
                else None
            ),
        )
        for item in sorted(subfund_objects, key=lambda value: value.object_id)
    )
    share_classes = tuple(
        FundShareClass(
            share_class_id=item.object_id,
            sub_fund_id=(
                item.parent_object_id
                if item.parent_object_id in subfund_ids
                and item.relationship == "share_class_of"
                else None
            ),
            distribution_policy=(
                item.fields.get("distribution_policy")
                if item.field_source_ids.get("distribution_policy")
                else None
            ),
            source_ids=item.source_ids,
            distribution_policy_source_id=item.field_source_ids.get("distribution_policy"),
        )
        for item in sorted(items, key=lambda value: value.object_id)
        if item.object_type.casefold() in {"share_class", "fund_share_class"}
    )
    return FundHierarchy(sub_funds, share_classes)


@dataclass(frozen=True)
class FundLifecycleEvent:
    fund_id: str
    event_id: str
    status: FundLifecycleStatus
    effective_at: str
    available_at: str
    source: str
    source_id: str
    authority: SourceAuthority
    successor_fund_id: str | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        try:
            status = FundLifecycleStatus(self.status)
            authority = SourceAuthority(self.authority)
        except ValueError as exc:
            raise FundIdentityError("lifecycle status or source authority is unsupported") from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "authority", authority)
        for field in ("fund_id", "event_id", "source", "source_id"):
            if not getattr(self, field).strip():
                raise FundIdentityError(f"{field} must be non-empty")
        _timestamp(self.effective_at, "effective_at")
        _timestamp(self.available_at, "available_at")
        if self.revision < 1:
            raise FundIdentityError("revision must be positive")
        if self.status is FundLifecycleStatus.MERGED and not self.successor_fund_id:
            raise FundIdentityError("merged events require a successor fund ID")

    def to_claims(self) -> tuple[IdentityClaim, ...]:
        common = {
            "instrument_id": self.fund_id,
            "source": self.source,
            "authority": self.authority,
            "source_id": self.source_id,
            "object_type": "fund_lifecycle_event",
            "object_id": self.event_id,
            "parent_object_id": self.fund_id,
            "relationship": "lifecycle_event_for",
            "valid_from": self.effective_at,
            "available_at": self.available_at,
            "revision": self.revision,
            "event_type": self.status.value,
        }
        claims = [
            IdentityClaim(
                field="lifecycle_status",
                value=self.status.value,
                **common,
            )
        ]
        if self.successor_fund_id:
            claims.append(
                IdentityClaim(
                    field="successor_fund_id",
                    value=self.successor_fund_id,
                    **common,
                )
            )
        return tuple(claims)


def lifecycle_events_from_claims(claims: Iterable[IdentityClaim]) -> tuple[FundLifecycleEvent, ...]:
    """Rebuild lifecycle events from the canonical append-only identity claims."""

    groups: dict[tuple[str, str, str], dict[int, list[IdentityClaim]]] = {}
    for claim in claims:
        if claim.object_type != "fund_lifecycle_event":
            continue
        key = (claim.instrument_id, claim.object_id, claim.source_id)
        groups.setdefault(key, {}).setdefault(claim.revision, []).append(claim)

    events: list[FundLifecycleEvent] = []
    for (fund_id, event_id, source_id), revisions in sorted(groups.items()):
        revision = max(revisions)
        group = revisions[revision]
        status_claims = [claim for claim in group if claim.field == "lifecycle_status"]
        if len(status_claims) != 1:
            raise FundIdentityError("lifecycle event must have exactly one status claim")
        status_claim = status_claims[0]
        try:
            status = FundLifecycleStatus(status_claim.value)
        except ValueError as exc:
            raise FundIdentityError("lifecycle event has an unsupported status") from exc
        successors = {claim.value for claim in group if claim.field == "successor_fund_id"}
        if len(successors) > 1:
            raise FundIdentityError("lifecycle event has conflicting successor fund IDs")
        events.append(
            FundLifecycleEvent(
                fund_id=fund_id,
                event_id=event_id,
                status=status,
                effective_at=status_claim.valid_from or "",
                available_at=status_claim.available_at or "",
                source=status_claim.source,
                source_id=source_id,
                authority=status_claim.authority,
                successor_fund_id=next(iter(successors), None),
                revision=revision,
            )
        )
    return tuple(sorted(events, key=lambda event: (event.effective_at, event.event_id, event.revision)))


@dataclass(frozen=True)
class FundEvidence:
    evidence_id: str
    effective_at: str
    available_at: str
    period: FundEvidencePeriod
    source_id: str

    def __post_init__(self) -> None:
        try:
            period = FundEvidencePeriod(self.period)
        except ValueError as exc:
            raise FundIdentityError("fund evidence period label is unsupported") from exc
        object.__setattr__(self, "period", period)
        if not self.evidence_id.strip() or not self.source_id.strip():
            raise FundIdentityError("fund evidence requires an ID and source ID")
        _timestamp(self.effective_at, "effective_at")
        _timestamp(self.available_at, "available_at")


@dataclass(frozen=True)
class FundEvidenceSelection:
    eligible: tuple[FundEvidence, ...]
    excluded: tuple[tuple[FundEvidence, str], ...]


def select_prospective_fund_evidence(
    evidence: Iterable[FundEvidence],
    *,
    inception_at: str | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> FundEvidenceSelection:
    """Exclude pre-inception, incubated, backfilled, and not-yet-known evidence."""

    items = tuple(evidence)
    missing_cutoffs = tuple(
        field
        for field, value in (
            ("inception_at", inception_at),
            ("effective_at", effective_at),
            ("decision_time", decision_time),
        )
        if value is None
    )
    if missing_cutoffs:
        reason = ",".join(f"{field}_unavailable" for field in missing_cutoffs)
        return FundEvidenceSelection((), tuple((item, reason) for item in items))
    inception = _timestamp(inception_at, "inception_at")
    effective = _timestamp(effective_at, "effective_at")
    decision = _timestamp(decision_time, "decision_time")
    eligible: list[FundEvidence] = []
    excluded: list[tuple[FundEvidence, str]] = []
    for item in evidence:
        item_effective = _timestamp(item.effective_at, "evidence.effective_at")
        item_available = _timestamp(item.available_at, "evidence.available_at")
        reason = (
            "not_known_at_decision_time"
            if item_available > decision
            else "after_effective_time"
            if item_effective > effective
            else "pre_inception"
            if item_effective < inception
            else "incubated_period"
            if item.period is FundEvidencePeriod.INCUBATED
            else "backfilled_period"
            if item.period is FundEvidencePeriod.BACKFILLED
            else None
        )
        if reason is None:
            eligible.append(item)
        else:
            excluded.append((item, reason))
    return FundEvidenceSelection(tuple(eligible), tuple(excluded))


@dataclass(frozen=True)
class FundTerm:
    name: str
    value: str
    available_at: str
    valid_from: str
    source_id: str | None = None
    overlay_id: str | None = None
    valid_to: str | None = None
    conflicted: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.value.strip():
            raise FundIdentityError("fund term name and value must be non-empty")
        if not (self.source_id and self.source_id.strip()) and not (
            self.overlay_id and self.overlay_id.strip()
        ):
            raise FundIdentityError("fund terms require a source ID or declared overlay ID")
        _timestamp(self.available_at, "available_at")
        _timestamp(self.valid_from, "valid_from")
        if self.valid_to is not None:
            if _timestamp(self.valid_to, "valid_to") <= _timestamp(self.valid_from, "valid_from"):
                raise FundIdentityError("valid_to must be after valid_from")


@dataclass(frozen=True)
class FundRecommendationReadiness:
    precise_liquidity_available: bool
    precise_cost_available: bool
    reasons: tuple[str, ...]


def fund_recommendation_readiness(
    terms: Iterable[FundTerm],
    *,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> FundRecommendationReadiness:
    """Fail closed when dealing or fee terms are missing or conflicted."""

    if effective_at is None or decision_time is None:
        unavailable_cutoffs = tuple(
            f"{field}_unavailable"
            for field, value in (("effective_time", effective_at), ("decision_time", decision_time))
            if value is None
        )
        return FundRecommendationReadiness(False, False, unavailable_cutoffs)
    effective = _timestamp(effective_at, "effective_at")
    decision = _timestamp(decision_time, "decision_time")
    known: dict[str, list[FundTerm]] = {"dealing_cutoff": [], "ongoing_fee_bps": []}
    for term in terms:
        if term.name not in known:
            continue
        if _timestamp(term.available_at, "available_at") > decision:
            continue
        if _timestamp(term.valid_from, "valid_from") > effective:
            continue
        if term.valid_to is not None and _timestamp(term.valid_to, "valid_to") <= effective:
            continue
        known[term.name].append(term)

    reasons: list[str] = []
    states: dict[str, bool] = {}
    for name, matching in known.items():
        if not matching:
            states[name] = False
            reasons.append(f"missing_{name}")
            continue
        values = {term.value for term in matching}
        if len(values) > 1 or any(term.conflicted for term in matching):
            states[name] = False
            reasons.append(f"conflicted_{name}")
            continue
        states[name] = True
    return FundRecommendationReadiness(
        precise_liquidity_available=states["dealing_cutoff"],
        precise_cost_available=states["ongoing_fee_bps"],
        reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class FundMetricAvailability:
    state: FundMetricState
    value: str | None
    reason: str | None
    source_id: str | None = None
    overlay_id: str | None = None


def fund_metric_availability(
    structure: FundStructure | str | None,
    metric: str,
    observation: FundTerm | None = None,
    *,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> FundMetricAvailability:
    """Keep ETF spread observations out of ordinary-fund NAV dealing paths."""

    if metric != "bid_ask_spread":
        raise FundIdentityError("unsupported fund pricing metric")
    resolved_structure = (
        structure
        if isinstance(structure, FundStructure)
        else _fund_structure(structure)
    )
    if resolved_structure is FundStructure.ORDINARY_FUND:
        return FundMetricAvailability(
            FundMetricState.NOT_APPLICABLE,
            None,
            "not_applicable_to_ordinary_fund_dealing",
        )
    if resolved_structure is None:
        return FundMetricAvailability(FundMetricState.UNAVAILABLE, None, "fund_structure_unavailable")
    if observation is None:
        return FundMetricAvailability(FundMetricState.UNAVAILABLE, None, "spread_observation_unavailable")
    if observation.name != metric:
        return FundMetricAvailability(FundMetricState.UNAVAILABLE, None, "spread_observation_mismatch")
    if effective_at is None or decision_time is None:
        return FundMetricAvailability(FundMetricState.UNAVAILABLE, None, "point_in_time_cutoff_unavailable")
    effective = _timestamp(effective_at, "effective_at")
    decision = _timestamp(decision_time, "decision_time")
    if _timestamp(observation.available_at, "available_at") > decision:
        return FundMetricAvailability(FundMetricState.UNAVAILABLE, None, "spread_not_known_at_decision_time")
    if _timestamp(observation.valid_from, "valid_from") > effective or (
        observation.valid_to is not None
        and _timestamp(observation.valid_to, "valid_to") <= effective
    ):
        return FundMetricAvailability(FundMetricState.UNAVAILABLE, None, "spread_not_valid_at_effective_time")
    return FundMetricAvailability(
        FundMetricState.AVAILABLE,
        observation.value,
        None,
        observation.source_id,
        observation.overlay_id,
    )


def _fund_structure(value: str | None) -> FundStructure | None:
    if value is None:
        return None
    try:
        return FundStructure(value.strip().casefold())
    except ValueError:
        return None


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise FundIdentityError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise FundIdentityError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)
