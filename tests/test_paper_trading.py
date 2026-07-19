from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import (
    PaperLedger,
    PaperLedgerError,
    PaperLedgerIntegrityError,
    _digest,
)
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum


def _proposal(*, quantity_delta: float = 10.0, source: str = "paper-test") -> dict[str, object]:
    input_material = {
        "instrument_id": "VWCE",
        "target_quantity": quantity_delta,
        "source": source,
    }
    input_checksum = _digest(input_material)
    gate_policy = load_gate_policy()
    assert gate_policy.policy is not None
    payload: dict[str, object] = {
        "schema_version": "proposal.v1",
        "proposal_id": f"proposal_{input_checksum[:20]}",
        "instrument_id": "VWCE",
        "outcome": "proposal_ready",
        "proposal_allowed": True,
        "authority_stage": "paper",
        "execution_allowed": False,
        "quantity_delta": quantity_delta,
        "rationale": "All required paper evidence passed.",
        "gates": [{"gate_id": gate_id, "passed": True, "reason": "passed", "blocker": True} for gate_id in REQUIRED_GATES],
        "alternatives": [],
        "as_of": "2099-01-01T00:00:00+00:00",
        "expires_at": "2099-01-02T00:00:00+00:00",
        "policy_version": "proposal-policy.v1",
        "authority_policy_checksum": current_authority_policy_checksum(),
        "gate_policy_version": gate_policy.policy.policy_version,
        "gate_policy_checksum": gate_policy.checksum,
        "input_checksum": input_checksum,
        "input_material": input_material,
    }
    payload["decision_checksum"] = _digest(payload)
    return payload


def _write_proposal(root: Path, proposal: dict[str, object]) -> None:
    path = root / "data" / "operations" / "proposals" / f"{proposal['proposal_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, sort_keys=True) + "\n", encoding="utf-8")


def test_paper_lifecycle_replays_cash_positions_and_marks_after_restart(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    opened = ledger.open_account(initial_cash=1_000, occurred_at=datetime(2026, 7, 19, tzinfo=timezone.utc))
    assert opened.status == "ready"

    order = ledger.accept_proposal(_proposal(), execution_price=10)
    assert order["status"] == "accepted"
    partial = ledger.record_fill(str(order["order_id"]), quantity=4, price=10)
    assert partial["status"] == "partially_filled"
    ledger.record_fill(str(order["order_id"]), quantity=6, price=11, fee=2)
    marked = ledger.mark(
        "VWCE",
        adjusted_close=12,
        source_authority="test-adjusted-close",
        source_checksum="a" * 64,
        occurred_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )

    assert marked.cash == pytest.approx(892)
    assert marked.equity == pytest.approx(1_012)
    assert marked.pnl == pytest.approx(12)
    assert marked.open_positions == 1
    assert marked.positions[0].average_cost == pytest.approx(10.8)
    assert marked.positions[0].unrealised_pnl == pytest.approx(12)
    assert marked.reconciliation_status == "ready"
    assert PaperLedger(tmp_path).trade_rows()[0]["source_authority"] == "local_paper_ledger"

    restarted = PaperLedger(tmp_path).snapshot()
    assert restarted.to_payload() == marked.to_payload()
    assert PaperLedger(tmp_path).reconcile()["status"] == "ready"


def test_paper_sell_realises_pnl_and_supports_cancellation_and_rejection(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000)
    order = ledger.accept_proposal(_proposal(), execution_price=10)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10)

    sell_proposal = _proposal(quantity_delta=-4.0, source="paper-sell")
    sell = ledger.accept_proposal(sell_proposal, execution_price=13)
    ledger.record_fill(str(sell["order_id"]), quantity=4, price=13)
    snapshot = ledger.snapshot()
    assert snapshot.closed_trades == 1
    assert snapshot.positions[0].realised_pnl == pytest.approx(12)
    assert snapshot.win_rate == pytest.approx(1)

    cancelled = ledger.accept_proposal(_proposal(source="paper-cancel"), execution_price=10)
    assert ledger.cancel_order(str(cancelled["order_id"]), reason="Manual review deferred")["status"] == "cancelled"
    rejected = ledger.reject_proposal(_proposal(source="paper-reject"), reason="Evidence window expired")
    assert rejected["reason"] == "Evidence window expired"
    with pytest.raises(PaperLedgerError, match="cannot also be rejected"):
        ledger.reject_proposal(sell_proposal, reason="Contradictory decision")


