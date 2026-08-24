from __future__ import annotations

import inspect
import json
import hashlib
from io import BytesIO

import pandas as pd
import pytest

from etf_cockpit.app.pages.backtests import backtests_page
from etf_cockpit.backtest.engine import (
    BacktestDataUnavailableError,
    _execution_evidence,
    _log_equity_returns,
    _probabilistic_sharpe,
    quality_momentum_evidence_checksum,
    run_backtest,
)
from etf_cockpit.backtest.metrics import performance_metrics, tail_event_diagnostics
from etf_cockpit.core.config import load_config
from etf_cockpit.core.atomic_io import AtomicWriteRequest
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit import services


def test_tail_event_diagnostics_expose_worst_windows_and_loss_clustering() -> None:
    index = pd.bdate_range("2026-01-01", periods=14)
    equity = pd.Series(
        [100.0, 105.0, 100.0, 96.0, 92.0, 90.0, 95.0, 94.0, 100.0, 99.0, 101.0, 100.0, 103.0, 104.0],
        index=index,
    )

    diagnostics = tail_event_diagnostics(equity)

    assert diagnostics["worst_1d_return"] < 0
    assert diagnostics["worst_5d_return"] < diagnostics["worst_1d_return"]
    assert diagnostics["worst_10d_return"] < 0
    assert diagnostics["loss_cluster_max_days"] == 4
    assert diagnostics["worst_drawdown_start"] == index[1].date()
    assert diagnostics["worst_drawdown_end"] == index[5].date()
    assert diagnostics["worst_drawdown_duration_days"] == 5


def test_tail_event_diagnostics_measure_loss_concentration_and_stress_alignment() -> None:
    index = pd.bdate_range("2026-01-01", periods=21)
    returns = pd.Series(
        [-0.01] * 10 + [0.01] * 10,
        index=index[1:],
    )
    equity = pd.concat(
        [pd.Series([100.0], index=[index[0]]), 100.0 * (1.0 + returns).cumprod()]
    )
    volatility = pd.Series(range(len(equity)), index=equity.index, dtype=float)
    regime = pd.Series("calm", index=equity.index)
    regime.iloc[-1] = "stress"

    diagnostics = tail_event_diagnostics(
        equity,
        volatility=volatility,
        regime=regime,
    )

    assert diagnostics["diagnostic_status"] == "available"
    assert diagnostics["diagnostic_method"] == "historical_tail_diagnostics.v2"
    assert diagnostics["negative_return_concentration_share"] == pytest.approx(0.5)
    assert diagnostics["positive_performance_concentration_share"] == pytest.approx(0.5)
    assert diagnostics["negative_performance_concentration_share"] == pytest.approx(0.5)
    assert diagnostics["performance_concentration_basis"] == "negative_gross_log_return"
    assert diagnostics["performance_concentration_status"] == "available"
    assert diagnostics["few_days_explain_most_performance"] is False
    assert diagnostics["positive_performance_few_sessions_explain_most"] is False
    assert diagnostics["negative_performance_few_sessions_explain_most"] is False
    assert len(diagnostics["largest_negative_contribution_periods"]) == 5
    contribution_returns = [record["return"] for record in diagnostics["largest_negative_contribution_periods"]]
    assert contribution_returns == sorted(contribution_returns)
    assert diagnostics["largest_negative_contribution_periods"][0]["date"] == diagnostics["largest_negative_period_date"]
    assert diagnostics["losses_during_high_volatility"] is False
    assert diagnostics["high_volatility_loss_status"] == "available"
    assert diagnostics["losses_during_regime_stress"] is False
    assert diagnostics["regime_stress_loss_status"] == "available"
    assert diagnostics["execution_allowed"] is False
    assert performance_metrics(equity)["losses_during_regime_stress"] is None


