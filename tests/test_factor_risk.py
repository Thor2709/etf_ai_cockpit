from __future__ import annotations

import inspect
import numpy as np
import pandas as pd

from etf_cockpit.portfolio.factor_risk import (
    FACTOR_MODEL_VERSION,
    _lookthrough_map,
    build_factor_exposures,
    build_factor_risk_report,
)


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(19)
    dates = pd.bdate_range("2025-01-01", periods=100)
    market = rng.normal(0.0002, 0.006, len(dates))
    momentum = np.linspace(-1.0, 1.0, 8)
    low_volatility = np.linspace(1.0, -1.0, 8)
    rows: list[dict[str, object]] = []
    allocation_rows: list[dict[str, object]] = []
    features: list[dict[str, object]] = []
    for index in range(8):
        instrument_id = f"ETF{index}"
        residual = rng.normal(0.0, 0.002 + index * 0.0001, len(dates))
        log_returns = market + 0.0015 * momentum[index] + 0.001 * low_volatility[index] + residual
        prices = 100 * np.exp(np.cumsum(log_returns))
        rows.extend({"date": dt.date(), "etf_id": instrument_id, "adjusted_close": float(price)} for dt, price in zip(dates, prices))
        allocation_rows.append({"etf_id": instrument_id, "current_weight": 0.125, "market_value_eur": 1_000 + index * 250})
        features.append({"etf_id": instrument_id, "date": dates[-1].date(), "momentum_120d": momentum[index], "vol_60d_ann": -low_volatility[index]})
    return pd.DataFrame(rows), pd.DataFrame(allocation_rows), pd.DataFrame(features)


def test_factor_model_reports_exposures_returns_covariance_specific_risk_and_reconciled_components() -> None:
    prices, allocation, features = _fixture()

    report = build_factor_risk_report(prices, allocation, features)

    assert report["model_version"] == FACTOR_MODEL_VERSION
    assert report["status"] in {"available", "partial"}
    assert report["execution_allowed"] is False
    assert {"market", "momentum"}.issubset(set(report["factor_returns"]["factor"]))
    covariance = report["factor_covariance"].to_numpy(float)
    assert np.all(np.linalg.eigvalsh(covariance) >= -1e-12)
    assert len(report["specific_risk"]) == 8
    assert abs(report["portfolio"]["component_share_sum"] - 1.0) < 1e-9
    assert abs(report["portfolio_contributions"]["variance_share"].sum() - 1.0) < 1e-9
    assert report["diagnostics"]["baseline_beta"]


def test_factor_exposures_use_full_lookthrough_weights_and_report_coverage() -> None:
    _prices, allocation, _features = _fixture()
    allocation["sector"] = "Technology"
    allocation["region"] = "United States"
    allocation["currency"] = "USD"
    holdings = pd.DataFrame(
        [
            {"instrument_id": "ETF0", "weight": 0.6, "sector": "Technology", "region": "United States", "currency": "USD"},
            {"instrument_id": "ETF0", "weight": 0.4, "sector": "Healthcare", "region": "United States", "currency": "USD"},
        ]
    )

    exposures = build_factor_exposures(allocation, holdings=holdings)
    lookthrough = build_factor_risk_report(_prices, allocation, holdings=holdings)["coverage"]["lookthrough"]
    industry = exposures[(exposures["instrument_id"] == "ETF0") & exposures["factor"].str.startswith("industry:")]

    assert set(industry["factor"]) == {"industry:Healthcare", "industry:Technology"}
    assert abs(industry["exposure"].sum() - 1.0) < 1e-12
    assert lookthrough["dimensions"]["industry"]["full_coverage"] is True


def test_lookthrough_rejects_boolean_and_nonfinite_weights() -> None:
    holdings = pd.DataFrame(
        [
            {"instrument_id": "ETF0", "weight": np.bool_(True), "sector": "Technology"},
            {"instrument_id": "ETF0", "weight": float("inf"), "sector": "Healthcare"},
        ]
    )

    assert _lookthrough_map(holdings) == {}


def test_lookthrough_rejects_aggregate_weight_above_tolerance() -> None:
    holdings = pd.DataFrame(
        [
            {"instrument_id": "ETF0", "weight": 1.0, "sector": "Technology"},
            {"instrument_id": "ETF0", "weight": 1.0, "sector": "Healthcare"},
        ]
    )

    assert _lookthrough_map(holdings) == {}


def test_constant_or_undercovered_factors_are_excluded_with_a_reason() -> None:
    _prices, allocation, features = _fixture()
    features["quality_score_10"] = 5.0

    report = build_factor_risk_report(_prices, allocation, features)

    assert "quality" in report["diagnostics"]["excluded_factors"]
    assert "constant_exposure" == report["diagnostics"]["excluded_factors"]["quality"]
    assert "some_factors_excluded_for_coverage_or_rank" in report["warnings"]


def test_public_factor_series_is_compared_when_supplied() -> None:
    prices, allocation, features = _fixture()
    initial = build_factor_risk_report(prices, allocation, features)
    public = initial["factor_returns"][["date", "factor", "factor_return"]].rename(columns={"factor_return": "factor_return"})

    report = build_factor_risk_report(prices, allocation, features, public_factors=public)

    assert report["diagnostics"]["public_factor_validation"]["status"] == "available"
    assert report["diagnostics"]["public_factor_validation"]["rows"]


def test_risk_workspace_surfaces_factor_model_evidence_and_exports() -> None:
    from etf_cockpit.app.pages.risk import risk_page

    source = inspect.getsource(risk_page)
    assert "build_factor_risk_report" in source
    assert "risk_factor_contributions.csv" in source
    assert "risk_factor_returns.csv" in source


def test_risk_workspace_surfaces_performance_attribution() -> None:
    from etf_cockpit.app.pages.risk import risk_page

    source = inspect.getsource(risk_page)
    assert "build_performance_attribution" in source
    assert "risk.export-performance-attribution" in source
