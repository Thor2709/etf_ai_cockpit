from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from etf_cockpit.application.ui_facade import load_paper_incidents
from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, _digest
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum
from etf_cockpit.trading.incidents import IncidentJournal, IncidentJournalIntegrityError, run_operational_drill


def _proposal(source: str) -> dict[str, object]:
    input_material = {"instrument_id": "VWCE", "target_quantity": 10.0, "source": source}
    input_checksum = _digest(input_material)
    gate_policy = load_gate_policy()
    assert gate_policy.policy is not None
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "schema_version": "proposal.v1",
        "proposal_id": f"proposal_{input_checksum[:20]}",
        "instrument_id": "VWCE",
        "outcome": "proposal_ready",
        "proposal_allowed": True,
        "authority_stage": "paper",
        "execution_allowed": False,
        "quantity_delta": 10.0,
        "rationale": "Synthetic incident recovery test.",
        "gates": [
            {"gate_id": gate_id, "passed": True, "reason": "passed", "blocker": True}
            for gate_id in REQUIRED_GATES
        ],
        "alternatives": [],
        "as_of": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "policy_version": "proposal-policy.v1",
        "authority_policy_checksum": current_authority_policy_checksum(),
        "gate_policy_version": gate_policy.policy.policy_version,
        "gate_policy_checksum": gate_policy.checksum,
        "input_checksum": input_checksum,
        "input_material": input_material,
    }
    payload["decision_checksum"] = _digest(payload)
    return payload


def test_unknown_state_causes_immediate_freeze(isolated_runtime_root: Path) -> None:
    ledger = PaperLedger(isolated_runtime_root)
    ledger.open_account(initial_cash=1_000)
    ledger.record_operational_error(
        "unknown_state",
        message="Paper order state is unknown after disconnect.",
        related_id="synthetic-order",
        occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    with pytest.raises(PaperLedgerError, match="frozen"):
        ledger.accept_proposal(_proposal("freeze"), execution_price=10)

    assert ledger.snapshot().reconciliation_status == "frozen"
    assert ledger.snapshot().order_count == 0
    assert load_paper_incidents(isolated_runtime_root)["frozen"] is True


def test_unfreezing_requires_clean_reconciliation(isolated_runtime_root: Path) -> None:
    ledger = PaperLedger(isolated_runtime_root)
    ledger.open_account(initial_cash=1_000)
    ledger.record_operational_error(
        "unknown_state",
        message="Paper order state is unknown.",
        occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    expected = ledger.reconciliation_state()
    assert expected == {"account_id": "local-paper", "cash": 1_000.0, "orders": [], "positions": []}

    mismatch = ledger.reconcile_operational_state({**expected, "cash": 999.0})
    assert mismatch["status"] == "mismatch"
    assert mismatch["frozen"] is True
    assert ledger.snapshot().reconciliation_status == "frozen"
    with pytest.raises(PaperLedgerError, match="frozen"):
        ledger.accept_proposal(_proposal("before-recovery"), execution_price=10)

    recovered = ledger.reconcile_operational_state(expected)
    assert recovered["status"] == "ready"
    assert recovered["frozen"] is False
    assert ledger.snapshot().reconciliation_status == "ready"
    order = ledger.accept_proposal(_proposal("after-recovery"), execution_price=10)
    retry = ledger.accept_proposal(_proposal("after-recovery"), execution_price=10)
    assert retry["order_id"] == order["order_id"]
    assert ledger.snapshot().order_count == 1
    assert ledger.snapshot().event_count == 3
    assert ledger.snapshot().operational_incidents == 1


def test_incident_journal_hash_chain_integrity(isolated_runtime_root: Path) -> None:
    journal = IncidentJournal(isolated_runtime_root)
    incident = journal.record(
        "disconnect",
        message="Synthetic disconnect incident.",
        occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    postmortem = journal.append_postmortem(
        str(incident["incident_id"]),
        summary="Paper order status was checked after the disconnect.",
        evidence={"ledger_reviewed": True},
        occurred_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="immutable"):
        journal.append_postmortem(
            str(incident["incident_id"]),
            summary="Changed post-mortem.",
            evidence={"ledger_reviewed": False},
        )

    rows = journal.path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[1])
    payload["payload"]["summary"] = "Modified post-mortem."
    rows[1] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    journal.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(IncidentJournalIntegrityError, match="hash chain"):
        journal.events()
    assert postmortem["summary"] == "Paper order status was checked after the disconnect."


@pytest.mark.parametrize("scenario", ["disconnect", "order_break"])
def test_operational_drills_have_deterministic_results(scenario: str) -> None:
    first = run_operational_drill(scenario)
    second = run_operational_drill(scenario)

    assert first == second
    assert first["status"] == "passed"
    assert all(first["checks"].values())
    assert first["execution_allowed"] is False