def test_performance_concentration_selects_the_sign_of_gross_performance() -> None:
    index = pd.bdate_range("2026-03-02", periods=8)
    positive = 100.0 * (1.0 + pd.Series([0.20, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01], index=index[1:])).cumprod()
    positive = pd.concat([pd.Series([100.0], index=[index[0]]), positive])
    negative = 100.0 * (1.0 + pd.Series([-0.20, -0.01, -0.01, -0.01, -0.01, -0.01, -0.01], index=index[1:])).cumprod()
    negative = pd.concat([pd.Series([100.0], index=[index[0]]), negative])

    positive_diagnostics = tail_event_diagnostics(positive)
    negative_diagnostics = tail_event_diagnostics(negative)

    assert positive_diagnostics["performance_concentration_basis"] == "positive_gross_log_return"
    assert positive_diagnostics["performance_concentration_share"] == positive_diagnostics["positive_performance_concentration_share"]
    assert positive_diagnostics["few_days_explain_most_performance"] is True
    assert negative_diagnostics["performance_concentration_basis"] == "negative_gross_log_return"
    assert negative_diagnostics["performance_concentration_share"] == negative_diagnostics["negative_performance_concentration_share"]
    assert negative_diagnostics["few_days_explain_most_performance"] is True


def test_performance_metrics_tail_path_does_not_bridge_invalid_equity_gap() -> None:
    index = pd.bdate_range("2026-02-02", periods=4)
    metrics = performance_metrics(pd.Series([100.0, "invalid", 80.0, 81.0], index=index))

    assert metrics["worst_1d_return"] == pytest.approx(0.0125)
    assert metrics["largest_negative_period_return"] is None
    assert metrics["loss_cluster_max_days"] == 0
    assert metrics["diagnostic_status"] == "available"
    assert metrics["max_drawdown"] == 0.0
    assert metrics["cagr"] == pytest.approx((81.0 / 100.0) ** 126 - 1.0)


def test_performance_metrics_reports_total_loss_when_equity_reaches_zero() -> None:
    metrics = performance_metrics(pd.Series([100.0, 0.0, 80.0]))

    assert metrics["max_drawdown"] == -1.0


def test_tail_windows_drawdown_clusters_and_volatility_do_not_cross_invalid_gap() -> None:
    index = pd.bdate_range("2026-02-02", periods=10)
    diagnostics = tail_event_diagnostics(
        pd.Series([100.0, 90.0, 80.0, 70.0, 60.0, float("nan"), 50.0, 45.0, 40.0, 35.0], index=index)
    )

    assert diagnostics["worst_5d_return"] is None
    assert diagnostics["worst_10d_return"] is None
    assert diagnostics["loss_cluster_max_days"] == 4
    assert diagnostics["worst_drawdown_start"] == index[0].date()
    assert diagnostics["worst_drawdown_end"] == index[4].date()
    assert diagnostics["worst_drawdown_duration_sessions"] == 5
    assert diagnostics["high_volatility_loss_status"] == "unavailable"


def test_inferred_volatility_window_resets_at_invalid_gap() -> None:
    segment_returns = pd.Series([-0.01, 0.01] * 10)
    first = [100.0, *(100.0 * (1.0 + segment_returns).cumprod()).tolist()]
    second = [80.0, *(80.0 * (1.0 + segment_returns).cumprod()).tolist()]
    equity = pd.Series([*first, float("nan"), *second], index=pd.bdate_range("2026-05-01", periods=43))

    diagnostics = tail_event_diagnostics(equity)

    assert diagnostics["high_volatility_loss_status"] == "unavailable"
    assert diagnostics["high_volatility_loss_reason"] == "at least 20 aligned finite observations are required"


def test_loss_concentration_has_its_own_unavailable_status_without_losses() -> None:
    index = pd.bdate_range("2026-04-01", periods=8)
    diagnostics = tail_event_diagnostics(pd.Series(range(100, 108), index=index, dtype=float))

    assert diagnostics["negative_return_concentration_share"] is None
    assert diagnostics["negative_return_concentration_status"] == "unavailable"
    assert diagnostics["negative_return_concentration_reason"] == "no finite negative return observations are available"
    assert diagnostics["negative_return_concentration_method"]
    assert diagnostics["performance_concentration_status"] == "available"


