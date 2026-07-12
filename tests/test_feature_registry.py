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
