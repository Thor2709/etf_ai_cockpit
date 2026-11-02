"""Quarantined, append-only evidence submitted from external AI research.

Open defaults: evidence is stored as JSONL below the configured data root;
missing files represent an empty store, and no evidence is score-eligible.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlsplit

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.paths import DATA_DIR
from etf_cockpit.core.session_log import SECRET_KEY_RE


_KINDS = frozenset({"news", "filing", "analyst", "sentiment", "web", "other"})
_FIELDS = frozenset({
    "subject", "kind", "claim", "stance", "confidence", "source_url",
    "source_title", "published_at", "retrieved_at", "excerpt",
})


def _path(root: Path | None) -> Path:
    return (Path(root) if root is not None else DATA_DIR) / "ai_research_evidence.jsonl"


def _revision(path: Path) -> str:
    payload = path.read_bytes() if path.is_file() else b""
    return hashlib.sha256(payload).hexdigest()


def _validate_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_source_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("source_url must be an HTTP or HTTPS URL")
    source_url = value.strip()
    parsed = urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source_url must not contain credentials")
    # Decode parameter names before checking, including signed provider URLs.
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if SECRET_KEY_RE.search(key) or key.casefold() in {"key", "auth", "sig", "signature"}:
            raise ValueError("source_url must not contain credential query parameters")
    return source_url


def validate_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Validate caller-supplied evidence without treating its text as trusted."""

    if not isinstance(item, Mapping) or set(item) - _FIELDS:
        raise ValueError("research evidence item has unknown fields")
    for name, maximum in (("subject", 256), ("claim", 4000), ("source_title", 500)):
        value = item.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"{name} must be non-empty text no longer than {maximum} characters")
    kind = str(item.get("kind", "")).strip().casefold()
    if kind not in _KINDS:
        raise ValueError("kind must be news, filing, analyst, sentiment, web, or other")
    source_url = _validate_source_url(item.get("source_url"))
    try:
        stance = float(item.get("stance"))
        confidence = float(item.get("confidence"))
    except (TypeError, ValueError):
        raise ValueError("stance and confidence must be finite numbers") from None
    if not math.isfinite(stance) or not -1.0 <= stance <= 1.0:
        raise ValueError("stance must be between -1 and 1")
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    published_at = _validate_timestamp(item.get("published_at"), "published_at")
    retrieved_at = _validate_timestamp(item.get("retrieved_at"), "retrieved_at")
    from datetime import datetime, timezone

    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    if published > retrieved:
        raise ValueError("published_at cannot be later than retrieved_at")
    if retrieved > datetime.now(timezone.utc):
        raise ValueError("retrieved_at cannot be in the future")
    excerpt = item.get("excerpt", "")
    if not isinstance(excerpt, str) or len(excerpt) > 500:
        raise ValueError("excerpt must be text no longer than 500 characters")
    content = {
        "subject": item["subject"].strip(),
        "kind": kind,
        "claim": item["claim"].strip(),
        "stance": stance,
        "confidence": confidence,
        "source_url": source_url,
        "source_title": item["source_title"].strip(),
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "known_at": retrieved_at,
        "excerpt": excerpt,
        "label": "ai_external_unverified",
        "executable_authority": False,
        "scoring_eligible": False,
    }
    identity_payload = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    content["evidence_id"] = "ai-evidence-" + hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()[:32]
    return content


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("AI research evidence store is unreadable") from exc
    if any(not isinstance(row, dict) or row.get("label") != "ai_external_unverified" or row.get("executable_authority") is not False or row.get("scoring_eligible") is not False for row in records):
        raise ValueError("AI research evidence store contains an invalid record")
    for row in records:
        _validate_source_url(row.get("source_url"))
    return records


def research_evidence_revision(root: Path | None = None) -> str:
    """Return a content hash for the current evidence generation."""

    return _revision(_path(root))


def load_ai_research_evidence(root: Path | None = None) -> list[dict[str, Any]]:
    """Read the canonical local store, failing closed on malformed bytes."""

    return _read(_path(root))


def append_ai_research_evidence(
    items: Iterable[Mapping[str, Any]],
    *,
    expected_revision: str,
    root: Path | None = None,
) -> tuple[str, ...]:
    """Atomically append deduplicated rows if the previewed generation is current."""

    path = _path(root)
    guard_path = path.with_name(path.name + ".guard")
    validated = tuple(validate_item(item) for item in items)
    if not validated:
        raise ValueError("at least one research evidence item is required")
    with persistent_file_guard(guard_path):
        current_revision = _revision(path)
        if current_revision != expected_revision:
            raise RuntimeError("research evidence changed after preview; request a new preview")
        records = _read(path)
        known = {str(row["evidence_id"]) for row in records}
        appended: list[str] = []
        for row in validated:
            evidence_id = str(row["evidence_id"])
            if evidence_id not in known:
                records.append(row)
                known.add(evidence_id)
                appended.append(evidence_id)
        if appended:
            payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in records).encode("utf-8")
            atomic_write_bytes(path, payload, lambda candidate: _validate_store_file(candidate))
        return tuple(appended)


def _validate_store_file(path: Path) -> None:
    _read(path)


__all__ = ["append_ai_research_evidence", "load_ai_research_evidence", "research_evidence_revision", "validate_item"]