def test_tail_event_diagnostics_fail_closed_for_malformed_or_insufficient_evidence() -> None:
    diagnostics = tail_event_diagnostics(
        pd.Series([100.0, "invalid", float("inf"), 101.0]),
        benchmark=pd.Series([100.0, 101.0, 102.0, 103.0]),
    )

    assert diagnostics["diagnostic_status"] == "unavailable"
    assert diagnostics["worst_5d_return"] is None
    assert diagnostics["performance_concentration_status"] == "unavailable"
    assert diagnostics["high_volatility_loss_status"] == "unavailable"
    assert diagnostics["regime_stress_loss_status"] == "unavailable"
    assert diagnostics["execution_allowed"] is False


def test_backtest_rejects_insufficient_complete_adjusted_price_history() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=259, end_date=pd.Timestamp("2026-06-26").date())

    with pytest.raises(BacktestDataUnavailableError, match="not_enough_data"):
        run_backtest(config, prices)


def test_backtest_report_makes_data_and_execution_assumptions_explicit() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    missing_date = pd.to_datetime(prices["date"]).drop_duplicates().sort_values().iloc[280]
    prices = prices.loc[~((pd.to_datetime(prices["date"]) == missing_date) & (prices["etf_id"] == config.universe.enabled_ids[0]))].copy()

    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert report.metadata["price_field"] == "adjusted_close"
    assert report.metadata["forward_fill_used"] is False
    assert report.metadata["missing_observation_rows"] >= 1
    assert report.metadata["lookahead_protection"] == "history_truncated_at_signal_date"
    assert report.metadata["execution_delay_sessions"] == 1
    assert report.metadata["benchmark_strategy"] == "unavailable"
    assert report.metadata["benchmark_data_id"] is None
    assert report.metadata["data_status"] == "warning"
    assert missing_date in report.equity_curves.index
    assert report.equity_curves.loc[missing_date].isna().all()
    next_date = report.equity_curves.index[report.equity_curves.index.get_loc(missing_date) + 1]
    observed_returns = report.equity_curves["buy_and_hold"].pct_change(fill_method=None)
    assert pd.isna(observed_returns.loc[missing_date])
    assert pd.isna(observed_returns.loc[next_date])
    buy_and_hold = report.results.loc[report.results["strategy_name"] == "buy_and_hold"].iloc[0]
    assert buy_and_hold["max_drawdown"] == performance_metrics(report.equity_curves["buy_and_hold"])["max_drawdown"]
    gap_safe_log_returns = _log_equity_returns(report.equity_curves["buy_and_hold"])
    assert missing_date not in gap_safe_log_returns.index
    assert next_date not in gap_safe_log_returns.index
    assert buy_and_hold["probabilistic_sharpe"] == pytest.approx(
        _probabilistic_sharpe(gap_safe_log_returns)
    )
    required_trade_fields = {
        "signal_date",
        "execution_date",
        "decision_price",
        "next_open_reference_price",
        "close_to_next_open_gap",
        "arrival_price_assumption",
        "spread_proxy",
        "same_bar_execution_avoided",
        "capacity_eur",
        "cost_data_quality",
        "next_period_reference_price",
    }
    assert required_trade_fields <= set(report.trade_log.columns)
    assert report.trade_log["same_bar_execution_avoided"].eq(True).all()
    assert (pd.to_datetime(report.trade_log["execution_date"]) > pd.to_datetime(report.trade_log["signal_date"])).all()
    required_result_fields = {
        "worst_1d_return",
        "worst_5d_return",
        "worst_10d_return",
        "worst_drawdown_duration_days",
        "worst_drawdown_duration_sessions",
        "observed_session_count",
        "largest_negative_period_date",
        "largest_negative_contribution_periods",
        "negative_return_concentration_share",
        "few_days_explain_most_performance",
        "positive_performance_concentration_share",
        "negative_performance_concentration_share",
        "performance_concentration_basis",
        "performance_concentration_status",
        "losses_during_high_volatility",
        "losses_during_regime_stress",
        "diagnostic_status",
        "diagnostic_method",
        "execution_allowed",
        "loss_cluster_max_days",
        "overfitting_warning",
        "parameter_sensitivity_status",
    }
    assert required_result_fields <= set(report.results.columns)
    assert report.results["overfitting_warning"].notna().all()
    assert report.results["execution_allowed"].eq(False).all()


