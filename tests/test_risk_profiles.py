from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path
from types import SimpleNamespace

from etf_cockpit.portfolio.benchmark_reference_contract import (
    CanonicalBenchmarkRegistry,
    VWCE_CANONICAL_SHARE_CLASS,
    VwceAnchorEvidence,
    VwceListingObservation,
    project_profile_relative_analysis,
    resolve_vwce_anchor,
)
from etf_cockpit.portfolio.risk_profiles import (
    edit_risk_profile,
    load_risk_profile_presets,
    project_risk_profile,
    replay_risk_profile_projection,
    risk_profile_preset_version,
    risk_profile_version_record,
)


_RISK_PROFILE_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "risk_profiles_v1.yaml"


def _presets():
    return load_risk_profile_presets(_RISK_PROFILE_CONFIG)


def _anchor_projection() -> dict[str, object]:
    source_a = hashlib.sha256(b"risk-profile-vwce-source-a").hexdigest()
    source_b = hashlib.sha256(b"risk-profile-vwce-source-b").hexdigest()
    anchor = VwceAnchorEvidence(
        canonical_isin="IE00BK5BQT80",
        canonical_share_class_id=VWCE_CANONICAL_SHARE_CLASS,
        official_facts_as_of="2024-01-01",
        benchmark_name="FTSE All-World",
        benchmark_as_of="2024-01-01",
        fees={"ongoing_charges": "fixture"},
        fees_as_of="2024-01-01",
        tracking={"tracking_difference": "fixture"},
        tracking_as_of="2024-01-01",
        product_risk_indicator={"version": "priips-2.0", "value": "fixture"},
        risk_indicator_as_of="2024-01-01",
        currency="USD",
        source_hashes=(source_a, source_b),
        listing_observations=(
            VwceListingObservation(
                "listing:xetra",
                "VWCE",
                "XETR",
                "EUR",
                "2020-01-01T00:00:00Z",
                "2024-01-02T00:00:00Z",
                source_a,
            ),
        ),
        effective_at="2020-01-01T00:00:00Z",
        known_at="2024-01-02T00:00:00Z",
        minimum_horizon_years=0.1,
        maximum_horizon_years=10.0,
    )
    resolution = resolve_vwce_anchor(
        anchor,
        listing_id="listing:xetra",
        effective_date="2024-02-01",
        decision_time="2025-02-02T00:00:00Z",
        currency="EUR",
        horizon_years=1.0,
    )
    return project_profile_relative_analysis(
        {"analysis_id": "candidate-fixture"},
        resolution,
        anchor=anchor,
        registry=CanonicalBenchmarkRegistry(vwce_anchors=(anchor,)),
    )


def _analysis(*, with_anchor: bool = True, targets: dict[str, float] | None = None):
    binding = SimpleNamespace(
        account_id="account-fixture",
        portfolio_id="portfolio-fixture",
        snapshot_id="snapshot-fixture",
        source_revision="1",
        source_checksum="source-fixture",
        price_source_revision="1",
        price_source_checksum="price-fixture",
        as_of="2025-02-01",
        holdings_view="combined",
        holdings_sources=(),
    )
    candidate = SimpleNamespace(
        candidate_id="candidate-fixture",
        name="Candidate fixture",
        targets=targets or {"ETF-A": 0.25, "ETF-B": 0.75},
        cash_weight=0.0,
    )
    evidence = {"profile_relative": _anchor_projection()} if with_anchor else {}
    return SimpleNamespace(
        candidate=candidate,
        allocations=(),
        snapshot_binding=binding,
        service_evidence=evidence,
        constraints=(),
        source_stale=False,
        sector_exposure=(),
        region_exposure=(),
        currency_exposure=(),
        cost=None,
    )


