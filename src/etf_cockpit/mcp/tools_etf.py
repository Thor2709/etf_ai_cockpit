"""MCP ETF holdings, look-through and disclosure tools.

Open defaults: holdings and document pages contain 25 rows; holdings gaps are
omitted unless requested. Look-through keeps the canonical 90-day freshness and
0.80 coverage gates. Disclosures are read only; imports use two-phase confirmation.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from etf_cockpit.application import mcp_etf_views
from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, tool
from etf_cockpit.mcp.serialise import normalise


_CURSORS = CursorCodec()


def _snapshot() -> object:
    session = current_call_context().session
    candidate = getattr(session, "snapshot", None)
    if candidate is None:
        candidate = getattr(getattr(session, "headless_session", None), "snapshot", None)
    if candidate is None:
        raise MCPToolError("SNAPSHOT_UNAVAILABLE", "The local headless snapshot is unavailable", "Start the MCP server with its configured headless session and rebuild the local snapshot.")
    return candidate


def _page(rows: list[Any], cursor: str | None, filters: dict[str, object], limit: int) -> dict[str, object]:
    try:
        size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters=filters) if cursor else 0
    selected = rows[offset : offset + size + 1]
    return {"rows": normalise(selected[:size]), "next_cursor": _CURSORS.encode(offset + size, filters=filters) if len(selected) > size else None}


@tool(tier="read", description="Read point-in-time ETF holdings, splits, coverage and optional missing business days.", read_only_hint=True, idempotent_hint=True, profiles=("core", "full"))
def etf_holdings(instrument_id: str, as_of: date, top_n: int = 25, include_gaps: bool = False, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, object]:
    if top_n < 1 or top_n > 100:
        raise InvalidArgumentsError("top_n must be between 1 and 100")
    try:
        result = mcp_etf_views.etf_holdings_view(instrument_id, as_of, top_n=top_n, include_gaps=include_gaps)
    except (OSError, ValueError, TypeError) as exc:
        raise MCPToolError("HOLDINGS_UNAVAILABLE", str(exc), "Check that a dated holdings snapshot and validated listing evidence are available.") from None
    page = _page(list(result.get("holdings") or ()), cursor, {"instrument_id": instrument_id, "as_of": as_of.isoformat(), "top_n": top_n}, limit)
    return {**result, "holdings": page["rows"], "next_cursor": page["next_cursor"]}


@tool(tier="read", description="Read fail-closed point-in-time exposure for one ETF or the portfolio.", read_only_hint=True, idempotent_hint=True, profiles=("core", "full"))
def etf_look_through(instrument_id: str | None = None, portfolio: bool = False, decision_time: datetime | None = None) -> dict[str, object]:
    if decision_time is None:
        raise InvalidArgumentsError("decision_time is required")
    if portfolio:
        return normalise(mcp_etf_views.portfolio_look_through_view(_snapshot(), decision_time))
    if not instrument_id or not instrument_id.strip():
        raise InvalidArgumentsError("instrument_id is required unless portfolio=true")
    return normalise(mcp_etf_views.etf_look_through_view(instrument_id, decision_time))


@tool(tier="read", description="Compare direct ETF holdings overlap and optionally include the current portfolio.", read_only_hint=True, idempotent_hint=True)
def etf_overlap(instrument_ids: list[str], weights: dict[str, float] | None = None, include_portfolio: bool = False) -> dict[str, object]:
    if not instrument_ids or len(instrument_ids) > 50:
        raise InvalidArgumentsError("instrument_ids must contain between 1 and 50 ids")
    if len(set(instrument_ids)) != len(instrument_ids):
        raise InvalidArgumentsError("instrument_ids must be unique")
    if weights is not None and set(weights) - set(instrument_ids):
        raise InvalidArgumentsError("weights may only name requested instruments")
    try:
        result = mcp_etf_views.etf_overlap_view(_snapshot(), instrument_ids, weights=weights, include_portfolio=include_portfolio)
    except MCPToolError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise MCPToolError("OVERLAP_UNAVAILABLE", str(exc), "Check local canonical holdings and snapshot availability before retrying.") from None
    return normalise(result)


@tool(tier="read", description="Read canonical ETF cost, tracking and tax assumptions for a bounded horizon.", read_only_hint=True, idempotent_hint=True)
def etf_economics(instrument_id: str, horizon_days: int = 252) -> dict[str, object]:
    if horizon_days < 1 or horizon_days > 3650:
        raise InvalidArgumentsError("horizon_days must be between 1 and 3650")
    return normalise(mcp_etf_views.etf_economics_view(_snapshot(), instrument_id, horizon_days=horizon_days))


@tool(tier="read", description="Read ETF KID, SFDR, methodology, report records and conflicts.", read_only_hint=True, idempotent_hint=True)
def etf_disclosures(instrument_id: str, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, object]:
    result = mcp_etf_views.etf_disclosures_view(instrument_id)
    docs = list(result.get("documents") or ())
    reports = list(result.get("parsed_fields") or ())
    page = _page(docs + reports, cursor, {"instrument_id": instrument_id}, limit)
    return {**result, "documents_and_fields": page["rows"], "documents": None, "parsed_fields": None, "next_cursor": page["next_cursor"]}


def _preview_disclosure(kind: str, path: str, instrument_id: str, as_of: date, sha256: str | None = None) -> dict[str, object]:
    try:
        return normalise(mcp_etf_views.preview_disclosure_import(kind, Path(path), instrument_id, as_of, sha256))
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from None


@tool(tier="edit", description="Import a local ETF issuer document, holdings snapshot or report after a side-effect-free validation preview.", read_only_hint=False, destructive_hint=True, preview=_preview_disclosure)
def etf_disclosure_import(kind: str, path: str, instrument_id: str, as_of: date, sha256: str | None = None, confirm_token: str | None = None) -> dict[str, object]:
    try:
        return normalise(mcp_etf_views.commit_disclosure_import(kind, Path(path), instrument_id, as_of, sha256))
    except (OSError, TypeError, ValueError) as exc:
        raise MCPToolError("DISCLOSURE_IMPORT_REFUSED", str(exc), "Refresh the preview and verify the local source file and checksum.") from None


__all__ = ["etf_disclosure_import", "etf_disclosures", "etf_economics", "etf_holdings", "etf_look_through", "etf_overlap"]