def test_execution_evidence_uses_next_session_adjusted_close() -> None:
    evidence = _execution_evidence(
        current_prices=pd.Series({"A": 100.0}),
        next_adjusted_close=pd.Series({"A": 105.0}),
        next_open=pd.Series({"A": 106.0}),
        next_high=pd.Series({"A": 108.0}),
        next_low=pd.Series({"A": 104.0}),
        changed_weights=pd.Series({"A": 1.0}),
    )

    assert evidence["next_period_reference_price"] == 105.0
    assert evidence["arrival_price_assumption"] == "next_adjusted_close"
    assert evidence["next_period_reference_price"] != evidence["decision_price"]


def test_backtests_page_exposes_lab_evidence_sections() -> None:
    source = inspect.getsource(backtests_page)

    assert "Tail-event diagnostics" in source
    assert "Operational execution evidence" in source
    assert "quality-momentum" in source
    assert "Overfitting warning" in source
    assert "next-open" in source
    assert "Largest negative contribution period" in source
    assert "Largest negative contribution periods" in source
    assert "negative_return_concentration_status" in source
    assert "Few sessions explain most performance" in source
    assert "Losses during high volatility" in source
    assert "Losses during regime stress" in source


def test_backtest_registers_quality_momentum_and_quality_only_baselines() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())

    report = run_backtest(config, prices, rebalance_frequency_days=42)

    assert {"quality_only", "quality_momentum", "momentum_only", "equal_weight"} <= set(report.results["strategy_name"])
    assert report.metadata["quality_momentum_strategy_version"] == "quality_momentum.v1"
    assert report.metadata["quality_momentum_evidence"] == "unavailable"
    assert report.metadata["quality_momentum_evidence_available_rows"] == 0
    assert set(report.quality_momentum_evidence.columns) >= {"signal_date", "status", "reason", "execution_allowed"}


def test_quality_momentum_checksum_verifies_exact_persisted_csv_bytes(tmp_path) -> None:
    evidence = pd.DataFrame(
        [
            {
                "instrument_id": "VWCE",
                "signal_date": "2026-06-26",
                "quality_score": None,
                "execution_allowed": False,
            }
        ]
    )
    persisted = evidence.to_csv(index=False).encode("utf-8")
    path = tmp_path / "quality-momentum.csv"
    path.write_bytes(persisted)

    assert quality_momentum_evidence_checksum(evidence) == quality_momentum_evidence_checksum(
        path.read_bytes()
    )


