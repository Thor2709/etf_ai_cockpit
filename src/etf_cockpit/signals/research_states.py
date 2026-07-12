"""Typed public research state and internal analytical-intent contracts.

The historical signal pipeline still has callers that pass the v1 ``action``
strings.  Those strings are deliberately kept at compatibility boundaries;
the models and helpers in this module are the release-facing vocabulary.  A
state never implies an executable order and every public authority contract
keeps ``execution_allowed`` fixed to ``False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


class ResearchState(StrEnum):
    """Public, instrument-level research lifecycle state."""

    RESEARCH_CANDIDATE = "research_candidate"
    WATCHLIST = "watchlist"
    HOLD_REVIEW = "hold_review"
    AVOID = "avoid"
    NEEDS_EVIDENCE = "needs_evidence"
    MANUAL_REVIEW = "manual_review"
    NOT_SCOREABLE = "not_scoreable"


class PortfolioReviewState(StrEnum):
    """Portfolio context is separate from instrument research state."""

    NOT_APPLICABLE = "not_applicable"
    MAINTAIN_REVIEW = "maintain_review"
    INCREASE_EXPOSURE_REVIEW = "increase_exposure_review"
    REDUCE_EXPOSURE_REVIEW = "reduce_exposure_review"
    EXIT_THESIS_REVIEW = "exit_thesis_review"
    CONSTRAINTS_BLOCKED = "constraints_blocked"


class InternalSignalIntent(StrEnum):
    """Analytical/backtest intent; never a public authority state."""

    INCREASE = "increase"
    MAINTAIN = "maintain"
    DECREASE = "decrease"
    EXIT = "exit"
    NONE = "none"


class GateSeverity(StrEnum):
    BLOCKER = "blocker"
    AUTHORITY_WARNING = "authority_warning"
    NOTICE = "notice"


AnalysisStatus = Literal["complete", "partial", "unavailable"]
MigrationSemantics = Literal["lossless", "lossy"]


@dataclass(frozen=True)
class ScoreComponent:
    """Small adapter accepted by :func:`resolve_research_state`.

    Existing ``SimpleScoreComponent`` instances are intentionally accepted by
    duck typing, so this type is useful for focused governance tests without
    coupling the governance module to the scoring implementation.
    """

    key: str
    status: str = "ok"
    score: float | None = None
    authority: str = "evidence"
    source_id: str | None = None


class GateResult(BaseModel):
    """Typed gate evidence used by the migration/research-state adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    gate_id: str = Field(min_length=1)
    severity: GateSeverity = GateSeverity.NOTICE
    passed: bool = True
    message: str = ""


class AuthorityDecision(BaseModel):
    """A conservative decision envelope consumed by state adapters.

    Task 3 owns the central gate resolver.  Task 2 only needs a typed seam, so
    defaults intentionally remain diagnostic and non-promoting.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    analysis_status: AnalysisStatus = "unavailable"
    research_state: ResearchState = ResearchState.MANUAL_REVIEW
    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    execution_allowed: Literal[False] = False
    gates: tuple[GateResult, ...] = ()


# Compatibility import values are deliberately kept out of all public enums.
LEGACY_ACTION_TO_RESEARCH_STATE: Mapping[str, ResearchState] = {
    "buy": ResearchState.RESEARCH_CANDIDATE,
    "add": ResearchState.RESEARCH_CANDIDATE,
    "add_candidate": ResearchState.RESEARCH_CANDIDATE,
    "hold": ResearchState.HOLD_REVIEW,
    "trim": ResearchState.HOLD_REVIEW,
    "trim_candidate": ResearchState.HOLD_REVIEW,
    "sell": ResearchState.AVOID,
    "no_trade": ResearchState.NEEDS_EVIDENCE,
    "manual_review": ResearchState.MANUAL_REVIEW,
}

LEGACY_ACTION_TO_INTENT: Mapping[str, InternalSignalIntent] = {
    "buy": InternalSignalIntent.INCREASE,
    "add": InternalSignalIntent.INCREASE,
    "add_candidate": InternalSignalIntent.INCREASE,
    "hold": InternalSignalIntent.MAINTAIN,
    "trim": InternalSignalIntent.DECREASE,
    "trim_candidate": InternalSignalIntent.DECREASE,
    "sell": InternalSignalIntent.EXIT,
    "no_trade": InternalSignalIntent.NONE,
    "manual_review": InternalSignalIntent.NONE,
}


def normalise_legacy_action(value: object) -> str | None:
    """Return a stable text representation while preserving missing values."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def research_state_for_legacy_action(value: object) -> ResearchState:
    """Map a v1 action to a safe public state, failing closed on unknown text."""

    action = normalise_legacy_action(value)
    return LEGACY_ACTION_TO_RESEARCH_STATE.get(
        action.casefold() if action is not None else "",
        ResearchState.MANUAL_REVIEW,
    )


