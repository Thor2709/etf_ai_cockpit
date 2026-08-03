from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.signals.canonical_scoring import (
    CanonicalComponent,
    apply_structure_confidence_cap,
    build_canonical_score,
    canonical_score_from_signal_row,
    load_score_policy,
)


def _component(key: str, raw: float | None, role: str = "attractiveness", *, status: str = "ok", authority: str = "vendor_unofficial") -> CanonicalComponent:
    return CanonicalComponent(
        key=key,
        raw_metric=raw,
        score_role=role,
        peer_group="synthetic",
        source_id=f"source:{key}",
        source_authority=authority,
        freshness_status="ok",
        uncertainty="low",
        status=status,
        explanation=f"{key} explanation",
    )


def test_formula_policy_is_versioned_and_cross_platform_deterministic() -> None:
    policy = load_score_policy("ETF")
    assert policy.formula_version == "score-engine-v3.0.0"
    assert len(policy.formula_checksum) == 64
    assert policy.formula_checksum == load_score_policy("ETF", path=Path("configs/score_engine_v3.yaml")).formula_checksum
    assert policy.as_dict()["execution_allowed"] is False


def test_canonical_score_has_separated_outputs_and_reconciling_contributions() -> None:
    score = build_canonical_score(
        instrument_id="ETF-1",
        asset_type="ETF",
        decision_time="2026-07-10",
        components=[
            _component("momentum", 0.8),
            _component("trend", 0.4),
            _component("relative_strength", 0.2),
            _component("risk", 0.6, "risk_implementation"),
            _component("liquidity_cost", 0.5, "risk_implementation"),
            _component("baseline", 0.3, "expected_return", authority="model_advisory"),
            _component("timesfm", -0.2, "expected_return", authority="model_advisory"),
        ],
    )

    assert score.attractiveness_10 is not None
    assert score.expected_return_10 is not None
    assert score.risk_implementation_10 is not None
    assert score.evidence_confidence_10 is not None
    assert score.source_vintage_hash and len(score.source_vintage_hash) == 64
    for group in ("attractiveness", "expected_return", "risk_implementation"):
        rows = [row for row in score.contributions if row["group"] == group]
        component_raw = sum(float(row["contribution_raw"]) for row in rows)
        output = getattr(score, f"{group}_10")
        assert output is not None
        assert component_raw == pytest.approx((float(output) / 5.0) - 1.0, abs=0.02)


def test_missing_or_conflicted_evidence_reduces_coverage_and_confidence() -> None:
    complete = build_canonical_score(
        instrument_id="ETF-1",
        asset_type="ETF",
        decision_time="2026-07-10",
        components=[_component("momentum", 0.5), _component("trend", 0.5), _component("relative_strength", 0.5), _component("risk", 0.5, "risk_implementation")],
    )
    incomplete = build_canonical_score(
        instrument_id="ETF-1",
        asset_type="ETF",
        decision_time="2026-07-10",
        components=[
            _component("momentum", 0.5),
            _component("trend", None, status="unavailable"),
            _component("relative_strength", 0.5, status="blocked"),
            _component("risk", 0.5, "risk_implementation", status="ok"),
        ],
    )
    assert incomplete.coverage < complete.coverage
    assert incomplete.evidence_confidence_10 is not None
    assert complete.evidence_confidence_10 is not None
    assert incomplete.evidence_confidence_10 < complete.evidence_confidence_10
    assert any(warning.startswith("attractiveness_coverage:") for warning in incomplete.warnings)


def test_structure_confidence_cap_only_changes_evidence_confidence() -> None:
    score = build_canonical_score(
        instrument_id="ETF-1",
        asset_type="ETF",
        decision_time="2026-07-10",
        components=[_component("momentum", 0.5), _component("trend", 0.5), _component("relative_strength", 0.5), _component("risk", 0.5, "risk_implementation")],
    )
    capped = apply_structure_confidence_cap(score, 0.0)

    assert capped.evidence_confidence_10 == 0.0
    assert capped.attractiveness_10 == score.attractiveness_10
    assert capped.expected_return_10 == score.expected_return_10
    assert capped.coverage == score.coverage
    assert "structure_confidence_cap:0.000" in capped.warnings


def test_legacy_migration_composite_omits_missing_components_instead_of_neutralising_them() -> None:
    score = build_canonical_score(
        instrument_id="ETF-1",
        asset_type="ETF",
        decision_time="2026-07-10",
        components=[_component("momentum", 0.8), _component("trend", None, status="unavailable")],
        legacy_component_weights={"momentum": 0.5, "trend": 0.5},
    )

    assert score.legacy_composite_raw == 0.8
    assert score.decision_distribution["attractiveness"] is not None


def test_signal_adapter_reconciles_legacy_total_and_retains_vintage_metadata() -> None:
    config = load_config()
    score = canonical_score_from_signal_row(
        {
            "etf_id": "VWCE",
            "score_momentum": 0.2,
            "score_trend": 0.3,
            "score_relative_strength": 0.1,
            "score_risk": 0.4,
            "score_rebalance": 0.0,
            "score_baseline_ml": 0.2,
            "score_timesfm": 0.0,
            "score_toto": 0.0,
            "cost_penalty": 0.01,
            "turnover_penalty": 0.0,
        },
        config,
        "2026-07-10",
    )
    assert score.legacy_composite_raw is not None
    assert score.formula_version == "score-engine-v3.0.0"
    assert score.source_vintage_hash
    assert score.as_dict()["execution_allowed"] is False


def test_formula_registry_has_content_addressed_signature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.data import trust_artifacts

    destination = tmp_path / "score_formula_registry.json"
    monkeypatch.setattr(trust_artifacts, "SCORE_FORMULA_REGISTRY_PATH", destination)
    trust_artifacts.write_score_formula_registry()
    registry = json.loads(destination.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in registry.items() if key not in {"signature_algorithm", "registry_signature"}}

    expected = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert registry["signature_algorithm"] == "sha256-content-address"
    assert registry["registry_signature"] == expected
