from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class MetricConflict:
    instrument_id: str
    field: str
    selected_value: object
    values: tuple[object, ...]
    source_ids: tuple[str, ...]
    requires_manual_review: bool


@dataclass(frozen=True)
class ConflictResolution:
    selected: dict[str, MetricClaim]
    conflicts: tuple[MetricConflict, ...]


def resolve_conflicts(claims: Iterable[MetricClaim]) -> ConflictResolution:
    grouped: dict[str, list[MetricClaim]] = {}
    for claim in claims:
        grouped.setdefault(claim.field, []).append(claim)
    selected: dict[str, MetricClaim] = {}
    conflicts: list[MetricConflict] = []
    for field, field_claims in grouped.items():
        ordered = sorted(field_claims, key=lambda claim: (-claim.authority.rank, claim.source_id))
        winner = ordered[0]
        selected[field] = winner
        values = tuple({claim.value for claim in field_claims})
        if len(values) > 1:
            conflicts.append(
                MetricConflict(
                    instrument_id=winner.instrument_id,
                    field=field,
                    selected_value=winner.value,
                    values=values,
                    source_ids=tuple(sorted(claim.source_id for claim in field_claims)),
                    requires_manual_review=True,
                )
            )
    return ConflictResolution(selected=selected, conflicts=tuple(conflicts))
