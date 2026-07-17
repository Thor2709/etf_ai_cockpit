from __future__ import annotations

from dataclasses import asdict

from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio.costs import (
    COST_MODEL_ID,
    compare_realised_fill,
    cost_capacity_status,
    estimate_execution_cost,
    estimate_rebalance_cost,
    fixed_cost_eur,
    spread_cost_bps,
    square_root_impact_bps,
    volatility_volume_impact_bps,
)


def test_cost_components_are_finite_and_conservative() -> None:
    assert fixed_cost_eur(1.0, 1_000.0) == 1.0
    assert fixed_cost_eur(1.0, 0.0) == 0.0
    assert spread_cost_bps(8.0) == 8.0
    assert spread_cost_bps(8.0, order_type="limit") == 4.0
    assert square_root_impact_bps(10_000.0, 100_000.0, 25.0) > 0
    assert volatility_volume_impact_bps(10_000.0, 100_000.0, 0.02) > 0


def test_cost_reflects_order_type_listing_and_session_assumptions() -> None:
    config = load_config()
    market = estimate_execution_cost(config, "VWCE", 5_000.0, order_type="market", listing="XETRA", session="continuous")
    limit = estimate_execution_cost(config, "VWCE", 5_000.0, order_type="limit", listing="XETRA", session="continuous")
    auction = estimate_execution_cost(config, "VWCE", 5_000.0, order_type="market", listing="XETRA", session="auction")

    assert market.spread_bps > limit.spread_bps
    assert auction.total_cost_bps > market.total_cost_bps
    assert "listing=XETRA" in auction.assumptions


def test_cost_is_monotonic_with_order_size_and_reports_capacity() -> None:
    config = load_config()
    small = estimate_execution_cost(config, "VWCE", 1_000.0, adv_eur=100_000.0, daily_volatility=0.02)
    large = estimate_execution_cost(config, "VWCE", 10_000.0, adv_eur=100_000.0, daily_volatility=0.02)

    assert small.total_cost_eur < large.total_cost_eur
    assert large.capacity_eur == 10_000.0
    assert large.capacity_status == "within_configured_participation"
    assert small.execution_allowed is False
    assert small.model_id == COST_MODEL_ID


def test_missing_microstructure_widens_cost_and_is_explicit() -> None:
    config = load_config()
    complete = estimate_execution_cost(config, "VWCE", 10_000.0, adv_eur=100_000.0, daily_volatility=0.02)
    missing = estimate_execution_cost(config, "VWCE", 10_000.0)

    assert missing.total_cost_eur > complete.total_cost_eur
    assert missing.uncertainty_multiplier > 1.0
    assert missing.data_quality == "degraded_missing_microstructure"
    assert missing.capacity_status == "unavailable_missing_adv"


def test_local_calibration_and_realised_comparison_do_not_rewrite_estimate() -> None:
    config = load_config()
    estimate = estimate_execution_cost(
        config,
        "VWCE",
        5_000.0,
        calibration={"spread_bps": 2.0, "slippage_bps": 1.0, "adv_eur": 250_000.0, "daily_volatility": 0.01},
    )
    before = asdict(estimate)
    realised = compare_realised_fill(estimate, reference_price=100.0, fill_price=100.2, filled_value_eur=4_000.0)

    assert estimate.data_quality == "calibrated_local_inputs"
    assert realised["estimate_id"] == estimate.estimate_id
    assert realised["realised_price_impact_bps"] == 20.0
    assert asdict(estimate) == before


def test_rebalance_and_ui_preview_use_the_same_model() -> None:
    config = load_config()
    portfolio = estimate_rebalance_cost(config, 10_000.0, {"VWCE": 0.10, "LYP6": -0.05})
    preview = cost_capacity_status(config, "VWCE")

    assert portfolio.model_id == COST_MODEL_ID
    assert portfolio.total_order_value_eur == 1_500.0
    assert portfolio.total_cost_eur > 0
    assert preview["model_id"] == COST_MODEL_ID
    assert preview["execution_allowed"] is False
