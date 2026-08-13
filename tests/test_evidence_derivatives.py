from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.features.regime import build_benchmark_attribution_lookup, build_market_regime, build_portfolio_fit_lookup
from etf_cockpit.models.calibration import calibration_lookup, evaluate_forecast_calibration
from etf_cockpit.signals.strategy_templates import strategy_template_labels, template_description


def _available_reference() -> dict[str, object]:
    return {
        "status": "available",
        "registry_hash": "r" * 64,
        "benchmark_data_id": "BENCH",
        "benchmark": {"status": "available", "content_hash": "b" * 64},
        "cash": {"status": "available", "content_hash": "c" * 64},
        "peer_set": {"status": "unavailable", "content_hash": None},
        "selected_records": {
            "benchmark": "b" * 64,
            "cash": "c" * 64,
            "peer_set": None,
        },
        "analysis": {
            "start_date": "2025-01-01",
            "end_date": "2026-12-31",
            "decision_time": "2026-12-31T23:59:59Z",
        },
        "execution_allowed": False,
    }


def test_forecast_calibration_scores_matured_local_forecasts() -> None:
    dates = pd.bdate_range("2026-01-01", periods=90)
    prices = pd.DataFrame(
        {
            "date": dates,
            "etf_id": ["ABC"] * len(dates),
            "adjusted_close": [100.0 + i for i in range(len(dates))],
        }
    )
    forecasts = pd.DataFrame(
        [
            {
                "model_name": "baseline",
                "etf_id": "ABC",
                "forecast_date": "2026-01-15",
                "horizon_days": 20,
                "expected_return": 0.18,
                "q10_return": 0.05,
                "q90_return": 0.35,
                "status": "ok",
                "model_allowed_in_score": True,
            },
            {
                "model_name": "baseline",
                "etf_id": "ABC",
                "forecast_date": "2026-02-02",
                "horizon_days": 20,
                "expected_return": 0.16,
                "q10_return": 0.04,
                "q90_return": 0.30,
                "status": "ok",
                "model_allowed_in_score": True,
            },
            {
                "model_name": "baseline",
                "etf_id": "ABC",
                "forecast_date": "2026-02-16",
                "horizon_days": 20,
                "expected_return": 0.14,
                "q10_return": 0.03,
                "q90_return": 0.25,
                "status": "ok",
                "model_allowed_in_score": True,
            },
        ]
    )

    calibration = evaluate_forecast_calibration(forecasts, prices)
    lookup = calibration_lookup(calibration)

    assert calibration.loc[0, "matured_forecasts"] == 3
    assert calibration.loc[0, "oos_mase"] is not None
    assert calibration.loc[0, "oos_directional_accuracy"] == 1.0
    assert lookup["ABC"]["score"] is not None


def test_market_regime_and_portfolio_fit_are_yfinance_price_based() -> None:
    dates = pd.bdate_range("2025-01-01", periods=260)
    rows = []
    for instrument_id, slope in (("BENCH", 0.20), ("ALT", 0.10)):
        for index, dt in enumerate(dates):
            rows.append({"date": dt, "etf_id": instrument_id, "adjusted_close": 100.0 + index * slope})
    prices = pd.DataFrame(rows)
    candidates = pd.DataFrame({"instrument_id": ["XYZ"], "sma200_signal": [True]})

    reference = _available_reference()
    regime = build_market_regime(
        prices, candidates, benchmark_id="BENCH", benchmark_reference=reference
    )
    fit = build_portfolio_fit_lookup(prices, benchmark_id="BENCH", benchmark_reference=reference)

    assert regime["regime_score_10"] is not None
    assert regime["regime_label"] in {"Supportive", "Caution", "Defensive review"}
    assert fit["ALT"]["score"] is not None


