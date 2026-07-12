from __future__ import annotations

from datetime import date

import pytest

from etf_cockpit.core.types import DataQualityIssue, DataQualityReport
from etf_cockpit.governance.gate_policy import PortfolioContext, resolve_authority
from etf_cockpit.signals.research_states import GateResult, GateSeverity, ResearchState


def _gate(gate_id: str, *, passed: bool = True, severity: GateSeverity = GateSeverity.NOTICE) -> GateResult:
    return GateResult(gate_id=gate_id, passed=passed, severity=severity)


def test_failed_blocker_cannot_be_erased_by_later_pass() -> None:
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        [_gate("signal"), _gate("identity", passed=False, severity=GateSeverity.BLOCKER)],
        None,
    )

    assert decision.research_state is ResearchState.NOT_SCOREABLE
    assert decision.research_promotion_allowed is False
    assert decision.portfolio_review_allowed is False
    assert decision.execution_allowed is False
    assert [gate.gate_id for gate in decision.gates] == ["identity", "signal"]


def test_authority_warning_downgrades_positive_state_and_remains_visible() -> None:
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        [_gate("signal"), _gate("valuation", passed=False, severity=GateSeverity.AUTHORITY_WARNING)],
        None,
    )

    assert decision.research_state is ResearchState.MANUAL_REVIEW
    assert decision.research_promotion_allowed is False
    assert any(gate.gate_id == "valuation" and not gate.passed for gate in decision.gates)
    assert decision.analysis_status == "partial"


def test_notice_stays_visible_without_downgrading_positive_state() -> None:
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        [_gate("signal"), _gate("cost", passed=False, severity=GateSeverity.NOTICE)],
        None,
    )

    assert decision.research_state is ResearchState.RESEARCH_CANDIDATE
    assert decision.research_promotion_allowed is True
    assert decision.analysis_status == "complete"
    assert decision.gates[-1].gate_id == "cost"


def test_validated_portfolio_context_is_separate_from_research_state() -> None:
    context = PortfolioContext(
        validated=True,
        portfolio_review_state="reduce_exposure_review",
        as_of_date=date(2026, 7, 12),
        holdings_checksum="a" * 64,
    )
    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, [_gate("identity")], context)

    assert decision.research_state is ResearchState.RESEARCH_CANDIDATE
    assert decision.research_promotion_allowed is True
    assert decision.portfolio_review_state.value == "reduce_exposure_review"
    assert decision.portfolio_review_allowed is True
    assert decision.execution_allowed is False


def test_unvalidated_portfolio_context_cannot_grant_review() -> None:
    context = PortfolioContext(validated=False, portfolio_review_state="increase_exposure_review")
    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, [_gate("identity")], context)

    assert decision.portfolio_review_state.value == "not_applicable"
    assert decision.portfolio_review_allowed is False


def test_malformed_gate_input_fails_closed_with_unavailable_metadata() -> None:
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        [{"gate_id": "identity", "severity": "unsupported", "passed": True}],  # type: ignore[list-item]
        None,
    )

    assert decision.research_state is ResearchState.MANUAL_REVIEW
    assert decision.analysis_status == "unavailable"
    assert decision.research_promotion_allowed is False
    assert decision.portfolio_review_allowed is False
    assert decision.gate_policy_version == "unavailable"
    assert decision.gate_policy_checksum == "unavailable"
    assert decision.diagnostics


def test_authority_decision_carries_policy_metadata_and_is_deterministic() -> None:
    gates = [_gate("cost"), _gate("identity"), _gate("valuation")]
    first = resolve_authority(ResearchState.RESEARCH_CANDIDATE, gates, None)
    second = resolve_authority(ResearchState.RESEARCH_CANDIDATE, list(reversed(gates)), None)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.gate_policy_version != "unavailable"
    assert len(first.gate_policy_checksum) == 64
    assert all(gate.gate_policy_version == first.gate_policy_version for gate in first.gates)
    assert all(len(gate.gate_policy_checksum) == 64 for gate in first.gates)


def test_unknown_gate_id_fails_closed() -> None:
    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, [_gate("future_gate")], None)

    assert decision.research_state is ResearchState.MANUAL_REVIEW
    assert decision.analysis_status == "unavailable"
    assert decision.execution_allowed is False


def test_deprecated_trading_allowed_warns_and_always_returns_false() -> None:
    report = DataQualityReport(
        as_of_date=date(2026, 7, 12),
        issues=[DataQualityIssue("ALL", "block", "data_quality", "blocked")],
    )

    with pytest.deprecated_call():
        assert report.trading_allowed is False
