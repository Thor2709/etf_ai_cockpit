"""Bug-hunt S3 reproductions (strict xfail: each asserts the CORRECT behaviour)."""

from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace as N

import pandas as pd
import pytest

import etf_cockpit.signals.simple_scores as s
from etf_cockpit.core.config import (
    CostConfig,
    DataProvidersConfig,
    ETFConfig,
    UniverseConfig,
)
from etf_cockpit.core.types import ComponentScores, SignalResult
from etf_cockpit.features.drawdown import rolling_max_drawdown
from etf_cockpit.features.etf_economics import calculate_etf_liquidity
from etf_cockpit.models.calibration import evaluate_forecast_calibration
from etf_cockpit.signals.canonical_scoring import canonical_score_from_signal_row
from etf_cockpit.signals.friction_edge import estimate_friction_adjusted_return


def test_s3_01_valid_score_evidence_passes_authority():
    components = s._attach_component_provenance(
        [s._component("momentum", 1.0, ""), s._component("etf_exposure", 1.0, "")],
        "2026-01-01",
        date(2026, 1, 1),
    )
    assert all(c.score_eligible for c in components)
    score = s.SimpleInstrumentScore(
        "X", "X", "Primary tier", "ETF", "X", "X", "2026-01-01",
        100.0, 9.0, "Positive", "", components, [],
        backtest_validity="usable_low_authority",
    )
    decision = s._attach_authority(score).authority_decision
    assert next(g for g in decision.gates if g.gate_id == "evidence").passed


def test_s3_02_log_forecast_units_are_respected():
    p = pd.DataFrame({
        "etf_id": ["X"] * 5,
        "date": pd.date_range("2026-01-01", periods=5),
        "adjusted_close": [100, 110, 110, 110, 110],
    })
    f = pd.DataFrame([dict(
        etf_id="X", model_name="baseline", forecast_date="2026-01-01", horizon_days=1,
        expected_return=math.log(1.1), q10_return=math.log(1.099), q90_return=math.log(1.101),
        status="ok", model_allowed_in_score=True,
    )])
    c = evaluate_forecast_calibration(f, p).iloc[0]
    assert c.q10_q90_coverage == 1
    assert c.oos_mase == pytest.approx(0)
    r = estimate_friction_adjusted_return(
        dict(q10_return=math.log(1.099), q50_return=math.log(1.1),
             q90_return=math.log(1.101), horizon_days=1),
        order_value_eur=10000,
        cost_estimate=dict(order_value_eur=10000, total_cost_bps=100, total_cost_eur=100),
    )
    assert r.net_expected_return == pytest.approx(0.09)


def test_s3_03_future_holdings_cannot_support_historical_score(monkeypatch):
    h = pd.DataFrame({"etf_id": ["VWCE"], "weight": [1.0], "as_of_date": ["2026-10-05"]})
    monkeypatch.setattr(s, "load_reference_dataset", lambda *_: h)
    info = s._etf_exposure_lookup()["VWCE"]
    c = s._attach_component_provenance(
        [s._etf_exposure_component(info)], "2026-01-20", date(2026, 1, 20)
    )[0]
    assert not c.score_eligible


def test_s3_04_future_peer_does_not_change_known_candidate(monkeypatch):
    monkeypatch.setattr(s, "_etf_exposure_lookup", dict)
    a = dict(
        instrument_id="A", asset_type="ETF", latest_date="2026-01-20", latest_price=100.0,
        rows=504, return_6m=0.1, return_3m=0.1, return_12m=0.1, sma50_signal=True,
        sma200_signal=True, volatility_60d_ann=0.1, current_drawdown=-0.01,
    )
    b = dict(a, instrument_id="B", latest_date="2026-02-20", return_6m=0.9)

    def score(rows):
        result = s.build_candidate_simple_scores(
            pd.DataFrame(rows), pd.DataFrame(), decision_date=date(2026, 1, 20)
        )
        return next(x for x in result if x.display_id == "A")

    assert score([a]).final_score_10 == score([a, b]).final_score_10


