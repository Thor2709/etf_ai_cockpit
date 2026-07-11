from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.signals.actions import preliminary_action
from etf_cockpit.signals.gates import evaluate_risk_gates
from etf_cockpit.signals.signal_pipeline import _cost_stress_metrics


def test_action_threshold_mapping_add_and_trim() -> None:
    config = load_config()
    add_action = preliminary_action(config, total_score=0.62, confidence=0.70, current_weight=0.10, drift=-0.02, hard_band=0.05, trend_200=1)
    trim_action = preliminary_action(config, total_score=-0.42, confidence=0.70, current_weight=0.10, drift=0.01, hard_band=0.05, trend_200=1)
    assert add_action == "add"
    assert trim_action == "trim"


def test_risk_gate_blocks_low_edge_after_costs() -> None:
    config = load_config()
    row = pd.Series(
        {
            "etf_id": "WORLD_CORE",
            "trend_200": 1.0,
            "drawdown_60d_max": -0.03,
            "expected_edge_60d": 0.0001,
            "cost_bps": 13.0,
            "current_weight": 0.10,
        }
    )
    blocked, _ = evaluate_risk_gates(
        config,
        row,
        DataQualityReport(as_of_date=pd.Timestamp("2026-06-26").date(), issues=[]),
        candidate_action="add",
        projected_weight=0.12,
        cash_weight=0.10,
    )
    assert "edge_below_cost_threshold" in blocked


def test_cost_stress_metrics_include_low_base_high_scenarios() -> None:
    config = load_config()

    metrics = _cost_stress_metrics(
        config,
        etf_id="WORLD_CORE",
        expected_edge_bps=50.0,
        base_cost_bps=7.0,
        trade_value_eur=500.0,
    )

    assert metrics["cost_low_bps"] < metrics["cost_base_bps"] < metrics["cost_high_bps"]
    assert metrics["edge_to_cost_low"] > metrics["edge_to_cost_base"] > metrics["edge_to_cost_high"]
    assert metrics["cost_stress_warning"] in {
        "edge_survives_high_cost_stress",
        "edge_fails_high_cost_stress",
        "edge_fails_base_cost",
        "insufficient_edge_or_cost",
    }
    assert "configured spread+slippage+FX" in metrics["cost_stress_assumptions"]
