from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etf_cockpit.analysis.sparebank import analyse_sparebank_ec, load_sparebank_scorecard_policy
from etf_cockpit.signals import canonical_scoring
from etf_cockpit.signals.canonical_scoring import CanonicalScoreError, canonical_score_from_simple_components


FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"


def _teaching_bank() -> dict[str, object]:
    return json.loads((FIXTURES / "teaching_bank.json").read_text(encoding="utf-8"))


def _complete_scorecard(*, price: float = 100.0, tactical: dict[str, object] | None = None):
    evidence = _teaching_bank()
    return analyse_sparebank_ec(
        evidence,
        decision_time="2025-01-02T00:00:00Z",
        price=price,
        bank_metrics=(
            {"metric": "cost_of_risk", "value": 0.001, "source_id": "fixture:cost-of-risk"},
            {"metric": "cost_income_ratio", "value": 0.4, "source_id": "fixture:cost-income"},
        ),
        bank_economics_evidence={
            "reported_earnings": 100.0,
            "average_common_equity": 1000.0,
            "cet1": 150.0,
            "ppp": 0.0,
            "credit_loss": 0.0,
            "rwa": 1000.0,
            "target_ratio": 0.1,
            "funding": {"lcr": 2.0, "nsfr": 1.2},
        },
        valuation_assumptions={
            "central_owner_value_per_ec": 130.0,
            "cost_of_equity": 0.05,
            "marketability": {"days_to_trade": 21.0},
        },
        tactical_evidence=tactical,
    )


def test_ec_uses_sparebank_scorecard_and_never_reaches_generic_etf_fallback(monkeypatch) -> None:
    calls: list[str] = []
    original = canonical_scoring.load_score_policy

    def spy(asset_type: str = "ETF", **kwargs):
        calls.append(asset_type.upper())
        return original(asset_type, **kwargs)

    monkeypatch.setattr(canonical_scoring, "load_score_policy", spy)
    with pytest.raises(CanonicalScoreError, match="native Sparebank scorecard"):
        canonical_score_from_simple_components("TEACHING-EC", "equity_certificate", "2025-01-02", ())
    assert calls == []

    analysis = analyse_sparebank_ec(_teaching_bank(), decision_time="2025-01-02T00:00:00Z")
    assert analysis.routing.applies
    assert analysis.scorecard.formula_version == "sparebank-scorecard-v1.1.0"
    assert original("STOCK").asset_type == "STOCK"
    assert original("OTHER").groups == original("ETF").groups


def test_score_engine_hash_is_shared_and_sparebank_policy_is_separate() -> None:
    etf = canonical_scoring.load_score_policy("ETF")
    stock = canonical_scoring.load_score_policy("STOCK")
    assert etf.formula_checksum == stock.formula_checksum

    config_path = Path("configs/sparebank_scorecard_v1.yaml")
    normalized = config_path.read_bytes().replace(b"\r\n", b"\n")
    policy = load_sparebank_scorecard_policy(config_path)
    assert policy.formula_checksum == hashlib.sha256(normalized).hexdigest()
    assert policy.formula_checksum != etf.formula_checksum
    assert policy.judgement_status == "judgement-v1-provisional"


def test_evidence_gates_flag_and_insufficient_coverage_has_no_composite() -> None:
    unresolved = _teaching_bank()
    unresolved["facts"].pop("sparebankens_fond")
    unresolved_result = analyse_sparebank_ec(unresolved, decision_time="2025-01-02T00:00:00Z")

    pit_result = analyse_sparebank_ec(
        _teaching_bank(), decision_time="2024-12-31T00:00:00Z"
    )
    denominator_result = analyse_sparebank_ec(
        _teaching_bank(), decision_time="2025-01-02T00:00:00Z", price=0.0
    )

    for result in (unresolved_result.scorecard, pit_result.scorecard, denominator_result.scorecard):
        assert result.status == "partial"
        assert result.composite_10 is None
    assert "OWNER_CLAIM_UNRESOLVED" in unresolved_result.scorecard.gate_reasons
    assert "PIT_CHECK_FAILED" in pit_result.scorecard.gate_reasons
    assert "INVALID_VALUATION_DENOMINATOR" in denominator_result.scorecard.gate_reasons


def test_axes_without_producers_are_unavailable_and_lower_overall_coverage() -> None:
    scorecard = _complete_scorecard().scorecard
    for axis_id in ("lending_economics", "capital_allocation", "portfolio_context"):
        assert scorecard.axes[axis_id]["status"] == "UNAVAILABLE"
        assert scorecard.axes[axis_id]["rating_10"] is None
        assert scorecard.axes[axis_id]["coverage"] == 0.0
    assert scorecard.overall_coverage < 1.0
    assert scorecard.axes["credit_concentration"]["coverage"] < 1.0


def test_composite_reproduces_from_breakdown_and_is_capped_by_gates() -> None:
    scorecard = _complete_scorecard().scorecard
    weights = load_sparebank_scorecard_policy().scorecard["axis_weights"]
    rated_axes = [
        (weights[axis_id], axis["rating_10"])
        for axis_id, axis in scorecard.axes.items()
        if axis["rating_10"] is not None and weights[axis_id] > 0
    ]
    assert scorecard.composite_before_gate_cap_10 == pytest.approx(
        sum(weight * rating for weight, rating in rated_axes) / sum(weight for weight, _ in rated_axes)
    ), {
        "gate_reasons": scorecard.gate_reasons,
        "axes": {key: (value["status"], value["rating_10"], value["coverage"]) for key, value in scorecard.axes.items()},
    }
    assert scorecard.composite_before_gate_cap_10 > 5.0
    assert scorecard.gate_cap_10 == 5.0
    assert scorecard.composite_10 == 5.0
    assert "DAYS_TO_TRADE_ABOVE_LIMIT" in scorecard.gate_reasons
    assert all(axis["rule_version"] == scorecard.judgement_version for axis in scorecard.axes.values())
    assert all("calculation_ids" in axis and "inputs" in axis for axis in scorecard.axes.values())


def test_strong_tactical_evidence_cannot_lift_a_gate_or_change_underwriting() -> None:
    evidence = _teaching_bank()
    evidence["facts"].pop("sparebankens_fond")
    blocked = analyse_sparebank_ec(evidence, decision_time="2025-01-02T00:00:00Z")
    strong_tactical = analyse_sparebank_ec(
        evidence,
        decision_time="2025-01-02T00:00:00Z",
        tactical_evidence={
            "status": "available",
            "horizon": "1-3 months",
            "components": ({"key": "momentum", "raw_metric": 1.0}, {"key": "timesfm", "raw_metric": 1.0}, {"key": "toto", "raw_metric": 1.0}),
        },
    )
    assert blocked.scorecard.composite_10 is None
    assert strong_tactical.scorecard.composite_10 is None
    assert strong_tactical.scorecard.gate_reasons == blocked.scorecard.gate_reasons
    assert strong_tactical.scorecard.underwriting == blocked.scorecard.underwriting
    assert strong_tactical.scorecard.tactical["status"] == "available"
    assert strong_tactical.scorecard.tactical["affects_underwriting"] is False
    assert strong_tactical.scorecard.underwriting["label"] == "Underwriting"
    assert strong_tactical.scorecard.tactical["label"] == "Tactical"
