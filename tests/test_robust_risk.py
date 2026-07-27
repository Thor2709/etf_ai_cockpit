from __future__ import annotations

import inspect
from dataclasses import replace
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.portfolio.factor_risk import build_factor_risk_report
from etf_cockpit.portfolio.robust_risk import (
    ESTIMATOR_NAMES,
    build_robust_risk_report,
    covariance_estimators,
    integrate_fixed_income_risk,
)
from test_factor_risk import _fixture as _factor_fixture
from test_fixed_income_risk import _risk
from etf_cockpit.analysis.fixed_income_risk import calculate_fixed_income_risk


def _fixture(periods: int = 100) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2025-01-01", periods=periods)
    common = rng.normal(0.0002, 0.007, periods)
    rows: list[dict[str, object]] = []
    allocation: list[dict[str, object]] = []
    for index in range(4):
        instrument_id = f"ETF{index}"
        returns = 0.75 * common + rng.normal(0.0001 * index, 0.002 + index * 0.0002, periods)
        values = 100 * np.exp(np.cumsum(returns))
        rows.extend(
            {
                "date": dt.date(),
                "etf_id": instrument_id,
                "adjusted_close": float(value),
                "volume": 100_000 + index * 10_000,
            }
            for dt, value in zip(dates, values)
        )
        allocation.append({"etf_id": instrument_id, "current_weight": 0.25, "market_value_eur": 2_500.0})
    return pd.DataFrame(rows), pd.DataFrame(allocation)


def test_covariance_estimators_are_psd_and_report_oos_selection_tail_risk_and_components() -> None:
    prices, allocation = _fixture()

    report = build_robust_risk_report(prices, allocation, bootstrap_reps=40, block_size=5)

    assert set(ESTIMATOR_NAMES) == set(report["covariances"])
    for estimator, covariance in report["covariances"].items():
        if covariance.empty:
            continue
        assert np.all(np.linalg.eigvalsh(covariance.to_numpy(float)) >= -1e-10), estimator
        assert report["diagnostics"]["estimators"][estimator]["positive_semidefinite"] is True
    assert report["selected_estimator"] in ESTIMATOR_NAMES
    assert not report["estimator_comparison"].empty
    assert report["portfolio"]["component_share_sum"] == pytest.approx(1.0)
    assert report["bootstrap"]["status"] == "available"
    assert report["bootstrap"]["lower_5"] <= report["bootstrap"]["upper_95"]
    assert report["tail_risk"]["portfolio"]["var_95"] >= 0
    assert report["tail_risk"]["portfolio"]["expected_shortfall_95"] >= report["tail_risk"]["portfolio"]["var_95"]
    assert report["tail_risk"]["liquidity_adjusted"]["status"] == "available"


def test_ill_conditioned_fixture_is_visibly_regularised_and_diagonal_baseline_exists() -> None:
    prices, allocation = _fixture()
    duplicate = prices[prices["etf_id"] == "ETF0"].copy()
    duplicate["etf_id"] = "ETF4"
    duplicate["volume"] = 90_000
    report = build_robust_risk_report(pd.concat([prices, duplicate], ignore_index=True), allocation)

    assert not report["covariances"]["diagonal"].empty
    assert any(item["regularised"] for item in report["diagnostics"]["estimators"].values())
    assert "diagonal" in set(report["estimator_comparison"]["estimator"])


def test_factor_model_covariance_is_consumed_when_factor_report_is_available() -> None:
    prices, allocation, features = _factor_fixture()
    factor_report = build_factor_risk_report(prices, allocation, features)

    report = build_robust_risk_report(prices, allocation, factor_report=factor_report, bootstrap_reps=10)

    assert not report["covariances"]["factor_model"].empty
    assert report["diagnostics"]["estimators"]["factor_model"]["positive_semidefinite"] is True


def test_short_history_is_explicitly_limited_and_covariance_contract_is_reusable() -> None:
    prices, allocation = _fixture(periods=12)
    returns = build_robust_risk_report(prices, allocation)["returns"]

    report = build_robust_risk_report(prices, allocation, bootstrap_reps=10)
    matrices = covariance_estimators(returns)

    assert "short_return_history" in report["warnings"]
    assert set(matrices) == set(ESTIMATOR_NAMES)


def test_risk_workspace_surfaces_robust_risk_evidence() -> None:
    from etf_cockpit.app.pages.risk import risk_page

    source = inspect.getsource(risk_page)
    assert "build_robust_risk_report" in source
    assert "_robust_estimator_panel" in source


def test_fixed_income_components_marginals_and_scenarios_reconcile_without_zero_fill() -> None:
    complete_input = _risk(
        spread_shock_bps=Decimal("20"),
        rating_change_loss=Decimal("1"),
        default_probability=Decimal("0.01"),
        recovery_rate=Decimal("0.4"),
        liquidity_cost_bps=Decimal("5"),
    )
    complete = calculate_fixed_income_risk(complete_input)
    missing_scenario = replace(
        calculate_fixed_income_risk(replace(complete_input, position_face_value=Decimal("2000"))),
        scenarios=(calculate_fixed_income_risk(replace(complete_input, position_face_value=Decimal("2000"))).scenarios[0],),
    )
    report = integrate_fixed_income_risk((complete, missing_scenario))
    rows = {row["scenario_id"]: row for row in report["scenarios"]}
    assert rows["up-10"]["reconciled"] is True
    assert rows["up-10"]["total_pnl"] == rows["up-10"]["known_component_total"]
    assert rows["key-up"]["total_pnl"] is None
    assert rows["key-up"]["missing_instruments"] == ["BOND-1"]
    assert report["components"][1]["value"] is not Decimal("0")
    assert report["execution_allowed"] is False

    unsupported = calculate_fixed_income_risk(_risk(instrument_kind="bond_etf"))
    unavailable = integrate_fixed_income_risk((unsupported,))
    assert unavailable["status"] == "unavailable"
    assert unavailable["reason_codes"] == ["fixed_income_scenarios_unavailable"]
