from __future__ import annotations

from dataclasses import dataclass

from etf_cockpit.data.contracts import SourceAuthority


@dataclass(frozen=True)
class EvidenceSource:
    dataset: str
    source_id: str
    authority: SourceAuthority
    as_of_date: str | None
    freshness_status: str


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


def ledger_entry_for_component(
    instrument_id: str,
    component: str,
    value: float | None,
    source: EvidenceSource | None,
    *,
    conflict_id: str | None = None,
) -> EvidenceLedgerEntry:
    eligible = source is not None and bool(source.source_id) and value is not None and not conflict_id and source.freshness_status not in {"stale", "unavailable"}
    reason = "eligible" if eligible else "missing, stale or conflicted evidence"
    return EvidenceLedgerEntry(instrument_id, component, value, source, conflict_id, eligible, False, reason)
