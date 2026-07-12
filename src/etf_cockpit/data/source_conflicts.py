"""Deterministic source conflict resolution with an auditable trail."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from etf_cockpit.data.contracts import SourceAuthority


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


@dataclass(frozen=True)
class ConflictResolution:
    selected: dict[str, MetricClaim]
    conflicts: tuple[MetricConflict, ...]
    claims: tuple[MetricClaim, ...] = ()
    requires_manual_review: bool = False


def resolve_conflicts(claims: Iterable[MetricClaim]) -> ConflictResolution:
    """Select a canonical claim while retaining every source disagreement.

    Official/issuer claims outrank vendors and context/model sources.  Ties
    are broken by source ID, source name and stable value representation, so
    reversing input order cannot change the result.
    """

    items = tuple(_coerce_claim(item) for item in claims)
    grouped: dict[tuple[str, str], list[MetricClaim]] = {}
    for claim in items:
        if not claim.instrument_id or not claim.field:
            continue
        grouped.setdefault((claim.instrument_id, claim.field), []).append(claim)
    selected: dict[str, MetricClaim] = {}
    conflicts: list[MetricConflict] = []
    for (instrument_id, field), field_claims in sorted(grouped.items()):
        ordered = sorted(field_claims, key=_claim_sort_key)
        winner = ordered[0]
        key = field if len({item.instrument_id for item in items}) == 1 else f"{instrument_id}:{field}"
        selected[key] = winner
        values = _stable_values(item.value for item in field_claims)
        source_ids = tuple(sorted({item.source_id or "unknown" for item in field_claims}))
        missing_source = any(not item.source_id for item in field_claims)
        if len(values) > 1 or missing_source:
            conflict_id = _conflict_id(instrument_id, field, values, source_ids)
            reason = _reason(winner, field_claims, values)
            conflicts.append(
                MetricConflict(
                    instrument_id=instrument_id,
                    field=field,
                    selected_value=winner.value,
                    values=values,
                    source_ids=source_ids,
                    requires_manual_review=True,
                    conflict_id=conflict_id,
                    reason=reason,
                    resolution_status="manual_review",
                    evidence_quality="reduced",
                    selected_source_id=winner.source_id,
                )
            )
    ordered_claims = tuple(sorted(items, key=lambda item: (item.instrument_id, item.field, *_claim_sort_key(item))))
    return ConflictResolution(
        selected=selected,
        conflicts=tuple(conflicts),
        claims=ordered_claims,
        requires_manual_review=bool(conflicts),
    )


def _coerce_claim(claim: MetricClaim) -> MetricClaim:
    if not isinstance(claim, MetricClaim):
        raise TypeError("metric claims must be MetricClaim instances")
    try:
        authority = claim.authority if isinstance(claim.authority, SourceAuthority) else SourceAuthority(str(claim.authority).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unknown metric authority: {claim.authority!r}") from exc
    return MetricClaim(
        instrument_id=str(claim.instrument_id or "").strip(),
        field=str(claim.field or "").strip(),
        value=claim.value,
        source=str(claim.source or "").strip(),
        authority=authority,
        source_id=str(claim.source_id or "").strip(),
        unit=claim.unit,
        period=claim.period,
        as_of=claim.as_of,
        freshness_status=str(claim.freshness_status or "unknown").strip().lower(),
        confidence=claim.confidence,
    )


def _claim_sort_key(claim: MetricClaim) -> tuple[int, str, str, str]:
    return (
        -claim.authority.rank,
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


def _reason(winner: MetricClaim, claims: Iterable[MetricClaim], values: tuple[object, ...]) -> str:
    authority_names = sorted({item.authority.value for item in claims})
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


def _conflict_id(instrument_id: str, field: str, values: tuple[object, ...], source_ids: tuple[str, ...]) -> str:
    payload = "|".join((instrument_id, field, *(_stable_repr(item) for item in values), *source_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
