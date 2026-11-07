"""MCP adapters for local paper bots, accounts and paper-order controls.

Open defaults: bot status is as of now; forward bot jobs use the current UTC
date; replay survivorship is ``strict`` and replay export is false; new paper
accounts use the supplied name as their account id; manual order prices and
costs come only from the validated local store; pages default to 25 and cap at
100 rows. Every write defaults to ``dry_run=True`` and needs a fresh token to
commit. Missing evidence remains unavailable and blocks the order path.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import (
    PaperAccountOpenRequest,
    PaperOrderCancelRequest,
    PageRequest,
)
from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, tool


_CURSORS = CursorCodec()


def _session():
    session = current_call_context().session
    if session is None or not hasattr(session, "root"):
        raise MCPToolError("PAPER_SERVICE_UNAVAILABLE", "The headless paper service is unavailable", "Start the configured headless application session and retry.")
    return session


def _api(session) -> LocalApplicationApi:
    return LocalApplicationApi(lambda: session.snapshot, root=session.root)


def _issue_token(arguments: Mapping[str, Any]) -> str:
    context = current_call_context()
    payload = {**dict(arguments), "dry_run": False}
    payload.pop("confirm_token", None)
    return context.confirmation_store.issue(payload, store_revision=context.store_revision, client_id=context.client_id)


def _page(items: Sequence[Any], *, cursor: str | None, limit: int, filters: Mapping[str, object], key: str) -> dict[str, Any]:
    try:
        page_size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters=dict(filters)) if cursor else 0
    rows = list(items)
    page = rows[offset : offset + page_size + 1]
    has_more = len(page) > page_size
    return {
        key: page[:page_size],
        "total": len(rows),
        "next_cursor": _CURSORS.encode(offset + page_size, filters=dict(filters)) if has_more else None,
    }


def _workflow(session, workflow_type: str, payload: Mapping[str, object], label: str) -> dict[str, object]:
    submit = getattr(session, "submit_workflow", None)
    if not callable(submit):
        raise MCPToolError("JOB_SERVICE_UNAVAILABLE", "The durable workflow service is unavailable", "Use a headless session with the durable job scheduler configured.")
    fingerprint = hashlib.sha256(json.dumps([workflow_type, payload], sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()
    workflow_id = submit(
        workflow_type,
        label=label,
        input_payload=dict(payload),
        dedupe_key=f"mcp:{workflow_type}:{fingerprint}",
    )
    return {"job_id": workflow_id, "status": "queued", "execution_allowed": False}


@tool(tier="read", description="Show B0-B3 forward paper bot holdings, P&L versus the VWCE shadow and replay caveats.", read_only_hint=True, idempotent_hint=True, profiles=("core", "full"))
def paper_bots_status(as_of: str | None = None, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    session = _session()
    from etf_cockpit.application.paper_bots_view import load_paper_bots_view

    cutoff = None
    if as_of is not None:
        try:
            cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError:
            raise InvalidArgumentsError("as_of must be an ISO-8601 datetime") from None
        if cutoff.tzinfo is None:
            raise InvalidArgumentsError("as_of must include a timezone")
    view = load_paper_bots_view(session.root, as_of=cutoff)
    forward = view.get("forward") if isinstance(view, Mapping) else None
    if isinstance(forward, Mapping) and isinstance(forward.get("bots"), list):
        forward = {**dict(forward), **_page(forward["bots"], cursor=cursor, limit=limit, filters={"as_of": as_of}, key="bots")}
    return {**dict(view), "forward": forward, "execution_allowed": False}


@tool(tier="paper", description="Submit due B0-B3 paper bot decisions to the durable local worker.", profiles=("full",))
def paper_bots_run(as_of: str | None = None, dry_run: bool = True, confirm_token: str | None = None) -> dict[str, Any]:
    session = _session()
    cutoff = datetime.now(timezone.utc) if as_of is None else _parse_aware(as_of, "as_of")
    now = datetime.now(timezone.utc)
    if cutoff.astimezone(timezone.utc).date() != now.date():
        raise InvalidArgumentsError("paper_bots_run accepts only the current UTC calendar day")
    args = {"as_of": cutoff.isoformat()}
    if dry_run:
        return {"status": "confirmation_required", "as_of": args["as_of"], "confirm_token": _issue_token(args), "execution_allowed": False}
    with session.activity_publication():
        return _workflow(session, "paper_bots_run", args, "Paper bot decisions")


@tool(tier="paper", description="Submit a historical paper bot replay from stored score and price history.", profiles=("full",))
def paper_replay_run(
    as_of: str,
    survivorship: str = "strict",
    export: bool = False,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    session = _session()
    cutoff = _parse_aware(as_of, "as_of")
    if cutoff > datetime.now(timezone.utc):
        raise InvalidArgumentsError("as_of must not be in the future")
    if survivorship not in {"strict", "unverified"}:
        raise InvalidArgumentsError("survivorship must be 'strict' or 'unverified'")
    args = {"as_of": cutoff.isoformat(), "survivorship": survivorship, "export": bool(export)}
    if dry_run:
        return {"status": "confirmation_required", "as_of": args["as_of"], "survivorship": survivorship, "export": export, "confirm_token": _issue_token(args), "execution_allowed": False}
    with session.activity_publication():
        return _workflow(session, "paper_replay_run", args, "Paper historical replay")


@tool(tier="paper", description="Open a separate local AI paper account with owner-supplied name, currency and starting cash.", profiles=("full",))
def paper_account_open(
    name: str,
    base_currency: str,
    starting_cash: float,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    session = _session()
    if not name.strip():
        raise InvalidArgumentsError("name must not be empty")
    args = {"name": name.strip(), "base_currency": base_currency.strip().upper(), "starting_cash": starting_cash}
    if dry_run:
        return {"status": "confirmation_required", "account_id": args["name"], "base_currency": args["base_currency"], "starting_cash": starting_cash, "confirm_token": _issue_token(args), "execution_allowed": False}
    with session.activity_publication():
        account = _api(session).open_paper_account(
            PaperAccountOpenRequest(account_id=args["name"], initial_cash=starting_cash, base_currency=args["base_currency"])
        )
    return {"account_id": account.account_id, "status": account.status, "base_currency": account.base_currency, "cash": account.cash, "execution_allowed": False}


@tool(tier="read", description="Show one local paper account's positions, cash, orders, timeline, P&L and transaction-cost attribution.", read_only_hint=True, idempotent_hint=True, profiles=("core", "full"))
def paper_portfolio(account_id: str, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    session = _session()
    from etf_cockpit.application.paper_views import load_paper_tca_view, load_paper_timeline

    try:
        api = _api(session)
        account_page = api.get_paper(PageRequest(offset=0, limit=1), account_id=account_id)
        if not account_page.items:
            return {
                "status": "unavailable",
                "account_id": account_id,
                "unavailable_reason": "paper_account_unavailable",
                "equity": None,
                "cash": None,
                "pnl": None,
                "positions": [],
                "orders": [],
                "timeline": [],
                "execution_allowed": False,
            }
        account = account_page.items[0].model_dump(mode="python")
        if account.get("status") != "ready":
            return {
                "status": account.get("status", "unavailable"),
                "account_id": account_id,
                "unavailable_reason": account.get("message") or "paper_account_unavailable",
                "equity": account.get("equity"),
                "cash": account.get("cash"),
                "pnl": account.get("pnl"),
                "positions": [],
                "orders": [],
                "timeline": [],
                "execution_allowed": False,
            }
        orders: list[dict[str, Any]] = []
        order_offset = 0
        while True:
            order_page = api.get_paper_orders(PageRequest(offset=order_offset, limit=500), account_id=account_id)
            orders.extend(item.model_dump(mode="python") for item in order_page.items)
            if order_page.next_offset is None:
                break
            order_offset = order_page.next_offset
        positions = list(account.get("positions", ()))
        instruments = sorted({str(row.get("instrument_id", "")).upper() for row in orders if row.get("instrument_id")})
        instruments.extend(
            str(item.get("instrument_id", "")).upper()
            for item in positions
            if item.get("instrument_id") and item.get("instrument_id") not in instruments
        )
        timeline = [
            row
            for instrument in instruments
            for row in load_paper_timeline(session.root, instrument, account_id=account_id).get("rows", [])
        ]
        tca = load_paper_tca_view(session.root, account_id=account_id)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"status": "unavailable", "account_id": account_id, "unavailable_reason": f"paper_portfolio_unavailable:{type(exc).__name__}", "execution_allowed": False}
    try:
        page_size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters={"account_id": account_id}) if cursor else 0
    tca_rows = list(tca.get("rows", ())) if isinstance(tca, Mapping) else []
    pos_page = positions[offset : offset + page_size + 1]
    order_page = orders[offset : offset + page_size + 1]
    timeline_page = timeline[offset : offset + page_size + 1]
    tca_page = tca_rows[offset : offset + page_size + 1]
    has_more = any(len(page) > page_size for page in (pos_page, order_page, timeline_page, tca_page))
    next_cursor = _CURSORS.encode(offset + page_size, filters={"account_id": account_id}) if has_more else None
    if isinstance(tca, Mapping):
        tca = {**dict(tca), "rows": tca_page[:page_size], "next_cursor": next_cursor}
    return {
        "status": account["status"],
        "account_id": account_id,
        "as_of": account.get("as_of"),
        "base_currency": account.get("base_currency"),
        "equity": account.get("equity"),
        "cash": account.get("cash"),
        "pnl": account.get("pnl"),
        "positions": pos_page[:page_size],
        "orders": order_page[:page_size],
        "timeline": timeline_page[:page_size],
        "tca": tca,
        "next_cursor": next_cursor,
        "execution_allowed": False,
    }


@tool(tier="read", description="Show paper kill-switch, incident freeze, canary and configured pre-trade limits.", read_only_hint=True, idempotent_hint=True, profiles=("full",))
def paper_controls_status(account_id: str | None = None) -> dict[str, Any]:
    session = _session()
    account = account_id or "local-paper"
    from etf_cockpit.application.paper_manual_order import load_paper_controls_status

    return load_paper_controls_status(session.root, account)


@tool(tier="paper", description="Preview and record a gate-checked manual paper proposal using stored price and cost evidence.", idempotent_hint=True, profiles=("core", "full"), preview=lambda **kwargs: paper_order_preview(**kwargs))
def paper_order_preview(
    account_id: str,
    instrument_id: str,
    side: str,
    quantity: float | None = None,
    amount_eur: float | None = None,
    target_weight: float | None = None,
    rationale: str = "",
    evidence_refs: list[str] | None = None,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    session = _session()
    if side not in {"buy", "sell"}:
        raise InvalidArgumentsError("side must be 'buy' or 'sell'")
    if not rationale.strip():
        raise InvalidArgumentsError("rationale must not be empty")
    args = {
        "account_id": account_id, "instrument_id": instrument_id, "side": side,
        "quantity": quantity, "amount_eur": amount_eur, "target_weight": target_weight,
        "rationale": rationale, "evidence_refs": evidence_refs or [],
    }
    from etf_cockpit.application.paper_manual_order import preview_manual_paper_order

    persisted: dict[str, Any] | None = None
    if dry_run:
        preview = preview_manual_paper_order(
            root=session.root, snapshot=session.snapshot, account_id=account_id,
            instrument_id=instrument_id, side=side, quantity=quantity,
            amount_eur=amount_eur, target_weight=target_weight, rationale=rationale,
            evidence_refs=tuple(evidence_refs or ()), persist=False,
        )
    else:
        from etf_cockpit.application.paper_manual_order import persist_manual_paper_proposal

        with session.activity_publication():
            preview = preview_manual_paper_order(
                root=session.root, snapshot=session.snapshot, account_id=account_id,
                instrument_id=instrument_id, side=side, quantity=quantity,
                amount_eur=amount_eur, target_weight=target_weight, rationale=rationale,
                evidence_refs=tuple(evidence_refs or ()), persist=True,
            )
            if preview.get("status") == "proposal_ready":
                persisted = persist_manual_paper_proposal(preview, root=session.root)
    if preview.get("status") != "proposal_ready":
        return preview
    if dry_run:
        preview["confirm_token"] = _issue_token(args)
        preview["confirmation_arguments"] = {**args, "dry_run": False}
        preview["status"] = "confirmation_required"
        return preview
    assert persisted is not None
    persisted["confirm_token"] = _issue_token({
        "proposal_id": str(preview["proposal_id"]),
        "instrument_id": instrument_id,
        "quantity": preview["quantity"],
    })
    return persisted


@tool(tier="paper", description="Accept and fill one approved manual paper proposal with its server-derived price and costs.", idempotent_hint=True, profiles=("core", "full"), preview=lambda **kwargs: paper_order_place(**kwargs))
def paper_order_place(
    proposal_id: str,
    instrument_id: str,
    quantity: float,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    session = _session()
    args = {"proposal_id": proposal_id, "instrument_id": instrument_id, "quantity": quantity}
    if dry_run:
        return {"status": "confirmation_required", **args, "confirm_token": _issue_token(args), "execution_allowed": False}
    from etf_cockpit.application.paper_manual_order import accept_manual_paper_proposal

    try:
        with session.activity_publication():
            result = accept_manual_paper_proposal(
                root=session.root, proposal_id=proposal_id,
                instrument_id=instrument_id, quantity=quantity,
            )
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise MCPToolError("PAPER_ORDER_REFUSED", "The paper order could not be accepted", f"Review current account and gate evidence ({type(exc).__name__}).") from None
    return {**result, "execution_allowed": False}


@tool(tier="paper", description="Cancel one open paper order and record the reason.", idempotent_hint=True, profiles=("full",))
def paper_order_cancel(order_id: str, reason: str, dry_run: bool = True, confirm_token: str | None = None) -> dict[str, Any]:
    session = _session()
    if not reason.strip():
        raise InvalidArgumentsError("reason must not be empty")
    args = {"order_id": order_id, "reason": reason.strip()}
    if dry_run:
        return {"status": "confirmation_required", **args, "confirm_token": _issue_token(args), "execution_allowed": False}
    from etf_cockpit.application.paper_manual_order import find_paper_order_account

    account_id = find_paper_order_account(session.root, order_id)
    if account_id is None:
        raise MCPToolError("PAPER_ORDER_NOT_FOUND", "No paper order matches order_id", "Check paper_portfolio and retry with an open order_id.")
    with session.activity_publication():
        result = _api(session).cancel_paper_order(PaperOrderCancelRequest(account_id=account_id, order_id=order_id, reason=reason.strip()))
    return {"account_id": account_id, "order": result, "cancelled": True, "execution_allowed": False}


@tool(tier="paper", description="Activate the local paper kill switch and cancel open paper orders when configured.", idempotent_hint=True, profiles=("full",))
def paper_kill_switch_activate(reason: str, dry_run: bool = True, confirm_token: str | None = None) -> dict[str, Any]:
    session = _session()
    if not reason.strip():
        raise InvalidArgumentsError("reason must not be empty")
    args = {"reason": reason.strip()}
    if dry_run:
        return {"status": "confirmation_required", **args, "confirm_token": _issue_token(args), "execution_allowed": False}
    from etf_cockpit.application.paper_manual_order import activate_paper_kill_switch

    with session.activity_publication():
        activated = activate_paper_kill_switch(session.root, reason.strip())
    return {"active": True, "accounts": activated, "execution_allowed": False}


def _parse_aware(value: str, name: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise InvalidArgumentsError(f"{name} must be an ISO-8601 datetime") from None
    if result.tzinfo is None:
        raise InvalidArgumentsError(f"{name} must include a timezone")
    return result.astimezone(timezone.utc)


__all__ = [
    "paper_account_open", "paper_bots_run", "paper_bots_status", "paper_controls_status",
    "paper_kill_switch_activate", "paper_order_cancel", "paper_order_place", "paper_order_preview",
    "paper_portfolio", "paper_replay_run",
]