def test_backtest_service_reuses_quality_momentum_cache_after_persistence(
    tmp_path, monkeypatch
) -> None:
    from etf_cockpit.data.etf_structure import LocalStructuralEvidence

    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(services, "load_prices", lambda: prices.copy())
    monkeypatch.setattr(services, "load_fundamental_evidence", pd.DataFrame)
    monkeypatch.setattr(
        services,
        "_load_local_structural_evidence",
        lambda: LocalStructuralEvidence(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(services, "ensure_run_manifest", lambda *_args, **_kwargs: {})
    service = services.BacktestService(config, universe_revision="test-revision")

    generated = service.run_backtest()
    monkeypatch.setattr(
        services,
        "structure_confidence_caps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("empty structural evidence must not replay once per signal row")
        ),
    )
    cached = service._load_cached_backtest()

    assert cached is not None
    assert isinstance(cached.results.iloc[0]["largest_negative_contribution_periods"], list)
    assert cached.results.iloc[0]["largest_negative_contribution_periods"] == generated.results.iloc[0][
        "largest_negative_contribution_periods"
    ]
    assert cached.metadata["quality_momentum_evidence_checksum"] == generated.metadata[
        "quality_momentum_evidence_checksum"
    ]
    metadata_path = tmp_path / "backtest_metadata.json"
    original_metadata = metadata_path.read_bytes()
    metadata = json.loads(original_metadata)
    metadata["reference_identity"]["execution_allowed"] = 0
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert service._load_cached_backtest() is None
    metadata_path.write_bytes(original_metadata)

    results_path = tmp_path / "backtest_results.csv"
    sidecar_path = services._universe_cache_meta_path(results_path)
    original_results = results_path.read_bytes()
    original_sidecar = sidecar_path.read_bytes()

    incomplete_results = pd.read_csv(BytesIO(original_results)).loc[
        lambda frame: frame["strategy_name"] == "quality_momentum"
    ]
    incomplete_payload = incomplete_results.to_csv(index=False).encode("utf-8")
    incomplete_sidecar = json.loads(original_sidecar)
    incomplete_sidecar["payload_sha256"] = hashlib.sha256(incomplete_payload).hexdigest()
    results_path.write_bytes(incomplete_payload)
    sidecar_path.write_text(json.dumps(incomplete_sidecar), encoding="utf-8")
    assert service._load_cached_backtest() is None

    for missing_column in ("diagnostic_method", "gross_log_return"):
        legacy_results = pd.read_csv(BytesIO(original_results)).drop(columns=[missing_column])
        legacy_payload = legacy_results.to_csv(index=False).encode("utf-8")
        legacy_sidecar = json.loads(original_sidecar)
        legacy_sidecar["payload_sha256"] = hashlib.sha256(legacy_payload).hexdigest()
        results_path.write_bytes(legacy_payload)
        sidecar_path.write_text(json.dumps(legacy_sidecar), encoding="utf-8")
        assert service._load_cached_backtest() is None

    for column, malformed_value in (
        ("execution_allowed", True),
        ("worst_1d_return", "not-a-number"),
        ("worst_1d_return", True),
        ("worst_1d_return", float("inf")),
        ("largest_negative_period_return", 0.1),
        ("observed_session_count", 0),
        ("observed_session_count", 3.0),
        ("worst_drawdown_start", 123),
        ("worst_drawdown_start", "2026-1-1"),
        ("worst_drawdown_duration_sessions", 1140),
        ("diagnostic_status", "unavailable"),
        ("high_volatility_loss_sessions", -1),
        ("high_volatility_loss_sessions", 3.0),
        ("worst_drawdown_duration_days", 3.0),
        ("performance_concentration_basis", "flat_gross_log_return"),
        ("largest_negative_contribution_periods", "not-json"),
        (
            "largest_negative_contribution_periods",
            json.dumps([{"date": "2026-01-02", "return": "-0.1"}]),
        ),
        (
            "largest_negative_contribution_periods",
            json.dumps([{"date": "20260102", "return": -0.1}]),
        ),
    ):
        malformed_results = pd.read_csv(BytesIO(original_results))
        malformed_results[column] = malformed_value
        malformed_payload = malformed_results.to_csv(index=False).encode("utf-8")
        malformed_sidecar = json.loads(original_sidecar)
        malformed_sidecar["payload_sha256"] = hashlib.sha256(malformed_payload).hexdigest()
        results_path.write_bytes(malformed_payload)
        sidecar_path.write_text(json.dumps(malformed_sidecar), encoding="utf-8")
        assert service._load_cached_backtest() is None


def test_backtest_service_reuses_mixed_availability_integer_diagnostics(
    tmp_path, monkeypatch
) -> None:
    from etf_cockpit.data.etf_structure import LocalStructuralEvidence

    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(services, "load_prices", lambda: prices.copy())
    monkeypatch.setattr(services, "load_fundamental_evidence", pd.DataFrame)
    monkeypatch.setattr(
        services,
        "_load_local_structural_evidence",
        lambda: LocalStructuralEvidence(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(services, "ensure_run_manifest", lambda *_args, **_kwargs: {})
    def mixed_availability_report(selected_config, selected_prices, **kwargs):
        report = run_backtest(
            selected_config,
            selected_prices,
            rebalance_frequency_days=10,
            transaction_cost_bps=100_000.0,
            **kwargs,
        )
        unavailable_strategy = "momentum_only"
        report.equity_curves[unavailable_strategy] = 0.0
        row_index = report.results.index[
            report.results["strategy_name"] == unavailable_strategy
        ].item()
        diagnostics = tail_event_diagnostics(report.equity_curves[unavailable_strategy])
        for field, value in diagnostics.items():
            report.results.at[row_index, field] = value
        report.results.at[row_index, "max_drawdown"] = services.max_drawdown(
            report.equity_curves[unavailable_strategy]
        )
        return report

    monkeypatch.setattr(services, "_run_backtest_compatibly", mixed_availability_report)
    service = services.BacktestService(config, universe_revision="test-revision")

    generated = service.run_backtest()
    counts = generated.results["high_volatility_loss_sessions"]
    assert counts.notna().any() and counts.isna().any()
    durations = generated.results["worst_drawdown_duration_days"]
    assert durations.notna().any() and durations.isna().any()
    monkeypatch.setattr(
        service,
        "run_backtest",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("valid cache must not be recomputed")),
    )
    monkeypatch.setattr(
        services,
        "atomic_write_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache hit must not publish")),
    )

    cached = service.load_or_run_backtest()

    assert cached.results["high_volatility_loss_sessions"].map(
        lambda value: pd.isna(value) or type(value) is int
    ).all()
    assert cached.results["worst_drawdown_duration_days"].map(
        lambda value: pd.isna(value) or type(value) is int
    ).all()


