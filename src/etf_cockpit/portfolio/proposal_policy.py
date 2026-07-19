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
import os
from pathlib import Path
from typing import Literal, Mapping

import yaml

from etf_cockpit.core.paths import OPERATIONS_DIR
from etf_cockpit.governance.models import AuthorityMatrixPolicy
from etf_cockpit.governance.product_scope import AUTHORITY_MATRIX_PATH, load_authority_matrix, load_gate_policy


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
    gate_policy_version: str
    gate_policy_checksum: str
    input_checksum: str
    input_material: Mapping[str, object]

    def to_payload(self) -> dict[str, object]:
        payload = {
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
            "gate_policy_version": self.gate_policy_version,
            "gate_policy_checksum": self.gate_policy_checksum,
            "input_checksum": self.input_checksum,
            "input_material": dict(self.input_material),
        }
        payload["decision_checksum"] = _checksum(payload)
        return payload


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
    authority_policy_checksum, resolved_stages = _resolve_authority(request)
    gate_policy_version, gate_policy_checksum = _gate_policy_metadata()

    gates_by_id = {item.gate_id: item for item in request.gate_evidence}
    if len(gates_by_id) != len(request.gate_evidence):
        raise ValueError("gate evidence IDs must be unique")
    missing_inputs = {
        "optimizer_output": not str(request.optimiser_output_id or "").strip(),
        "portfolio_state": not str(request.portfolio_revision or "").strip(),
        "data_freshness": not str(request.data_revision or "").strip(),
    }
    gates: list[GateEvidence] = []
    for gate_id in REQUIRED_GATES:
        gate = gates_by_id.get(gate_id)
        if gate is None:
            gates.append(GateEvidence(gate_id, False, "Required immutable evidence was not supplied."))
        elif missing_inputs.get(gate_id, False) and gate.passed:
            gates.append(GateEvidence(gate_id, False, "Required immutable evidence was not supplied."))
        else:
            gates.append(gate)
    gates.extend(sorted((item for item in request.gate_evidence if item.gate_id not in REQUIRED_GATES), key=lambda item: item.gate_id))

    authority_stage = _lowest_stage(resolved_stages)
    quantity_delta = round(float(request.target_quantity - request.current_quantity), 8)
    failures = [item for item in gates if not item.passed]

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
        "strategy_stage": resolved_stages[0],
        "model_id": request.model_id,
        "model_stage": resolved_stages[1],
        "account_id": request.account_id,
        "account_stage": resolved_stages[2],
        "optimiser_output_id": request.optimiser_output_id,
        "portfolio_revision": request.portfolio_revision,
        "data_revision": request.data_revision,
        "as_of": _timestamp(request.as_of),
        "expires_at": _timestamp(request.expires_at),
        "authority_policy_checksum": authority_policy_checksum,
        "gates": [item.to_payload() for item in gates],
        "outcome": outcome,
        "quantity_delta": quantity_delta,
        "policy_version": PROPOSAL_POLICY_VERSION,
        "gate_policy_version": gate_policy_version,
        "gate_policy_checksum": gate_policy_checksum,
        "request_rationale": request.rationale.strip(),
        "decision_rationale": rationale,
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
        authority_policy_checksum=authority_policy_checksum,
        gate_policy_version=gate_policy_version,
        gate_policy_checksum=gate_policy_checksum,
        input_checksum=input_checksum,
        input_material=canonical_input,
    )


def save_proposal_decision(decision: ProposalDecision, *, directory: Path = OPERATIONS_DIR / "proposals") -> Path:
    """Persist one immutable proposal decision for local review and replay."""

    path = directory / f"{decision.proposal_id}.json"
    payload = decision.to_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Existing proposal record is unreadable: {path}") from exc
        if existing != payload:
            raise ValueError(f"Immutable proposal record conflicts with existing proposal: {decision.proposal_id}")
        return path
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Existing proposal record is unreadable: {path}") from exc
        if existing != payload:
            raise ValueError(f"Immutable proposal record conflicts with existing proposal: {decision.proposal_id}")
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
        if isinstance(payload, dict) and _valid_record(payload):
            records.append(payload)
    return tuple(records)


def _lowest_stage(stages: tuple[AuthorityStage, ...]) -> AuthorityStage:
    return min(stages, key=lambda value: _STAGE_RANK[value])


def _gate_policy_metadata() -> tuple[str, str]:
    result = load_gate_policy()
    if result.diagnostic_mode or result.policy is None or len(result.checksum) != 64:
        raise ValueError("gate policy unavailable: " + "; ".join(result.diagnostics))
    return str(result.policy.policy_version), result.checksum