def test_benchmark_attribution_uses_overlapping_yfinance_returns() -> None:
    dates = pd.bdate_range("2025-01-01", periods=260)
    rows = []
    for index, dt in enumerate(dates):
        rows.append({"date": dt, "etf_id": "BENCH", "adjusted_close": 100.0 + index * 0.20})
        rows.append({"date": dt, "etf_id": "ALT", "adjusted_close": 100.0 + index * 0.35})
    prices = pd.DataFrame(rows)

    attribution = build_benchmark_attribution_lookup(
        prices, window=120, benchmark_id="BENCH", benchmark_reference=_available_reference()
    )
    alt = attribution["ALT"]

    assert alt["benchmark_id"] == "BENCH"
    assert alt["period_days"] == 120
    assert alt["instrument_return"] is not None
    assert alt["benchmark_return"] is not None
    assert alt["beta_to_benchmark"] is not None
    assert alt["correlation_to_benchmark"] is not None
    assert alt["alpha_proxy"] is not None
    assert "does not prove causality" in alt["label"]


def test_benchmark_attribution_short_history_is_pending() -> None:
    dates = pd.bdate_range("2026-01-01", periods=30)
    prices = pd.DataFrame(
        [
            {"date": dt, "etf_id": instrument_id, "adjusted_close": 100.0 + index}
            for index, dt in enumerate(dates)
            for instrument_id in ("BENCH", "ALT")
        ]
    )

    attribution = build_benchmark_attribution_lookup(
        prices, window=120, benchmark_id="BENCH", benchmark_reference=_available_reference()
    )

    assert attribution["ALT"]["instrument_return"] is None
    assert "pending" in attribution["ALT"]["label"].lower()


def test_benchmark_attribution_uses_same_overlapping_horizon_for_instrument_and_benchmark() -> None:
    dates = pd.bdate_range("2025-01-01", periods=140)
    rows = []
    for index, dt in enumerate(dates):
        rows.append({"date": dt, "etf_id": "BENCH", "adjusted_close": 100.0 + index})
        if index >= 40:
            rows.append({"date": dt, "etf_id": "ALT", "adjusted_close": 200.0 + (index - 40) * 2.0})
    prices = pd.DataFrame(rows)

    attribution = build_benchmark_attribution_lookup(
        prices, window=120, benchmark_id="BENCH", benchmark_reference=_available_reference()
    )
    alt = attribution["ALT"]
    # ALT overlaps the benchmark from its first clean date; the displayed
    # return must not use an instrument-only horizon that starts elsewhere.
    assert alt["instrument_return"] == round((398.0 / 200.0) - 1.0, 4)


def test_metadata_cannot_bypass_canonical_peer_selection() -> None:
    dates = pd.bdate_range("2025-01-01", periods=140)
    rows = []
    for index, dt in enumerate(dates):
        rows.extend(
            [
                {"date": dt, "etf_id": "BENCH", "adjusted_close": 100.0 + index * 0.2},
                {"date": dt, "etf_id": "AI_A", "adjusted_close": 100.0 + index * 0.3},
                {"date": dt, "etf_id": "AI_B", "adjusted_close": 100.0 + index * 0.25},
            ]
        )
    prices = pd.DataFrame(rows)

    attribution = build_benchmark_attribution_lookup(
        prices,
        window=120,
        benchmark_id="BENCH",
        benchmark_reference=_available_reference(),
        metadata={
            "AI_A": {"theme": "AI"},
            "AI_B": {"theme": "AI"},
        },
    )

    assert attribution["AI_A"]["theme_attribution_status"] == "N/A"
    assert attribution["AI_A"]["theme_relative_return"] is None
    assert attribution["AI_A"]["theme_alpha_proxy"] is None
    assert attribution["AI_A"]["sector_attribution_status"] == "N/A"


