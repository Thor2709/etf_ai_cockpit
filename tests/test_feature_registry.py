from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etf_cockpit.app.router import PAGES
from etf_cockpit.governance.models import FeatureRegistryEntry
from etf_cockpit.governance.product_scope import (
    DEFAULT_POLICY_PATHS,
    load_feature_registry,
)


def write_yaml(root: Path, payload: object) -> Path:
    path = root / "feature_registry.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_feature_registry_covers_every_production_route() -> None:
    result = load_feature_registry(DEFAULT_POLICY_PATHS.feature_registry)

    assert result.diagnostic_mode is False
    assert result.policy is not None
    entries = result.policy.entries
    assert len({entry.feature_id for entry in entries}) == len(entries)
    assert len({entry.route for entry in entries}) == len(entries)
    assert set(PAGES).issubset({entry.route for entry in entries})
    assert all(entry.visible is True for entry in entries)
    assert all(entry.execution_allowed is False for entry in entries)


def test_stock_research_registry_exposes_growth_expectations_contract() -> None:
    result = load_feature_registry(DEFAULT_POLICY_PATHS.feature_registry)

    assert result.policy is not None
    stock_research = next(entry for entry in result.policy.entries if entry.feature_id == "stock_research")
    assert "ISSUE-0095" in stock_research.issue_ids
    assert {"reported_growth", "official_guidance_import", "licensed_consensus_import"} <= set(stock_research.data_dependencies)
    assert stock_research.authority == "evidence_only"
    assert stock_research.execution_allowed is False


def test_hardware_profiles_are_exposed_by_onboarding_and_jobs() -> None:
    result = load_feature_registry(DEFAULT_POLICY_PATHS.feature_registry)

    assert result.policy is not None
    entries = {entry.feature_id: entry for entry in result.policy.entries}
    assert "ISSUE-0151" in entries["onboarding"].issue_ids
    assert "ISSUE-0151" in entries["jobs"].issue_ids
    assert "resource_profiles" in entries["jobs"].data_dependencies
    assert entries["jobs"].lifecycle == "supported_with_limitations"
    assert entries["jobs"].execution_allowed is False


def test_feature_registry_rejects_duplicate_routes(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        {
            "schema_version": "1.0",
            "policy_id": "features",
            "policy_version": "1",
            "execution_allowed": False,
            "features": [
                {"feature_id": "one", "route": "/", "lifecycle": "supported"},
                {"feature_id": "two", "route": "/", "lifecycle": "supported"},
            ],
        },
    )

    with pytest.raises(ValidationError, match="route"):
        load_feature_registry(path)


def test_invalid_feature_registry_fails_closed(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, {"features": [{"feature_id": "missing-route"}]})

    result = load_feature_registry(path)

    assert result.diagnostic_mode is True
    assert result.policy is None
    assert result.research_state == "manual_review"
    assert result.score_state == "not_scoreable"
    assert result.research_promotion_allowed is False
    assert result.portfolio_review_allowed is False
    assert result.execution_allowed is False


def test_experimental_feature_cannot_gain_positive_score_authority() -> None:
    with pytest.raises(ValidationError, match="positive authority"):
        FeatureRegistryEntry(
            feature_id="experimental",
            route="/experimental",
            lifecycle="experimental",
            score_authority=True,
        )