def test_paper_drawdown_retains_the_historical_equity_peak(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000)
    order = ledger.accept_proposal(_proposal(source="drawdown"), execution_price=10)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10)
    ledger.mark("VWCE", adjusted_close=12, source_checksum="a" * 64)
    trough = ledger.mark("VWCE", adjusted_close=9, source_checksum="b" * 64)

    assert trough.drawdown == pytest.approx((990 - 1_020) / 1_020)


def test_paper_fill_retries_are_idempotent_and_use_acceptance_fee(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000)
    order = ledger.accept_proposal(_proposal(source="fee"), execution_price=10, fee=10)

    first = ledger.record_fill(str(order["order_id"]), quantity=10, price=10)
    retry = ledger.record_fill(str(order["order_id"]), quantity=10, price=10)

    assert first == retry
    assert ledger.snapshot().cash == pytest.approx(890)


def test_paper_corporate_action_retry_does_not_double_adjust_account(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000)
    order = ledger.accept_proposal(_proposal(source="action"), execution_price=10)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10)

    first = ledger.apply_corporate_action(
        "VWCE",
        action_id="action-1",
        split_ratio=2,
        cash_dividend_per_unit=0.5,
        source_checksum="c" * 64,
    )
    retry = ledger.apply_corporate_action(
        "VWCE",
        action_id="action-1",
        split_ratio=2,
        cash_dividend_per_unit=0.5,
        source_checksum="c" * 64,
    )

    assert retry.to_payload() == first.to_payload()
    assert retry.cash == pytest.approx(905)


def test_paper_rejected_proposal_cannot_be_accepted_and_fill_ids_cannot_cross_orders(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000)
    rejected = _proposal(source="reject-first")
    ledger.reject_proposal(rejected, reason="Manual no-trade")
    with pytest.raises(PaperLedgerError, match="rejected"):
        ledger.accept_proposal(rejected, execution_price=10)

    first = ledger.accept_proposal(_proposal(source="fill-one"), execution_price=10)
    second = ledger.accept_proposal(_proposal(source="fill-two"), execution_price=10)
    ledger.record_fill(str(first["order_id"]), fill_id="shared-fill", quantity=1, price=10)
    with pytest.raises(PaperLedgerError, match="another paper order"):
        ledger.record_fill(str(second["order_id"]), fill_id="shared-fill", quantity=1, price=10)


def test_paper_corporate_action_and_integrity_failure_are_explicit(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000)
    order = ledger.accept_proposal(_proposal(), execution_price=10)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10)
    snapshot = ledger.apply_corporate_action(
        "VWCE",
        split_ratio=2,
        cash_dividend_per_unit=0.5,
        source_authority="test-corporate-action",
        source_checksum="b" * 64,
    )
    assert snapshot.positions[0].quantity == pytest.approx(20)
    assert snapshot.positions[0].average_cost == pytest.approx(5)
    assert snapshot.cash == pytest.approx(905)

    ledger.path.write_text(ledger.path.read_text(encoding="utf-8").replace("VWCE", "TAMPERED", 1), encoding="utf-8")
    with pytest.raises(PaperLedgerIntegrityError, match="checksum|hash"):
        PaperLedger(tmp_path).snapshot()


def test_paper_requires_gate_approved_proposal_and_open_account(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    with pytest.raises(PaperLedgerError, match="Open"):
        ledger.accept_proposal(_proposal(), execution_price=10)
    ledger.open_account(initial_cash=100)
    blocked = dict(_proposal(), proposal_allowed=False, outcome="manual_review")
    blocked["decision_checksum"] = _digest({key: value for key, value in blocked.items() if key != "decision_checksum"})
    with pytest.raises(PaperLedgerError, match="proposal-ready"):
        ledger.accept_proposal(blocked, execution_price=10)


def test_instrument_detail_reads_the_local_paper_ledger(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app.selectors import instrument_detail

    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=100)
    order = ledger.accept_proposal(_proposal(source="instrument-detail"), execution_price=5)
    ledger.record_fill(str(order["order_id"]), quantity=2, price=5)
    monkeypatch.setattr(instrument_detail, "PAPER_TRADES_PATH", tmp_path / "data" / "derived" / "paper_trades.parquet")

    panel = instrument_detail._paper_trade_panel("VWCE")
    assert panel["status"] == "available"
    assert panel["rows"][0]["source_authority"] == "local_paper_ledger"
