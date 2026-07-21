from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etf_cockpit.governance.capability_scope import (
    CAPABILITY_STAGES,
    InstrumentDescriptor,
    resolve_instrument_capability,
    resolve_strategy_capability,
    strategy_capability_export,
)
from etf_cockpit.governance.models import StrategyScopePolicy
from etf_cockpit.governance.product_scope import DEFAULT_POLICY_PATHS, load_strategy_scope


def _policy() -> StrategyScopePolicy:
    result = load_strategy_scope(DEFAULT_POLICY_PATHS.strategy_scope)
    assert result.diagnostic_mode is False
    assert result.policy is not None
    return result.policy


def test_default_scope_is_a_complete_strategy_and_instrument_matrix() -> None:
    policy = _policy()

    assert policy.matrix_version == "2026-07-21"
    assert all(tuple(profile.cells) == CAPABILITY_STAGES for profile in policy.capability_profiles)
    assert all(entry.capability_profile for entry in policy.entries)
    assert all(entry.ui_visibility == "system_map" for entry in policy.entries)
    assert {
        "futures",
        "intraday",
        "options",
        "shorting",
        "event_driven_filings",
        "alternative_data",
    } <= {entry.strategy_id for entry in policy.entries}
    assert {
        "stock",
        "etf",
        "bond_etf",
        "ordinary_fund",
        "fixed_rate_bond",
        "zero_coupon_bond",
        "floating_rate_bond",
        "inflation_linked_bond",
        "callable_bond",
        "cash",
        "fx",
    } <= {rule.asset_family for rule in policy.instrument_rules}
    assert policy.exclusion_policy.policy_version == "2026-07-21"
    assert policy.execution_allowed is False
    with pytest.raises(TypeError):
        policy.capability_profiles[0].cells["analyse"] = policy.capability_profiles[0].cells["analyse"]
    with pytest.raises(TypeError):
        policy.profile_assignments["martingale"] = "portfolio_research"


@pytest.mark.parametrize(
    "strategy_id",
    ["martingale", "grid", "rl_agents", "llm_only_management", "model_only_trading", "unvalidated_sentiment", "futures", "options", "shorting"],
)
def test_rejected_strategy_profiles_cannot_gain_any_stage_authority(strategy_id: str) -> None:
    policy = _policy()

    for stage in CAPABILITY_STAGES:
        decision = resolve_strategy_capability(policy, strategy_id=strategy_id, stage=stage)
        assert decision.state == "rejected"
        assert decision.execution_allowed is False
        assert decision.reason_code.startswith("STRATEGY_REJECTED_")


def test_strategy_matrix_exposes_staged_authority_without_enabling_execution() -> None:
    policy = _policy()

    assert resolve_strategy_capability(policy, strategy_id="etf_trend_momentum", stage="analyse").state == "supported"
    assert resolve_strategy_capability(policy, strategy_id="etf_trend_momentum", stage="portfolio").state == "supported"
    for stage in ("draft_order", "canary", "bounded_automatic"):
        decision = resolve_strategy_capability(policy, strategy_id="etf_trend_momentum", stage=stage)
        assert decision.state == "unavailable"
        assert decision.execution_allowed is False
        assert "EXECUTION_DISABLED" in decision.reason_code


def test_instrument_resolver_is_explicit_long_only_and_horizon_aware() -> None:
    policy = _policy()
    stock = InstrumentDescriptor(
        asset_type="stock",
        security_type="ordinary_share",
        cfi_code="ESVUFR",
        exchange="XNAS",
        market_cap_usd=10_000_000_000,
        average_daily_value_usd=25_000_000,
    )

    decision = resolve_instrument_capability(policy, stock, stage="analyse", horizon="1M", risk_profile="very_aggressive")

    assert decision.asset_family == "stock"
    assert decision.state == "supported"
    assert decision.reason_code == "INSTRUMENT_STOCK_SUPPORTED"
    assert decision.allowed_actions == ("buy_add", "hold", "avoid_no_trade", "trim_sell", "manual_review")
    assert decision.execution_allowed is False
    assert resolve_instrument_capability(policy, stock, stage="analyse", horizon="1M", risk_profile="very_cautious") == decision


