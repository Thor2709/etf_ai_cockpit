"""Focused MCP portfolio and paper-lane contract checks."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.application import paper_manual_order
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.confirm import ConfirmationStore
from etf_cockpit.mcp.errors import ConfirmationError
from etf_cockpit.mcp.registry import CallContext, invoke_tool, use_call_context


class _NoSideEffects:
    def acquire(self, _name: str) -> None:
        return None


class _Session:
    def __init__(self, root: Path, snapshot: object | None = None) -> None:
        self.root = root
        self.snapshot = snapshot or SimpleNamespace()
        self.submissions: list[tuple[str, dict[str, object]]] = []

    def activity_publication(self):
        return nullcontext()

    def submit_workflow(self, workflow_type: str, **kwargs: object) -> str:
        self.submissions.append((workflow_type, dict(kwargs)))
        return "wf_fixture"


def _context(tmp_path: Path, session: _Session | None = None) -> CallContext:
    return CallContext(
        enabled_tiers=frozenset({"read", "edit", "paper"}),
        profile="full",
        client_id="test-client",
        confirmation_store=ConfirmationStore(b"c" * 32),
        audit=AuditRecorder(sink=lambda _record: None),
        session=session or _Session(tmp_path),
        rate_limiter=_NoSideEffects(),
    )


def test_every_write_tool_refuses_missing_confirm_token_before_side_effects(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    calls = {
        "portfolio_import_preview": {"path": str(tmp_path / "source.csv"), "dry_run": False},
        "portfolio_import_commit": {"preview_id": "preview_fixture", "dry_run": False},
        "portfolio_import_rollback": {"batch_id": "batch_fixture", "reason": "test", "dry_run": False},
        "journal_record": {"thesis": "test", "decision": "test", "evidence_refs": [], "dry_run": False},
        "paper_bots_run": {"as_of": now, "dry_run": False},
        "paper_replay_run": {"as_of": now, "dry_run": False},
        "paper_account_open": {"name": "test-account", "base_currency": "EUR", "starting_cash": 1000.0, "dry_run": False},
        "paper_order_preview": {"account_id": "test-account", "instrument_id": "ETF1", "side": "buy", "quantity": 1.0, "rationale": "test", "dry_run": False},
        "paper_order_place": {"proposal_id": "proposal_fixture", "instrument_id": "ETF1", "quantity": 1.0, "dry_run": False},
        "paper_order_cancel": {"order_id": "order_fixture", "reason": "test", "dry_run": False},
        "paper_kill_switch_activate": {"reason": "test", "dry_run": False},
    }
    context = _context(tmp_path)

    for name, arguments in calls.items():
        with pytest.raises(ConfirmationError):
            invoke_tool(name, arguments, context=context)

    assert not (tmp_path / "data").exists()


def test_missing_manual_price_remains_unavailable_not_zero(tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_trading import PaperLedger

    PaperLedger(tmp_path, account_id="missing-account").open_account(initial_cash=1000.0)
    result = paper_manual_order.preview_manual_paper_order(
        root=tmp_path,
        snapshot=SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(by_id=lambda: {}))),
        account_id="missing-account",
        instrument_id="ETF1",
        side="buy",
        quantity=1.0,
        rationale="missing-data fixture",
    )

    assert result["status"] == "unavailable"
    assert result["price"] is None
    assert result["fee"] is None
    assert result["fx_rate"] is None
    assert result["unavailable_reason"]


def test_page_output_is_compact_and_has_cursor() -> None:
    from etf_cockpit.mcp.tools_paper import _page

    result = _page(
        [{"bot_id": str(index)} for index in range(40)],
        cursor=None,
        limit=5,
        filters={"as_of": None},
        key="bots",
    )

    assert len(result["bots"]) == 5
    assert result["total"] == 40
    assert isinstance(result["next_cursor"], str)


def test_paper_order_tool_calls_canonical_manual_order_service(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.mcp import tools_paper

    calls: list[dict[str, object]] = []

    def preview(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"status": "unavailable", "price": None, "unavailable_reason": "price_unavailable", "execution_allowed": False}

    monkeypatch.setattr(paper_manual_order, "preview_manual_paper_order", preview)
    session = _Session(tmp_path)
    with use_call_context(_context(tmp_path, session)):
        result = tools_paper.paper_order_preview(
            account_id="test-account", instrument_id="ETF1", side="buy", quantity=1.0,
            rationale="fixture", dry_run=True,
        )

    assert result["status"] == "unavailable"
    assert len(calls) == 1
    assert calls[0]["root"] == tmp_path
    assert calls[0]["persist"] is False


def test_paper_bot_status_pages_bot_rows(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.application import paper_bots_view
    from etf_cockpit.mcp import tools_paper

    monkeypatch.setattr(
        paper_bots_view,
        "load_paper_bots_view",
        lambda *_args, **_kwargs: {"forward": {"status": "available", "bots": [{"bot_id": str(index)} for index in range(35)]}},
    )
    with use_call_context(_context(tmp_path, _Session(tmp_path))):
        result = tools_paper.paper_bots_status(limit=4)

    assert len(result["forward"]["bots"]) == 4
    assert result["forward"]["total"] == 35
    assert result["forward"]["next_cursor"]


def test_paper_bot_run_submits_to_durable_session_service(tmp_path: Path) -> None:
    from etf_cockpit.mcp import tools_paper

    session = _Session(tmp_path)
    with use_call_context(_context(tmp_path, session)):
        result = tools_paper.paper_bots_run(dry_run=False)

    assert result["job_id"] == "wf_fixture"
    assert session.submissions[0][0] == "paper_bots_run"
    assert session.submissions[0][1]["input_payload"]["as_of"].endswith("+00:00")
