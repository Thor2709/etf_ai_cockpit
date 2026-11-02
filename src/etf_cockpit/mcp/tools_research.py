"""MCP research tools for quarantined, externally supplied evidence.

Open defaults: research pages contain 25 findings; one preview token confirms
one complete batch, tokens expire after 15 minutes, and thesis entries stay
pending human review with no execution or scoring authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from etf_cockpit.core.paths import ROOT
from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE
from etf_cockpit.mcp.registry import current_call_context, tool


_CURSORS = CursorCodec()


def _root() -> Path:
    context = current_call_context()
    session_root = getattr(context.session, "root", None)
    root = Path(session_root or ROOT).resolve()
    if root != ROOT.resolve():
        raise MCPToolError("DATA_ROOT_MISMATCH", "Research storage is outside the configured data root", "Restart the MCP server with the configured owner data root.")
    return root


def _confirmation_token(payload: Mapping[str, object]) -> str:
    context = current_call_context()
    return context.confirmation_store.issue(
        dict(payload), store_revision=context.store_revision, client_id=context.client_id
    )


@tool(tier="read", description="Read local research findings, sentiment, and optional news or thesis context.", read_only_hint=True, idempotent_hint=True)
def research_findings(
    subject: str | None = None,
    kind: str | None = None,
    since: str | None = None,
    include_news: bool = False,
    include_theses: bool = False,
    cursor: str | None = None,
    prepare_items: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from etf_cockpit.application.research_evidence import (
        load_research_findings,
        research_revision,
        validate_research_batch,
    )

    root = _root()
    if prepare_items is not None:
        try:
            rows = validate_research_batch(prepare_items)
        except (TypeError, ValueError) as exc:
            raise InvalidArgumentsError(str(exc)) from None
        expected_revision = research_revision(root)
        payload = {"items": [dict(item) for item in prepare_items], "expected_revision": expected_revision}
        return {
            "preview": {"item_count": len(rows), "expected_revision": expected_revision,
                        "label": "ai_external_unverified", "known_at_field": "retrieved_at",
                        "writes_scores_or_authority": False},
            "confirm_token": _confirmation_token(payload),
            "execution_allowed": False,
        }
    if kind is not None and kind not in {"news", "filing", "analyst", "sentiment", "web", "other"}:
        raise InvalidArgumentsError("kind must be news, filing, analyst, sentiment, web, or other")
    if subject is not None and (not subject.strip() or len(subject) > 256):
        raise InvalidArgumentsError("subject must be non-empty text no longer than 256 characters")
    filters = {
        "subject": subject, "kind": kind, "since": since,
        "include_news": include_news, "include_theses": include_theses,
    }
    offset = _CURSORS.decode(cursor, filters=filters) if cursor else 0
    try:
        result = load_research_findings(
            root=root, subject=subject, kind=kind, since=since,
            include_news=include_news, include_theses=include_theses,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise MCPToolError("RESEARCH_UNAVAILABLE", "Local research evidence could not be read", f"Check the configured data root ({type(exc).__name__}).") from None
    findings = result.pop("findings", [])
    page = findings[offset : offset + DEFAULT_PAGE_SIZE + 1]
    has_more = len(page) > DEFAULT_PAGE_SIZE
    result["findings"] = page[:DEFAULT_PAGE_SIZE]
    result["next_cursor"] = _CURSORS.encode(offset + DEFAULT_PAGE_SIZE, filters=filters) if has_more else None
    return result


@tool(tier="research", description="Store one batch of labelled AI research findings after a matching preview.", idempotent_hint=True)
def research_record_findings(
    items: Sequence[Mapping[str, Any]],
    expected_revision: str,
    confirm_token: str,
) -> dict[str, Any]:
    from etf_cockpit.application.research_evidence import record_research_findings

    try:
        identifiers = record_research_findings(
            items, expected_revision=expected_revision, root=_root()
        )
    except RuntimeError as exc:
        raise MCPToolError("PREVIEW_STALE", "Research evidence changed after preview", "Request a fresh preview for the whole batch.") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from None
    return {
        "ids": list(identifiers), "deduplicated": len(identifiers) != len(items),
        "label": "ai_external_unverified", "known_at_field": "retrieved_at",
        "execution_allowed": False, "scoring_eligible": False,
    }


@tool(tier="read", description="Preview a thesis diary entry and issue a single-use confirmation token.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def research_record_thesis_preview(
    instrument_ids: Sequence[str],
    thesis: str,
    evidence_refs: Sequence[str],
    invalidation_rules: Sequence[str],
    review_date: str,
) -> dict[str, Any]:
    from etf_cockpit.application.research_evidence import thesis_revision

    root = _root()
    expected_revision = thesis_revision(root)
    payload = {
        "instrument_ids": list(instrument_ids), "thesis": thesis,
        "evidence_refs": list(evidence_refs), "invalidation_rules": list(invalidation_rules),
        "review_date": review_date, "expected_revision": expected_revision,
    }
    return {
        "preview": {"instrument_count": len(instrument_ids), "expected_revision": expected_revision,
                    "human_review_status": "pending", "execution_allowed": False},
        "confirm_token": _confirmation_token(payload), "execution_allowed": False,
    }


@tool(tier="research", description="Record an AI thesis with evidence references and invalidation rules.", idempotent_hint=True, profiles=("full",))
def research_record_thesis(
    instrument_ids: Sequence[str],
    thesis: str,
    evidence_refs: Sequence[str],
    invalidation_rules: Sequence[str],
    review_date: str,
    expected_revision: str,
    confirm_token: str,
) -> dict[str, Any]:
    from etf_cockpit.application.research_evidence import record_research_thesis

    try:
        identifiers = record_research_thesis(
            instrument_ids=instrument_ids, thesis=thesis, evidence_refs=evidence_refs,
            invalidation_rules=invalidation_rules, review_date=review_date,
            expected_revision=expected_revision, root=_root(),
        )
    except RuntimeError as exc:
        raise MCPToolError("PREVIEW_STALE", "The thesis diary changed after preview", "Request a fresh thesis preview and confirm the full entry again.") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from None
    return {
        "thesis_id": identifiers[0] if len(identifiers) == 1 else None,
        "thesis_ids": list(identifiers), "human_review_status": "pending",
        "final_advisory_label": "manual_review", "execution_allowed": False,
        "executable_authority": False,
    }


__all__ = [
    "research_findings", "research_record_findings", "research_record_thesis",
    "research_record_thesis_preview",
]