def test_backtest_cache_reader_uses_one_complete_snapshot_under_interleaving(
    tmp_path, monkeypatch
) -> None:
    from etf_cockpit.data.etf_structure import LocalStructuralEvidence

    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(services, "load_prices", lambda: prices.copy())
    monkeypatch.setattr(services, "load_fundamental_evidence", pd.DataFrame)
    monkeypatch.setattr(
        services,
        "_load_local_structural_evidence",
        lambda: LocalStructuralEvidence(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(services, "ensure_run_manifest", lambda *_args, **_kwargs: {})
    service = services.BacktestService(config, universe_revision="test-revision")
    service.run_backtest()

    real_read = services.read_atomic_group
    real_write = services.atomic_write_group
    calls: list[tuple] = []
    published = False

    def interleaved_read(paths, *, timeout_seconds=5.0):
        nonlocal published
        path_tuple = tuple(paths)
        calls.append(path_tuple)
        snapshot = real_read(path_tuple, timeout_seconds=timeout_seconds)
        if not published:
            published = True
            by_path = dict(zip(path_tuple, snapshot, strict=True))
            results_path = next(path for path in path_tuple if path.name == "backtest_results.csv")
            results = pd.read_csv(BytesIO(by_path[results_path]))
            results.loc[results["strategy_name"] == "signal_strategy", "calmar"] = 999.0
            replacement = results.to_csv(index=False).encode("utf-8")
            sidecar_path = services._universe_cache_meta_path(results_path)
            sidecar = json.loads(by_path[sidecar_path].decode("utf-8"))
            sidecar["payload_sha256"] = hashlib.sha256(replacement).hexdigest()
            by_path[results_path] = replacement
            by_path[sidecar_path] = json.dumps(sidecar, sort_keys=True).encode("utf-8")
            real_write(
                tuple(
                    AtomicWriteRequest(path, payload, lambda _candidate: None)
                    for path, payload in by_path.items()
                )
            )
        return snapshot

    monkeypatch.setattr(services, "read_atomic_group", interleaved_read)
    cached = service._load_cached_backtest()

    assert cached is not None
    assert len(calls) == 1
    assert {path.name for path in calls[0]} == {
        "backtest_results.csv",
        "backtest_results.csv.meta.json",
        "equity_curves.csv",
        "equity_curves.csv.meta.json",
        "trade_log.csv",
        "trade_log.csv.meta.json",
        "signal_log.csv",
        "signal_log.csv.meta.json",
        "quality_momentum_evidence.csv",
        "quality_momentum_evidence.csv.meta.json",
        "backtest_metadata.json",
    }
    assert cached.results.loc[cached.results["strategy_name"] == "signal_strategy", "calmar"].iloc[0] != 999.0
