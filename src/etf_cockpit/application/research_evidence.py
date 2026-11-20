"""Application services for quarantined AI research evidence.

Open defaults: evidence is local only, externally supplied text remains
untrusted, and neither evidence type is eligible for scores or authority.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from etf_cockpit.audit.thesis_diary import ThesisDiaryStore, build_thesis_entry
from etf_cockpit.data.ai_research_evidence import (
    append_ai_research_evidence,
    load_ai_research_evidence,
    research_evidence_revision,
    validate_item,
)


def validate_research_batch(items: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    rows = tuple(validate_item(item) for item in items)
    if not rows:
        raise ValueError("at least one research evidence item is required")
    return rows


def search_document_chunks(root: Path, query: str, *, as_of: str, limit: int = 10, mode: str = "lexical") -> dict[str, object]:
    """Search the local document chunk store (INT-23); hit text stays untrusted.

    ``mode="hybrid"`` fuses lexical and dense rankings only while ``HYBRID_ENABLED`` is set and the
    embeddings are available; otherwise the result is lexical and ``mode_used`` says so.
    """

    from etf_cockpit.data import document_embeddings
    from etf_cockpit.data.document_chunks import CHUNK_STORE_NAME, search

    if mode not in {"lexical", "hybrid"}:
        raise ValueError("mode must be 'lexical' or 'hybrid'")
    path = Path(root) / "data" / CHUNK_STORE_NAME
    reason = None
    if mode == "hybrid":
        reason = "hybrid retrieval is disabled until the evaluation shows it is not worse than lexical"
        if document_embeddings.HYBRID_ENABLED:
            hybrid = document_embeddings.hybrid_search(path, query, as_of=as_of, limit=limit)
            if hybrid["status"] == "available":
                return {**hybrid, "mode_used": "hybrid"}
            reason = str(hybrid["reason"])
    return {**search(path, query, as_of=as_of, limit=limit), "mode_used": "lexical", "fallback_reason": reason}


def index_imported_pdf(root: Path, pdf_path: Path, *, source_id: str) -> int | None:
    """INT-23: chunk an imported, text-bearing PDF into the local chunk store; ``None`` when it cannot be read.

    ``known_at`` is the import instant; the publication date is not known here, so ``published_at`` uses the
    same instant (never earlier), which keeps every search at an earlier cut-off free of this document.
    """

    import sqlite3

    from etf_cockpit.data.document_chunks import CHUNK_STORE_NAME, chunk_pages, index_document
    from etf_cockpit.parsers.priips_kid import _read_pages

    pages, warning = _read_pages(Path(pdf_path))
    if warning is not None:
        return None
    known_at = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    chunks = chunk_pages(pages, document_sha256=digest, source_id=source_id, published_at=known_at, known_at=known_at)
    try:
        index_document(Path(root) / "data" / CHUNK_STORE_NAME, chunks)
    except (OSError, sqlite3.DatabaseError):
        return None
    return len(chunks)


def research_revision(root: Path) -> str:
    return research_evidence_revision(Path(root) / "data")


def record_research_findings(
    items: Iterable[Mapping[str, Any]], *, expected_revision: str, root: Path
) -> tuple[str, ...]:
    return append_ai_research_evidence(
        items, expected_revision=expected_revision, root=Path(root) / "data"
    )


def thesis_revision(root: Path) -> str:
    store = ThesisDiaryStore(Path(root) / "data")
    digest = hashlib.sha256()
    for path in (store.index_path, store.events_path, store.commitment_path):
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()


def record_research_thesis(
    *,
    instrument_ids: Iterable[str],
    thesis: str,
    evidence_refs: Iterable[str],
    invalidation_rules: Iterable[str],
    review_date: str,
    expected_revision: str,
    root: Path,
) -> tuple[str, ...]:
    selected_ids = tuple(dict.fromkeys(str(value).strip() for value in instrument_ids if str(value).strip()))
    references = tuple(str(value).strip() for value in evidence_refs)
    rules = tuple(str(value).strip() for value in invalidation_rules)
    if not selected_ids or len(selected_ids) > 25:
        raise ValueError("instrument_ids must contain between 1 and 25 ids")
    if any(not value for value in references) or any(not value for value in rules):
        raise ValueError("evidence_refs and invalidation_rules must contain non-empty text")
    if not isinstance(thesis, str) or not thesis.strip() or len(thesis) > 4000:
        raise ValueError("thesis must be non-empty text no longer than 4000 characters")
    try:
        review = date.fromisoformat(review_date)
    except (TypeError, ValueError):
        raise ValueError("review_date must be an ISO-8601 date") from None
    if review < datetime.now(timezone.utc).date():
        raise ValueError("review_date cannot be in the past")
    if thesis_revision(root) != expected_revision:
        raise RuntimeError("thesis diary changed after preview; request a new preview")

    store = ThesisDiaryStore(Path(root) / "data")
    created_at = datetime.now(timezone.utc).isoformat()
    ids: list[str] = []
    for instrument_id in selected_ids:
        entry = build_thesis_entry(
            prompt=thesis.strip(),
            model="unverified external submission",
            source_snapshot={},
            retrieval_snapshot={},
            evidence_snapshot={
                "evidence_refs": list(references),
                "invalidation_rules": list(rules),
                "review_date": review.isoformat(),
            },
            llm_output={
                "summary": thesis.strip(),
                "blocked_trade_explanations": [],
                "contradictions": [],
                "external_review_questions": [],
                "confidence": 0.0,
                "executable_authority": False,
            },
            instrument_id=instrument_id,
            input_sources=list(references),
            thesis_summary=thesis.strip(),
            human_review_status="pending",
            final_advisory_label="manual_review",
            decision_time=created_at,
            created_at=created_at,
            generation_record={"provenance": "synthetic_fallback", "synthetic": True},
        )
        stored = store.create(entry)
        ids.append(stored.thesis_id)
    return tuple(ids)


def load_research_findings(
    *,
    root: Path,
    subject: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    include_news: bool = False,
    include_theses: bool = False,
) -> dict[str, Any]:
    evidence = load_ai_research_evidence(Path(root) / "data")
    cutoff = None
    if since is not None:
        cutoff = _timestamp(since, "since")
    subject_key = subject.strip().casefold() if isinstance(subject, str) and subject.strip() else None
    selected_kind = kind.strip().casefold() if isinstance(kind, str) and kind.strip() else None

    def matches(item: Mapping[str, Any]) -> bool:
        stamp = _timestamp(item.get("known_at"), "known_at")
        return (
            (not subject_key or subject_key in str(item.get("subject", "")).casefold())
            and (not selected_kind or item.get("kind") == selected_kind)
            and (cutoff is None or stamp >= cutoff)
        )

    rows: list[dict[str, Any]] = []
    matched_evidence: list[dict[str, Any]] = []
    for item in evidence:
        finding = _untrusted_finding(item)
        if not matches(finding):
            continue
        matched_evidence.append(item)
        rows.append(finding)

    if include_news:
        rows.extend(item for item in _load_news(Path(root), subject_key, cutoff) if matches(item))
    if include_theses:
        rows.extend(item for item in _load_theses(Path(root), subject_key) if matches(item))
    rows.sort(key=lambda row: (_timestamp(row.get("known_at"), "known_at"), str(row.get("id", ""))), reverse=True)

    stances = [float(item["stance"]) for item in matched_evidence if isinstance(item.get("stance"), (int, float))]
    latest = max((_timestamp(item["retrieved_at"], "retrieved_at") for item in matched_evidence), default=None)
    age_days = None if latest is None else max(0.0, (datetime.now(timezone.utc) - latest).total_seconds() / 86400.0)
    if stances:
        mean = sum(stances) / len(stances)
        dispersion = sum((value - mean) ** 2 for value in stances) / len(stances)
        dispersion = dispersion**0.5
    else:
        mean = dispersion = None
    return {
        "status": "available" if rows else "unavailable",
        "unavailable_reason": None if rows else "no_matching_research_evidence",
        "findings": rows,
        "sentiment": {
            "n": len(stances),
            "mean": mean,
            "dispersion": dispersion,
            "staleness_days": age_days,
        },
        "execution_allowed": False,
        "scoring_eligible": False,
    }


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp with a timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be an ISO-8601 timestamp with a timezone")
    return parsed.astimezone(timezone.utc)


def _untrusted_finding(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("evidence_id"),
        "subject": item.get("subject"),
        "kind": item.get("kind"),
        "label": item.get("label"),
        "source_url": item.get("source_url"),
        "source_title": item.get("source_title"),
        "published_at": item.get("published_at"),
        "retrieved_at": item.get("retrieved_at"),
        "known_at": item.get("known_at"),
        "stance": item.get("stance"),
        "confidence": item.get("confidence"),
        "untrusted": {"claim": item.get("claim"), "excerpt": item.get("excerpt", "")},
        "executable_authority": False,
    }


def _load_news(root: Path, subject: str | None, cutoff: datetime | None) -> list[dict[str, Any]]:
    from etf_cockpit.data.news_context import load_news_items

    path = root / "data" / "clean" / "news_context.parquet"
    if not path.is_file():
        return []
    frame = load_news_items(path, strict=True)
    rows: list[dict[str, Any]] = []
    for item in frame.to_dict(orient="records"):
        identifier = str(item.get("instrument_id", ""))
        known_at = item.get("ingested_at")
        try:
            stamp = _timestamp(str(known_at), "ingested_at")
        except ValueError:
            continue
        if subject and subject not in identifier.casefold():
            continue
        if cutoff and stamp < cutoff:
            continue
        rows.append({
            "id": item.get("news_id"), "subject": identifier, "kind": "news",
            "label": "local_news_context", "known_at": stamp.isoformat(),
            "published_at": item.get("published_at"), "retrieved_at": stamp.isoformat(),
            "untrusted": {"claim": item.get("headline"), "excerpt": item.get("excerpt", "")},
            "executable_authority": False,
        })
    return rows


def _load_theses(root: Path, subject: str | None) -> list[dict[str, Any]]:
    store = ThesisDiaryStore(root / "data")
    rows: list[dict[str, Any]] = []
    for entry in store.list_entries():
        if subject and subject not in entry.instrument_id.casefold():
            continue
        rows.append({
            "id": entry.thesis_id, "subject": entry.instrument_id, "kind": "thesis",
            "label": "ai_thesis_pending_review", "known_at": entry.decision_time,
            "review_date": entry.evidence_snapshot.get("review_date"),
            "untrusted": {"claim": entry.thesis_summary, "evidence_refs": entry.input_sources,
                          "invalidation_rules": entry.evidence_snapshot.get("invalidation_rules", [])},
            "human_review_status": entry.human_review_status,
            "execution_allowed": False, "executable_authority": False,
        })
    return rows


__all__ = [
    "index_imported_pdf", "load_research_findings", "record_research_findings", "record_research_thesis",
    "research_revision", "search_document_chunks", "thesis_revision", "validate_research_batch",
]
