"""FEAT lane (PLAN-FIX-20261023): R1-F6 EUR close for liquidity, A04-F1..F8 feature-layer fixes. Fixtures only."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import etf_cockpit.features.macro as macro
import etf_cockpit.features.regime as regime
from etf_cockpit.core.config import load_config
from etf_cockpit.features.etf_economics import calculate_etf_liquidity
from etf_cockpit.features.feature_pipeline import compute_features, eur_basis_prices
from etf_cockpit.features.feature_store import (
    FeatureStoreError,
    LocalFeatureStore,
    TargetDefinition,
    _forward_benchmark_return,
    _prepare_benchmark,
)
from etf_cockpit.features.macro import build_macro_context
from etf_cockpit.features.regime import (
    _candidate_pct_above_sma200,
    _peer_attribution_result,
    build_market_regime,
    per_series_returns,
)

KNOWN_BY = "2026-12-31T23:59:59+00:00"


@pytest.fixture
def bound_benchmark(monkeypatch):
    monkeypatch.setattr(regime, "validate_benchmark_reference", lambda *a, **k: "BENCH")
    monkeypatch.setattr(regime, "_clip_to_reference_window", lambda prices, reference: prices.copy())


# --- R1-F6: liquidity turnover in EUR, close_local kept ------------------------------------------
def test_r1_f6_liquidity_score_uses_eur_close_and_keeps_local_close() -> None:
    days = pd.bdate_range("2025-10-01", periods=140)
    prices = pd.DataFrame(
        {"date": days, "etf_id": "NOKX", "adjusted_close": 100.0, "close": 100.0, "volume": 1000.0, "currency": "NOK"}
    )
    rates = 0.10 * np.exp(-0.002 * np.arange(len(days)))  # EUR per NOK, a falling krone
    fx = pd.DataFrame(
        {
            "as_of_date": days.date,
            "base_currency": "NOK",
            "quote_currency": "EUR",
            "rate": rates,
            "source": "fixture",
            "ingested_at": "2025-09-01T00:00:00Z",
        }
    )
    eur = eur_basis_prices(prices, fx, configured_currency={"NOKX": "NOK"}, known_by=KNOWN_BY)

    assert eur.frame["close"].iloc[-1] == pytest.approx(100.0 * rates[-1])
    assert (eur.frame["close_local"] == 100.0).all()
    local_score = compute_features(prices)["liquidity_score"].iloc[-1]
    eur_score = compute_features(eur.frame)["liquidity_score"].iloc[-1]
    assert local_score == pytest.approx(0.0)  # constant local turnover is blind to the falling krone
    assert eur_score < 0.0


# --- A04-F1 / F2 / F6: returns from unfilled prices ----------------------------------------------
def test_a04_f2_f6_returns_use_each_series_and_peer_coverage() -> None:
    index = pd.bdate_range("2026-01-01", periods=8)
    prices = pd.DataFrame(
        {"A": [100.0, 101.0, np.nan, np.nan, 104.0, 105.0, 106.0, 107.0], "B": np.arange(100.0, 108.0)}, index=index
    )
    returns = per_series_returns(prices)

    assert returns["A"].isna().sum() == 3  # first close and the two missing sessions
    assert returns["A"].iloc[4] == pytest.approx(104.0 / 101.0 - 1.0)  # multi-session return, no 0.0 on the gap
    assert not (returns["A"].dropna() == 0.0).any()
    assert returns["B"].notna().sum() == 7  # another instrument keeps every return date
    peer_index = pd.bdate_range("2025-01-01", periods=100)
    peer_returns = pd.DataFrame(
        {"X": np.full(100, 0.01), "P1": np.full(100, 0.02), "P2": np.full(100, 0.04), "P3": np.full(100, 0.08)},
        index=peer_index,
    )
    peer_returns.loc[peer_index[:30], "P3"] = np.nan
    result = _peer_attribution_result(peer_returns, "X", ["P1", "P2", "P3"], "sector", 100)
    assert result["sector_sample_size"] == 100  # skipna=False would have kept only 70 rows
    assert result["sector_attribution_status"] == "available"


def test_a04_f1_macro_regime_panel_is_not_forward_filled(monkeypatch) -> None:
    dates = pd.date_range("2024-01-01", periods=240, freq="B")
    rows = []
    for index, current in enumerate(dates):
        rows.append({"date": current, "etf_id": "BOND", "adjusted_close": 100 + index * 0.03})
        if index < len(dates) - 6:  # EQUITY is stale for the last six sessions
            rows.append({"date": current, "etf_id": "EQUITY", "adjusted_close": 100 + index * 0.2})
    captured: dict[str, pd.DataFrame] = {}

    def fake_regime(frame, *args, **kwargs):
        captured["frame"] = frame
        return {"regime_score_10": None}

    monkeypatch.setattr(macro, "build_market_regime", fake_regime)
    build_macro_context(pd.DataFrame(rows), [{"id": "EQUITY", "name": "Global equity", "asset_class": "equity"}])

    equity = captured["frame"].loc[captured["frame"]["etf_id"] == "EQUITY"]
    assert pd.Timestamp(equity["date"].max()) == pd.Timestamp(dates[-7], tz="UTC")  # the real last close, not filled


# --- A04-F5: unavailable benchmark SMA200 -> unavailable regime ----------------------------------
def test_a04_f5_benchmark_without_sma200_history_is_unavailable_not_penalised(bound_benchmark) -> None:
    days = pd.bdate_range("2025-01-01", periods=260)
    rng = np.random.default_rng(5)
    rows = []
    for etf in ("BENCH", "A", "B"):
        values = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(days))))
        for index, (day, value) in enumerate(zip(days, values)):
            if etf == "BENCH" and index < 120:  # 140 closes: enough for 60/120d returns, too few for SMA200
                continue
            rows.append({"etf_id": etf, "date": day, "adjusted_close": value})
    result = build_market_regime(pd.DataFrame(rows), benchmark_id="BENCH")

    assert result["regime_score_10"] is None
    assert result["regime_label"] == "Regime unavailable"


# --- A04-F3 / F4: ETF liquidity ------------------------------------------------------------------
def _history(rows: int = 80, instrument: str = "VWCE", currency: str = "EUR") -> pd.DataFrame:
    dates = pd.date_range("2026-04-01", periods=rows, freq="B")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "etf_id": instrument,
            "open": close - 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "adjusted_close": close,
            "volume": 10_000.0,
            "currency": currency,
        }
    )


def test_a04_f3_missing_volume_is_never_zero_filled() -> None:
    config = load_config()
    all_nan = _history().assign(volume=np.nan)
    report = calculate_etf_liquidity(config, all_nan, "VWCE", order_value_eur=10_000)
    assert report.rolling_turnover_eur_20d is None
    assert report.median_daily_volume_20d is None
    assert report.exchange_capacity_eur is None
    assert report.capacity_status == "blocked_missing_liquidity"
    assert "turnover" in report.missing_evidence

    partial = _history()
    partial.loc[partial.index[-10:], "volume"] = np.nan  # half of the last 20 sessions
    reference = calculate_etf_liquidity(config, _history(), "VWCE")
    report = calculate_etf_liquidity(config, partial, "VWCE")
    assert report.median_daily_volume_20d == pytest.approx(10_000.0)  # zero-fill would give 5_000
    assert report.rolling_turnover_eur_20d is not None
    assert report.rolling_turnover_eur_20d != 0.0
    assert report.exchange_capacity_eur is not None
    assert reference.exchange_capacity_eur is not None


def test_a04_f4_price_scope_applies_known_at_and_all_identity_columns() -> None:
    config = load_config()
    history = _history(rows=40)
    cutoff_date = history["date"].iloc[30]
    history["known_at"] = history["date"] + pd.Timedelta(hours=18)
    revised = history.iloc[[30]].copy()
    revised["close"] = 999.0
    revised["known_at"] = cutoff_date + pd.Timedelta(days=3)  # a revision learned after the as_of
    history = pd.concat([history, revised], ignore_index=True)
    history["instrument_id"] = "VWCE"
    history.loc[history.index[5], "instrument_id"] = "OTHER"  # conflicting identity columns: row rejected

    report = calculate_etf_liquidity(config, history, "VWCE", as_of=cutoff_date.date())

    assert report.latest_price == pytest.approx(130.0)  # the 999 revision was not known at the as_of
    assert report.rows == 30  # rows 0..30 minus the identity-conflicting row, the future revision dropped
    usd_history = _history(instrument="ZZUSD", currency="USD")
    latest = usd_history["date"].iloc[-1]
    fx = pd.DataFrame(
        {
            "as_of_date": [latest.date()],
            "base_currency": "USD",
            "quote_currency": "EUR",
            "rate": [0.9],
            "source": "fixture",
            "ingested_at": [(latest + pd.Timedelta(hours=16)).isoformat() + "Z"],
        }
    )
    same_day_fx = calculate_etf_liquidity(config, usd_history, "ZZUSD", fx_evidence=fx)
    assert same_day_fx.fx_status == "available"
    assert same_day_fx.rolling_turnover_eur_20d is not None


# --- A04-F7: targets ----------------------------------------------------------------------------
def test_a04_f7_targets_use_known_revisions_dedupe_and_strict_adjusted_flags(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_target(TargetDefinition("fwd1", 1))
    store.register_target(TargetDefinition("fwd2", 2))
    dates = pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-05"])
    prices = pd.DataFrame(
        {
            "etf_id": "A",
            "date": dates,
            "adjusted_close": [100.0, 150.0, 102.0, 110.0],
            "known_at": pd.to_datetime(["2026-01-01 18:00", "2026-01-04 09:00", "2026-01-02 18:00", "2026-01-05 18:00"]),
        }
    )
    targets = store.build_targets(prices, ["2026-01-01 23:00"])
    # Origin = the 100.0 revision (the 150.0 one was learned on 01-04); the duplicate date does not shift the horizon.
    assert targets.loc[0, "fwd1"] == pytest.approx(102.0 / 100.0 - 1.0)
    assert targets.loc[0, "fwd2"] == pytest.approx(110.0 / 100.0 - 1.0)

    unadjusted = prices.assign(is_adjusted="False")
    with pytest.raises(FeatureStoreError):
        store.build_targets(unadjusted, ["2026-01-02"])
    benchmark = pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-04-01"], "adjusted_close": [100.0, 101.0, 102.0, 160.0]}
    )
    prepared = _prepare_benchmark(benchmark, "date", "adjusted_close")
    assert _forward_benchmark_return(prepared, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-04-01")) == pytest.approx(0.60)
    # A benchmark close on an earlier date cannot stand in for the instrument's target end date.
    assert _forward_benchmark_return(prepared.iloc[:2], pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")) is None
    assert _forward_benchmark_return(prepared, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")) == pytest.approx(0.02)


# --- A04-F8: candidate breadth needs a knowledge time --------------------------------------------
def test_a04_f8_candidate_rows_without_known_at_stay_unavailable() -> None:
    no_known_at = pd.DataFrame([{"sma200_signal": True, "as_of": "2024-01-02", "source_id": "fixture"}])
    assert _candidate_pct_above_sma200(no_known_at, decision_time="2024-02-01T00:00:00+00:00") is None
    known = no_known_at.assign(known_at="2024-01-02")
    assert _candidate_pct_above_sma200(known, decision_time="2024-01-03") == 1.0
    assert _candidate_pct_above_sma200(known, decision_time="2024-01-02") is None  # same-day date-only boundary


# --- RV-SG review findings (feature store, economics) --------------------------------------------
def test_rv_sg_6_benchmark_origin_uses_the_revision_known_at_the_decision() -> None:
    benchmark = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02"],
            "adjusted_close": [100.0, 200.0, 110.0, 110.0],
            "known_at": ["2026-01-01 18:00", "2026-01-04 09:00", "2026-01-02 18:00", "2026-01-02 18:00"],
        }
    )
    decision, end = pd.Timestamp("2026-01-01 23:00"), pd.Timestamp("2026-01-02")
    prepared = _prepare_benchmark(benchmark, "date", "adjusted_close")
    # The 200.0 revision was learned after the decision: the origin stays 100.0.
    assert _forward_benchmark_return(prepared, decision, end) == pytest.approx(0.10)
    shuffled = _prepare_benchmark(benchmark.iloc[::-1].reset_index(drop=True), "date", "adjusted_close")
    assert _forward_benchmark_return(shuffled, decision, end) == pytest.approx(0.10)  # input order is irrelevant
    unknown = benchmark.assign(known_at="2026-01-04")  # nothing known at the decision: unavailable, not the revised close
    assert _forward_benchmark_return(_prepare_benchmark(unknown, "date", "adjusted_close"), decision, end) is None


def test_rv_sg_6_build_targets_excess_return_ignores_a_benchmark_revised_after_the_decision(tmp_path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_target(TargetDefinition("ex1", 1, kind="excess_return"))
    prices = pd.DataFrame({"etf_id": "A", "date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "adjusted_close": [100.0, 120.0]})
    benchmark = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02"]),
            "adjusted_close": [100.0, 400.0, 110.0],
            "known_at": pd.to_datetime(["2026-01-01 18:00", "2026-01-09 09:00", "2026-01-02 18:00"]),
        }
    )
    targets = store.build_targets(prices, ["2026-01-01 23:00"], benchmark_prices=benchmark)
    assert targets.loc[0, "ex1"] == pytest.approx(0.20 - 0.10)


def test_rv_sg_7_liquidity_volatility_keeps_missing_adjusted_close_unavailable() -> None:
    config = load_config()
    gap = _history()
    gap.loc[gap.index[-30], "adjusted_close"] = np.nan  # positive close, missing adjusted close
    report = calculate_etf_liquidity(config, gap, "VWCE")
    adjusted = pd.to_numeric(gap["adjusted_close"], errors="coerce")
    expected = adjusted.pct_change(fill_method=None).dropna().tail(60).std()
    zero_filled = adjusted.pct_change(fill_method="pad").dropna().tail(60).std()
    assert expected != pytest.approx(zero_filled)
    assert report.daily_volatility == pytest.approx(expected)
