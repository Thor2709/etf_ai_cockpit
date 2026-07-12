from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etf_cockpit.governance.models import GatePolicyEntry
from etf_cockpit.governance.product_scope import (
    DEFAULT_POLICY_PATHS,
    load_gate_policy,
)


def write_yaml(root: Path, payload: object) -> Path:
    path = root / "gate_policy.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_default_gate_policy_is_ordered_and_fail_closed() -> None:
    result = load_gate_policy(DEFAULT_POLICY_PATHS.gate_policy)

    assert result.diagnostic_mode is False
    assert result.policy is not None
    names = [gate.gate_id for gate in result.policy.gates]
    assert names == [
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
    assert all(gate.execution_allowed is False for gate in result.policy.gates)
    assert result.policy.execution_allowed is False
    assert {gate.severity for gate in result.policy.gates} == {"blocker", "authority_warning"}


def test_blocking_gate_cannot_allow_research_promotion() -> None:
    with pytest.raises(ValidationError, match="research_promotion_allowed"):
        GatePolicyEntry(
            gate_id="identity",
            order=1,
            severity="blocker",
            research_promotion_allowed=True,
            portfolio_review_allowed=False,
        )


def test_gate_policy_rejects_duplicate_order(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        {
            "schema_version": "1.0",
            "policy_id": "gates",
            "policy_version": "1",
            "execution_allowed": False,
            "gates": [
                {"gate_id": "first", "order": 1, "severity": "blocker"},
                {"gate_id": "second", "order": 1, "severity": "notice"},
            ],
        },
    )

    with pytest.raises(ValidationError, match="order"):
        load_gate_policy(path)


def test_invalid_gate_policy_fails_closed(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, {"gates": [{"gate_id": "unknown", "severity": "bad"}]})

    result = load_gate_policy(path)

    assert result.diagnostic_mode is True
    assert result.policy is None
    assert result.research_state == "manual_review"
    assert result.score_state == "not_scoreable"
    assert result.research_promotion_allowed is False
    assert result.portfolio_review_allowed is False
    assert result.execution_allowed is False
