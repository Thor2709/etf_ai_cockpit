from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.portfolio.attribution import ATTRIBUTION_MODEL_VERSION, build_performance_attribution


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-01", periods=5)
    prices = pd.DataFrame(
        {
            "date": dates.tolist() * 2,
            "etf_id": ["AAA"] * 5 + ["BBB"] * 5,
            "adjusted_close": [100.0, 101.0, 103.0, 102.0, 104.0, 100.0, 99.0, 100.0, 101.0, 102.0],
        }
    )
    allocation = pd.DataFrame(
        {
            "etf_id": ["AAA", "BBB"],
            "current_weight": [0.6, 0.3],
            "currency": ["EUR", "USD"],
        }
    )
    return prices, allocation


def test_linked_asset_and_cash_contributions_reconcile_time_weighted_return() -> None:
    prices, allocation = _fixture()

    report = build_performance_attribution(prices, allocation)

    assert report["model_version"] == ATTRIBUTION_MODEL_VERSION
    assert report["execution_allowed"] is False
    assert report["time_weighted_return"] is not None
    asset_total = float(report["asset_contributions"]["contribution"].sum())
    assert abs(float(report["time_weighted_return"]) - asset_total - float(report["cash_contribution"])) < 1e-12
    assert abs(float(report["identity_residual"])) < 1e-12
    assert report["coverage"]["instrument_count"] == 2


def test_explicit_cashflows_costs_factors_currency_and_decisions_are_visible() -> None:
    prices, allocation = _fixture()
    factors = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-02", periods=4).tolist() * 2,
            "factor": ["market"] * 4 + ["momentum"] * 4,
            "factor_return": [0.01, -0.005, 0.002, 0.004, 0.003, -0.001, 0.002, 0.001],
        }
    )
    exposures = pd.DataFrame({"market": [1.0, 1.0], "momentum": [-0.5, 0.5]}, index=["AAA", "BBB"])
    report = build_performance_attribution(
        prices,
        allocation,
        factor_returns=factors,
        factor_exposures=exposures,
        cashflows=pd.DataFrame({"date": [pd.Timestamp("2026-01-01")], "amount": [1.0]}),
        costs=pd.DataFrame({"category": ["commission", "tax"], "amount": [2.0, 1.0]}),
        decisions=pd.DataFrame({"instrument_id": ["AAA"], "model_weight": [0.5], "approved_weight": [0.6], "realised_weight": [0.55]}),
    )

    assert report["money_weighted_status"] in {"available", "partial"}
    assert report["money_weighted_return"] is not None
    assert set(report["cost_attribution"]["category"]) == {"commission", "tax"}
    assert not report["factor_attribution"].empty
    assert set(report["currency_attribution"]["currency"]) == {"EUR", "USD"}
    assert not report["decision_attribution"].empty
    assert np.isfinite(float(report["net_return_after_explicit_costs"]))


def test_missing_adjusted_rows_are_not_forward_filled_and_unavailable_inputs_are_explicit() -> None:
    prices, allocation = _fixture()
    prices.loc[(prices["etf_id"] == "BBB") & (prices["date"] == pd.Timestamp("2026-01-05")), "adjusted_close"] = np.nan

    report = build_performance_attribution(prices, allocation)

    assert "missing_adjusted_price_cells_excluded" in report["warnings"]
    assert "explicit_costs_unavailable" in report["warnings"]
    assert "external_cashflows_unavailable_for_money_weighted_return" in report["warnings"]
    assert report["coverage"]["missing_return_cells"] > 0