def test_instrument_resolver_rejects_unknown_and_provider_misclassification() -> None:
    policy = _policy()

    unknown = resolve_instrument_capability(
        policy,
        InstrumentDescriptor(asset_type="mystery", security_type="unknown", cfi_code="XXXXXX"),
        stage="analyse",
        horizon="1M",
    )
    leveraged = resolve_instrument_capability(
        policy,
        InstrumentDescriptor(asset_type="etf", security_type="ordinary_etf", leveraged=True),
        stage="analyse",
        horizon="1M",
    )
    conflicting = resolve_instrument_capability(
        policy,
        InstrumentDescriptor(asset_type="stock", security_type="ordinary_fund", cfi_code="CIXXXX"),
        stage="analyse",
        horizon="1M",
    )

    assert (unknown.state, unknown.reason_code) == ("rejected", "UNKNOWN_INSTRUMENT_CLASSIFICATION")
    assert (leveraged.state, leveraged.reason_code) == ("rejected", "EXCLUDED_LEVERAGED_PRODUCT")
    assert (conflicting.state, conflicting.reason_code) == ("rejected", "CONFLICTING_INSTRUMENT_CLASSIFICATION")
    assert not unknown.allowed_actions
    assert not leveraged.allowed_actions
    assert not conflicting.allowed_actions


def test_known_asset_with_unknown_cfi_or_missing_liquidity_fails_closed() -> None:
    policy = _policy()
    unknown_cfi = resolve_instrument_capability(
        policy,
        InstrumentDescriptor(
            asset_type="stock",
            security_type="ordinary_share",
            cfi_code="XXXXXX",
            market_cap_usd=10_000_000_000,
            average_daily_value_usd=25_000_000,
        ),
        stage="analyse",
        horizon="1M",
    )
    missing_liquidity = resolve_instrument_capability(
        policy,
        InstrumentDescriptor(asset_type="etf", security_type="ordinary_etf", cfi_code="CEQXXX"),
        stage="analyse",
        horizon="1M",
    )

    assert (unknown_cfi.state, unknown_cfi.reason_code) == ("rejected", "UNKNOWN_CFI_CLASSIFICATION")
    assert (missing_liquidity.state, missing_liquidity.reason_code) == ("unavailable", "LIQUIDITY_EVIDENCE_MISSING")


@pytest.mark.parametrize(
    "descriptor",
    [
        InstrumentDescriptor(asset_type="stock", market_cap_usd=10_000_000_000, average_daily_value_usd=25_000_000),
        InstrumentDescriptor(asset_type="stock", security_type="ordinary_share", market_cap_usd=10_000_000_000, average_daily_value_usd=25_000_000),
        InstrumentDescriptor(security_type="ordinary_share", cfi_code="ESVUFR", market_cap_usd=10_000_000_000, average_daily_value_usd=25_000_000),
    ],
)
def test_partial_classification_evidence_is_unavailable(descriptor: InstrumentDescriptor) -> None:
    decision = resolve_instrument_capability(_policy(), descriptor, stage="analyse", horizon="1M")

    assert (decision.state, decision.reason_code) == ("unavailable", "CLASSIFICATION_EVIDENCE_INCOMPLETE")
    assert decision.allowed_actions == ()
    assert decision.execution_allowed is False


def test_fund_dealing_frequency_can_make_one_week_horizon_unavailable() -> None:
    policy = _policy()
    fund = InstrumentDescriptor(asset_type="ordinary_fund", security_type="mutual_fund", cfi_code="CIXXXX", dealing_frequency="weekly")

    decision = resolve_instrument_capability(policy, fund, stage="analyse", horizon="1W")

    assert decision.state == "unavailable"
    assert decision.reason_code == "HORIZON_UNSUPPORTED_FOR_DEALING_FREQUENCY"
    assert decision.execution_allowed is False


