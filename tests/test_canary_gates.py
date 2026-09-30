from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from etf_cockpit.application.ui_facade import load_canary_status
from etf_cockpit.portfolio.paper_trading import PaperLedger, _digest
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum
from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.trading.canary import CanaryConfig, CanaryController, CanaryError, seal_evidence


def _proposal(*, quantity_delta: float = 1.0) -> dict[str, object]:
    input_material = {"instrument_id": "VWCE", "target_quantity": quantity_delta, "source": "canary-test"}
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
        "rationale": "Canary fixture passed independent paper gates.",
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


def _automatic_controller(root: Path) -> CanaryController:
    controller = CanaryController(
        root,
        config=CanaryConfig(
            enabled=True,
            stage_flags={"paper": True, "capped_automatic": True},
            loss_limit=Decimal("100"),
        ),
    )
    promoted = controller.promote(
        "capped_automatic",
        operator_enabled=True,
        promotion_evidence=seal_evidence(
            {
                "controls_passed": True,
                "release_certified": True,
                "reconciliation_clear": True,
                "rollback_tested": True,
            }
        ),
    )
    assert promoted.allowed is True
    return controller


def _sealed_order_evidence(proposal: dict[str, object]):
    sealed_proposal = seal_evidence(proposal)
    sealed_controls = seal_evidence(
        {
            "proposal_id": proposal["proposal_id"],
            "proposal_hash": sealed_proposal.sha256,
            "allowed": True,
            "execution_allowed": False,
            "control_source": "pre_trade_controls",
        }
    )
    return sealed_proposal, sealed_controls


def test_fresh_install_rejects_canary_orders(tmp_path: Path) -> None:
    proposal = _proposal()
    sealed_proposal, sealed_controls = _sealed_order_evidence(proposal)
    controller = CanaryController(tmp_path)

    with pytest.raises(CanaryError, match="canary_opt_in_missing"):
        controller.accept_paper_order(
            proposal=sealed_proposal,
            control_evidence=sealed_controls,
            execution_price=10,
        )

    assert controller.status()["state"] == "disabled"
    assert controller.audit_events()[-1]["event_type"] == "paper_order_blocked"


def test_loss_limit_breach_auto_demotes_to_paper_and_is_audited(tmp_path: Path) -> None:
    controller = _automatic_controller(tmp_path)

    decision = controller.observe_loss(Decimal("101"))

    assert decision.allowed is False
    assert decision.stage == "paper"
    assert controller.status()["stage"] == "paper"
    event = controller.audit_events()[-1]
    assert event["event_type"] == "auto_demoted"
    assert event["details"]["reason"] == "loss_limit_breach"
    assert event["details"]["loss_limit"] == "100"


def test_reconciliation_break_auto_demotes_to_paper_and_blocks_orders(tmp_path: Path) -> None:
    controller = _automatic_controller(tmp_path)

    decision = controller.observe_reconciliation(reconciled=False)

    assert decision.allowed is False
    assert decision.stage == "paper"
    assert controller.status()["state"] == "reconciliation_blocked"
    assert controller.paper_order_gate().unmet_dependencies == ("reconciliation_break_active",)
    events = controller.audit_events()
    assert events[-2]["event_type"] == "reconciliation_break"
    assert events[-1]["event_type"] == "auto_demoted"
    assert events[-1]["details"]["reason"] == "reconciliation_break"

    controller.observe_reconciliation(reconciled=True)
    assert controller.status()["stage"] == "paper"
    assert controller.status()["state"] == "paper_canary"


def test_order_without_sealed_proposal_or_control_hashes_is_rejected(tmp_path: Path) -> None:
    controller = CanaryController(
        tmp_path,
        config=CanaryConfig(enabled=True, stage_flags={"paper": True}),
    )

    with pytest.raises(CanaryError, match="sealed proposal and sealed control evidence"):
        controller.accept_paper_order(
            proposal=None,
            control_evidence=None,
            execution_price=10,
        )

    assert controller.audit_events()[-1]["details"]["reason"] == "sealed_proposal_or_control_evidence_missing"


