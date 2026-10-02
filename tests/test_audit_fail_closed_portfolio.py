from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.analysis.sparebank.bank_economics import credit_reconciliation
from etf_cockpit.backtest.engine import run_backtest
from etf_cockpit.core.config import load_config
from etf_cockpit.data.capital_efficiency import capital_efficiency_analysis
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.features.crowding import build_correlation_clusters
from etf_cockpit.portfolio.factor_risk import (
    _factor_covariance,
    _portfolio_decomposition,
    build_factor_risk_report,
)
from etf_cockpit.portfolio.optimiser import PortfolioOptimiser
from etf_cockpit.portfolio.rebalancing import RebalanceConstraints, build_rebalance_report
from etf_cockpit.portfolio.robust_risk import build_robust_risk_report
from etf_cockpit.portfolio.risk_analytics import (
    drawdown_contribution,
    return_correlation_matrix,
)
from test_factor_risk import _fixture as factor_fixture
from test_stock_research import _statements


def _non_overlapping_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=80)
    rows = [
        {"date": day.date(), "etf_id": "A", "adjusted_close": 100.0 + index}
        for index, day in enumerate(dates[:40])
    ]
    rows.extend(
        {"date": day.date(), "etf_id": "B", "adjusted_close": 100.0 + index}
        for index, day in enumerate(dates[40:])
    )
    return pd.DataFrame(rows)


def _common_prices(ids: tuple[str, ...] = ("A", "B", "C")) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=80)
    rows = []
    for instrument_index, instrument_id in enumerate(ids):
        returns = np.linspace(-0.01, 0.012, len(dates)) + instrument_index * 0.001
        for day, price in zip(dates, 100.0 * np.exp(np.cumsum(returns))):
            rows.append({"date": day.date(), "etf_id": instrument_id, "adjusted_close": float(price)})
    return pd.DataFrame(rows)


def test_robust_risk_rejects_non_overlapping_return_histories() -> None:
    report = build_robust_risk_report(_non_overlapping_prices(), bootstrap_reps=0)

    assert report["status"] == "unavailable"
    assert report["reason_code"] == "shared_return_history_unavailable"
    assert all(matrix.empty for matrix in report["covariances"].values())


@pytest.mark.parametrize(
    "missing_input",
    ["exposure", "factor_covariance", "specific_volatility", "factor_exposure_column"],
)
def test_robust_factor_estimator_rejects_incomplete_inputs(missing_input: str) -> None:
    ids = ["A", "B", "C"]
    factor_report = {
        "factor_covariance": pd.DataFrame([[0.01]], index=["market"], columns=["market"]),
        "exposure_matrix": pd.DataFrame({"market": [1.0, 0.5, -0.5]}, index=ids),
        "specific_risk": pd.DataFrame(
            {"instrument_id": ids, "specific_vol_ann": [0.1, 0.1, 0.1]}
        ),
    }
    if missing_input == "exposure":
        factor_report["exposure_matrix"].loc["B", "market"] = np.nan
    elif missing_input == "factor_covariance":
        factor_report["factor_covariance"].loc["market", "market"] = np.nan
    elif missing_input == "factor_exposure_column":
        factor_report["factor_covariance"] = pd.DataFrame(
            [[0.01, 0.002], [0.002, 0.02]],
            index=["market", "sector"],
            columns=["market", "sector"],
        )
    else:
        factor_report["specific_risk"].loc[1, "specific_vol_ann"] = np.nan

    report = build_robust_risk_report(
        _common_prices(), factor_report=factor_report, bootstrap_reps=0
    )

    assert report["covariances"]["factor_model"].empty
    assert report["diagnostics"]["estimators"]["factor_model"]["status"] == "unavailable"
    assert report["diagnostics"]["estimators"]["factor_model"]["reason_code"] == "factor_model_inputs_incomplete"


def test_correlation_matrix_rejects_non_overlapping_histories() -> None:
    correlation = return_correlation_matrix(_non_overlapping_prices(), ["A", "B"])

    assert correlation.isna().to_numpy().all()
    assert correlation.attrs["status"] == "unavailable"
    assert correlation.attrs["reason_code"] == "shared_return_history_unavailable"


def test_correlation_matrix_rejects_and_identifies_requested_asset_without_prices() -> None:
    prices = _common_prices(("A",))

    correlation = return_correlation_matrix(prices, ["A", "B"])

    assert correlation.isna().to_numpy().all()
    assert list(correlation.index) == ["A", "B"]
    assert correlation.attrs["status"] == "unavailable"
    assert correlation.attrs["reason_code"] == "requested_asset_prices_unavailable"
    assert correlation.attrs["excluded_assets"] == {
        "B": "requested_asset_price_history_unavailable"
    }


