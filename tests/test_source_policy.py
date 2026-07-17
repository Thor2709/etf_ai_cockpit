from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.data.source_policy import (
    MANDATORY_SOURCE_TIERS,
    SourcePolicy,
    SourcePolicyError,
    SourceTier,
    load_source_policies,
    source_policy_report,
)


def test_versioned_policy_declares_only_replayable_mandatory_source_tiers() -> None:
    policies = load_source_policies()

    assert policies
    assert {item.source_tier.value for item in policies if item.mandatory_allowed} <= MANDATORY_SOURCE_TIERS
    assert all(not item.network_required for item in policies if item.mandatory_allowed)
    assert all(item.quota_failure == "non_blocking" for item in policies)


def test_cache_status_is_local_and_never_performs_provider_io(tmp_path: Path) -> None:
    policy = SourcePolicy(
        provider_id="manual_local",
        dataset_type="local",
        source_tier=SourceTier.LOCAL_USER_IMPORT,
        mandatory_allowed=True,
        optional_provider=False,
        cache_path="cache",
        licence="user-owned",
        fair_use_note="local",
        network_required=False,
        quota_failure="non_blocking",
    )

    assert policy.cache_status(tmp_path) == "missing"
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "snapshot.json").write_text("{}\n", encoding="utf-8")
    assert policy.cache_status(tmp_path) == "available"
    assert policy.to_row(tmp_path)["network"] == "not required"


def test_source_policy_report_is_explicitly_no_network(tmp_path: Path) -> None:
    report = source_policy_report(tmp_path)

    assert report["schema_version"] == "data-source-policy.v1"
    assert report["status"] == "passed"
    assert report["network_calls"] is False
    assert report["rows"]


def test_mandatory_unofficial_source_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        "schema_version: data-source-policy.v1\n"
        "quota_failure: non_blocking\n"
        "sources:\n"
        "  - {provider_id: bad, dataset_type: prices, source_tier: best_effort_unofficial, mandatory_allowed: true, cache_path: data/raw, network_required: false}\n",
        encoding="utf-8",
    )

    with pytest.raises(SourcePolicyError):
        load_source_policies(path)
