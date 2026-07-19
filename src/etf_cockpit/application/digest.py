"""Deterministic, fail-closed application digest for the dashboard.

The digest adapts already available local evidence.  It does not fetch data,
infer urgency from timestamps or grant execution authority.  Missing source
contracts remain visible as unavailable input status so the dashboard cannot
mistake an empty cache for a quiet day.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from etf_cockpit.application.contracts import DigestItemViewModel, DigestViewModel


_SOURCE_NAMES = (
    "data_health",
    "alerts",
    "source_revisions",
    "events",
    "model_drift",
    "portfolio_risk",
    "proposal_state",
    "paper_incidents",
    "recovery_export",
)
_SEVERITIES = {"critical", "warning", "info"}
_STATUSES = {"available", "unavailable", "manual_review"}
_SEVERITY_RANK = {"critical": 0, "warning": 10, "info": 20}
_STATUS_RANK = {"manual_review": 0, "unavailable": 5, "available": 10}


class DigestUnavailableError(RuntimeError):
    """Raised when a known local digest source cannot be adapted safely."""


def build_digest(
    records: Mapping[str, Iterable[Mapping[str, object] | object] | None],
    *,
    as_of: str | None = None,
) -> DigestViewModel:
    """Build a stable queue from typed-or-mapping source records.

    Each source is represented in ``source_status`` even when it has no local
    records.  A record without provenance, a title or a rationale is retained
    but becomes ``manual_review`` rather than being silently promoted to an
    actionable item.
    """

    items: dict[str, DigestItemViewModel] = {}
    source_status: list[tuple[str, str]] = []
    for source in _SOURCE_NAMES:
        raw_records = tuple(records.get(source) or ())
        source_records = tuple(_as_mapping(item) for item in raw_records)
        malformed_count = sum(item is None for item in source_records)
        source_records = tuple(item for item in source_records if item is not None)
        if malformed_count:
            source_records += (
                {
                    "item_id": f"{source}:malformed",
                    "title": "Malformed local input requires review",
                    "rationale": f"{malformed_count} {source.replace('_', ' ')} record(s) could not be adapted safely.",
                    "status": "manual_review",
                    "provenance": "unavailable",
                },
            )
        if not source_records:
            source_status.append((source, "unavailable"))
            continue

        source_state = "available"
        for index, record in enumerate(source_records):
            item = _build_item(source, index, record, as_of=as_of)
            if item.status == "manual_review":
                source_state = "manual_review"
            elif item.status == "unavailable" and source_state == "available":
                source_state = "unavailable"
            items[item.item_id] = _prefer(items.get(item.item_id), item)
        source_status.append((source, source_state))

    if not items:
        items["digest:no-local-evidence"] = DigestItemViewModel(
            item_id="digest:no-local-evidence",
            source="digest",
            category="evidence",
            severity="warning",
            status="manual_review",
            title="No local evidence is available for prioritisation",
            rationale="Required alert, event, risk, proposal and recovery inputs are unavailable; inspect the source workspaces before acting.",
            as_of=as_of,
            provenance="application.digest",
            priority=5,
        )

    ordered = tuple(sorted(items.values(), key=lambda item: (item.priority, item.source, item.item_id)))
    return DigestViewModel(
        as_of=as_of,
        items=ordered,
        source_status=tuple(sorted((name, status) for name, status in source_status)),
    )


def build_digest_from_snapshot(
    snapshot: object,
    *,
    proposal_records: Sequence[object] = (),
    local_root: Path | str | None = None,
) -> DigestViewModel:
    """Adapt a snapshot and optional proposal view models into the digest."""

    report = getattr(snapshot, "data_report", None)
    as_of = _text(getattr(report, "as_of_date", None))
    records: dict[str, Iterable[Mapping[str, object] | object] | None] = {
        "alerts": _records(snapshot, "alerts"),
        "source_revisions": _records(snapshot, "source_revisions"),
        "events": _records(snapshot, "events") or _records(snapshot, "operations"),
        "model_drift": _records(snapshot, "model_drift"),
        "portfolio_risk": _records(snapshot, "portfolio_risk") or _records(snapshot, "risk_report"),
        "proposal_state": proposal_records or _records(snapshot, "proposals"),
        "paper_incidents": _records(snapshot, "paper_incidents"),
        "recovery_export": _records(snapshot, "recovery_export") or _records(snapshot, "recovery_status"),
    }
    snapshot_records = getattr(snapshot, "digest_records", None)
    snapshot_root = _text(getattr(snapshot, "digest_root", None))
    requested_root = _text(local_root)
    roots_match = not snapshot_root or not requested_root or _normalise_root(snapshot_root) == _normalise_root(requested_root)
    if isinstance(snapshot_records, Mapping) and roots_match:
        for source in _SOURCE_NAMES:
            if source in snapshot_records:
                records[source] = snapshot_records.get(source)
    elif isinstance(snapshot_records, Mapping):
        records["source_revisions"] = (
            {
                "item_id": "digest:root-mismatch",
                "category": "source_revision",
                "severity": "warning",
                "status": "manual_review",
                "title": "Digest source root changed",
                "rationale": "The snapshot was built from a different local root; source records were withheld to prevent mixed-workspace evidence.",
                "provenance": f"snapshot-root:{snapshot_root}",
            },
        )
    if report is not None:
        report_status = _text(getattr(report, "status", None)) or "unavailable"
        records["data_health"] = (
            {
                "item_id": "data-health",
                "category": "data_quality",
                "severity": "info" if report_status.casefold() == "clean" else "critical" if report_status.casefold() == "blocked" else "warning",
                "status": "available" if report_status.casefold() == "clean" else "manual_review",
                "title": f"Data health is {report_status}",
                "rationale": "Data-quality gates outrank forecasts and actions; inspect the data-health report before relying on downstream evidence.",
                "as_of": as_of,
                "provenance": "snapshot.data_report",
            },
        )
    return build_digest(records, as_of=as_of)


def _build_item(source: str, index: int, record: Mapping[str, object], *, as_of: str | None) -> DigestItemViewModel:
    item_id = _text(
        record.get("item_id")
        or record.get("id")
        or record.get("alert_id")
        or record.get("event_id")
        or record.get("operation_id")
        or record.get("proposal_id")
        or record.get("incident_id")
        or record.get("workflow_id")
    ) or f"{source}:{index}"
    category = _text(record.get("category")) or source
    title = _text(record.get("title") or record.get("name"))
    if not title and source == "proposal_state":
        outcome = _text(record.get("outcome") or record.get("status")) or "pending"
        title = f"Proposal {_text(record.get('proposal_id')) or item_id} is {outcome}"
    rationale = _text(record.get("rationale") or record.get("message") or record.get("reason"))
    provenance = _text(
        record.get("provenance")
        or record.get("source_checksum")
        or record.get("source_id")
        or record.get("input_checksum")
    )
    status = _normalise_status(record.get("status") or record.get("outcome"))
    if not title or not rationale or not provenance:
        status = "manual_review"
    if not title:
        title = f"{source.replace('_', ' ').title()} input requires review"
    if not rationale:
        rationale = "The source did not provide a complete explanation; manual review is required."
    if not provenance:
        provenance = "unavailable"
    severity = _normalise_severity(record.get("severity"), status)
    effective_as_of = _text(record.get("as_of") or record.get("occurred_at") or as_of)
    priority = _SEVERITY_RANK[severity] + _STATUS_RANK[status]
    return DigestItemViewModel(
        item_id=item_id,
        source=source,
        category=category,
        severity=severity,
        status=status,
        title=title,
        rationale=rationale,
        as_of=effective_as_of,
        provenance=provenance,
        priority=priority,
    )


def _prefer(existing: DigestItemViewModel | None, candidate: DigestItemViewModel) -> DigestItemViewModel:
    if existing is None:
        return candidate
    return min(existing, candidate, key=lambda item: (item.priority, item.status, item.provenance))


def _normalise_status(value: object) -> str:
    status = (_text(value) or "").casefold()
    if status in {"ok", "clean", "ready", "success", "available", "passed", "complete", "approved", "accepted"}:
        return "available"
    if status in {"missing", "unavailable", "unknown", "not_configured"}:
        return "unavailable"
    if status in {"blocked", "deferred", "rejected", "expired", "failed", "cancelled", "error"}:
        return "manual_review"
    return "manual_review" if status not in _STATUSES else status


def _normalise_severity(value: object, status: str) -> str:
    severity = (_text(value) or "").casefold()
    if severity in _SEVERITIES:
        return severity
    if status == "manual_review":
        return "warning"
    return "info"


def _records(snapshot: object, name: str) -> tuple[object, ...]:
    value = getattr(snapshot, name, None)
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, Mapping) else None
    return None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _normalise_root(value: str) -> str:
    return str(Path(value).expanduser().resolve()).casefold()


__all__ = ["DigestUnavailableError", "build_digest", "build_digest_from_snapshot"]
