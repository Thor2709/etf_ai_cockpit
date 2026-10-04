"""Research-state vocabulary for signal callers.

The shared contracts live in :mod:`etf_cockpit.core.research_states` so core and
governance can use them without importing the signals domain (ADR-0002).
"""

from __future__ import annotations

from etf_cockpit.core.research_states import (
    ALLOWED_EVIDENCE_SOURCE_IDS,
    AnalysisStatus,
    AuthorityDecision,
    GateResult,
    GateSeverity,
    internal_intent_for_legacy_action,
    InternalSignalIntent,
    LEGACY_ACTION_TO_INTENT,
    LEGACY_ACTION_TO_RESEARCH_STATE,
    MigrationSemantics,
    normalise_analysis_status,
    normalise_legacy_action,
    PortfolioReviewState,
    public_authority_payload,
    research_state_for_legacy_action,
    ResearchState,
    resolve_research_state,
    ScoreComponent,
)

__all__ = [
    "AnalysisStatus",
    "ALLOWED_EVIDENCE_SOURCE_IDS",
    "AuthorityDecision",
    "GateResult",
    "GateSeverity",
    "InternalSignalIntent",
    "LEGACY_ACTION_TO_INTENT",
    "LEGACY_ACTION_TO_RESEARCH_STATE",
    "MigrationSemantics",
    "PortfolioReviewState",
    "ResearchState",
    "ScoreComponent",
    "internal_intent_for_legacy_action",
    "normalise_legacy_action",
    "normalise_analysis_status",
    "public_authority_payload",
    "research_state_for_legacy_action",
    "resolve_research_state",
]
