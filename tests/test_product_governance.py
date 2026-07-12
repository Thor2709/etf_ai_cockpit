from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etf_cockpit.governance.models import ProductGovernancePolicy
from etf_cockpit.governance.product_scope import (
    DEFAULT_POLICY_PATHS,
    GovernanceLoadResult,
    load_product_governance,
)


def write_yaml(root: Path, payload: object) -> Path:
    path = root / "policy.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})

    with pytest.raises(ValidationError, match="order_transmission"):
        load_product_governance(path)


def test_product_policy_is_immutable_and_checksum_bearing() -> None:
    result = load_product_governance(DEFAULT_POLICY_PATHS.product)

    assert isinstance(result, GovernanceLoadResult)
    assert result.policy is not None
    assert result.schema_version == result.policy.schema_version == "1.0"
    assert result.checksum == result.policy.checksum
    assert result.checksum == hashlib.sha256(DEFAULT_POLICY_PATHS.product.read_bytes()).hexdigest()
    assert result.execution_allowed is False
    assert result.policy.product.canonical_name == "ETF AI Cockpit"
    assert result.policy.authority.maximum_operational_authority == "manual_research"
    assert result.policy.authority.broker_execution == "forbidden"
    with pytest.raises(ValidationError):
        result.policy.policy_version = "tampered"


def test_missing_product_policy_fails_closed_to_diagnostic_mode(tmp_path: Path) -> None:
    result = load_product_governance(tmp_path / "missing.yaml")

    assert result.diagnostic_mode is True
    assert result.policy is None
    assert result.research_state == "manual_review"
    assert result.score_state == "not_scoreable"
    assert result.research_promotion_allowed is False
    assert result.portfolio_review_allowed is False
    assert result.execution_allowed is False
    assert result.checksum == "unavailable"


def test_product_policy_rejects_any_positive_authority_flag(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        {
            "schema_version": "1.0",
            "policy_id": "test",
            "policy_version": "1",
            "authority": {
                "execution_allowed": True,
                "executable_authority": False,
                "order_transmission": False,
            },
        },
    )

    with pytest.raises(ValidationError, match="execution_allowed"):
        load_product_governance(path)


def test_product_model_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProductGovernancePolicy(
            schema_version="1.0",
            policy_id="test",
            policy_version="1",
            authority={
                "execution_allowed": False,
                "executable_authority": False,
                "order_transmission": False,
            },
            unexpected="not permitted",
        )
