"""MCP instrument identity and universe tools.

Open defaults: universe pages contain 25 records. Search is local; only
instrument_lookup may use the existing configured identity providers.
Hard deletes are not exposed.
"""

from __future__ import annotations

from typing import Any

from etf_cockpit.application import mcp_universe_ops
from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import issue_confirmation_token, tool
from etf_cockpit.mcp.serialise import normalise


_CURSORS = CursorCodec()


def _page(rows: list[Any], cursor: str | None, filters: dict[str, object], limit: int) -> dict[str, object]:
    try:
        size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters=filters) if cursor else 0
    selected = rows[offset : offset + size + 1]
    return {"records": normalise(selected[:size]), "next_cursor": _CURSORS.encode(offset + size, filters=filters) if len(selected) > size else None}


@tool(tier="read", description="Search the configured local universe without changing it.", read_only_hint=True, idempotent_hint=True)
def universe_search(query: str | None = None, asset_type: str | None = None, tier: str | None = None, enabled: bool | None = None, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, object]:
    snapshot = mcp_universe_ops.universe_snapshot()
    records = list(snapshot["records"])
    needle = (query or "").strip().casefold()
    records = [
        item for item in records
        if (not needle or needle in " ".join((item.instrument_id, item.name, item.ticker, item.isin)).casefold())
        and (asset_type is None or item.asset_type.casefold() == asset_type.casefold())
        and (tier is None or item.tier.casefold() == tier.casefold())
        and (enabled is None or item.enabled is enabled)
    ]
    filters = {"query": query, "asset_type": asset_type, "tier": tier, "enabled": enabled}
    page = _page(records, cursor, filters, limit)
    return {**page, "revision": snapshot["revision"], "unavailable_reason": "Universe integrity is unavailable." if snapshot["integrity_errors"] else None}


@tool(tier="read", description="Resolve an ISIN, ticker or name using the existing instrument lookup providers.", read_only_hint=True, idempotent_hint=True, open_world_hint=True)
def instrument_lookup(identifier: str) -> dict[str, object]:
    if not identifier.strip():
        raise InvalidArgumentsError("identifier must not be empty")
    try:
        return normalise(mcp_universe_ops.lookup_instrument_view(identifier))
    except (KeyError, ValueError) as exc:
        raise MCPToolError("IDENTITY_LOOKUP_UNAVAILABLE", str(exc), "Check the identifier and configured local provider status before retrying.") from None


@tool(tier="read", description="Read identity, classification, membership and market-clock projections.", read_only_hint=True, idempotent_hint=True)
def identity_get(instrument_id: str) -> dict[str, object]:
    if not instrument_id.strip():
        raise InvalidArgumentsError("instrument_id must not be empty")
    return normalise(mcp_universe_ops.identity_view(instrument_id))


def _preview_change(action: str, instrument_id: str | None = None, fields: dict[str, object] | None = None, expected_revision: str | None = None) -> dict[str, object]:
    try:
        return normalise(mcp_universe_ops.preview_universe_change(action, instrument_id, fields, expected_revision=expected_revision))
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from None


@tool(tier="edit", description="Validate and preview an add, edit, disable or enable action; no universe data is written.", read_only_hint=True, idempotent_hint=True)
def universe_change_preview(action: str, instrument_id: str | None = None, fields: dict[str, object] | None = None) -> dict[str, object]:
    preview = _preview_change(action, instrument_id, fields)
    token_payload = {"action": action, "instrument_id": instrument_id, "fields": fields, "expected_revision": preview["expected_revision"]}
    return {**preview, "confirm_token": issue_confirmation_token(token_payload), "confirmation_fields": token_payload}


@tool(tier="edit", description="Commit a validated universe change after the caller echoes the exact preview fields and revision.", read_only_hint=False, destructive_hint=True, preview=_preview_change)
def universe_change_commit(action: str, instrument_id: str | None = None, fields: dict[str, object] | None = None, expected_revision: str | None = None, confirm_token: str | None = None) -> dict[str, object]:
    try:
        return normalise(mcp_universe_ops.commit_universe_change(action, instrument_id, fields, expected_revision=expected_revision))
    except (KeyError, TypeError, ValueError) as exc:
        raise MCPToolError("UNIVERSE_CHANGE_REFUSED", str(exc), "Refresh universe_search and request a new change preview.") from None


def _preview_import(source: str, expected_revision: str | None = None) -> dict[str, object]:
    try:
        preview = mcp_universe_ops.preview_universe_import(source)
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from None
    if expected_revision is not None and expected_revision != preview["expected_revision"]:
        raise InvalidArgumentsError("universe revision changed; request a fresh import preview")
    return normalise(preview)


@tool(tier="edit", description="Validate a local universe import or the savings-bank gap list.", read_only_hint=True, idempotent_hint=True)
def universe_import_preview(source: str) -> dict[str, object]:
    preview = _preview_import(source)
    token_payload = {"source": source, "expected_revision": preview["expected_revision"]}
    return {**preview, "confirm_token": issue_confirmation_token(token_payload), "confirmation_fields": token_payload}


@tool(tier="edit", description="Commit a validated universe import after the caller echoes its source and expected revision.", read_only_hint=False, destructive_hint=True, preview=_preview_import)
def universe_import_commit(source: str, expected_revision: str | None = None, confirm_token: str | None = None) -> dict[str, object]:
    try:
        result = mcp_universe_ops.commit_universe_import(source, expected_revision=expected_revision)
        return normalise(result)
    except (OSError, TypeError, ValueError) as exc:
        raise MCPToolError("UNIVERSE_IMPORT_REFUSED", str(exc), "Refresh the import preview and retry with the current universe revision.") from None


__all__ = ["identity_get", "instrument_lookup", "universe_change_commit", "universe_change_preview", "universe_import_commit", "universe_import_preview", "universe_search"]
