"""Central, deterministic authority resolution for the release paths.

Gate results are evidence, not executable instructions.  This module applies
the ordered local gate policy, keeps blocker decisions monotonic and returns
the typed v2 authority envelope used by compatibility and export callers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from string import hexdigits
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.signals.research_states import (
    AuthorityDecision,
    GateResult,
    GateSeverity,
    PortfolioReviewState,
    ResearchState,
)


class PortfolioContext(BaseModel):
    """Validated portfolio snapshot context for a separate review dimension."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    validated: StrictBool = False
    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
    as_of_date: date | None = None
    holdings_checksum: str = "unavailable"

    @property
    def usable(self) -> bool:
        checksum = self.holdings_checksum
        has_checksum = len(checksum) == 64 and all(character in hexdigits for character in checksum)
        return bool(
            self.validated
            and self.portfolio_review_state is not PortfolioReviewState.NOT_APPLICABLE
            and self.as_of_date is not None
            and has_checksum
        )


_UNAVAILABLE = "unavailable"


def _diagnostic_decision(message: str) -> AuthorityDecision:
    gate = GateResult(
        gate_id="policy",
        order=0,
        severity=GateSeverity.BLOCKER,
        passed=False,
        message=message,
        gate_policy_version=_UNAVAILABLE,
        gate_policy_checksum=_UNAVAILABLE,
    )
    return AuthorityDecision(
        analysis_status="unavailable",
        research_state=ResearchState.MANUAL_REVIEW,
        portfolio_review_state=PortfolioReviewState.NOT_APPLICABLE,
        research_promotion_allowed=False,
        portfolio_review_allowed=False,
        execution_allowed=False,
        gates=(gate,),
        gate_policy_version=_UNAVAILABLE,
        gate_policy_checksum=_UNAVAILABLE,
        diagnostics=(message,),
    )


def _coerce_gate(raw: GateResult | Mapping[str, object]) -> GateResult:
    if isinstance(raw, GateResult):
        return raw
    if not isinstance(raw, Mapping):
        raise TypeError("gate result must be a GateResult or mapping")
    # Do not allow pydantic's permissive bool coercion to turn malformed gate
    # evidence into a passing result.
    if "passed" in raw and not isinstance(raw["passed"], bool):
        raise TypeError("gate passed must be a boolean")
    return GateResult.model_validate(raw)


def _coerce_context(raw: PortfolioContext | Mapping[str, object] | None) -> PortfolioContext | None:
    if raw is None:
        return None
    if isinstance(raw, PortfolioContext):
        return raw
    if not isinstance(raw, Mapping):
        raise TypeError("portfolio context must be a PortfolioContext or mapping")
    return PortfolioContext.model_validate(raw)


def _policy_metadata() -> tuple[object, str, str]:
    result = load_gate_policy()
    if result.diagnostic_mode or result.policy is None:
        raise ValueError("; ".join(result.diagnostics) or "gate policy unavailable")
    policy = result.policy
    version = str(policy.policy_version or _UNAVAILABLE)
    checksum = str(result.checksum or policy.checksum or _UNAVAILABLE)
    if version == _UNAVAILABLE or len(checksum) != 64:
        raise ValueError("gate policy metadata unavailable")
    return policy, version, checksum


def resolve_authority(
    base_state: ResearchState,
    gates: Sequence[GateResult | Mapping[str, object]],
    portfolio_context: PortfolioContext | Mapping[str, object] | None,
) -> AuthorityDecision:
    """Resolve research and portfolio authority with fail-closed precedence.

    Gate evidence is normalised into policy order.  A failed blocker is
    monotonic, failed authority warnings downgrade positive research authority,
    and notices remain visible without increasing authority.  No branch can
    ever grant execution authority.
    """

    try:
        typed_state = base_state if isinstance(base_state, ResearchState) else ResearchState(base_state)
        policy, policy_version, policy_checksum = _policy_metadata()
        typed_gates = [_coerce_gate(raw) for raw in gates]
        if not typed_gates:
            raise ValueError("gate results unavailable")
        policy_entries = {entry.gate_id: entry for entry in policy.gates}
        seen: set[str] = set()
        normalised: list[GateResult] = []
        for gate in typed_gates:
            if gate.gate_id not in policy_entries:
                raise ValueError(f"unsupported gate id: {gate.gate_id}")
            if gate.gate_id in seen:
                raise ValueError(f"duplicate gate id: {gate.gate_id}")
            seen.add(gate.gate_id)
            policy_entry = policy_entries[gate.gate_id]
            normalised.append(
                gate.model_copy(
                    update={
                        "order": policy_entry.order,
                        "severity": policy_entry.severity,
                        "gate_policy_version": policy_version,
                        "gate_policy_checksum": policy_checksum,
                    }
                )
            )
        missing_gate_ids = sorted(set(policy_entries) - seen)
        if missing_gate_ids:
            raise ValueError(f"gate results incomplete; missing: {', '.join(missing_gate_ids)}")
        ordered_gates = tuple(sorted(normalised, key=lambda gate: (gate.order, gate.gate_id)))
        context = _coerce_context(portfolio_context)
    except (TypeError, ValueError, ValidationError) as exc:
        return _diagnostic_decision(str(exc) or "authority input unavailable")

    failed_blocker = any(not gate.passed and gate.severity is GateSeverity.BLOCKER for gate in ordered_gates)
    failed_warning = any(not gate.passed and gate.severity is GateSeverity.AUTHORITY_WARNING for gate in ordered_gates)

    research_state = typed_state
    if failed_blocker:
        research_state = ResearchState.NOT_SCOREABLE
    elif failed_warning and typed_state is ResearchState.RESEARCH_CANDIDATE:
        research_state = ResearchState.MANUAL_REVIEW

    research_promotion_allowed = (
        typed_state is ResearchState.RESEARCH_CANDIDATE
        and research_state is ResearchState.RESEARCH_CANDIDATE
        and not failed_blocker
        and not failed_warning
    )

    portfolio_state = (
        context.portfolio_review_state
        if context is not None and context.usable
        else PortfolioReviewState.NOT_APPLICABLE
    )
    portfolio_review_allowed = bool(
        context is not None
        and context.usable
        and not failed_blocker
        and not failed_warning
    )
    analysis_status: Literal["complete", "partial", "unavailable"] = "partial" if (failed_blocker or failed_warning) else "complete"

    return AuthorityDecision(
        analysis_status=analysis_status,
        research_state=research_state,
        portfolio_review_state=portfolio_state,
        research_promotion_allowed=research_promotion_allowed,
        portfolio_review_allowed=portfolio_review_allowed,
        execution_allowed=False,
        gates=ordered_gates,
        gate_policy_version=policy_version,
        gate_policy_checksum=policy_checksum,
        diagnostics=(),
    )


__all__ = ["PortfolioContext", "resolve_authority"]
