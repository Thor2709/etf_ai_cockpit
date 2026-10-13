"""Semi-automatic Pillar 3 / annual-report figure queue (SB2).

Extracted figures are written to ``data/pending/pillar3/<instrument_id>.json`` with their source
document, page and printed text. A figure is **pending** until the owner confirms it in the UI; only
**confirmed** figures ever reach the scorecard, and only from the moment of confirmation
(``decided_at``), so a later confirmation can never be used for an earlier decision time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from etf_cockpit.core.atomic_io import atomic_write_json

SCHEMA_VERSION = "pillar3_pending.v1"

# metric -> (plain-language label, unit). Percent figures are stored in percent, as printed.
PILLAR3_METRICS: dict[str, tuple[str, str]] = {
    "cet1_ratio_pct": ("CET1 ratio", "percent"),
    "cet1_requirement_pct": ("CET1 requirement including buffers and Pillar 2", "percent"),
    "leverage_ratio_pct": ("Leverage ratio", "percent"),
    "lcr_pct": ("Liquidity coverage ratio (LCR)", "percent"),
    "nsfr_pct": ("Net stable funding ratio (NSFR)", "percent"),
    "deposit_to_loan_ratio_pct": ("Deposit-to-loan ratio (deposit coverage)", "percent"),
    "stage2_pct_gross_loans": ("Stage 2 share of gross loans", "percent"),
    "stage3_pct_gross_loans": ("Stage 3 share of gross loans", "percent"),
    "rwa_nok": ("Risk-weighted assets", "NOK"),
}

STATUSES = ("pending", "confirmed", "rejected")


def queue_path(root: Path, instrument_id: str) -> Path:
    return Path(root) / "data" / "pending" / "pillar3" / f"{str(instrument_id).strip().upper()}.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def figure_id(metric: str, document_id: str, period: str, page: object, value: object) -> str:
    digest = hashlib.sha256(f"{metric}|{document_id}|{period}|{page}|{value}".encode("utf-8")).hexdigest()[:12]
    return f"{metric}:{digest}"


def load_queue(root: Path, instrument_id: str) -> dict[str, object]:
    """Read the queue for one instrument; a missing or unreadable file is an empty queue."""

    path = queue_path(root, instrument_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "instrument_id": str(instrument_id).upper(), "documents": [], "figures": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("figures"), list):
        return {"schema_version": SCHEMA_VERSION, "instrument_id": str(instrument_id).upper(), "documents": [], "figures": []}
    payload.setdefault("documents", [])
    return payload


def save_queue(root: Path, instrument_id: str, queue: Mapping[str, object]) -> Path:
    path = queue_path(root, instrument_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(queue)
    payload["schema_version"] = SCHEMA_VERSION
    payload["instrument_id"] = str(instrument_id).upper()
    payload["execution_allowed"] = False
    atomic_write_json(path, payload)
    return path


def merge_extraction(
    root: Path,
    instrument_id: str,
    document: Mapping[str, object],
    figures: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Add newly extracted figures as pending; keep every earlier decision untouched."""

    queue = load_queue(root, instrument_id)
    documents = [item for item in queue["documents"] if isinstance(item, Mapping) and item.get("document_id") != document.get("document_id")]
    documents.append(dict(document))
    existing = {str(item.get("figure_id")): item for item in queue["figures"] if isinstance(item, Mapping)}
    extracted_at = _utc_now()
    for figure in figures:
        item = dict(figure)
        item["figure_id"] = str(item.get("figure_id") or figure_id(str(item["metric"]), str(document.get("document_id")), str(item.get("period")), item.get("page"), item.get("value")))
        item.setdefault("document_id", document.get("document_id"))
        previous = existing.get(item["figure_id"])
        if previous is not None and previous.get("status") in {"confirmed", "rejected"}:
            continue  # an owner decision is never overwritten by a re-extraction
        item.update(status="pending", extracted_at=extracted_at, decided_at=None, decided_by=None, note=None)
        existing[item["figure_id"]] = item
    queue["documents"] = documents
    queue["figures"] = sorted(existing.values(), key=lambda row: (str(row.get("metric")), str(row.get("figure_id"))))
    save_queue(root, instrument_id, queue)
    return queue


def decide(
    root: Path,
    instrument_id: str,
    figure: str,
    decision: str,
    *,
    decided_at: str | None = None,
    note: str | None = None,
) -> dict[str, object]:
    """Confirm or reject a figure, retaining the history of any superseded confirmation."""

    if decision not in {"confirmed", "rejected"}:
        raise ValueError("decision must be 'confirmed' or 'rejected'")
    queue = load_queue(root, instrument_id)
    target = next((item for item in queue["figures"] if isinstance(item, dict) and item.get("figure_id") == figure), None)
    if target is None:
        raise KeyError(f"figure {figure} is not in the queue for {instrument_id}")
    if target.get("status") != "pending":
        raise ValueError(f"figure {figure} has already been decided")
    stamp = decided_at or _utc_now()
    if decision == "confirmed":
        for other in queue["figures"]:
            if (
                isinstance(other, dict)
                and other is not target
                and other.get("metric") == target.get("metric")
                and other.get("period") == target.get("period")
                and other.get("status") == "confirmed"
                and not other.get("superseded_at")
            ):
                other["superseded_at"] = stamp
                other["superseded_by"] = target.get("figure_id")
    target.update(status=decision, decided_at=stamp, decided_by="owner", note=note)
    if decision == "confirmed":
        target.pop("superseded_at", None)
        target.pop("superseded_by", None)
    save_queue(root, instrument_id, queue)
    return queue


def pending_count(root: Path, instrument_id: str) -> int:
    return sum(1 for item in load_queue(root, instrument_id)["figures"] if isinstance(item, Mapping) and item.get("status") == "pending")


def confirmed_figures(queue: Mapping[str, object], decision_time: str | None) -> list[Mapping[str, object]]:
    """Active confirmed figures at ``decision_time``, including retained historical states."""

    cutoff = _parse(decision_time) if decision_time else None
    best: dict[tuple[str, str], Mapping[str, object]] = {}
    for item in queue.get("figures", ()):
        if not isinstance(item, Mapping) or item.get("status") != "confirmed":
            continue
        decided = _parse(item.get("decided_at"))
        if decided is None or (cutoff is not None and decided > cutoff):
            continue
        superseded = _parse(item.get("superseded_at"))
        if item.get("superseded_at") and superseded is None:
            continue
        if superseded is not None and (cutoff is None or superseded <= cutoff):
            continue
        metric = str(item.get("metric"))
        period = str(item.get("period") or "")
        key = (metric, period)
        current = best.get(key)
        if current is None or decided > (_parse(current.get("decided_at")) or datetime.min.replace(tzinfo=timezone.utc)):
            best[key] = item
    return list(best.values())


def _parse(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