def internal_intent_for_legacy_action(value: object) -> InternalSignalIntent:
    action = normalise_legacy_action(value)
    return LEGACY_ACTION_TO_INTENT.get(
        action.casefold() if action is not None else "",
        InternalSignalIntent.NONE,
    )


def _component_status(component: object) -> str:
    return str(getattr(component, "status", "") or "").strip().casefold()


def _component_score(component: object) -> float | None:
    value = getattr(component, "score", None)
    if value is None:
        value = getattr(component, "score_10", None)
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def resolve_research_state(
    components: Sequence[ScoreComponent | object],
    decision: AuthorityDecision,
) -> ResearchState:
    """Resolve a public state without allowing unavailable evidence to promote it.

    This is deliberately a narrow adapter, not Task 3's gate resolver.  The
    decision's already-resolved non-positive state is retained; a positive
    candidate requires complete analysis and at least one usable non-model
    component.  Blockers or malformed evidence always fail closed.
    """

    try:
        typed_decision = decision if isinstance(decision, AuthorityDecision) else AuthorityDecision.model_validate(decision)
    except Exception:
        return ResearchState.MANUAL_REVIEW

    states = {item.value for item in ResearchState}
    if typed_decision.research_state.value not in states:
        return ResearchState.MANUAL_REVIEW

    if typed_decision.analysis_status == "unavailable":
        return ResearchState.NOT_SCOREABLE

    if any(
        _component_status(component)
        in {"blocked", "blocker", "failed", "unavailable", "invalid", "n/a", "na"}
        for component in components
    ):
        return ResearchState.NOT_SCOREABLE

    usable = [
        component
        for component in components
        if _component_score(component) is not None
        and str(getattr(component, "source_id", "") or "").split(":", 1)[0].casefold() != "model"
    ]
    if typed_decision.research_state is ResearchState.RESEARCH_CANDIDATE and not usable:
        return ResearchState.NOT_SCOREABLE

    # An authority warning may downgrade positive promotion but does not need
    # to invent a new state.  The central resolver in Task 3 owns that policy.
    return typed_decision.research_state


def public_authority_payload(
    *,
    research_state: ResearchState | str,
    portfolio_review_state: PortfolioReviewState | str = PortfolioReviewState.NOT_APPLICABLE,
    analysis_status: AnalysisStatus = "unavailable",
    research_promotion_allowed: bool = False,
    portfolio_review_allowed: bool = False,
    legacy_action: object = None,
    migration_version: str = "2.0",
    gate_policy_version: str = "unavailable",
    gate_policy_checksum: str = "unavailable",
) -> dict[str, object]:
    """Build the release-facing v2 authority fields in deterministic order."""

    state = ResearchState(research_state)
    portfolio_state = PortfolioReviewState(portfolio_review_state)
    return {
        "research_state": state.value,
        "portfolio_review_state": portfolio_state.value,
        "analysis_status": analysis_status,
        "research_promotion_allowed": bool(research_promotion_allowed),
        "portfolio_review_allowed": bool(portfolio_review_allowed),
        "execution_allowed": False,
        "legacy_action": normalise_legacy_action(legacy_action),
        "migration_version": str(migration_version),
        "gate_policy_version": str(gate_policy_version),
        "gate_policy_checksum": str(gate_policy_checksum),
        "schema_version": "2.0",
    }


__all__ = [
    "AnalysisStatus",
    "AuthorityDecision",
    "GateResult",
    "GateSeverity",
    "InternalSignalIntent",
    "LEGACY_ACTION_TO_INTENT",
    "LEGACY_ACTION_TO_RESEARCH_STATE",
    "PortfolioReviewState",
    "ResearchState",
    "ScoreComponent",
    "internal_intent_for_legacy_action",
    "normalise_legacy_action",
    "public_authority_payload",
    "research_state_for_legacy_action",
    "resolve_research_state",
]
