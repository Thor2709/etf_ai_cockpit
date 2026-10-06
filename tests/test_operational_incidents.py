from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from etf_cockpit.application.paper_views import load_paper_incidents
from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, _digest
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum
from etf_cockpit.trading import incidents as incident_module
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


@pytest.mark.parametrize("tamper", ["suffix", "delete", "empty"])
def test_incident_journal_rejects_truncation_against_durable_head(
    isolated_runtime_root: Path,
    tamper: str,
) -> None:
    journal = IncidentJournal(isolated_runtime_root)
    journal.record(
        "unknown_state",
        message="Synthetic incident for truncation test.",
        requires_freeze=True,
        occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    expected = {"account_id": "local-paper", "state": "clean"}
    assert journal.reconcile(expected, expected)["status"] == "ready"
    assert journal.is_frozen is False

    if tamper == "suffix":
        rows = journal.path.read_text(encoding="utf-8").splitlines()
        journal.path.write_text(rows[0] + "\n", encoding="utf-8")
    elif tamper == "delete":
        journal.path.unlink()
    else:
        journal.path.write_text("", encoding="utf-8")

    with pytest.raises(IncidentJournalIntegrityError, match="anchor"):
        journal.is_frozen
    if tamper == "delete":
        incidents = load_paper_incidents(isolated_runtime_root)
        assert incidents["status"] == "invalid"
        assert incidents["frozen"] is True
        assert incidents["execution_allowed"] is False

        snapshot = PaperLedger(isolated_runtime_root).snapshot()
        assert snapshot.reconciliation_status == "frozen"


@pytest.mark.parametrize("scenario", ["disconnect", "order_break"])
def test_operational_drills_have_deterministic_results(
    scenario: str,
    isolated_runtime_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = iter((isolated_runtime_root / f"{scenario}-first", isolated_runtime_root / f"{scenario}-second"))
    monkeypatch.setattr(incident_module.tempfile, "TemporaryDirectory", lambda **_kwargs: nullcontext(next(roots)))
    first = run_operational_drill(scenario)
    second = run_operational_drill(scenario)

    assert first == second
    assert first["status"] == "passed"
    assert all(first["checks"].values())
    assert first["execution_allowed"] is False


def _two_event_journal(root: Path) -> IncidentJournal:
    journal = IncidentJournal(root)
    journal.record("baseline", message="Baseline", occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    journal.record("second", message="Second", occurred_at=datetime(2026, 7, 21, tzinfo=timezone.utc))
    return journal


def test_interrupted_anchor_update_after_append_rolls_forward_and_reanchors(isolated_runtime_root: Path) -> None:
    journal = IncidentJournal(isolated_runtime_root)
    journal.record("baseline", message="Baseline", occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    with patch.object(incident_module.os, "replace", side_effect=OSError("disk full")):
        with pytest.raises(ValueError):
            journal.record("freeze", message="Freeze", requires_freeze=True, occurred_at=datetime(2026, 7, 21, tzinfo=timezone.utc))
    assert journal.is_frozen is True
    assert len(journal.events()) == 2
    anchor = json.loads(journal._head_path.read_text(encoding="utf-8"))
    assert anchor["event_count"] == 2
    journal.record("third", message="Third", occurred_at=datetime(2026, 7, 22, tzinfo=timezone.utc))
    assert len(journal.events()) == 3


def test_interrupted_first_append_rolls_forward(isolated_runtime_root: Path) -> None:
    journal = IncidentJournal(isolated_runtime_root)
    with patch.object(incident_module.os, "replace", side_effect=OSError("disk full")):
        with pytest.raises(ValueError):
            journal.record("baseline", message="Baseline", occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert len(journal.events()) == 1
    assert json.loads(journal._head_path.read_text(encoding="utf-8"))["event_count"] == 1


def test_anchor_two_events_behind_or_stale_hash_stays_fail_closed(isolated_runtime_root: Path) -> None:
    journal = _two_event_journal(isolated_runtime_root)
    anchor = json.loads(journal._head_path.read_text(encoding="utf-8"))
    stale_body = {key: anchor[key] for key in ("schema_version", "account_id")} | {"event_count": 0, "head_hash": "0" * 64}
    journal._head_path.write_text(
        json.dumps(stale_body | {"content_hash": incident_module._digest(stale_body)}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    with pytest.raises(IncidentJournalIntegrityError, match="anchor"):
        journal.events()
    wrong_head = {key: anchor[key] for key in ("schema_version", "account_id")} | {"event_count": 1, "head_hash": "f" * 64}
    journal._head_path.write_text(
        json.dumps(wrong_head | {"content_hash": incident_module._digest(wrong_head)}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    with pytest.raises(IncidentJournalIntegrityError, match="anchor"):
        journal.events()
