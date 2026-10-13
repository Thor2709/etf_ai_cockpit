from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.sparebank import analyse_sparebank_ec, build_sparebank_scorecard, load_sparebank_scorecard_policy
from etf_cockpit.application.financial_institution_views import _with_local_marketability
from etf_cockpit.core.settings_bundle import load_settings_bundle


FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"


def _evidence(*, missing_compensation: bool = False) -> dict[str, object]:
    evidence = json.loads((FIXTURES / "teaching_bank.json").read_text(encoding="utf-8"))
    facts = evidence["facts"]
    for name, value in (
        ("overkursfond", 0.0),
        ("utjevningsfond", 0.0),
        ("gavefond", 0.0),
        ("kompensasjonsfond", 0.0),
    ):
        facts[name] = {
            "available": True,
            "value": value,
            "unit": "NOK",
            "period": "2024-12-31",
            "source_locator": "synthetic test fact",
        }
    if missing_compensation:
        facts.pop("kompensasjonsfond")
    return evidence


def _complete_analysis(evidence: dict[str, object] | None = None):
    return analyse_sparebank_ec(
        evidence or _evidence(),
        decision_time="2025-01-02T00:00:00Z",
        price=100.0,
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
    )


def test_partial_coverage_above_minimum_exposes_weighted_composite_and_missing_axes() -> None:
    analysis = _complete_analysis()
    policy = load_sparebank_scorecard_policy()
    weights = dict(policy.scorecard["axis_weights"])
    weights["owner_claim_integrity"] = 3.0
    weighted_policy = replace(policy, scorecard={**policy.scorecard, "axis_weights": weights})
    scorecard = build_sparebank_scorecard(
        analysis,
        decision_time="2025-01-02T00:00:00Z",
        decision_price=100.0,
        valuation_assumptions={
            "central_owner_value_per_ec": 130.0,
            "cost_of_equity": 0.05,
            "marketability": {"days_to_trade": 21.0},
        },
        policy=weighted_policy,
    )
    rated = [
        (weights[axis_id], axis["rating_10"])
        for axis_id, axis in scorecard.axes.items()
        if axis["rating_10"] is not None
    ]
    assert scorecard.composite_before_gate_cap_10 == pytest.approx(
        sum(weight * rating for weight, rating in rated) / sum(weight for weight, _ in rated)
    )
    assert scorecard.composite_10 is not None
    assert scorecard.composite_coverage >= 0.25
    assert scorecard.missing_axes
    assert scorecard.status == "partial"


def test_coverage_below_minimum_has_no_composite_and_reports_reason() -> None:
    result = analyse_sparebank_ec(
        _evidence(),
        decision_time="2024-12-31T00:00:00Z",
    ).scorecard
    assert result.composite_coverage < 0.25
    assert result.composite_10 is None
    assert "MINIMUM_COMPOSITE_COVERAGE_NOT_MET" in result.gate_reasons


def test_owner_claim_gate_flags_but_does_not_null_composite() -> None:
    evidence = _evidence()
    evidence["facts"].pop("sparebankens_fond")
    result = _complete_analysis(evidence).scorecard
    assert result.composite_10 is not None
    assert "OWNER_CLAIM_UNRESOLVED" in result.gate_reasons
    assert result.axes["owner_claim_integrity"]["rating_10"] is not None


def test_identity_conflict_still_blocks_composite() -> None:
    evidence = _evidence()
    evidence["operating_country"] = "SE"
    result = analyse_sparebank_ec(evidence, decision_time="2025-01-02T00:00:00Z").scorecard
    assert result.status == "BLOCKED"
    assert result.composite_10 is None
    assert "JURISDICTION_EVIDENCE_CONFLICT" in result.gate_reasons


def test_missing_kompensasjonsfond_marks_owner_claim_axis_partial_without_zero_fill() -> None:
    result = _complete_analysis(_evidence(missing_compensation=True))
    axis = result.scorecard.axes["owner_claim_integrity"]
    assert result.claim_state.self_owned_pools == {"sparebankens_fond": 600.0, "gavefond": 0.0}
    assert "kompensasjonsfond" not in result.claim_state.self_owned_pools
    assert "kompensasjonsfond" in result.claim_state.unavailable_fields
    assert axis["status"] == "partial"
    assert axis["partial_reason"] == "kompensasjonsfond not reported"


def test_marketability_uses_only_as_of_price_and_candidate_report_data(tmp_path: Path) -> None:
    report_dir = tmp_path / "data" / "reports"
    report_dir.mkdir(parents=True)
    (report_dir / "yfinance_trade_candidate_analysis_20250103T120000Z.json").write_text(
        json.dumps([{"instrument_id": "BANK-EC", "latest_date": "2025-01-02", "shares": 20}]),
        encoding="utf-8",
    )
    (report_dir / "yfinance_trade_candidate_analysis_20250104T120000Z.json").write_text(
        json.dumps([{"instrument_id": "BANK-EC", "latest_date": "2025-01-03", "shares": 999}]),
        encoding="utf-8",
    )
    prices = pd.DataFrame(
        [
            {"instrument_id": "BANK-EC", "date": "2025-01-01", "close": 10.0, "currency": "NOK", "volume": 100.0},
            {"instrument_id": "BANK-EC", "date": "2025-01-02", "close": 10.0, "currency": "NOK", "volume": 200.0},
            {"instrument_id": "BANK-EC", "date": "2025-01-03", "close": 10.0, "currency": "NOK", "volume": 900.0},
            {"instrument_id": "BANK-EC", "date": "2025-01-04", "close": 10.0, "currency": "NOK", "volume": 10000.0},
        ]
    )
    result = _with_local_marketability(
        tmp_path,
        "BANK-EC",
        pd.Timestamp("2025-01-03T23:59:59Z"),
        prices,
        None,
    )["marketability"]
    assert result["median_volume_60d"] == 200.0
    assert result["days_to_trade"] == pytest.approx(1.0)
    assert result["order_quantity"] == 20.0
    assert result["candidate_report"] == "yfinance_trade_candidate_analysis_20250103T120000Z.json"
    assert result["market_data_as_of"] == "2025-01-03"


def test_settings_bundle_loads_after_scorecard_config_change() -> None:
    bundle = load_settings_bundle(Path.cwd())
    assert bundle.revision
