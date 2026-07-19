"""Deterministic, non-executable proposal policy for ISSUE-0130.

The policy consumes an immutable optimiser/portfolio snapshot and explicit gate
evidence.  A score, signal or UI action alone can never create a proposal.
The result is a review decision with alternatives and an authority envelope;
it is not an order and never grants execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal, Mapping

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import OPERATIONS_DIR


PROPOSAL_POLICY_VERSION = "proposal-policy.v1"
PROPOSAL_SCHEMA_VERSION = "proposal.v1"
EXECUTION_ALLOWED = False

AuthorityStage = Literal[
    "research",
    "shadow_proposal",
    "paper",
    "broker_read_only",
    "draft_order",
    "capped_automatic",
    "disabled",
]
ProposalOutcome = Literal["proposal_ready", "no_trade", "defer", "reduce", "manual_review"]

REQUIRED_GATES = (
    "optimizer_output",
    "portfolio_state",
    "data_freshness",
    "model_confidence",
    "event_risk",
    "liquidity",
    "cost",
    "concentration",
    "account_authority",
)
_STAGE_RANK: dict[str, int] = {
    "research": 0,
    "shadow_proposal": 1,
    "paper": 2,
    "broker_read_only": 3,
    "draft_order": 4,
    "capped_automatic": 5,
    "disabled": -1,
}


@dataclass(frozen=True)
class GateEvidence:
    gate_id: str
    passed: bool
    reason: str
    blocker: bool = True

    def to_payload(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "reason": self.reason,
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class ProposalRequest:
    instrument_id: str
    current_quantity: float
    target_quantity: float
    strategy_id: str
    strategy_stage: AuthorityStage
    model_id: str
    model_stage: AuthorityStage
    account_id: str
    account_stage: AuthorityStage
    optimiser_output_id: str | None
    portfolio_revision: str | None
    data_revision: str | None
    as_of: datetime
    expires_at: datetime
    authority_policy_checksum: str
    gate_evidence: tuple[GateEvidence, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class ProposalAlternative:
    name: Literal["no_trade", "defer", "reduce", "manual_review"]
    reason: str
    quantity_delta: float
    selected: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "reason": self.reason,
            "quantity_delta": self.quantity_delta,
            "selected": self.selected,
        }


@dataclass(frozen=True)
class ProposalDecision:
    proposal_id: str
    instrument_id: str
    outcome: ProposalOutcome
    proposal_allowed: bool
    authority_stage: AuthorityStage
    execution_allowed: Literal[False]
    quantity_delta: float
    rationale: str
    gates: tuple[GateEvidence, ...]
    alternatives: tuple[ProposalAlternative, ...]
    as_of: str
    expires_at: str
    policy_version: str
    authority_policy_checksum: str
    input_checksum: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "instrument_id": self.instrument_id,
            "outcome": self.outcome,
            "proposal_allowed": self.proposal_allowed,
            "authority_stage": self.authority_stage,
            "execution_allowed": self.execution_allowed,
            "quantity_delta": self.quantity_delta,
            "rationale": self.rationale,
            "gates": [item.to_payload() for item in self.gates],
            "alternatives": [item.to_payload() for item in self.alternatives],
            "as_of": self.as_of,
            "expires_at": self.expires_at,
            "policy_version": self.policy_version,
            "authority_policy_checksum": self.authority_policy_checksum,
            "input_checksum": self.input_checksum,
        }


def build_proposal_decision(request: ProposalRequest) -> ProposalDecision:
    """Evaluate a proposal request without creating an order.

    Missing immutable optimiser or portfolio evidence is a manual-review
    outcome.  Every required gate is represented, including missing gates, so
    callers cannot mistake an incomplete input for a passing policy result.
    """

    instrument_id = str(request.instrument_id).strip().upper()
    if not instrument_id:
        raise ValueError("instrument_id must not be blank")
    if request.current_quantity < 0 or request.target_quantity < 0:
        raise ValueError("quantities must be non-negative")
    if request.expires_at <= request.as_of:
        raise ValueError("expires_at must be after as_of")
    for name, value in (
        ("strategy_stage", request.strategy_stage),
        ("model_stage", request.model_stage),
        ("account_stage", request.account_stage),
    ):
        if value not in _STAGE_RANK:
            raise ValueError(f"unsupported {name}: {value}")
    if not str(request.authority_policy_checksum).strip():
        raise ValueError("authority_policy_checksum must not be blank")

    gates_by_id = {item.gate_id: item for item in request.gate_evidence}
    if len(gates_by_id) != len(request.gate_evidence):
        raise ValueError("gate evidence IDs must be unique")
    gates: list[GateEvidence] = []
    for gate_id in REQUIRED_GATES:
        gate = gates_by_id.get(gate_id)
        gates.append(
            gate
            if gate is not None
            else GateEvidence(gate_id, False, "Required immutable evidence was not supplied.")
        )
    gates.extend(sorted((item for item in request.gate_evidence if item.gate_id not in REQUIRED_GATES), key=lambda item: item.gate_id))

    authority_stage = _lowest_stage((request.strategy_stage, request.model_stage, request.account_stage))
    quantity_delta = round(float(request.target_quantity - request.current_quantity), 8)
    failures = [item for item in gates if not item.passed]
    missing_evidence = not request.optimiser_output_id or not request.portfolio_revision or not request.data_revision
    if missing_evidence:
        failures.append(GateEvidence("immutable_inputs", False, "Optimiser output, portfolio revision and data revision are all required."))

    if failures:
        outcome: ProposalOutcome = "manual_review"
        allowed = False
        rationale = "Proposal blocked: " + " ".join(item.reason for item in failures)
    elif authority_stage not in {"shadow_proposal", "paper"}:
        outcome = "manual_review"
        allowed = False
        rationale = f"Proposal blocked: authority stage {authority_stage} cannot create a shadow or paper proposal."
    elif abs(quantity_delta) <= 0:
        outcome = "no_trade"
        allowed = False
        rationale = "No-trade alternative selected because the target quantity equals the current quantity."
    else:
        outcome = "proposal_ready"
        allowed = True
        rationale = request.rationale.strip() or "All required proposal gates passed for an immutable local review."

    alternatives = (
        ProposalAlternative("no_trade", "Hold the current position; no transaction authority is created.", 0.0, outcome == "no_trade"),
        ProposalAlternative("defer", "Defer until all freshness, event, cost and account evidence is current.", quantity_delta, outcome == "defer"),
        ProposalAlternative("reduce", "Use half the requested delta for a lower-turnover review alternative.", round(quantity_delta / 2, 8), outcome == "reduce"),
        ProposalAlternative("manual_review", rationale, 0.0, outcome == "manual_review"),
    )
    canonical_input = {
        "instrument_id": instrument_id,
        "current_quantity": request.current_quantity,
        "target_quantity": request.target_quantity,
        "strategy_id": request.strategy_id,
        "strategy_stage": request.strategy_stage,
        "model_id": request.model_id,
        "model_stage": request.model_stage,
        "account_id": request.account_id,
        "account_stage": request.account_stage,
        "optimiser_output_id": request.optimiser_output_id,
        "portfolio_revision": request.portfolio_revision,
        "data_revision": request.data_revision,
        "as_of": _timestamp(request.as_of),
        "expires_at": _timestamp(request.expires_at),
        "authority_policy_checksum": request.authority_policy_checksum,
        "gates": [item.to_payload() for item in gates],
        "outcome": outcome,
        "quantity_delta": quantity_delta,
    }
    input_checksum = _checksum(canonical_input)
    return ProposalDecision(
        proposal_id=f"proposal_{input_checksum[:20]}",
        instrument_id=instrument_id,
        outcome=outcome,
        proposal_allowed=allowed,
        authority_stage=authority_stage,
        execution_allowed=False,
        quantity_delta=quantity_delta if allowed else 0.0,
        rationale=rationale,
        gates=tuple(gates),
        alternatives=alternatives,
        as_of=_timestamp(request.as_of),
        expires_at=_timestamp(request.expires_at),
        policy_version=PROPOSAL_POLICY_VERSION,
        authority_policy_checksum=request.authority_policy_checksum,
        input_checksum=input_checksum,
    )


def save_proposal_decision(decision: ProposalDecision, *, directory: Path = OPERATIONS_DIR / "proposals") -> Path:
    """Persist one immutable proposal decision for local review and replay."""

    path = directory / f"{decision.proposal_id}.json"
    atomic_write_json(path, decision.to_payload())
    return path


def load_proposal_records(*, directory: Path = OPERATIONS_DIR / "proposals") -> tuple[dict[str, object], ...]:
    if not directory.exists():
        return ()
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("proposal_*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema_version") == PROPOSAL_SCHEMA_VERSION:
            records.append(payload)
    return tuple(records)


def _lowest_stage(stages: tuple[AuthorityStage, ...]) -> AuthorityStage:
    return min(stages, key=lambda value: _STAGE_RANK[value])


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat(timespec="seconds")


def _checksum(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "AuthorityStage",
    "EXECUTION_ALLOWED",
    "GateEvidence",
    "PROPOSAL_POLICY_VERSION",
    "PROPOSAL_SCHEMA_VERSION",
    "ProposalAlternative",
    "ProposalDecision",
    "ProposalOutcome",
    "ProposalRequest",
    "REQUIRED_GATES",
    "build_proposal_decision",
    "load_proposal_records",
    "save_proposal_decision",
]
