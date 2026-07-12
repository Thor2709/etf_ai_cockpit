from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etf_cockpit.app.router import PAGES
from etf_cockpit.chatgpt_bridge import export_pack
from etf_cockpit.governance.models import (
    FeatureRegistryEntry,
    GatePolicyEntry,
    StrategyScopeEntry,
)
from etf_cockpit.governance.product_scope import (
    DEFAULT_POLICY_PATHS,
    load_feature_registry,
    load_gate_policy,
    load_glossary,
    load_product_governance,
    load_strategy_scope,
)


REQUIRED_GLOSSARY_TERMS = {
    "alpha",
    "beta",
    "drawdown",
    "calibration",
    "pbo",
    "dsr",
    "mase",
    "slippage",
    "edge-to-cost",
    "evidence authority",
    "freshness",
    "research state",
    "portfolio-review state",
    "blocker",
    "authority-warning",
    "notice",
    "volatility",
    "liquidity/spread proxy",
    "confidence interval/quantile",
    "walk-forward",
    "purging/embargo",
    "model promotion",
    "forecast-error measures",
    "n/a versus zero",
    "source conflict",
}

REQUIRED_STRATEGY_IDS = {
    "baseline_simple_scores",
    "timesfm_challenger",
    "toto_challenger",
    "future_ml_challenger",
    "llm_assistance",
    "provider_news_context",
    "paper_portfolio",
    "pair_trading",
    "triple_barrier_research",
    "future_broker_architecture",
    "martingale",
    "grid",
    "rl_agents",
    "llm_only_management",
    "model_only_trading",
    "return_screenshots",
    "unvalidated_sentiment",
}


def write_yaml(root: Path, payload: object, name: str = "policy.yaml") -> Path:
    path = root / name
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("loader", "section"),
    [
        (load_product_governance, "product"),
        (load_feature_registry, "entries"),
        (load_strategy_scope, "entries"),
        (load_gate_policy, "gates"),
        (load_glossary, "entries"),
    ],
)
def test_metadata_only_policy_fails_closed(tmp_path: Path, loader, section: str) -> None:
    path = write_yaml(
        tmp_path,
        {"schema_version": "1.0", "policy_id": "metadata-only", "policy_version": "1"},
    )

    result = loader(path)

    assert result.diagnostic_mode is True, section
    assert result.policy is None
    assert result.research_state == "manual_review"
    assert result.score_state == "not_scoreable"
    assert result.research_promotion_allowed is False
    assert result.portfolio_review_allowed is False


@pytest.mark.parametrize(
    ("loader", "payload"),
    [
        (load_product_governance, {"authority": {}}),
        (load_feature_registry, {"features": []}),
        (load_strategy_scope, {"strategies": []}),
        (load_gate_policy, {"gates": []}),
        (load_glossary, {"glossary": []}),
    ],
)
def test_empty_nested_policy_section_fails_closed(tmp_path: Path, loader, payload: dict[str, object]) -> None:
    payload = {
        "schema_version": "1.0",
        "policy_id": "incomplete",
        "policy_version": "1",
        **payload,
    }

    result = loader(write_yaml(tmp_path, payload))

    assert result.diagnostic_mode is True
    assert result.policy is None


def test_unknown_schema_version_fails_closed(tmp_path: Path) -> None:
    payload = yaml.safe_load(DEFAULT_POLICY_PATHS.product.read_text(encoding="utf-8"))
    payload["schema_version"] = "9.9"

    result = load_product_governance(write_yaml(tmp_path, payload))

    assert result.diagnostic_mode is True
    assert result.policy is None
    assert any("schema" in message.casefold() for message in result.diagnostics)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"lifecycle": "rejected", "paper_authority": True}, "paper_authority"),
        ({"lifecycle": "future_only", "paper_authority": True}, "paper_authority"),
        ({"lifecycle": "rejected", "authority": "research_state"}, "authority"),
        ({"lifecycle": "future_only", "portfolio_review_allowed": True}, "portfolio_review_allowed"),
        ({"lifecycle": "supported", "authority": "none", "score_authority": True}, "authority"),
    ],
)
def test_strategy_authority_and_lifecycle_mismatches_are_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        StrategyScopeEntry(strategy_id="mismatch", name="Mismatch", **kwargs)


def test_feature_authority_and_lifecycle_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="authority"):
        FeatureRegistryEntry(
            feature_id="mismatch",
            route="/mismatch",
            lifecycle="supported",
            authority="none",
            score_authority=True,
        )


@pytest.mark.parametrize("severity", ["blocker", "authority_warning", "notice"])
def test_no_gate_severity_can_grant_promotion_or_review(severity: str) -> None:
    with pytest.raises(ValidationError, match="research_promotion_allowed"):
        GatePolicyEntry(
            gate_id="unsafe",
            order=1,
            severity=severity,
            research_promotion_allowed=True,
        )


def test_feature_registry_has_complete_metadata_and_route_coverage() -> None:
    result = load_feature_registry(DEFAULT_POLICY_PATHS.feature_registry)
    assert result.policy is not None
    assert result.diagnostic_mode is False
    assert {route for entry in result.policy.entries for route in entry.routes} == set(PAGES)
    for entry in result.policy.entries:
        assert entry.name
        assert entry.category
        assert entry.routes
        assert entry.data_dependencies
        assert entry.issue_ids
        assert entry.tests
        assert entry.export_contracts
        assert entry.package_gate


def test_strategy_inventory_and_typed_metadata_are_complete() -> None:
    result = load_strategy_scope(DEFAULT_POLICY_PATHS.strategy_scope)
    assert result.policy is not None
    entries = {entry.strategy_id: entry for entry in result.policy.entries}
    assert REQUIRED_STRATEGY_IDS <= entries.keys()
    for entry in result.policy.entries:
        assert entry.intended_use
        assert entry.permitted_authority in {
            "evidence_only",
            "context_only",
            "research_state",
            "portfolio_review",
            "user_record",
            "none",
        }
        assert entry.execution_authority == "none"
        assert entry.limitations
        assert entry.linked_issues
        assert entry.promotion_conditions


def test_glossary_covers_required_governance_terms() -> None:
    result = load_glossary(DEFAULT_POLICY_PATHS.glossary)
    assert result.policy is not None
    terms = {entry.term.casefold() for entry in result.policy.entries}
    assert REQUIRED_GLOSSARY_TERMS <= terms


def test_policy_checksum_manifest_names_real_revision_with_all_policy_files() -> None:
    manifest_path = Path("evidence/governance/policy_checksums.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_commit = manifest["source_commit"]
    paths = set(
        subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", source_commit, "--", "configs"],
            text=True,
        ).splitlines()
    )
    for record in manifest["policies"].values():
        relative_path = record["path"]
        assert relative_path in paths
        content = subprocess.check_output(["git", "show", f"{source_commit}:{relative_path}"])
        assert hashlib.sha256(content).hexdigest() == record["sha256"]


def test_audit_manifest_includes_governance_checksums_version_and_diagnostic_marker(tmp_path: Path) -> None:
    export_pack._write_audit_manifest(tmp_path, {}, {})

    manifest = json.loads((tmp_path / "audit_manifest.json").read_text(encoding="utf-8"))
    required = {item["path"] for item in manifest["required"]}
    governance = manifest["governance"]
    assert "evidence_export/governance/policy_checksums.json" in required
    assert "evidence_export/governance/policy_checksums.json" in manifest["checksums"]
    assert governance["schema_version"] == "1.0"
    assert governance["diagnostic_mode"] is False
    assert len(governance["policy_checksums"]) == 5
    assert governance["diagnostic_marker"] == "governance_valid"