def test_every_enabled_stage_flag_still_leaves_live_submission_blocked(tmp_path: Path) -> None:
    stage_flags = {
        "research": True,
        "shadow_proposal": True,
        "paper": True,
        "broker_read_only": True,
        "draft_order": True,
        "capped_automatic": True,
        "disabled": True,
        "live": True,
    }
    controller = CanaryController(
        tmp_path,
        config=CanaryConfig(enabled=True, stage_flags=stage_flags, loss_limit=Decimal("100")),
    )

    gate = controller.evaluate_live_submission()

    assert gate.allowed is False
    assert gate.execution_allowed is False
    assert "owner_decision_d6_live_submission_disabled" in gate.unmet_dependencies
    assert "ISSUE-0152_final_release_certification_missing" in gate.unmet_dependencies
    assert len(gate.unmet_dependencies) >= 4


def test_emergency_shutdown_blocks_and_rollback_restores_previous_stage(tmp_path: Path) -> None:
    controller = _automatic_controller(tmp_path)

    shutdown = controller.emergency_shutdown(reason="Synthetic emergency stop")
    assert shutdown.allowed is False
    assert controller.paper_order_gate().allowed is False
    assert controller.status()["state"] == "emergency_shutdown"

    rollback = controller.rollback(reason="Synthetic rollback review")

    assert rollback.allowed is True
    assert rollback.stage == "capped_automatic"
    assert controller.status()["stage"] == "capped_automatic"
    assert controller.audit_events()[-1]["event_type"] == "rollback"


def test_accepted_paper_order_records_verified_proposal_and_control_hashes(tmp_path: Path) -> None:
    proposal = _proposal()
    sealed_proposal, sealed_controls = _sealed_order_evidence(proposal)
    PaperLedger(tmp_path).open_account(initial_cash=1_000)
    controller = CanaryController(
        tmp_path,
        config=CanaryConfig(enabled=True, stage_flags={"paper": True}),
    )

    order = controller.accept_paper_order(
        proposal=sealed_proposal,
        control_evidence=sealed_controls,
        execution_price=10,
        occurred_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )

    assert order["execution_allowed"] is False
    event = controller.audit_events()[-1]
    assert event["event_type"] == "paper_order_accepted"
    assert event["details"]["order_id"] == order["order_id"]
    assert event["details"]["proposal_hash"] == sealed_proposal.sha256
    assert event["details"]["control_hash"] == sealed_controls.sha256
    assert order["control_binding_hash"] == event["details"]["control_binding_hash"]
    assert controller.status()["stage"] == "paper"


@pytest.mark.parametrize("changed_term", ["execution_price", "fee", "fx_rate"])
def test_canary_rejects_execution_terms_changed_after_control_sealing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_term: str
) -> None:
    proposal = _proposal()
    sealed_proposal, sealed_controls = _sealed_order_evidence(proposal)
    PaperLedger(tmp_path).open_account(initial_cash=1_000)
    controller = CanaryController(
        tmp_path,
        config=CanaryConfig(enabled=True, stage_flags={"paper": True}),
    )
    original_accept = PaperLedger.accept_proposal

    def change_term(self, proposal_payload, *args, **kwargs):
        kwargs[changed_term] = Decimal(str(kwargs[changed_term])) + Decimal("1")
        return original_accept(self, proposal_payload, *args, **kwargs)

    monkeypatch.setattr(PaperLedger, "accept_proposal", change_term)

    with pytest.raises(CanaryError, match="ledger rejected"):
        controller.accept_paper_order(
            proposal=sealed_proposal,
            control_evidence=sealed_controls,
            execution_price=10,
            occurred_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        )

    assert controller.audit_events()[-1]["event_type"] == "paper_order_blocked"


def test_facade_exposes_a_fresh_install_as_distinct_disabled_state(tmp_path: Path) -> None:
    status = load_canary_status(tmp_path)

    assert status["state"] == "disabled"
    assert status["live_submission"] == "blocked"
    assert status["execution_allowed"] is False
