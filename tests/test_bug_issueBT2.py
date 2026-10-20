"""#BT2 backtest V8 items (engine, metrics, benchmarks, costs) and the BT1 binding decisions."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

import etf_cockpit.application.backtest_service as backtest_service
import etf_cockpit.application.economics_inputs as economics_inputs
import etf_cockpit.application.structural_evidence as structural_evidence
from etf_cockpit.application.derived_cache import _universe_cache_meta_path
from etf_cockpit.backtest.benchmarks import investable_comparator_summary, momentum_weights
from etf_cockpit.backtest.engine import (
    BacktestDataUnavailableError,
    SURVIVORSHIP_CONDITIONAL,
    SURVIVORSHIP_FULL,
    _parameter_sensitivity_status,
    ai_added_value_vs_baseline,
    overall_quality_label,
    run_backtest,
)
from etf_cockpit.backtest.metrics import performance_metrics
from etf_cockpit.core.config import load_config
from etf_cockpit.data.etf_structure import LocalStructuralEvidence
from etf_cockpit.data.fx_data import sample_fx_rates
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.portfolio.costs import estimate_execution_cost, estimate_rebalance_cost
from etf_cockpit.signals.canonical_scoring import load_score_policy

END = pd.Timestamp("2026-06-26").date()
PIT_EVIDENCE = {"status": "point_in_time_verified", "source_id": "membership-fixture"}


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture(scope="module")
def prices(config) -> pd.DataFrame:
    return generate_sample_prices(config, periods=340, end_date=END)


@pytest.fixture(scope="module")
def default_report(config, prices):
    return run_backtest(config, prices, rebalance_frequency_days=42)


@pytest.fixture(scope="module")
def capacity_report(config, prices):
    return run_backtest(config, prices.assign(volume=1e9), rebalance_frequency_days=42, enforce_capacity=True)


def _certificate_ids(config) -> set[str]:
    return {
        item.id for item in config.universe.etfs if str(item.instrument_type or "").casefold() == "equity_certificate"
    }


# --- V8 items ---------------------------------------------------------------


def test_s17_n001_cache_miss_forwards_as_of_date_to_the_fresh_run(config, prices, monkeypatch, tmp_path) -> None:
    seen: dict[str, pd.Timestamp] = {}

    def fake_regimes(_config, run_prices, **_kwargs):
        seen["last_session"] = pd.to_datetime(run_prices["date"]).max()
        raise BacktestDataUnavailableError("stop after capturing the price window")

    sessions = sorted(pd.to_datetime(prices["date"]).unique())
    as_of = pd.Timestamp(sessions[200]).date()
    monkeypatch.setattr(backtest_service, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(backtest_service, "load_prices", lambda **_kwargs: prices.copy())
    monkeypatch.setattr(backtest_service, "load_fundamental_evidence", pd.DataFrame)
    monkeypatch.setattr(
        backtest_service,
        "_load_local_structural_evidence",
        lambda: LocalStructuralEvidence(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(backtest_service, "_open_backtest_calendar_identity_resolver", lambda: (None, None))
    monkeypatch.setattr(backtest_service, "run_backtest_cost_regimes", fake_regimes)

    report = backtest_service.BacktestService(config, universe_revision="bt2").load_or_run_backtest(as_of_date=as_of)

    assert report.results.empty
    assert seen["last_session"].date() <= as_of  # later sessions never reach a historical run


def test_s18_n001_cost_stress_replays_costs_at_their_trade_dates() -> None:
    index = pd.bdate_range("2026-01-05", periods=80)
    returns = 0.01 + np.where(np.arange(len(index)) % 2 == 0, 0.002, -0.002)
    equity = pd.DataFrame({"s": 1000.0 * np.cumprod(1.0 + returns)}, index=index)
    # One early cost: subtracting it from the final NAV hides that it compounds with every later gain.
    trades = [{"strategy": "s", "date": index[0].date(), "cost_eur": 700.0}]
    final = float(equity["s"].iloc[-1])
    assert final - 700.0 > float(equity["s"].iloc[0])  # the aggregate shortcut would call it stable
    assert final - 700.0 * final / float(equity["s"].iloc[0]) < float(equity["s"].iloc[0])
    assert _parameter_sensitivity_status(equity, trades, ["s"])["s"] == "mixed"
    # The same cost late in the window barely compounds and survives the stress.
    late = [{"strategy": "s", "date": index[-1].date(), "cost_eur": 700.0}]
    assert _parameter_sensitivity_status(equity, late, ["s"])["s"] == "stable"


def test_s18_n002_cost_model_identity_is_the_configured_version(config, prices) -> None:
    model = config.costs.cost_model.model_copy(update={"model_version": "execution-cost-v9"})
    patched = config.model_copy(update={"costs": config.costs.model_copy(update={"cost_model": model})})
    report = run_backtest(patched, prices, rebalance_frequency_days=42)
    assert report.metadata["cost_model_id"] == "execution-cost-v9"
    assert set(report.trade_log["cost_model_id"]) == {"execution-cost-v9"}
    assert report.metadata["investable_comparators"]["cost_model_id"] == "execution-cost-v9"


@pytest.mark.parametrize("label", ["c2_s19_n001", "c4_s24_n001"])
def test_metrics_never_bridge_an_invalid_equity_gap(label) -> None:
    index = pd.bdate_range("2026-02-02", periods=9)
    gapped = pd.Series([100.0, 101.0, 102.0, float("nan"), float("nan"), 200.0, 201.0, 202.0, 203.0], index=index)
    metrics = performance_metrics(gapped)
    # The 102 -> 200 jump spans a gap: it is not an observed return, so volatility stays that of the adjacent sessions.
    assert metrics["volatility"] < 0.5
    assert metrics["sharpe"] > 0.0
    # Only adjacent valid pairs count; a series that never has two adjacent pairs has no annualised figure.
    sparse = pd.Series([100.0, float("nan"), 110.0, float("nan"), 120.0], index=index[:5])
    assert performance_metrics(sparse)["volatility"] == 0.0


def test_s24_n001_negative_calmar_baseline_is_not_beaten_by_a_worse_signal() -> None:
    assert ai_added_value_vs_baseline(-1.02, -1.0) is False  # worse than the baseline, inside the old inverted margin
    assert ai_added_value_vs_baseline(-0.90, -1.0) is True
    assert ai_added_value_vs_baseline(1.04, 1.0) is True
    assert ai_added_value_vs_baseline(1.02, 1.0) is False
    assert ai_added_value_vs_baseline(0.01, 0.0) is True
    assert ai_added_value_vs_baseline(float("nan"), 1.0) is False


def test_c4_s24_n002_sortino_uses_downside_deviation_against_a_zero_target() -> None:
    log_returns = np.array([0.02, -0.01, 0.03, -0.02, 0.01, 0.02, 0.0, 0.015])
    equity = pd.Series(100.0 * np.exp(np.concatenate([[0.0], np.cumsum(log_returns)])))
    expected_downside = float(np.sqrt(np.mean(np.minimum(log_returns, 0.0) ** 2)) * np.sqrt(252))
    expected = float(log_returns.mean() * 252 / expected_downside)
    assert performance_metrics(equity)["sortino"] == pytest.approx(expected)


def test_c3_s18_n001_estimate_id_covers_capacity_inputs(config) -> None:
    def with_participation(rate: float):
        model = config.costs.cost_model.model_copy(update={"max_participation_rate": rate})
        patched = config.model_copy(update={"costs": config.costs.model_copy(update={"cost_model": model})})
        return estimate_execution_cost(patched, "VWCE", 5_000.0, adv_eur=1_000_000.0, daily_volatility=0.01)

    narrow, wide = with_participation(0.05), with_participation(0.20)
    assert narrow.total_cost_eur == wide.total_cost_eur and narrow.capacity_eur != wide.capacity_eur
    assert narrow.estimate_id != wide.estimate_id
    # Commission was already part of the identity.
    model = config.costs.cost_model.model_copy(update={"default_commission_eur": 9.0})
    pricey = config.model_copy(update={"costs": config.costs.model_copy(update={"cost_model": model})})
    base = estimate_execution_cost(config, "VWCE", 5_000.0)
    assert estimate_execution_cost(pricey, "VWCE", 5_000.0).estimate_id != base.estimate_id


def test_c5_s18_n001_non_finite_order_values_are_rejected_not_priced_as_free(config) -> None:
    for bad in (float("nan"), float("inf"), float("-inf"), "n/a"):
        with pytest.raises(ValueError):
            estimate_execution_cost(config, "VWCE", bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        estimate_rebalance_cost(config, 10_000.0, {"VWCE": float("nan")})
    with pytest.raises(ValueError):
        estimate_rebalance_cost(config, float("nan"), {"VWCE": 0.1})
    assert estimate_execution_cost(config, "VWCE", 0.0).total_cost_eur == 0.0
    assert estimate_execution_cost(config, "VWCE", None).total_cost_eur == 0.0  # type: ignore[arg-type]


def test_c2_s24_n002_rebalance_count_excludes_the_last_unexecutable_index(config, prices) -> None:
    enabled = prices[prices["etf_id"].isin(config.universe.enabled_ids)]
    rows = run_backtest(config, enabled, rebalance_frequency_days=10_000).metadata["complete_price_rows"]
    # Rebalance indexes are 220 and rows-1: the last one has no next session, so it never trades.
    report = run_backtest(config, enabled, rebalance_frequency_days=rows - 221)
    assert report.metadata["walk_forward_periods"] == 0
    assert (report.results["n_walk_forward_periods"] == 0).all()


def test_c3_s19_n002_overall_quality_follows_the_signal_strategy() -> None:
    def frame(signal: str, other: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "strategy_name": ["buy_and_hold", "momentum_only", "signal_strategy"],
                "backtest_quality": [other, other, signal],
            }
        )

    assert overall_quality_label(frame("low", "medium")) == "low"
    assert overall_quality_label(frame("medium", "low")) == "medium"
    assert overall_quality_label(pd.DataFrame()) == "low"


def test_c3_s19_n001_cached_quality_label_matches_the_fresh_policy(config, prices, monkeypatch, tmp_path) -> None:
    identity_path = tmp_path / "absent-identity-root" / "data" / "clean" / "instrument_identity.parquet"
    out_dir = tmp_path / "backtests"
    empty = LocalStructuralEvidence(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    monkeypatch.setattr(backtest_service, "IDENTITY_PATH", identity_path)
    monkeypatch.setattr(economics_inputs, "IDENTITY_PATH", identity_path)
    monkeypatch.setattr(backtest_service, "BACKTESTS_DIR", out_dir)
    monkeypatch.setattr(backtest_service, "load_prices", lambda **_kwargs: prices.copy())
    monkeypatch.setattr(backtest_service, "load_fundamental_evidence", pd.DataFrame)
    monkeypatch.setattr(backtest_service, "_load_local_structural_evidence", lambda: empty)
    monkeypatch.setattr(structural_evidence, "_load_local_structural_evidence", lambda: empty)
    monkeypatch.setattr(backtest_service, "ensure_run_manifest", lambda *_args, **_kwargs: {})
    service = backtest_service.BacktestService(config, universe_revision="bt2-cache")
    service.run_backtest()

    results_path = out_dir / "backtest_results.csv"
    results = pd.read_csv(results_path)
    results["backtest_quality"] = np.where(results["strategy_name"] == "signal_strategy", "medium", "low")
    assert results["strategy_name"].iloc[0] != "signal_strategy"  # the first row is not the headline strategy
    payload = results.to_csv(index=False).encode("utf-8")
    results_path.write_bytes(payload)
    sidecar_path = _universe_cache_meta_path(results_path)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    cached = service._load_cached_backtest()

    assert cached is not None
    assert cached.quality_label == overall_quality_label(cached.results) == "medium"


def test_c3_s20_n001_all_nan_momentum_gets_no_allocation() -> None:
    columns = ["A", "B", "C", "D"]
    history = pd.DataFrame(100.0, index=pd.RangeIndex(200), columns=columns)
    history.iloc[-1] = float("nan")
    weights = momentum_weights(history, columns)
    assert float(weights.abs().sum()) == 0.0
    history.iloc[-1] = [100.0, 120.0, float("nan"), 90.0]
    mixed = momentum_weights(history, columns)
    assert mixed["C"] == 0.0 and mixed["B"] > 0.0


# --- EUR feature basis ----------------------------------------------------------


def test_backtest_signal_features_use_the_eur_basis(config, prices) -> None:
    nok = "KOG"
    panel = prices.copy()
    mask = panel["etf_id"] == nok
    for column in ("open", "high", "low", "close", "adjusted_close"):
        panel.loc[mask, column] = 100.0  # flat listing-currency price
    fx = sample_fx_rates(panel)
    nok_rows = fx["base_currency"] == "NOK"
    fx.loc[nok_rows, "rate"] = 0.09 * np.exp(0.002 * np.arange(int(nok_rows.sum())))  # EURNOK moves steadily

    report = run_backtest(config, panel, rebalance_frequency_days=42, fx_rates=fx)

    rows = report.signal_log[report.signal_log["etf_id"] == nok]
    assert not rows.empty
    assert rows["momentum_60d"].notna().all() and (rows["momentum_60d"].abs() > 0.05).all()
    assert rows["momentum_60d"].iloc[-1] == pytest.approx(0.002 * 60, abs=1e-6)
    assert report.signal_log["currency_basis"].eq("EUR").all()

    unavailable = run_backtest(config, panel, rebalance_frequency_days=42, fx_rates=pd.DataFrame())
    blocked = unavailable.signal_log[unavailable.signal_log["etf_id"] == nok]
    assert blocked["momentum_60d"].isna().all()  # fx_unavailable: no feature, never the local price


# --- BT1 binding decisions --------------------------------------------------------


def test_survivorship_defaults_to_conditional_without_point_in_time_membership(config, prices, default_report) -> None:
    assert default_report.metadata["survivorship_label"] == SURVIVORSHIP_CONDITIONAL
    reasons = default_report.metadata["survivorship_reasons"]
    assert "universe_is_current_listing_set_no_point_in_time_membership_evidence" in reasons
    outside = sorted(set(prices["etf_id"]) - set(config.universe.enabled_ids))
    assert outside
    for etf_id in outside:
        assert f"panel_instrument_outside_enabled_universe_excluded: {etf_id}" in reasons


def test_survivorship_is_full_only_with_explicit_point_in_time_evidence(config, prices) -> None:
    enabled = prices[prices["etf_id"].isin(config.universe.enabled_ids)]
    verified = run_backtest(config, enabled, rebalance_frequency_days=42, point_in_time_membership_evidence=PIT_EVIDENCE)
    assert verified.metadata["survivorship_label"] == SURVIVORSHIP_FULL
    assert verified.metadata["survivorship_reasons"] == []
    for weak in ({"status": "point_in_time_verified"}, {"source_id": "x"}, {"status": "claimed", "source_id": "x"}):
        report = run_backtest(config, enabled, rebalance_frequency_days=42, point_in_time_membership_evidence=weak)
        assert report.metadata["survivorship_label"] == SURVIVORSHIP_CONDITIONAL
    # Evidence does not hide an excluded panel instrument.
    with_extra = run_backtest(config, prices, rebalance_frequency_days=42, point_in_time_membership_evidence=PIT_EVIDENCE)
    assert with_extra.metadata["survivorship_label"] == SURVIVORSHIP_CONDITIONAL
    assert not any("no_point_in_time_membership_evidence" in reason for reason in with_extra.metadata["survivorship_reasons"])


def test_initial_purchase_is_costed_for_every_strategy_without_capacity(config, default_report) -> None:
    report = default_report
    universe = report.metadata["universe_ids"]
    costs = report.metadata["initial_purchase_cost_eur"]
    assert set(costs) == set(report.metadata["strategies"])
    assert costs["equal_weight"] > 0.0 and costs["buy_and_hold"] > 0.0 and costs["signal_strategy"] > 0.0
    expected = estimate_rebalance_cost(
        config,
        10_000.0,
        {column: 1.0 / len(universe) for column in universe},
        conservative_instruments=_certificate_ids(config),
    ).total_cost_eur
    assert costs["equal_weight"] == pytest.approx(expected)
    first = report.equity_curves.dropna().iloc[0]
    assert first["equal_weight"] == pytest.approx(10_000.0 - costs["equal_weight"])
    drag = report.results.set_index("strategy_name")["cost_drag"]
    assert (drag["equal_weight"] >= costs["equal_weight"]) and (drag["buy_and_hold"] >= costs["buy_and_hold"])
    # Strategies without any position pay nothing (no purchase to cost).
    assert costs["quality_only"] == 0.0


def test_non_eur_instruments_fill_when_canonical_fx_exists_and_block_only_without_it(config, prices, capacity_report) -> None:
    initial = capacity_report.metadata["initial_allocation"]["equal_weight"]
    assert "no_fill_fx_unavailable" not in initial["fill_status"]
    assert initial["unfilled_eur"] == 0.0
    assert capacity_report.metadata["capacity_fx_unavailable_instruments"] == []
    assert (capacity_report.trade_log["capacity_fx_unavailable"].fillna("") == "").all()

    blocked = run_backtest(
        config, prices.assign(volume=1e9), rebalance_frequency_days=42, enforce_capacity=True, fx_rates=pd.DataFrame()
    )
    blocked_initial = blocked.metadata["initial_allocation"]["equal_weight"]
    assert "no_fill_fx_unavailable" in blocked_initial["fill_status"] and blocked_initial["unfilled_eur"] > 0.0
    assert "fx_unavailable_instruments_unfillable" in blocked.metadata["qualification_blockers"]


def test_equity_certificates_without_a_quote_fill_with_the_conservative_tier_flagged(config, capacity_report) -> None:
    certificates = _certificate_ids(config) & set(capacity_report.metadata["universe_ids"])
    assert certificates
    initial = capacity_report.metadata["initial_allocation"]["equal_weight"]
    assert "manual_quote_required" not in initial["fill_status"] and initial["unfilled_eur"] == 0.0
    assert capacity_report.metadata["cost_estimated_instruments"] == sorted(certificates)
    assert "manual_quote_instruments_unfillable" not in capacity_report.metadata["qualification_blockers"]
    flagged = capacity_report.trade_log["cost_estimated"]
    assert flagged.any() and flagged.dtype == bool
    certificate = sorted(certificates)[0]
    default = estimate_execution_cost(config, certificate, 5_000.0)
    conservative = estimate_execution_cost(config, certificate, 5_000.0, conservative_tier=True)
    assert conservative.data_quality == "cost_estimated"
    assert conservative.total_cost_bps >= default.total_cost_bps
    assert conservative.spread_bps >= default.spread_bps and conservative.slippage_bps >= default.slippage_bps
    assert conservative.estimate_id != default.estimate_id


def test_v3_baseline_is_mapped_from_the_repository_formula_identifier(config, default_report) -> None:
    expected = load_score_policy("ETF").formula_version
    v3 = default_report.metadata["investable_comparators"]["baselines"]["v3"]
    assert v3["status"] == "available" and v3["formula_version"] == expected

    results = {"signal_strategy": {"final_value_eur": 10_500.0}}
    common = dict(
        initial_value_eur=10_000.0, vwce=None, universe=["A"], start="2026-01-01", end="2026-06-26",
        cost_regime="modelled", cost_model_id="m",
    )
    mismatch = investable_comparator_summary(
        results, v3_formula_identity={"expected": expected, "observed": ["some-other-formula-1.0"]}, **common
    )
    assert mismatch["baselines"]["v3"]["status"] == "unavailable"
    assert "mismatch" in mismatch["baselines"]["v3"]["reason"]
    unobserved = investable_comparator_summary(results, v3_formula_identity={"expected": expected, "observed": []}, **common)
    assert unobserved["baselines"]["v3"]["status"] == "unavailable"
    assumed = investable_comparator_summary(results, **common)
    assert assumed["baselines"]["v3"]["status"] == "unavailable"
    assert assumed["baselines"]["v3"]["reason"] == "v3_formula_identity_not_supplied"