def test_s3_05_non_eur_capacity_requires_fx_evidence():
    p = pd.DataFrame({
        "etf_id": ["VUSA"] * 20,
        "date": pd.date_range("2026-01-01", periods=20),
        "close": [10.0] * 20,
        "adjusted_close": [10.0] * 20,
        "volume": [1000.0] * 20,
        "currency": ["GBP"] * 20,
    })
    cfg = N(
        costs=CostConfig(),
        universe=UniverseConfig(etfs=[ETFConfig(
            id="VUSA", name="VUSA", ticker="VUSA.L", role="core", currency="GBP")]),
    )
    r = calculate_etf_liquidity(cfg, p, "VUSA", order_value_eur=1100)
    assert r.exchange_capacity_eur is None
    assert r.rolling_turnover_eur_20d is None
    assert r.capacity_status == "blocked_missing_liquidity"
    assert "fx_rate_to_eur" in r.missing_evidence


def test_s3_05_eur_quoted_instrument_keeps_capacity():
    p = pd.DataFrame({
        "etf_id": ["VWCE"] * 20,
        "date": pd.date_range("2026-01-01", periods=20),
        "close": [10.0] * 20,
        "adjusted_close": [10.0] * 20,
        "volume": [1000.0] * 20,
        "currency": ["EUR"] * 20,
    })
    cfg = N(
        costs=CostConfig(),
        universe=UniverseConfig(etfs=[ETFConfig(
            id="VWCE", name="VWCE", ticker="VWCE.DE", role="core", currency="EUR")]),
    )
    r = calculate_etf_liquidity(cfg, p, "VWCE", order_value_eur=100)
    assert r.exchange_capacity_eur == pytest.approx(1000.0)


def test_s3_06_peak_outside_window_does_not_affect_rolling_drawdown():
    p = pd.Series([100.0] + [50.0] * 200 + [50.0 + 0.01 * i for i in range(1, 61)])
    assert rolling_max_drawdown(p, 60).iloc[-1] == pytest.approx(0.0)


def test_s3_06_drawdown_is_peak_to_trough_inside_window():
    p = pd.Series([10.0, 12.0, 6.0, 8.0, 9.0])
    out = rolling_max_drawdown(p, 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(-0.5)
    assert out.iloc[3] == pytest.approx(-0.5)
    assert out.iloc[4] == pytest.approx(0.0)


def test_s3_07_baseline_ensemble_weight_is_preserved():
    config = N(models=N(ensemble={"weights": {"momentum": 0.5, "baseline_ml": 0.5}}))
    score = canonical_score_from_signal_row(
        {"etf_id": "X", "score_momentum": 0.0, "score_baseline_ml": 1.0}, config, "2026-01-01"
    )
    assert score.legacy_composite_raw == pytest.approx(0.5)


def test_s3_08_configured_stock_uses_stock_policy(monkeypatch):
    monkeypatch.setattr(s, "_etf_exposure_lookup", dict)
    cfg = N(
        universe=UniverseConfig(etfs=[ETFConfig(
            id="UCG", name="UniCredit", ticker="UCG.MI", role="core", instrument_type="stock")]),
        costs=CostConfig(),
        data_providers=DataProvidersConfig(),
    )
    comp = ComponentScores(1.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    sig = SignalResult("r", date(2026, 1, 20), "UCG", "hold", 0.8, 1.0, comp, [], [], "", "", "3M")
    p = pd.DataFrame({
        "etf_id": ["UCG"] * 504,
        "date": pd.bdate_range(end="2026-01-20", periods=504),
        "adjusted_close": [100.0] * 504,
        "close": [100.0] * 504,
        "volume": [1000000.0] * 504,
    })
    score = s.build_universe_simple_scores(cfg, [sig], pd.DataFrame(), p)[0]
    assert "dual_momentum_etf" not in score.strategy_templates
    assert not any(c.key == "etf_exposure" for c in score.components)
