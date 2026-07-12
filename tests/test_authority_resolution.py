from __future__ import annotations

from datetime import date

import pytest

from etf_cockpit.core.types import DataQualityIssue, DataQualityReport
from etf_cockpit.governance.gate_policy import PortfolioContext, resolve_authority
from etf_cockpit.signals.signal_pipeline import _attach_authority
from etf_cockpit.signals.research_states import GateResult, GateSeverity, PortfolioReviewState, ResearchState
from etf_cockpit.core.types import ComponentScores, SignalResult


def _gate(gate_id: str, *, passed: bool = True, severity: GateSeverity = GateSeverity.NOTICE) -> GateResult:
    return GateResult(gate_id=gate_id, passed=passed, severity=severity)


_POLICY_SEVERITIES = {
    "identity": GateSeverity.BLOCKER,
    "data_quality": GateSeverity.BLOCKER,
    "evidence": GateSeverity.BLOCKER,
    "model_validity": GateSeverity.BLOCKER,
    "risk": GateSeverity.BLOCKER,
    "valuation": GateSeverity.AUTHORITY_WARNING,
    "signal": GateSeverity.AUTHORITY_WARNING,
    "portfolio_fit": GateSeverity.AUTHORITY_WARNING,
    "cost": GateSeverity.AUTHORITY_WARNING,
}


def _complete_gates() -> list[GateResult]:
    return [_gate(gate_id, severity=severity) for gate_id, severity in _POLICY_SEVERITIES.items()]


def test_failed_blocker_cannot_be_erased_by_later_pass() -> None:
    gates = _complete_gates()
    gates[0] = _gate("identity", passed=False, severity=GateSeverity.BLOCKER)
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        gates,
        None,
    )

    assert decision.research_state is ResearchState.NOT_SCOREABLE
    assert decision.research_promotion_allowed is False
    assert decision.portfolio_review_allowed is False
    assert decision.execution_allowed is False
    assert decision.gates[0].gate_id == "identity"
    assert decision.gates[0].passed is False


def test_authority_warning_downgrades_positive_state_and_remains_visible() -> None:
    gates = _complete_gates()
    gates[5] = _gate("valuation", passed=False, severity=GateSeverity.AUTHORITY_WARNING)
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        gates,
        None,
    )

    assert decision.research_state is ResearchState.MANUAL_REVIEW
    assert decision.research_promotion_allowed is False
    assert any(gate.gate_id == "valuation" and not gate.passed for gate in decision.gates)
    assert decision.analysis_status == "partial"


def test_policy_warning_stays_visible_and_downgrades_positive_state() -> None:
    gates = _complete_gates()
    gates[-1] = _gate("cost", passed=False, severity=GateSeverity.NOTICE)
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        gates,
        None,
    )

    assert decision.research_state is ResearchState.MANUAL_REVIEW
    assert decision.research_promotion_allowed is False
    assert decision.analysis_status == "partial"
    assert decision.gates[-1].severity is GateSeverity.AUTHORITY_WARNING
    assert decision.gates[-1].passed is False


def test_validated_portfolio_context_is_separate_from_research_state() -> None:
    context = PortfolioContext(
        validated=True,
        portfolio_review_state="reduce_exposure_review",
        as_of_date=date(2026, 7, 12),
        holdings_checksum="a" * 64,
    )
    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, _complete_gates(), context)

    assert decision.research_state is ResearchState.RESEARCH_CANDIDATE
    assert decision.research_promotion_allowed is True
    assert decision.portfolio_review_state.value == "reduce_exposure_review"
    assert decision.portfolio_review_allowed is True
    assert decision.execution_allowed is False


def test_unvalidated_portfolio_context_cannot_grant_review() -> None:
    context = PortfolioContext(validated=False, portfolio_review_state="increase_exposure_review")
    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, _complete_gates(), context)

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
    gates = _complete_gates()
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


def test_policy_severity_is_authoritative_for_failed_identity() -> None:
    gates = _complete_gates()
    gates[0] = _gate("identity", passed=False, severity=GateSeverity.NOTICE)

    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, gates, None)

    assert decision.research_state is ResearchState.NOT_SCOREABLE
    assert decision.research_promotion_allowed is False
    assert decision.gates[0].severity is GateSeverity.BLOCKER


def test_partial_gate_set_fails_closed_before_promotion() -> None:
    decision = resolve_authority(
        ResearchState.RESEARCH_CANDIDATE,
        [_gate("cost", severity=GateSeverity.AUTHORITY_WARNING)],
        None,
    )

    assert decision.analysis_status == "unavailable"
    assert decision.research_state is ResearchState.MANUAL_REVIEW
    assert decision.research_promotion_allowed is False
    assert decision.diagnostics


def test_portfolio_context_without_date_or_checksum_cannot_grant_review() -> None:
    context = PortfolioContext(
        validated=True,
        portfolio_review_state="reduce_exposure_review",
        as_of_date=None,
        holdings_checksum="unavailable",
    )

    decision = resolve_authority(ResearchState.RESEARCH_CANDIDATE, _complete_gates(), context)

    assert decision.portfolio_review_state is PortfolioReviewState.NOT_APPLICABLE
    assert decision.portfolio_review_allowed is False


def test_production_signal_release_path_publishes_resolved_gate_table() -> None:
    signal = SignalResult(
        run_id="run-1",
        signal_date=date(2026, 7, 12),
        etf_id="ETF1",
        action="hold",
        confidence=0.7,
        total_score=0.4,
        components=ComponentScores(
            momentum=0.4,
            trend=0.3,
            risk=0.2,
            rebalance=0.1,
            relative_strength=0.2,
            toto=0.0,
            timesfm=0.0,
            baseline_ml=0.4,
            chatgpt_thesis=0.0,
            cost_penalty=0.0,
            turnover_penalty=0.0,
            concentration_penalty=0.0,
        ),
        blocked_by=[],
        warnings=[],
        reason_short="hold",
        reason_long="hold",
        horizon_primary="1-3 months",
        model_versions_used={"baseline": "momentum_shrunk_v1"},
    )
    report = DataQualityReport(as_of_date=date(2026, 7, 12), issues=[])

    resolved = _attach_authority(signal, report)
    payload = resolved.to_v2_dict()

    assert payload["gate_policy_version"] != "unavailable"
    assert len(payload["gates"]) == 9
    assert [gate["gate_id"] for gate in payload["gates"]] == [
        "identity",
        "data_quality",
        "evidence",
        "model_validity",
        "risk",
        "valuation",
        "signal",
        "portfolio_fit",
        "cost",
    ]
    assert payload["execution_allowed"] is False
