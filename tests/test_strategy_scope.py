from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etf_cockpit.governance.models import StrategyScopeEntry
from etf_cockpit.governance.product_scope import (
    DEFAULT_POLICY_PATHS,
    load_strategy_scope,
)


def write_yaml(root: Path, payload: object) -> Path:
    path = root / "strategy_scope.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
    with pytest.raises(ValidationError, match="score_authority"):
        StrategyScopeEntry(lifecycle="experimental", score_authority=True)


def test_rejected_strategy_cannot_have_any_authority() -> None:
    with pytest.raises(ValidationError, match="authority"):
        StrategyScopeEntry(
            strategy_id="martingale",
            lifecycle="rejected",
            score_authority=False,
            research_promotion_allowed=True,
        )


def test_default_strategy_scope_contains_supported_and_rejected_families() -> None:
    result = load_strategy_scope(DEFAULT_POLICY_PATHS.strategy_scope)

    assert result.diagnostic_mode is False
    assert result.policy is not None
    by_id = {entry.strategy_id: entry for entry in result.policy.entries}
    assert by_id["etf_trend_momentum"].lifecycle == "supported"
    assert by_id["pair_trading"].lifecycle == "research_only"
    assert by_id["martingale"].lifecycle == "rejected"
    assert by_id["llm_only_management"].score_authority is False
    assert all(entry.execution_allowed is False for entry in result.policy.entries)


def test_invalid_strategy_scope_fails_closed(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        {
            "schema_version": "1.0",
            "policy_id": "strategies",
            "policy_version": "1",
            "execution_allowed": False,
            "strategies": [{"strategy_id": "bad", "lifecycle": "experimental", "score_authority": True}],
        },
    )

    with pytest.raises(ValidationError, match="score_authority"):
        load_strategy_scope(path)


def test_missing_strategy_scope_fails_closed(tmp_path: Path) -> None:
    result = load_strategy_scope(tmp_path / "missing.yaml")

    assert result.diagnostic_mode is True
    assert result.research_state == "manual_review"
    assert result.score_state == "not_scoreable"
    assert result.execution_allowed is False