def test_drawdown_contribution_keeps_missing_risk_unavailable() -> None:
    allocation = pd.DataFrame(
        [
            {"etf_id": "A", "name": "A", "current_weight": 0.5},
            {"etf_id": "B", "name": "B", "current_weight": 0.5},
        ]
    )
    features = pd.DataFrame(
        [
            {"etf_id": "A", "drawdown_current": -0.1, "drawdown_60d_max": -0.2, "vol_60d_ann": 0.2},
            {"etf_id": "B", "drawdown_current": -0.05, "drawdown_60d_max": -0.1, "vol_60d_ann": np.nan},
        ]
    )

    report = drawdown_contribution(allocation, features)

    assert report["drawdown_contribution"].isna().all()
    assert report["risk_share"].isna().all()
    assert report.attrs["status"] == "unavailable"
    assert report.attrs["reason_code"] == "drawdown_or_volatility_unavailable"


def test_factor_covariance_rejects_fewer_than_two_shared_observations() -> None:
    factor_returns = pd.DataFrame(
        {"date": [pd.Timestamp("2026-01-01")], "factor": ["market"], "factor_return": [0.01]}
    )

    covariance, diagnostics = _factor_covariance(factor_returns, ["market"])

    assert covariance.empty
    assert diagnostics["status"] == "unavailable"
    assert diagnostics["reason_code"] == "factor_covariance_shared_history_unavailable"


def test_factor_risk_decomposition_rejects_missing_exposure() -> None:
    factor_rows, instrument_rows, portfolio = _portfolio_decomposition(
        pd.DataFrame(
            [
                {"etf_id": "A", "current_weight": 0.5},
                {"etf_id": "B", "current_weight": 0.5},
            ]
        ),
        pd.DataFrame({"market": [1.0, np.nan]}, index=["A", "B"]),
        pd.DataFrame([[0.01]], index=["market"], columns=["market"]),
        pd.DataFrame({"instrument_id": ["A", "B"], "specific_vol_ann": [0.1, 0.1]}),
    )

    assert factor_rows.empty
    assert instrument_rows.empty
    assert portfolio["status"] == "unavailable"
    assert portfolio["reason_code"] == "factor_risk_decomposition_inputs_incomplete"


def test_factor_risk_rejects_unmeasured_specific_volatility() -> None:
    prices, allocation, features = factor_fixture()
    prices = prices.loc[
        (prices["etf_id"] != "ETF7")
        | (pd.to_datetime(prices["date"]) >= pd.to_datetime(prices["date"]).max() - pd.offsets.BDay(1))
    ].copy()

    report = build_factor_risk_report(prices, allocation, features)

    assert report["status"] == "unavailable"
    assert report["reason_code"] == "specific_risk_unavailable"
    assert report["specific_risk"].loc[
        report["specific_risk"]["instrument_id"] == "ETF7", "specific_vol_ann"
    ].isna().all()


def test_optimiser_rejects_non_overlapping_covariance_history() -> None:
    returns = pd.DataFrame({"A": [0.01, np.nan], "B": [np.nan, 0.02]})

    solution = PortfolioOptimiser(returns).solve("minimum_variance")

    assert solution.status == "unavailable"
    assert solution.diagnostics["reason_code"] == "covariance_unavailable"
    assert solution.weights.empty


def test_optimiser_rejects_missing_expected_returns() -> None:
    returns = pd.DataFrame(
        np.arange(60, dtype=float).reshape(20, 3) / 10000.0,
        columns=["A", "B", "C"],
    )

    solution = PortfolioOptimiser(returns).solve(
        "robust_mean_risk", expected_returns={"A": 0.05, "B": 0.02}
    )

    assert solution.status == "unavailable"
    assert solution.diagnostics["reason_code"] == "expected_returns_unavailable"
    assert "missing_expected_returns" in solution.warnings[0]


def test_crowding_marks_shared_covariance_unavailable_for_disjoint_history() -> None:
    dates = pd.date_range("2026-01-01", periods=120, freq="D")
    prices = pd.DataFrame(index=dates, columns=["A", "B"], dtype=float)
    prices.loc[dates[:70], "A"] = np.linspace(100.0, 120.0, 70)
    prices.loc[dates[50:], "B"] = np.linspace(100.0, 90.0, 70)

    report = build_correlation_clusters(prices, window=120, weights={"A": 0.5, "B": 0.5})

    assert report.status == "partial"
    assert "covariance is unavailable" in report.reason
    assert all(row.cluster_risk_contribution is None for row in report.rows)
    assert all(row.crowding_warning == "risk_covariance_unavailable" for row in report.rows)


def test_backtest_excludes_prelisting_prices_instead_of_recording_zero_returns() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    first_instrument = config.universe.enabled_ids[0]
    dates = pd.to_datetime(prices["date"]).drop_duplicates().sort_values().reset_index(drop=True)
    prelisting_date = dates.iloc[99]
    listing_date = dates.iloc[100]
    prices = prices.loc[
        ~(
            (prices["etf_id"] == first_instrument)
            & (pd.to_datetime(prices["date"]) < listing_date)
        )
    ].copy()

    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert report.metadata["date_range_start"] == listing_date.date()
    assert report.metadata["missing_observation_rows"] >= 100
    assert prelisting_date not in report.equity_curves.index
    assert report.metadata["forward_fill_used"] is False


