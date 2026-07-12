"""Typed provenance records and fail-closed score eligibility."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from etf_cockpit.data.contracts import SourceAuthority


@dataclass(frozen=True)
class EvidenceSource:
    # Keep the historical first five positional fields stable for parsers and
    # fixtures from the provider-registry wave.
    dataset: str
    source_id: str
    authority: SourceAuthority
    as_of_date: str | None
    freshness_status: str
    confidence: float | str | None = None
    quality: float | str | None = None
    provider_id: str | None = None
    conflict_id: str | None = None
    source_name: str | None = None
    checksum: str | None = None
    available: bool = True

    def __post_init__(self) -> None:
        authority = self.authority if isinstance(self.authority, SourceAuthority) else SourceAuthority(str(self.authority).strip().lower())
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "dataset", str(self.dataset or "").strip())
        object.__setattr__(self, "source_id", str(self.source_id or "").strip())
        object.__setattr__(self, "freshness_status", str(self.freshness_status or "unknown").strip().lower())

    @property
    def authority_rank(self) -> int:
        return self.authority.rank

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["authority"] = self.authority.value
        payload["authority_rank"] = self.authority_rank
        return payload


@dataclass(frozen=True)
class EvidenceLedgerEntry:
    instrument_id: str
    component: str
    value: float | None
    source: EvidenceSource | None
    conflict_id: str | None
    score_eligible: bool
    executable_authority: bool = False
    reason: str = ""
    raw_metric: float | None = None
    evidence_quality: float | str | None = None

    @property
    def source_id(self) -> str:
        return self.source.source_id if self.source is not None else ""

    @property
    def source_authority(self) -> str:
        return self.source.authority.value if self.source is not None else "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "component": self.component,
            "value": self.value,
            "source_id": self.source_id,
            "source_authority": self.source_authority,
            "authority_rank": self.source.authority_rank if self.source is not None else 0,
            "as_of_date": self.source.as_of_date if self.source is not None else None,
            "freshness_status": self.source.freshness_status if self.source is not None else "missing",
            "conflict_id": self.conflict_id,
            "score_eligible": self.score_eligible,
            "executable_authority": False,
            "reason": self.reason,
        }


_MISSING = object()


def ledger_entry_for_component(
    instrument_or_component: object,
    component_or_source: object,
    value: float | None | object = _MISSING,
    source: EvidenceSource | None = None,
    *,
    conflict_id: str | None = None,
) -> EvidenceLedgerEntry:
    """Build a ledger entry using either legacy or typed-call syntax.

    Legacy callers use ``(instrument_id, component, value, source)``.  New
    callers may pass ``(SimpleScoreComponent, EvidenceSource)``; the adapter
    reads ``key``/``score_10`` and keeps compatibility with duck-typed score
    components to avoid a dependency cycle.
    """

    if isinstance(component_or_source, EvidenceSource) and not isinstance(instrument_or_component, str):
        component = instrument_or_component
        instrument_id = str(getattr(component, "instrument_id", "") or "")
        component_name = str(getattr(component, "key", "") or "")
        component_value = getattr(component, "score_10", None)
        source_obj = component_or_source
    else:
        instrument_id = str(instrument_or_component or "")
        component_name = str(component_or_source or "")
        component_value = None if value is _MISSING else value
        source_obj = source
    if source_obj is not None and not isinstance(source_obj, EvidenceSource):
        raise TypeError("source must be an EvidenceSource or None")
    effective_conflict = conflict_id or (source_obj.conflict_id if source_obj else None)
    eligible, reason = _eligibility(component_value, source_obj, effective_conflict)
    numeric_value = _number_or_none(component_value)
    return EvidenceLedgerEntry(
        instrument_id=instrument_id,
        component=component_name,
        value=numeric_value,
        source=source_obj,
        conflict_id=effective_conflict,
        score_eligible=eligible,
        executable_authority=False,
        reason=reason,
        raw_metric=_number_or_none(getattr(instrument_or_component, "raw_score", None)) if source is None and not isinstance(instrument_or_component, str) else None,
        evidence_quality=source_obj.quality if source_obj is not None else None,
    )


def _eligibility(value: object, source: EvidenceSource | None, conflict_id: str | None) -> tuple[bool, str]:
    if value is None or _number_or_none(value) is None:
        return False, "ineligible: score value is unavailable"
    if source is None or not source.source_id:
        return False, "ineligible: source ID is missing"
    if not source.as_of_date:
        return False, "ineligible: evidence as-of date is missing"
    if not source.available:
        return False, "ineligible: source is unavailable"
    if conflict_id:
        return False, f"ineligible: material conflict {conflict_id} requires manual review"
    if source.freshness_status in {"stale", "stale_block", "unavailable", "missing", "unknown", "missing_or_pending", "not_checked"}:
        return False, f"ineligible: evidence freshness is {source.freshness_status}"
    if source.authority in {SourceAuthority.MODEL, SourceAuthority.COMMUNITY, SourceAuthority.MANUAL}:
        return False, f"ineligible: {source.authority.value} evidence is context-only"
    if not _quality_acceptable(source.quality) or not _quality_acceptable(source.confidence):
        return False, "ineligible: evidence confidence or quality is below the score threshold"
    return True, "eligible: source-backed fresh evidence"


def _quality_acceptable(value: float | str | None) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() not in {"low", "poor", "unavailable", "unknown"}
    try:
        return float(value) >= 0.5
    except (TypeError, ValueError):
        return False


def _number_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