def test_exclusion_thresholds_are_bounded_by_the_schema() -> None:
    payload = yaml.safe_load(DEFAULT_POLICY_PATHS.strategy_scope.read_text(encoding="utf-8"))
    payload["exclusion_policy"]["minimum_average_daily_value_usd"] = 1
    entries = payload.pop("strategies")
    for entry in entries:
        entry["capability_profile"] = payload["profile_assignments"][entry["strategy_id"]]

    with pytest.raises(ValidationError, match="minimum_average_daily_value_usd"):
        StrategyScopePolicy.model_validate({**payload, "entries": entries})


def test_legacy_v1_scope_migrates_deterministically_to_v2(tmp_path: Path) -> None:
    current = yaml.safe_load(DEFAULT_POLICY_PATHS.strategy_scope.read_text(encoding="utf-8"))
    legacy = {
        key: value
        for key, value in current.items()
        if key
        not in {
            "matrix_version",
            "ui_surface",
            "capability_profiles",
            "profile_assignments",
            "instrument_rules",
            "exclusion_policy",
        }
    }
    legacy["schema_version"] = "1.0"
    legacy["policy_version"] = "2026-07-12"
    legacy["strategies"] = [
        entry
        for entry in legacy["strategies"]
        if entry["strategy_id"] not in {"futures", "intraday", "options", "shorting", "event_driven_filings", "alternative_data"}
    ]
    path = tmp_path / "strategy_scope_v1.yaml"
    path.write_text(yaml.safe_dump(legacy, sort_keys=False), encoding="utf-8")

    first = load_strategy_scope(path)
    second = load_strategy_scope(path)

    assert first.policy is not None
    assert first.diagnostic_mode is False
    assert first.policy.schema_version == "2.0"
    assert first.policy.migrated_from_schema == "1.0"
    assert first.policy.migration_source_checksum == first.checksum
    assert len(first.policy.effective_checksum) == 64
    assert first.policy.model_dump(mode="json") == second.policy.model_dump(mode="json")
    assert {"futures", "intraday", "options", "shorting", "event_driven_filings", "alternative_data"} <= {
        entry.strategy_id for entry in first.policy.entries
    }
    assert resolve_strategy_capability(first.policy, strategy_id="martingale", stage="analyse").state == "rejected"


def test_legacy_v1_migration_rejects_duplicate_strategy_ids(tmp_path: Path) -> None:
    current = yaml.safe_load(DEFAULT_POLICY_PATHS.strategy_scope.read_text(encoding="utf-8"))
    legacy = {
        "schema_version": "1.0",
        "policy_id": "legacy-strategy-scope",
        "policy_version": "1",
        "execution_allowed": False,
        "executable_authority": False,
        "strategies": [current["strategies"][0], current["strategies"][0]],
    }
    path = tmp_path / "duplicate-v1.yaml"
    path.write_text(yaml.safe_dump(legacy, sort_keys=False), encoding="utf-8")

    result = load_strategy_scope(path)

    assert result.diagnostic_mode is True
    assert "legacy strategy identifiers must be unique" in result.diagnostics[0]
    assert result.execution_allowed is False


def test_capability_export_contains_resolved_rows_and_no_live_authority(tmp_path: Path) -> None:
    payload = strategy_capability_export(_policy())
    export_path = tmp_path / "strategy_capability_matrix.json"
    export_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    assert payload["matrix_version"] == "2026-07-21"
    assert payload["execution_allowed"] is False
    assert len(payload["strategy_matrix"]) == len(_policy().entries) * len(CAPABILITY_STAGES)
    assert {row["asset_family"] for row in payload["instrument_matrix"]} >= {"stock", "etf", "ordinary_fund", "fixed_rate_bond"}
    assert all(row["execution_allowed"] is False for row in payload["strategy_matrix"])
    assert len(payload["instrument_stage_matrix"]) == len(_policy().instrument_rules) * len(CAPABILITY_STAGES)
    assert all(row["execution_allowed"] is False for row in payload["instrument_stage_matrix"])
    assert all(
        {"reason_code", "required_data", "tests", "authority", "ui_visibility", "score_authority", "paper_authority", "live_authority"} <= set(row)
        for row in payload["strategy_matrix"]
    )
