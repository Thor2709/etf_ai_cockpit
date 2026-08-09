from __future__ import annotations

import hashlib
import json
from pathlib import Path

from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import _digest
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum


def paper_proposal(*, instrument_id: str = "VWCE", quantity_delta: float = 10.0) -> dict[str, object]:
    """Build the smallest policy-complete proposal accepted by the paper ledger."""

    input_material = {
        "instrument_id": instrument_id,
        "target_quantity": quantity_delta,
        "source": "issue0014-fixture",
    }
    gate_policy = load_gate_policy()
    assert gate_policy.policy is not None
    proposal: dict[str, object] = {
        "schema_version": "proposal.v1",
        "proposal_id": f"proposal_{_digest(input_material)[:20]}",
        "instrument_id": instrument_id,
        "outcome": "proposal_ready",
        "proposal_allowed": True,
        "authority_stage": "paper",
        "execution_allowed": False,
        "quantity_delta": quantity_delta,
        "rationale": "Deterministic ISSUE-0014 paper fixture.",
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
        "input_checksum": _digest(input_material),
        "input_material": input_material,
    }
    proposal["decision_checksum"] = _digest(proposal)
    return proposal


def write_paper_proposal(root: Path, proposal: dict[str, object]) -> None:
    path = root / "data" / "operations" / "proposals" / f"{proposal['proposal_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, sort_keys=True) + "\n", encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