def test_backtest_first_complete_price_row_is_warmup_only() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    raw = prices.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
    columns = [column for column in config.universe.enabled_ids if column in raw.columns]
    first_complete_date = pd.Timestamp(raw.reindex(columns=columns).dropna().index[0])

    report = run_backtest(
        config,
        prices,
        initial_value_eur=10_000.0,
        rebalance_frequency_days=42,
    )

    assert first_complete_date not in report.equity_curves.index
    assert not pd.to_datetime(report.trade_log["signal_date"]).eq(first_complete_date).any()
    assert not pd.to_datetime(report.trade_log["execution_date"]).eq(first_complete_date).any()
    assert (report.equity_curves.iloc[0] == 10_000.0).all()


def test_credit_reconciliation_does_not_assume_missing_stage3_flows_are_zero() -> None:
    result = credit_reconciliation(
        opening_stage3=100.0,
        new_stage3=10.0,
        cured_stage3=None,
        repaid_stage3=5.0,
        written_off_stage3=2.0,
    )

    assert result.closing_stage3 is None
    assert result.warning == "stage3_flow_inputs_incomplete"


def test_capitalisation_rejects_missing_rd_disclosure() -> None:
    statements = _statements()
    statements = statements.loc[
        ~(
            statements["canonical_metric"].eq("research_and_development")
            & statements["fiscal_year"].eq(2026)
        )
    ].copy()

    report = capital_efficiency_analysis(
        statements,
        instrument_id="ACME",
        tax_rate=0.25,
        intangible_assumptions={"enabled": True},
    )

    assert report["adjusted"]["status"] == "unavailable"
    assert "intangible_input_unavailable" in report["adjusted"]["reason"]


def test_rebalancing_defers_sale_when_tax_lot_gains_are_unparseable() -> None:
    config = load_config()
    holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0, "quantity": 40.0, "price_eur": 1_000.0},
            {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": 1_000.0},
        ]
    )
    tax_lots = pd.DataFrame(
        [{"instrument_id": "VWCE", "market_value_eur": 40_000.0, "unrealised_gain_eur": "unparseable"}]
    )

    report = build_rebalance_report(
        config,
        holdings,
        {"VWCE": 0.2, "LYP6": 0.7},
        target_cash_weight=0.1,
        constraints=RebalanceConstraints(tax_rate=0.25, tax_jurisdiction="AU"),
        tax_lots=tax_lots,
    )

    vwce = next(item for item in report.trades if item.instrument_id == "VWCE")
    assert vwce.status == "deferred_tax_lot_gains_unavailable"
    assert vwce.trade_value_eur == 0.0
    assert vwce.estimated_tax_eur == 0.0
    assert report.tax_status == "unavailable"
    assert "tax_lot_gains_unavailable" in report.warnings


@pytest.mark.parametrize(
    "tax_lot,expected_reason",
    [
        (
            {"instrument_id": "VWCE", "market_value_eur": 40_000.0, "unrealised_gain_eur": -np.inf},
            "non_finite_gain",
        ),
        (
            {"instrument_id": "VWCE", "unrealised_gain_eur": 10_000.0},
            "missing_market_value",
        ),
        (
            {"instrument_id": "VWCE", "market_value_eur": 0.0, "unrealised_gain_eur": 10_000.0},
            "zero_market_value",
        ),
        (
            {"instrument_id": "VWCE", "market_value_eur": np.inf, "unrealised_gain_eur": 10_000.0},
            "non_finite_market_value",
        ),
    ],
)
def test_rebalancing_defers_sale_for_invalid_tax_coverage_inputs(
    tax_lot: dict[str, object], expected_reason: str
) -> None:
    config = load_config()
    holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.4, "market_value_eur": 40_000.0, "quantity": 40.0, "price_eur": 1_000.0},
            {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0, "quantity": 20.0, "price_eur": 1_000.0},
        ]
    )

    report = build_rebalance_report(
        config,
        holdings,
        {"VWCE": 0.2, "LYP6": 0.7},
        target_cash_weight=0.1,
        constraints=RebalanceConstraints(tax_rate=0.25, tax_jurisdiction="AU"),
        tax_lots=pd.DataFrame([tax_lot]),
    )

    vwce = next(item for item in report.trades if item.instrument_id == "VWCE")
    assert vwce.status == "deferred_tax_lot_gains_unavailable", expected_reason
    assert vwce.trade_value_eur == 0.0
    assert vwce.estimated_tax_eur == 0.0
    assert report.tax_status == "unavailable"
    assert "tax_lot_gains_unavailable" in report.warnings