def test_five_presets_are_editable_as_new_versions_without_mutating_defaults() -> None:
    presets = _presets()

    assert tuple(item.label for item in presets) == (
        "Safe",
        "Safe–Medium",
        "Medium",
        "Medium–Aggressive",
        "Aggressive",
    )
    versions = [risk_profile_preset_version(item) for item in presets]
    original = versions[0]
    edited_versions = [
        edit_risk_profile(
            item,
            {"max_position_weight": dict(item.parameters)["max_position_weight"] + 0.01},
        )
        for item in versions
    ]
    edited = edited_versions[0]

    assert len({item.profile_id for item in presets}) == 5
    assert all(item.version == original.version + 1 for item in edited_versions)
    assert all(item.origin == "user_edit" for item in edited_versions)
    assert dict(original.parameters)["max_position_weight"] == 0.10
    assert dict(edited.parameters)["max_position_weight"] == 0.11
    assert original.policy_hash != edited.policy_hash
    assert [dict(item.parameters)["risk_budget_ratio"] for item in versions] == sorted(
        dict(item.parameters)["risk_budget_ratio"] for item in versions
    )


def test_profile_uses_dynamic_vwce_anchor_and_missing_anchor_is_unavailable() -> None:
    medium = next(item for item in _presets() if item.profile_id == "medium")
    profile = risk_profile_preset_version(medium)

    resolved = project_risk_profile(profile, _analysis(), object()).to_record()
    anchor = resolved["vwce_anchor"]
    assert isinstance(anchor, dict)
    assert anchor["status"] == "available"
    assert anchor["canonical_share_class_id"] == VWCE_CANONICAL_SHARE_CLASS
    assert anchor["effective_date"] == "2024-02-01"
    assert anchor["output_currency"] == "EUR"
    assert anchor["horizon_years"] == 1.0
    assert anchor["risk_envelope_status"] == "unavailable"
    assert dict(anchor["risk_metrics"])["expected_shortfall"] == "vwce_risk_distribution_unavailable"
    assert resolved["status"] == "partial"
    assert resolved["reason"] == "vwce_risk_distribution_unavailable"

    missing = project_risk_profile(profile, _analysis(with_anchor=False), object()).to_record()
    assert missing["status"] == "unavailable"
    assert missing["vwce_anchor"]["status"] == "unavailable"
    assert missing["reason"] == "vwce_anchor_resolution_unavailable"


def test_profile_constraints_use_after_trade_goals_constraints_without_mutating_raw_analysis() -> None:
    medium = next(item for item in _presets() if item.profile_id == "medium")
    profile = risk_profile_preset_version(medium)
    analysis = _analysis()
    before = (dict(analysis.candidate.targets), dict(analysis.service_evidence))

    projection = project_risk_profile(profile, analysis, object()).to_record()
    scenario = projection["scenario"]
    assert isinstance(scenario, dict)
    constraints = scenario["constraints"]
    position = next(item for item in constraints if item["constraint_id"] == "max_position_weight:ETF-A")
    assert position["status"] == "blocked"
    assert position["observed"] == 0.25
    assert position["limit"] == 0.20
    assert position["blocking"] is True
    assert analysis.candidate.targets == before[0]
    assert analysis.service_evidence == before[1]
    assert scenario["execution_allowed"] is False


def test_projection_replays_from_stored_profile_version_and_snapshot() -> None:
    medium = next(item for item in _presets() if item.profile_id == "medium")
    profile = edit_risk_profile(
        risk_profile_preset_version(medium),
        {"risk_budget_ratio": 1.02, "max_position_weight": 0.21},
    )
    stored_version = risk_profile_version_record(profile)
    analysis = _analysis()
    snapshot = object()

    first = project_risk_profile(profile, analysis, snapshot).to_record()
    replay = replay_risk_profile_projection(stored_version, analysis, snapshot)

    assert replay["projection_id"] == first["projection_id"]
    assert replay["scenario"] == first["scenario"]
    assert replay["profile"] == first["profile"]
    assert asdict(profile)["policy_hash"] == stored_version["policy_hash"]