def test_peer_attribution_does_not_forward_fill_a_single_peer_observation() -> None:
    dates = pd.bdate_range("2025-01-01", periods=140)
    rows = []
    for index, dt in enumerate(dates):
        rows.append({"date": dt, "etf_id": "BENCH", "adjusted_close": 100.0 + index * 0.2})
        rows.append({"date": dt, "etf_id": "ALT", "adjusted_close": 100.0 + index * 0.3})
        if index == 0:
            rows.append({"date": dt, "etf_id": "PEER", "adjusted_close": 100.0})
    prices = pd.DataFrame(rows)

    attribution = build_benchmark_attribution_lookup(
        prices,
        window=120,
        benchmark_id="BENCH",
        benchmark_reference=_available_reference(),
        metadata={"ALT": {"sector": "Technology"}, "PEER": {"sector": "Technology"}},
    )

    assert attribution["ALT"]["sector_attribution_status"] == "N/A"
    assert attribution["ALT"]["sector_sample_size"] == 0


def test_sparse_price_compatibility_keeps_regime_and_portfolio_forward_fill_but_not_peer_attribution() -> None:
    dates = pd.bdate_range("2025-01-01", periods=260)
    rows = []
    for index, dt in enumerate(dates):
        rows.append({"date": dt, "etf_id": "BENCH", "adjusted_close": 100.0 + index * 0.20})
        if not 180 <= index < 210:
            rows.append({"date": dt, "etf_id": "ALT", "adjusted_close": 100.0 + index * 0.35})
        if index == 0:
            rows.append({"date": dt, "etf_id": "PEER", "adjusted_close": 100.0})
    prices = pd.DataFrame(rows)

    regime_prices = prices[prices["etf_id"].isin(["BENCH", "ALT"])]
    reference = _available_reference()
    regime = build_market_regime(
        regime_prices, benchmark_id="BENCH", benchmark_reference=reference
    )
    fit = build_portfolio_fit_lookup(
        regime_prices, benchmark_id="BENCH", benchmark_reference=reference
    )
    attribution = build_benchmark_attribution_lookup(
        prices,
        window=120,
        benchmark_id="BENCH",
        benchmark_reference=reference,
        metadata={"ALT": {"sector": "Technology"}, "PEER": {"sector": "Technology"}},
    )
    pivot = regime_prices.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
    forward_filled_returns = pivot.ffill().pct_change(fill_method=None)
    expected_regime_volatility = float(
        forward_filled_returns.tail(60).std(skipna=True).median() * np.sqrt(252)
    )
    assert regime["median_volatility_60d_ann"] == round(expected_regime_volatility, 4)
    expected_alt = float(
        pd.concat(
            [
                forward_filled_returns["ALT"].tail(252),
                forward_filled_returns["BENCH"].tail(252),
            ],
            axis=1,
        ).dropna().iloc[:, 0].corr(
            pd.concat(
                [
                    forward_filled_returns["ALT"].tail(252),
                    forward_filled_returns["BENCH"].tail(252),
                ],
                axis=1,
            ).dropna().iloc[:, 1]
        )
    )
    assert fit["ALT"]["correlation_to_benchmark"] == round(expected_alt, 4)
    assert fit["BENCH"]["correlation_to_benchmark"] == 1.0
    assert attribution["ALT"]["sector_attribution_status"] == "N/A"
    assert attribution["ALT"]["sector_sample_size"] == 0


def test_strategy_template_library_assigns_stock_and_etf_templates() -> None:
    etf_templates = strategy_template_labels(
        asset_type="ETF",
        evidence_score=8.0,
        risk_friction_score=7.0,
        component_scores={"momentum": 8.0, "trend": 7.0, "relative_strength": 6.0, "risk": 6.0},
        regime_label="Supportive",
    )
    stock_templates = strategy_template_labels(
        asset_type="Stock",
        evidence_score=8.0,
        risk_friction_score=6.0,
        component_scores={"momentum": 7.0, "trend": 6.0, "stock_value": 8.0, "stock_quality": 7.0},
        regime_label="Supportive",
    )

    assert "dual_momentum_etf" in etf_templates
    assert "quality_momentum_stock" in stock_templates
    assert "value_momentum_stock" in stock_templates
    assert "Stock template" in template_description(stock_templates)
