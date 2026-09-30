from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, _digest
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum
from etf_cockpit.trading.pre_trade_controls import PreTradeControls


def _proposal(*, quantity_delta: float = 10.0, source: str = "pre-trade-test") -> dict[str, object]:
    input_material = {"instrument_id": "VWCE", "target_quantity": quantity_delta, "source": source}
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
        "gates": [
            {"gate_id": gate_id, "passed": True, "reason": "passed", "blocker": True}
            for gate_id in REQUIRED_GATES
        ],
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


def _known_broker_state() -> SimpleNamespace:
    return SimpleNamespace(
        account_status="reconciled",
        positions_status="reconciled",
        cash_status="reconciled",
        orders_status="reconciled",
        connected=True,
        breaks=(),
    )


def _evaluate_read_only(controls: PreTradeControls, proposal: dict[str, object], *, broker_state: object):
    return controls.evaluate_order(
        proposal,
        execution_price=10,
        quantity_delta=float(proposal["quantity_delta"]),
        fx_rate=1,
        broker_state=broker_state,
        daily_turnover=0,
        path="read_only",
        occurred_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )


def _evaluate_paper(controls: PreTradeControls, proposal: dict[str, object], *, at: datetime):
    return controls.evaluate_order(
        proposal,
        execution_price=10,
        quantity_delta=float(proposal["quantity_delta"]),
        fx_rate=1,
        positions={},
        open_orders={},
        paper_events=[],
        path="paper",
        who="paper-operator",
        occurred_at=at,
    )


def test_hard_order_limit_rejects_proposal_approved_by_proposal_policy(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=100_000)
    proposal = _proposal(quantity_delta=1_001)
    assert proposal["proposal_allowed"] is True

    with pytest.raises(PaperLedgerError, match="exceeds the hard limit"):
        ledger.accept_proposal(proposal, execution_price=10)

    blocked = next(event for event in PreTradeControls(tmp_path).audit_events() if event["event_type"] == "order_blocked")
    assert blocked["details"]["control"] == "max_order_value"
    assert blocked["who"] == "local-paper"
    assert blocked["why"]
    assert blocked["expiry"] is None


def test_kill_switch_cancels_open_paper_orders_and_blocks_paper_and_read_only_paths(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1_000)
    order = ledger.accept_proposal(_proposal(source="open-before-kill"), execution_price=10)
    at = datetime(2026, 9, 30, tzinfo=timezone.utc)
    controls = PreTradeControls(tmp_path)
    controls.activate_kill_switch(who="operator-a", reason="Operational halt", paper_ledger=ledger, occurred_at=at)

    assert ledger.orders()[0]["status"] == "cancelled"
    with pytest.raises(PaperLedgerError, match="kill switch"):
        ledger.accept_proposal(_proposal(source="blocked-by-kill"), execution_price=10)
    read_only = _evaluate_read_only(controls, _proposal(source="read-only-kill"), broker_state=_known_broker_state())
    assert read_only.allowed is False
    assert read_only.control == "kill_switch"
    audit_types = [event["event_type"] for event in controls.audit_events()]
    assert "kill_switch_activated" in audit_types
    assert "order_blocked" in audit_types
    assert order["order_id"] == ledger.orders()[0]["order_id"]


def test_override_expires_is_audited_and_self_approval_is_rejected(tmp_path: Path) -> None:
    controls = PreTradeControls(tmp_path)
    at = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    proposal = _proposal(quantity_delta=1_001, source="temporary-order-override")
    grant = controls.grant_override(
        "override-temporary-order",
        control="max_order_value",
        proposal_id=str(proposal["proposal_id"]),
        maker="risk-maker",
        checker="risk-checker",
        reason="Documented one-order review",
        expires_at=at + timedelta(minutes=5),
        occurred_at=at,
    )
    assert grant["event_type"] == "override_granted"
    assert _evaluate_paper(controls, proposal, at=at).allowed is True
    expired = _evaluate_paper(controls, proposal, at=at + timedelta(minutes=6))
    assert expired.allowed is False
    assert expired.control == "max_order_value"

    rejected = controls.grant_override(
        "override-self-approved",
        control="max_order_value",
        proposal_id=str(proposal["proposal_id"]),
        maker="same-person",
        checker="same-person",
        reason="Attempted self approval",
        expires_at=at + timedelta(minutes=4),
        occurred_at=at,
    )
    assert rejected["event_type"] == "override_rejected"
    events = controls.audit_events()
    assert any(event["event_type"] == "override_used" and event["expiry"] == grant["expiry"] for event in events)
    assert any(event["event_type"] == "override_expired" and event["expiry"] == grant["expiry"] for event in events)
    self_rejection = next(event for event in events if event["event_type"] == "override_rejected")
    assert self_rejection["who"] == "same-person"
    assert "self-approved" in self_rejection["why"]


def test_unknown_broker_state_blocks_read_only_order(tmp_path: Path) -> None:
    controls = PreTradeControls(tmp_path)
    unknown = SimpleNamespace(
        account_status="unknown",
        positions_status="reconciled",
        cash_status="reconciled",
        orders_status="reconciled",
        connected=True,
        breaks=(),
    )

    decision = _evaluate_read_only(controls, _proposal(source="unknown-broker-state"), broker_state=unknown)

    assert decision.allowed is False
    assert decision.control == "broker_state_unknown"
    blocked = controls.audit_events()[-1]
    assert blocked["event_type"] == "order_blocked"
    assert blocked["details"]["control"] == "broker_state_unknown"
    assert blocked["expiry"] is None


def test_missing_limits_configuration_blocks_and_is_audited(tmp_path: Path) -> None:
    controls = PreTradeControls(tmp_path, limits_path=tmp_path / "missing-limits.yaml")

    decision = _evaluate_paper(controls, _proposal(source="missing-limits"), at=datetime(2026, 9, 30, tzinfo=timezone.utc))

    assert decision.allowed is False
    assert decision.control == "limits_config"
    assert controls.audit_events()[-1]["event_type"] == "order_blocked"
