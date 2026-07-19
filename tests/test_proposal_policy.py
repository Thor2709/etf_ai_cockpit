from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

import etf_cockpit.portfolio.proposal_policy as proposal_policy

from etf_cockpit.portfolio.proposal_policy import (
    REQUIRED_GATES,
    GateEvidence,
    ProposalRequest,
    build_proposal_decision,
    load_proposal_records,
    save_proposal_decision,
)


@pytest.fixture(autouse=True)
def _authority_matrix(monkeypatch):
    capabilities = tuple(
        SimpleNamespace(capability_id=capability_id, authority_stage=stage, availability=availability)
        for capability_id, stage, availability in (
            ("strategy:paper_portfolio", "paper", "mandatory"),
            ("strategy:etf_trend_momentum", "shadow_proposal", "mandatory"),
            ("model:paper", "paper", "mandatory"),
            ("model:baseline", "research", "mandatory"),
            ("broker:paper_portfolio", "paper", "mandatory"),
            ("strategy:future_disabled", "disabled", "disabled"),
        )
    )
    result = SimpleNamespace(
        diagnostic_mode=False,
        diagnostics=(),
        checksum="a" * 64,
        policy=SimpleNamespace(capabilities=capabilities),
    )
    monkeypatch.setattr(proposal_policy, "load_authority_matrix", lambda: result)


def _request(**changes: object) -> ProposalRequest:
    gates = tuple(GateEvidence(gate_id, True, "passed") for gate_id in REQUIRED_GATES)
    values: dict[str, object] = {
        "instrument_id": "VWCE",
        "current_quantity": 10.0,
        "target_quantity": 12.0,
        "strategy_id": "strategy:paper_portfolio",
        "strategy_stage": "paper",
        "model_id": "model:paper",
        "model_stage": "paper",
        "account_id": "broker:paper_portfolio",
        "account_stage": "paper",
        "optimiser_output_id": "optimiser-run-1",
        "portfolio_revision": "portfolio-revision-1",
        "data_revision": "data-revision-1",
        "as_of": datetime(2026, 7, 19, 0, 0, tzinfo=timezone.utc),
        "expires_at": datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc),
        "authority_policy_checksum": "a" * 64,
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
    assert first.gate_policy_version == "2026-07-12"
    assert len(first.gate_policy_checksum) == 64
    assert {item.name for item in first.alternatives} == {"no_trade", "defer", "reduce", "manual_review"}
    assert all(item.gate_id in REQUIRED_GATES for item in first.gates)


def test_policy_resolves_registered_stage_and_rejects_caller_escalation() -> None:
    permitted = build_proposal_decision(
        _request(strategy_id="strategy:etf_trend_momentum", strategy_stage="shadow_proposal")
    )
    assert permitted.authority_stage == "shadow_proposal"
    assert permitted.proposal_allowed is True

    with pytest.raises(ValueError, match="stage mismatch"):
        build_proposal_decision(
            _request(strategy_id="strategy:etf_trend_momentum", strategy_stage="paper")
        )


def test_real_authority_matrix_is_typed_and_checksumed(monkeypatch) -> None:
    monkeypatch.undo()
    policy, checksum = proposal_policy._load_proposal_authority()

    capabilities = {item.capability_id: item for item in policy.capabilities}
    assert capabilities["strategy:etf_trend_momentum"].authority_stage == "shadow_proposal"
    assert capabilities["model:baseline"].authority_stage == "research"
    assert len(checksum) == 64


def test_stale_unknown_and_disabled_authority_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="checksum"):
        build_proposal_decision(_request(authority_policy_checksum="b" * 64))
    with pytest.raises(ValueError, match="not registered"):
        build_proposal_decision(_request(strategy_id="strategy:missing"))
    with pytest.raises(ValueError, match="disabled"):
        build_proposal_decision(
            _request(strategy_id="strategy:future_disabled", strategy_stage="disabled")
        )


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
    assert {item.gate_id for item in decision.gates if not item.passed} >= {
        "optimizer_output",
        "portfolio_state",
        "data_freshness",
    }
    assert decision.alternatives[-1].selected is True
    assert "required" in decision.rationale.casefold()


def test_failed_gate_and_lower_authority_stage_cannot_be_overridden() -> None:
    gates = tuple(
        GateEvidence(gate_id, gate_id != "liquidity", "liquidity unavailable" if gate_id == "liquidity" else "passed")
        for gate_id in REQUIRED_GATES
    )
    decision = build_proposal_decision(
        _request(
            strategy_id="strategy:etf_trend_momentum",
            strategy_stage="shadow_proposal",
            model_id="model:baseline",
            model_stage="research",
            gate_evidence=gates,
        )
    )

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


def test_conflicting_immutable_record_cannot_be_overwritten(tmp_path) -> None:
    decision = build_proposal_decision(_request())
    save_proposal_decision(decision, directory=tmp_path)
    conflicting = replace(decision, rationale="A materially different rationale.")

    with pytest.raises(ValueError, match="conflicts"):
        save_proposal_decision(conflicting, directory=tmp_path)


def test_loading_rejects_tampered_policy_metadata_and_input_material(tmp_path) -> None:
    decision = build_proposal_decision(_request())
    path = save_proposal_decision(decision, directory=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    payload["authority_policy_checksum"] = "b" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_proposal_records(directory=tmp_path) == ()

    payload["authority_policy_checksum"] = decision.authority_policy_checksum
    payload["input_material"]["target_quantity"] = 999.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_proposal_records(directory=tmp_path) == ()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("outcome", "manual_review"),
        ("proposal_allowed", False),
        ("quantity_delta", 99.0),
        ("rationale", "tampered rationale"),
        ("authority_stage", "research"),
        ("gates", []),
        ("alternatives", []),
    ),
)
def test_loading_rejects_tampered_derived_decision_fields(tmp_path, field, value) -> None:
    decision = build_proposal_decision(_request())
    path = save_proposal_decision(decision, directory=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_proposal_records(directory=tmp_path) == ()
