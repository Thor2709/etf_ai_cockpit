from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.features.forecast_lab import build_forecast_lab_report
from etf_cockpit.models.forecast_scores import forecast_return_distributions
from etf_cockpit.models.uncertainty import (
    decompose_forecast_uncertainty,
    generate_scenarios,
    replay_scenarios,
    uncertainty_gate_reasons,
)
from etf_cockpit.signals.actions import apply_gate_result


SETTINGS = {
    "high_disagreement_threshold": 0.03,
    "confidence_haircut": 0.50,
    "minimum_confidence": 0.35,
    "maximum_forecast_age_days": 5,
    "clone_return_tolerance": 0.000001,
    "scenario_seed": 109,
    "scenario_count": 32,
}


def _model(name: str, median: float, *, model_id: str | None = None) -> dict[str, object]:
    return {
        "model_name": name,
        "model_id": model_id or name,
        "q10_return": median - 0.10,
        "q50_return": median,
        "q90_return": median + 0.10,
        "forecast_date": "2026-06-01T00:00:00+00:00",
    }


def _distribution(models: list[dict[str, object]]) -> dict[str, object]:
    return {
        "status": "available",
        "q10_return": -0.10,
        "q50_return": 0.0,
        "q90_return": 0.10,
        "coverage_ratio": 0.80,
        "decision_time": "2026-06-01T00:00:00+00:00",
        "per_model_distributions": models,
    }


def test_return_distributions_preserve_each_model_input_additively() -> None:
    forecasts = pd.DataFrame([
        {
            "etf_id": "ETF-A",
            "model_name": "baseline",
            "model_id": "model-a",
            "target_id": "target-a",
            "horizon_days": 60,
            "expected_return": 0.02,
            "q10_return": 0.00,
            "q50_return": 0.02,
            "q90_return": 0.04,
            "coverage_ratio": 0.80,
            "forecast_date": "2026-06-01",
            "status": "ok",
            "model_allowed_in_score": True,
        },
        {
            "etf_id": "ETF-A",
            "model_name": "timesfm",
            "model_id": "model-b",
            "target_id": "target-b",
            "horizon_days": 60,
            "expected_return": 0.03,
            "q10_return": 0.01,
            "q50_return": 0.03,
            "q90_return": 0.05,
            "coverage_ratio": 0.90,
            "forecast_date": "2026-06-01",
            "status": "ok",
            "model_allowed_in_score": True,
        },
    ])

    output = forecast_return_distributions(
        forecasts,
        decision_time="2026-06-01T00:00:00Z",
    )["ETF-A"]

    assert [row["model_id"] for row in output["per_model_distributions"]] == ["model-a", "model-b"]
    assert output["per_model_distributions"][1]["q50_return"] == 0.03
    assert output["uncertainty_decomposition"]["status"] == "unavailable"


def test_decomposition_is_nonnegative_and_total_uses_root_sum_square() -> None:
    result = decompose_forecast_uncertainty(
        _distribution([_model("first", 0.0), _model("second", 0.02)]),
        SETTINGS,
        base_confidence=0.8,
    )

    components = [
        result["aleatoric_uncertainty"],
        result["epistemic_uncertainty"],
        result["data_quality_uncertainty"],
    ]
    assert all(isinstance(value, float) and value >= 0 for value in components)
    expected = sum(value * value for value in components) ** 0.5
    assert result["combination_rule"] == "root_sum_square"
    assert result["total_uncertainty"] == expected


def test_high_disagreement_flags_and_blocks_action_through_gate_contract() -> None:
    distribution = _distribution([_model("first", -0.12), _model("second", 0.12)])
    result = decompose_forecast_uncertainty(distribution, SETTINGS, base_confidence=0.8)
    reasons = uncertainty_gate_reasons(
        result,
        SETTINGS,
        effective_confidence=result["adjusted_confidence"],
    )

    assert result["disagreement_flagged"] is True
    assert result["adjusted_confidence"] == 0.4
    assert "forecast_model_disagreement" in reasons
    assert apply_gate_result("add", reasons) == "no_trade"


def test_duplicate_model_identity_gets_independent_breadth_discount() -> None:
    clone = _model("first_clone", 0.0, model_id="shared-model")
    distribution = _distribution([
        _model("first", 0.0, model_id="shared-model"),
        clone,
        _model("independent", 0.02, model_id="different-model"),
    ])

    result = decompose_forecast_uncertainty(distribution, SETTINGS, base_confidence=0.8)

    assert result["raw_model_count"] == 3
    assert result["effective_model_count"] == 2
    assert result["breadth_discount"] == 2 / 3


def test_scenario_seed_and_inputs_replay_identical_output_and_are_persisted() -> None:
    record = generate_scenarios(
        _distribution([_model("first", 0.0), _model("second", 0.02)]),
        SETTINGS,
    )
    assert record["status"] == "available"
    report = build_forecast_lab_report(
        pd.DataFrame(),
        pd.DataFrame(),
        scenario_records={"ETF-A": record},
    )
    persisted = report["scenario_replay_inputs"]["ETF-A"]

    assert persisted == {
        "scenario_seed": SETTINGS["scenario_seed"],
        "scenario_inputs": record["scenario_inputs"],
    }
    assert replay_scenarios(persisted) == record["scenario_returns"]


def test_missing_coverage_is_unavailable_not_zero() -> None:
    distribution = _distribution([_model("first", 0.0)])
    distribution["coverage_ratio"] = None

    result = decompose_forecast_uncertainty(distribution, SETTINGS, base_confidence=0.8)

    assert result["data_quality_uncertainty"] is None
    assert result["total_uncertainty"] is None
    assert result["status"] == "unavailable"
    assert "Coverage ratio is unavailable." in result["reason"]


def test_uncertainty_config_is_loaded_and_missing_section_fails_closed() -> None:
    config = load_config()

    assert config.forecast_uncertainty is not None
    assert config.forecast_uncertainty.scenario_seed == 109
    unavailable = decompose_forecast_uncertainty(_distribution([_model("first", 0.0)]), None)
    assert unavailable["status"] == "unavailable"
    assert "configuration is missing" in unavailable["reason"]