def _valid_record(payload: Mapping[str, object]) -> bool:
    if payload.get("schema_version") != PROPOSAL_SCHEMA_VERSION:
        return False
    if payload.get("policy_version") != PROPOSAL_POLICY_VERSION:
        return False
    if payload.get("execution_allowed") is not False:
        return False
    proposal_id = str(payload.get("proposal_id", ""))
    input_checksum = str(payload.get("input_checksum", ""))
    if len(input_checksum) != 64 or proposal_id != f"proposal_{input_checksum[:20]}":
        return False
    authority_checksum = str(payload.get("authority_policy_checksum", ""))
    gate_checksum = str(payload.get("gate_policy_checksum", ""))
    gate_version = str(payload.get("gate_policy_version", ""))
    if len(authority_checksum) != 64 or len(gate_checksum) != 64 or not gate_version:
        return False
    try:
        _, current_authority_checksum = _load_proposal_authority()
        current_gate_version, current_gate_checksum = _gate_policy_metadata()
    except ValueError:
        return False
    if authority_checksum != current_authority_checksum:
        return False
    if gate_version != current_gate_version or gate_checksum != current_gate_checksum:
        return False
    input_material = payload.get("input_material")
    if not isinstance(input_material, Mapping) or _checksum(input_material) != input_checksum:
        return False
    decision_checksum = str(payload.get("decision_checksum", ""))
    if len(decision_checksum) != 64:
        return False
    without_decision_checksum = {
        key: value for key, value in payload.items() if key != "decision_checksum"
    }
    if _checksum(without_decision_checksum) != decision_checksum:
        return False
    raw_gates = payload.get("gates")
    if not isinstance(raw_gates, (tuple, list)):
        return False
    gate_ids = [str(item.get("gate_id", "")) for item in raw_gates if isinstance(item, Mapping)]
    if len(gate_ids) != len(raw_gates) or len(gate_ids) != len(set(gate_ids)):
        return False
    return set(REQUIRED_GATES).issubset(gate_ids)


def current_authority_policy_checksum() -> str:
    """Return the checksum of the loaded local authority matrix."""

    _, checksum = _load_proposal_authority()
    return checksum


def _resolve_authority(request: ProposalRequest) -> tuple[str, tuple[AuthorityStage, AuthorityStage, AuthorityStage]]:
    policy, policy_checksum = _load_proposal_authority()
    supplied_checksum = str(request.authority_policy_checksum).strip().lower()
    if supplied_checksum != policy_checksum:
        raise ValueError("authority_policy_checksum does not match the loaded authority matrix")

    capabilities = {item.capability_id: item for item in policy.capabilities}
    resolved: list[AuthorityStage] = []
    for role, capability_id, claimed_stage in (
        ("strategy", request.strategy_id, request.strategy_stage),
        ("model", request.model_id, request.model_stage),
        ("account", request.account_id, request.account_stage),
    ):
        capability = capabilities.get(str(capability_id).strip())
        if capability is None:
            raise ValueError(f"{role} capability is not registered: {capability_id}")
        actual_stage = str(capability.authority_stage)
        if actual_stage not in _STAGE_RANK:
            raise ValueError(f"{role} capability has unsupported authority stage: {actual_stage}")
        if str(claimed_stage) != actual_stage:
            raise ValueError(
                f"{role} stage mismatch: declared {claimed_stage}, policy permits {actual_stage}"
            )
        if actual_stage == "disabled" or str(getattr(capability, "availability", "mandatory")) == "disabled":
            raise ValueError(f"{role} capability is disabled: {capability_id}")
        resolved.append(actual_stage)  # type: ignore[arg-type]
    return policy_checksum, (resolved[0], resolved[1], resolved[2])


def _load_proposal_authority() -> tuple[AuthorityMatrixPolicy, str]:
    """Load the capability policy without inheriting unrelated inventory gaps.

    ``load_authority_matrix`` also checks that every runtime route and dataset
    is registered.  That wider coverage check is valuable release evidence but
    currently has a known baseline gap.  Proposal authority only needs the
    typed matrix and its raw-file checksum, so fall back to strict model
    parsing while keeping malformed or missing policy data fail-closed.
    """

    result = load_authority_matrix()
    if result.policy is not None and len(result.checksum) == 64:
        return result.policy, result.checksum
    try:
        raw = AUTHORITY_MATRIX_PATH.read_bytes()
        payload = yaml.safe_load(raw)
        policy = AuthorityMatrixPolicy.model_validate(payload)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        diagnostics = "; ".join(result.diagnostics)
        raise ValueError(f"authority matrix unavailable: {diagnostics or exc}") from exc
    return policy, hashlib.sha256(raw).hexdigest()


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
    "current_authority_policy_checksum",
    "load_proposal_records",
    "save_proposal_decision",
]
