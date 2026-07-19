from __future__ import annotations

from datetime import datetime, timezone

from etf_cockpit.portfolio.proposal_policy import (
    REQUIRED_GATES,
    GateEvidence,
    ProposalRequest,
    build_proposal_decision,
    load_proposal_records,
    save_proposal_decision,
)


def _request(**changes: object) -> ProposalRequest:
    gates = tuple(GateEvidence(gate_id, True, "passed") for gate_id in REQUIRED_GATES)
    values: dict[str, object] = {
        "instrument_id": "VWCE",
        "current_quantity": 10.0,
        "target_quantity": 12.0,
        "strategy_id": "strategy:etf_trend_momentum",
        "strategy_stage": "paper",
        "model_id": "model:baseline",
        "model_stage": "paper",
        "account_id": "local-paper",
        "account_stage": "paper",
        "optimiser_output_id": "optimiser-run-1",
        "portfolio_revision": "portfolio-revision-1",
        "data_revision": "data-revision-1",
        "as_of": datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc),
        "expires_at": datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc),
        "authority_policy_checksum": "authority-checksum-1",
        "gate_evidence": gates,
        "rationale": "Target tracks the approved local optimiser output.",
    }
    values.update(changes)
    return ProposalRequest(**values)  # type: ignore[arg-type]


def test_complete_inputs_create_deterministic_non_executable_proposal() -> None:
    first = build_proposal_decision(_request())
    second = build_proposal_decision(_request())

    assert first == second
    assert first.outcome == "proposal_ready"
    assert first.proposal_allowed is True
    assert first.quantity_delta == 2.0
    assert first.authority_stage == "paper"
    assert first.execution_allowed is False
    assert {item.name for item in first.alternatives} == {"no_trade", "defer", "reduce", "manual_review"}
    assert all(item.gate_id in REQUIRED_GATES for item in first.gates)


def test_headline_or_score_only_input_is_manual_review_with_explicit_missing_gates() -> None:
    decision = build_proposal_decision(
        _request(
            optimiser_output_id=None,
            portfolio_revision=None,
            data_revision=None,
            gate_evidence=(),
        )
    )

    assert decision.outcome == "manual_review"
    assert decision.proposal_allowed is False
    assert decision.quantity_delta == 0.0
    assert all(not item.passed for item in decision.gates)
    assert decision.alternatives[-1].selected is True
    assert "required" in decision.rationale.casefold()


def test_failed_gate_and_lower_authority_stage_cannot_be_overridden() -> None:
    gates = tuple(
        GateEvidence(gate_id, gate_id != "liquidity", "liquidity unavailable" if gate_id == "liquidity" else "passed")
        for gate_id in REQUIRED_GATES
    )
    decision = build_proposal_decision(_request(gate_evidence=gates, account_stage="research"))

    assert decision.outcome == "manual_review"
    assert decision.authority_stage == "research"
    assert decision.proposal_allowed is False
    assert any(item.gate_id == "liquidity" and not item.passed for item in decision.gates)


def test_decision_persists_and_replays_schema_versioned_record(tmp_path) -> None:
    decision = build_proposal_decision(_request())
    path = save_proposal_decision(decision, directory=tmp_path)

    assert path.name == f"{decision.proposal_id}.json"
    records = load_proposal_records(directory=tmp_path)
    assert len(records) == 1
    assert records[0]["schema_version"] == "proposal.v1"
    assert records[0]["execution_allowed"] is False
    assert records[0]["input_checksum"] == decision.input_checksum
