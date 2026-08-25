from __future__ import annotations

import inspect
import json
import hashlib
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.app.pages.backtests import backtests_page
from etf_cockpit.app.pages.signals import _signals_operational_evidence
from etf_cockpit.backtest.engine import (
    BacktestReport,
    BacktestDataUnavailableError,
    _calendar_projection,
    _execution_evidence,
    _canonical_calendar_contract,
    _canonical_session_close_timestamp,
    _corporate_action_adjusted_pivot,
    _instrument_operational_evidence,
    _log_equity_returns,
    _price_source_identity,
    _probabilistic_sharpe,
    quality_momentum_evidence_checksum,
    run_backtest,
)
from etf_cockpit.backtest.metrics import performance_metrics, tail_event_diagnostics
from etf_cockpit.core.config import load_config
from etf_cockpit.core.atomic_io import AtomicWriteRequest
from etf_cockpit.data import duckdb_store, sample_data
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.data.market_calendar import ListingCalendarEvidence, MarketCalendarService
from etf_cockpit.app.pages.signals import _latest_operational_row
from etf_cockpit.app.selectors.instrument_detail import _operational_evidence_panel
from etf_cockpit.portfolio.costs import estimate_execution_cost
from etf_cockpit import services


def _flat_calendar_identity(**updates: object) -> dict[str, object]:
    identity: dict[str, object] = {
        "status": "available",
        "instrument_id": "X",
        "listing_id": "listing:X:XETR",
        "mic": "XETR",
        "calendar_id": "XETR",
        "timezone": "Europe/Berlin",
        "source_id": "calendar-test-source",
        "known_at": "2026-01-01T00:00:00+00:00",
        "valid_from": "2020-01-01",
    }
    identity.update(updates)
    return identity


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


def test_operational_evidence_fails_closed_for_partial_ohlc_and_same_bar() -> None:
    partial = _instrument_operational_evidence(
        instrument_id="VWCE",
        strategy="signal_strategy",
        signal_timestamp="2026-06-01T00:00:00",
        execution_timestamp="2026-06-02T00:00:00",
        signal_date=pd.Timestamp("2026-06-01").date(),
        execution_date=pd.Timestamp("2026-06-02").date(),
        decision_price=100.0,
        next_open=101.0,
        next_period_close=102.0,
        high=None,
        low=99.0,
        open_price=100.0,
        cost_spread_assumption_bps=8.0,
        cost_spread_assumption_source="execution-cost-v1",
    )
    assert partial["evidence_status"] == "unavailable"
    assert partial["observed_range_spread_proxy"] is None
    assert partial["fill_source"] == "simulated_backtest"
    assert partial["execution_allowed"] is False

    missing_open = _instrument_operational_evidence(
        instrument_id="VWCE",
        strategy="signal_strategy",
        signal_timestamp="2026-06-01T00:00:00",
        execution_timestamp="2026-06-02T00:00:00",
        signal_date=pd.Timestamp("2026-06-01").date(),
        execution_date=pd.Timestamp("2026-06-02").date(),
        decision_price=100.0,
        next_open=None,
        next_period_close=102.0,
        high=103.0,
        low=99.0,
        open_price=101.0,
        cost_spread_assumption_bps=8.0,
        cost_spread_assumption_source="execution-cost-v1",
    )
    assert missing_open["evidence_status"] == "unavailable"
    assert "next_open_reference_unavailable" in missing_open["evidence_reason"]

    same_bar = _instrument_operational_evidence(
        instrument_id="VWCE",
        strategy="signal_strategy",
        signal_timestamp="2026-06-02T00:00:00",
        execution_timestamp="2026-06-02T00:00:00",
        signal_date=pd.Timestamp("2026-06-02").date(),
        execution_date=pd.Timestamp("2026-06-02").date(),
        decision_price=100.0,
        next_open=101.0,
        next_period_close=102.0,
        high=102.0,
        low=99.0,
        open_price=100.0,
        cost_spread_assumption_bps=8.0,
        cost_spread_assumption_source="execution-cost-v1",
    )
    assert same_bar["evidence_status"] == "unavailable"
    assert same_bar["same_bar_execution_avoided"] is False

    later_same_session = _instrument_operational_evidence(
        instrument_id="VWCE",
        strategy="signal_strategy",
        signal_timestamp="2026-06-02T09:00:00",
        execution_timestamp="2026-06-02T10:00:00",
        signal_date=pd.Timestamp("2026-06-02").date(),
        execution_date=pd.Timestamp("2026-06-02").date(),
        decision_price=100.0,
        next_open=101.0,
        next_period_close=102.0,
        high=103.0,
        low=99.0,
        open_price=100.0,
        cost_spread_assumption_bps=8.0,
        cost_spread_assumption_source="execution-cost-v1",
        canonical_session_dates=pd.to_datetime(["2026-06-02", "2026-06-03"]),
        decision_price_source_identity="source|VWCE",
        next_open_source_identity="source|VWCE",
        next_period_source_identity="source|VWCE",
    )
    assert later_same_session["evidence_status"] == "unavailable"
    assert later_same_session["execution_delay_sessions"] is None

    mixed_timezone = _instrument_operational_evidence(
        instrument_id="VWCE",
        strategy="signal_strategy",
        signal_timestamp="2026-06-01T00:00:00",
        execution_timestamp="2026-06-02T00:00:00+00:00",
        signal_date=date(2026, 6, 1),
        execution_date=date(2026, 6, 2),
        decision_price=100.0,
        next_open=101.0,
        next_period_close=102.0,
        high=103.0,
        low=99.0,
        open_price=101.0,
        cost_spread_assumption_bps=4.0,
        cost_spread_assumption_source="execution-cost-v1",
        canonical_session_dates=pd.to_datetime(["2026-06-01", "2026-06-02"]),
        decision_price_source_identity="source|VWCE",
        next_open_source_identity="source|VWCE",
        next_period_source_identity="source|VWCE",
    )
    assert mixed_timezone["evidence_status"] == "unavailable"
    assert "signal_or_execution_timestamp_unavailable" in mixed_timezone["evidence_reason"]
    assert mixed_timezone["execution_allowed"] is False

    explicit_offsets = _instrument_operational_evidence(
        instrument_id="VWCE",
        strategy="signal_strategy",
        signal_timestamp="2026-06-01T02:00:00+02:00",
        execution_timestamp="2026-06-02T00:00:00+00:00",
        signal_date=date(2026, 6, 1),
        execution_date=date(2026, 6, 2),
        decision_price=100.0,
        next_open=101.0,
        next_period_close=102.0,
        high=103.0,
        low=99.0,
        open_price=101.0,
        cost_spread_assumption_bps=4.0,
        cost_spread_assumption_source="execution-cost-v1",
        canonical_session_dates=pd.to_datetime(["2026-06-01", "2026-06-02"]),
        decision_price_source_identity="source|VWCE",
        next_open_source_identity="source|VWCE",
        next_period_source_identity="source|VWCE",
    )
    assert explicit_offsets["evidence_status"] == "available"
    assert explicit_offsets["execution_allowed"] is False


def test_operational_evidence_does_not_label_a_missing_or_non_next_session_as_one_delay() -> None:
    kwargs = dict(
        instrument_id="VWCE",
        strategy="signal_strategy",
        signal_timestamp="2026-06-05T00:00:00+00:00",
        execution_timestamp="2026-06-09T00:00:00+00:00",
        signal_date=pd.Timestamp("2026-06-05").date(),
        execution_date=pd.Timestamp("2026-06-09").date(),
        decision_price=100.0,
        next_open=101.0,
        next_period_close=102.0,
        high=103.0,
        low=99.0,
        open_price=100.0,
        cost_spread_assumption_bps=8.0,
        cost_spread_assumption_source="execution-cost-v1",
        decision_price_source_identity="source|VWCE",
        next_open_source_identity="source|VWCE",
        next_period_source_identity="source|VWCE",
    )
    missing_observation = _instrument_operational_evidence(
        **kwargs, canonical_session_dates=pd.to_datetime(["2026-06-05", "2026-06-08", "2026-06-09"])
    )
    assert missing_observation["evidence_status"] == "unavailable"
    assert missing_observation["execution_delay_sessions"] is None
    assert "execution_not_next_canonical_market_session" in missing_observation["evidence_reason"]


def test_canonical_calendar_rejects_xetr_holiday_as_next_session() -> None:
    projection = {
        "status": "available",
        "instrument_id": "X",
        "identity_decision_id": "calendar-test-decision",
        "identity_decision_time": "2026-01-01T00:00:00+00:00",
        "identity_effective_at": "2020-01-01",
        "identity_objects": [{
            "object_type": "listing",
            "object_id": "listing:X:XETR",
            "fields": {"mic": "XETR", "calendar_id": "XETR", "timezone": "Europe/Berlin"},
        }],
        "identity_history": [{"source_id": "calendar-test-source"}],
    }
    _, reason = _canonical_calendar_contract(
        projection,
        "X",
        "2026-12-23T00:00:00+00:00",
        "2026-12-25T00:00:00+00:00",
    )
    assert reason == "canonical_execution_session_unavailable"


def test_canonical_calendar_requires_explicit_listing_and_requested_instrument() -> None:
    missing_listing = {
        "status": "available",
        "instrument_id": "X",
        "mic": "XETR",
        "calendar_id": "XETR",
        "timezone": "Europe/Berlin",
        "source_id": "calendar-test-source",
        "known_at": "2026-01-01T00:00:00+00:00",
        "valid_from": "2020-01-01",
    }
    _, reason = _canonical_calendar_contract(
        missing_listing,
        "X",
        "2026-06-01T00:00:00",
        "2026-06-02T00:00:00",
    )
    assert reason == "canonical_market_calendar_identity_unavailable"

    other_listing = ListingCalendarEvidence(
        listing_id="listing:OTHER:XETR",
        instrument_id="OTHER",
        mic="XETR",
        calendar_id="XETR",
        timezone="Europe/Berlin",
        source_id="calendar-test-source",
        source_checksum="a" * 64,
        valid_from=date(2020, 1, 1),
        known_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    _, reason = _canonical_calendar_contract(
        other_listing,
        "X",
        "2026-06-01T00:00:00",
        "2026-06-02T00:00:00",
    )
    assert reason == "canonical_market_calendar_identity_unavailable"


def test_canonical_calendar_rejects_unavailable_legacy_identity() -> None:
    identity = {
        "status": "unavailable",
        "instrument_id": "X",
        "fields": {
            "mic": "XETR",
            "calendar_id": "XETR",
            "timezone": "Europe/Berlin",
            "listing_id": "listing:X:XETR",
            "source_id": "unavailable-source",
            "known_at": "2026-01-01T00:00:00+00:00",
            "valid_from": "2020-01-01",
        },
    }

    _, reason = _canonical_calendar_contract(
        identity,
        "X",
        "2026-06-01T16:00:00+00:00",
        "2026-06-02T16:00:00+00:00",
    )

    assert reason == "canonical_market_calendar_identity_unavailable"


@pytest.mark.parametrize(
    ("field_name", "malformed"),
    (
        ("calendar_source_version", 123),
        ("source_version", 123),
        ("opening_auction_minutes", "5"),
    ),
)
def test_canonical_calendar_rejects_malformed_nested_types(
    field_name: str, malformed: object
) -> None:
    config = load_config()
    prices = generate_sample_prices(
        config, periods=20, end_date=pd.Timestamp("2026-06-26").date()
    )
    identity = json.loads(
        json.dumps(prices.loc[prices["etf_id"].eq("VWCE"), "calendar_identity"].iloc[0])
    )
    identity["identity_objects"][0]["fields"][field_name] = malformed

    _, reason = _canonical_calendar_contract(
        identity,
        "VWCE",
        "2026-06-01T16:00:00+00:00",
        "2026-06-02T16:00:00+00:00",
    )

    assert reason == "canonical_market_calendar_identity_unavailable"


@pytest.mark.parametrize(
    ("field_name", "malformed"),
    (
        ("source_version", ""),
        ("calendar_source_version", 0),
        ("source_checksum", ""),
        ("calendar_source_checksum", 0),
        ("identity_lineage_hash", "not-a-digest"),
        ("calendar_identity_lineage_hash", False),
    ),
)
def test_flat_calendar_projection_rejects_present_falsey_or_malformed_aliases(
    field_name: str, malformed: object
) -> None:
    identity = _flat_calendar_identity(**{field_name: malformed})

    assert _calendar_projection(identity, "X") == {}


@pytest.mark.parametrize(
    ("aliases", "values"),
    (
        (("source_version", "calendar_source_version"), ("v1", "v2")),
        (("source_checksum", "calendar_source_checksum"), ("a" * 64, "b" * 64)),
        (("identity_lineage_hash", "calendar_identity_lineage_hash"), ("a" * 64, "b" * 64)),
    ),
)
def test_flat_calendar_projection_rejects_conflicting_aliases(
    aliases: tuple[str, str], values: tuple[str, str]
) -> None:
    identity = _flat_calendar_identity(**dict(zip(aliases, values, strict=True)))

    assert _calendar_projection(identity, "X") == {}


def test_flat_calendar_projection_defaults_version_only_when_both_aliases_absent() -> None:
    identity = _flat_calendar_identity()
    projection = _calendar_projection(identity, "X")

    assert projection["identity_objects"][0]["fields"]["calendar_source_version"] == "identity-master.v1"


@pytest.mark.parametrize(
    "field_name", ("_persisted_source_checksum", "_persisted_lineage_hash")
)
def test_canonical_calendar_rejects_malformed_persisted_hashes(field_name: str) -> None:
    config = load_config()
    prices = generate_sample_prices(
        config, periods=20, end_date=pd.Timestamp("2026-06-26").date()
    )
    identity = json.loads(
        json.dumps(prices.loc[prices["etf_id"].eq("VWCE"), "calendar_identity"].iloc[0])
    )
    identity[field_name] = []

    _, reason = _canonical_calendar_contract(
        identity,
        "VWCE",
        "2026-06-01T16:00:00+00:00",
        "2026-06-02T16:00:00+00:00",
    )

    assert reason == "canonical_market_calendar_lineage_conflict"


@pytest.mark.parametrize(("field_name", "malformed"), (("source", 123), ("provider_symbol", True)))
def test_price_source_identity_rejects_non_string_fields(
    field_name: str, malformed: object
) -> None:
    prices = pd.DataFrame(
        [{
            "date": date(2026, 6, 1),
            "etf_id": "VWCE",
            "source": "sample_generator",
            "provider_symbol": "VWCE.DE",
        }]
    )
    prices.loc[0, field_name] = malformed

    assert _price_source_identity(prices, "VWCE", date(2026, 6, 1)) is None


def test_canonical_calendar_persists_listing_timezone_local_dates() -> None:
    projection = {
        "status": "available",
        "instrument_id": "X",
        "identity_decision_id": "calendar-test-decision",
        "identity_decision_time": "2026-01-01T00:00:00+00:00",
        "identity_effective_at": "2020-01-01",
        "identity_objects": [{
            "object_type": "listing",
            "object_id": "listing:X:XETR",
            "fields": {"mic": "XETR", "calendar_id": "XETR", "timezone": "Europe/Berlin"},
        }],
        "identity_history": [{"source_id": "calendar-test-source"}],
    }
    fields, reason = _canonical_calendar_contract(
        projection,
        "X",
        "2026-06-02T16:00:00+00:00",
        "2026-06-03T16:00:00+00:00",
    )
    assert reason is None
    assert fields["signal_date"] == date(2026, 6, 2)
    assert fields["execution_date"] == date(2026, 6, 3)

    _, reason = _canonical_calendar_contract(
        projection,
        "X",
        "2026-06-02T16:00:00",
        "2026-06-03T16:00:00+00:00",
    )
    assert reason == "canonical_market_session_timestamp_unavailable"


def test_canonical_calendar_rejects_unknown_timezone_without_crashing() -> None:
    projection = {
        "status": "available",
        "instrument_id": "X",
        "identity_decision_id": "calendar-test-decision",
        "identity_decision_time": "2026-01-01T00:00:00+00:00",
        "identity_effective_at": "2020-01-01",
        "identity_objects": [{
            "object_type": "listing",
            "object_id": "listing:X:UNKNOWN",
            "fields": {
                "mic": "XETR",
                "calendar_id": "XETR",
                "timezone": "Not/A_Real_Timezone",
            },
        }],
        "identity_history": [{"source_id": "calendar-test-source"}],
    }

    _, reason = _canonical_calendar_contract(
        projection,
        "X",
        "2026-06-02T16:00:00+00:00",
        "2026-06-03T16:00:00+00:00",
    )
    assert reason == "canonical_market_calendar_identity_unavailable"
    assert _canonical_session_close_timestamp(
        projection,
        "X",
        date(2026, 6, 2),
        service=MarketCalendarService(),
        knowledge_cutoff="2026-06-02T16:00:00+00:00",
    ) is None


def test_canonical_close_rejects_naive_knowledge_cutoff() -> None:
    projection = {
        "status": "available",
        "instrument_id": "X",
        "identity_decision_id": "calendar-test-decision",
        "identity_decision_time": "2026-01-01T00:00:00+00:00",
        "identity_effective_at": "2020-01-01",
        "identity_objects": [{
            "object_type": "listing",
            "object_id": "listing:X:XETR",
            "fields": {
                "mic": "XETR",
                "calendar_id": "XETR",
                "timezone": "Europe/Berlin",
            },
        }],
        "identity_history": [{"source_id": "calendar-test-source"}],
    }

    assert _canonical_session_close_timestamp(
        projection,
        "X",
        date(2026, 6, 2),
        service=MarketCalendarService(),
        knowledge_cutoff="2026-06-02T00:00:00",
    ) is None


def test_operational_evidence_rejects_close_prices_before_session_close() -> None:
    projection = {
        "status": "available",
        "instrument_id": "X",
        "identity_decision_id": "calendar-test-decision",
        "identity_decision_time": "2026-01-01T00:00:00+00:00",
        "identity_effective_at": "2020-01-01",
        "identity_objects": [{
            "object_type": "listing",
            "object_id": "listing:X:XETR",
            "fields": {
                "mic": "XETR",
                "calendar_id": "XETR",
                "timezone": "Europe/Berlin",
                "calendar_source_version": "identity-master.v1",
                "opening_auction_minutes": 5,
                "closing_auction_minutes": 10,
            },
        }],
        "identity_history": [{"source_id": "calendar-test-source"}],
    }

    evidence = _instrument_operational_evidence(
        instrument_id="X",
        strategy="signal_strategy",
        signal_timestamp="2026-06-02T00:30:00+00:00",
        execution_timestamp="2026-06-02T22:30:00+00:00",
        signal_date=date(2026, 6, 2),
        execution_date=date(2026, 6, 3),
        decision_price=100.0,
        next_open=101.0,
        next_period_close=102.0,
        high=103.0,
        low=99.0,
        open_price=101.0,
        cost_spread_assumption_bps=4.0,
        cost_spread_assumption_source="execution-cost-v1",
        decision_price_source_identity="source|X",
        next_open_source_identity="source|X",
        next_period_source_identity="source|X",
        calendar_identity=projection,
        calendar_service=MarketCalendarService(),
    )

    assert evidence["evidence_status"] == "unavailable"
    assert evidence["signal_date"] == date(2026, 6, 2)
    assert evidence["execution_date"] == date(2026, 6, 3)
    assert "decision_price_not_available_at_signal_timestamp" in evidence["evidence_reason"]
    assert evidence["same_bar_execution_avoided"] is False


def test_signals_select_latest_operational_row_by_decision_order() -> None:
    rows = [
        {
            "execution_timestamp": "2026-06-03T00:30:00+00:00",
            "signal_timestamp": "2026-06-02T21:00:00+00:00",
            "strategy": "signal_strategy",
            "decision_price": 103.0,
        },
        {
            "execution_timestamp": "2026-06-03T02:00:00+02:00",
            "signal_timestamp": "2026-06-02T23:00:00+02:00",
            "strategy": "signal_strategy",
            "decision_price": 102.0,
        },
    ]

    assert _latest_operational_row(rows)["decision_price"] == 103.0


def test_operational_producer_rejects_negative_or_unpaired_costs() -> None:
    values = dict(
        instrument_id="VWCE", strategy="signal_strategy",
        signal_timestamp="2026-06-01T00:00:00", execution_timestamp="2026-06-02T00:00:00",
        signal_date=pd.Timestamp("2026-06-01").date(), execution_date=pd.Timestamp("2026-06-02").date(),
        decision_price=100.0, next_open=99.0, next_period_close=102.0,
        high=103.0, low=98.0, open_price=99.0,
        cost_spread_assumption_bps=-1.0,
        cost_spread_assumption_source="execution-cost-v1",
        decision_price_source_identity="source|VWCE",
        next_open_source_identity="source|VWCE",
        next_period_source_identity="source|VWCE",
        canonical_session_dates=pd.to_datetime(["2026-06-01", "2026-06-02"]),
    )
    rejected = _instrument_operational_evidence(**values)
    assert rejected["evidence_status"] == "unavailable"
    rejected = _instrument_operational_evidence(**{**values, "cost_spread_assumption_bps": 1.0, "cost_spread_assumption_source": None})
    assert rejected["evidence_status"] == "unavailable"


def test_operational_ohlc_is_scaled_from_the_same_row_adjustment_factor() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-06-01", "etf_id": "VWCE", "open": 50.0, "high": 55.0, "low": 45.0, "close": 50.0, "adjusted_close": 100.0},
            {"date": "2026-06-02", "etf_id": "VWCE", "open": 51.0, "high": 56.0, "low": 46.0, "close": 51.0, "adjusted_close": 102.0},
        ]
    )
    adjusted_open = _corporate_action_adjusted_pivot(prices, "open", ["VWCE"])
    adjusted_high = _corporate_action_adjusted_pivot(prices, "high", ["VWCE"])
    adjusted_low = _corporate_action_adjusted_pivot(prices, "low", ["VWCE"])
    assert adjusted_open.loc[pd.Timestamp("2026-06-02"), "VWCE"] == pytest.approx(102.0)
    assert adjusted_high.loc[pd.Timestamp("2026-06-02"), "VWCE"] == pytest.approx(112.0)
    assert adjusted_low.loc[pd.Timestamp("2026-06-02"), "VWCE"] == pytest.approx(92.0)


def test_backtest_operational_evidence_is_exactly_instrument_scoped() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    report = run_backtest(config, prices, rebalance_frequency_days=42)

    evidence = report.operational_evidence
    expected_spreads = {
        instrument_id: estimate_execution_cost(config, instrument_id, 1.0).spread_bps
        for instrument_id in evidence["instrument_id"].unique()
    }
    assert not evidence.empty
    assert evidence["instrument_id"].notna().all()
    assert evidence["fill_source"].eq("simulated_backtest").all()
    assert evidence["execution_allowed"].eq(False).all()
    assert evidence["session_state"].isna().all()
    assert evidence["auction_state"].isna().all()
    assert evidence["order_lifecycle"].isna().all()
    assert evidence["observed_range_spread_proxy"].notna().all()
    assert evidence["cost_spread_assumption_bps"].notna().all()
    assert evidence["cost_spread_assumption_source"].str.endswith(":CostEstimate.spread_bps").all()
    assert evidence.apply(
        lambda row: row["cost_spread_assumption_bps"] == expected_spreads[row["instrument_id"]],
        axis=1,
    ).all()
    assert evidence["estimated_cost_bps_source"].str.endswith(":CostEstimate.total_cost_bps").all()
    assert (evidence["estimated_cost_bps"] >= evidence["cost_spread_assumption_bps"]).all()
    assert (evidence["estimated_cost_bps"] > evidence["cost_spread_assumption_bps"]).any()
    missing_timestamps = evidence.loc[
        evidence["signal_timestamp"].isna() | evidence["execution_timestamp"].isna()
    ]
    assert missing_timestamps["evidence_status"].eq("unavailable").all()
    assert missing_timestamps["evidence_reason"].str.contains(
        "signal_or_execution_timestamp_unavailable", regex=False
    ).all()
    timestamped = evidence.drop(index=missing_timestamps.index)
    assert len(timestamped) + len(missing_timestamps) == len(evidence)
    assert (
        pd.to_datetime(timestamped["execution_timestamp"])
        > pd.to_datetime(timestamped["signal_timestamp"])
    ).all()
    assert "lookahead_protection" not in set(evidence["signal_timestamp"].astype(str))
    assert evidence["evidence_status"].eq("available").any()


def test_operational_evidence_readback_preserves_raw_integer_types() -> None:
    rows = [
        {
            "execution_delay_sessions": value,
            "calendar_opening_auction_minutes": value,
            "calendar_closing_auction_minutes": value,
        }
        for value in (1, True, 1.5, "1", None)
    ]
    report = BacktestReport(
        results=pd.DataFrame(),
        equity_curves=pd.DataFrame(),
        trade_log=pd.DataFrame(),
        signal_log=pd.DataFrame(),
        ai_added_value=False,
        metadata={"operational_evidence_rows": rows},
    )

    evidence = report.operational_evidence

    for field in rows[0]:
        assert evidence[field].tolist() == [1, True, 1.5, "1", None]


def test_sample_calendar_identity_survives_persisted_backtest_without_identity_master(
    tmp_path, monkeypatch
) -> None:
    config = load_config()
    real_generator = sample_data.generate_sample_prices
    monkeypatch.setattr(
        sample_data,
        "generate_sample_prices",
        lambda selected_config: real_generator(
            selected_config, periods=360, end_date=pd.Timestamp("2026-06-26").date()
        ),
    )
    raw_dir = tmp_path / "raw"
    portfolios_dir = tmp_path / "portfolios"
    (raw_dir / "prices").mkdir(parents=True)
    portfolios_dir.mkdir()
    monkeypatch.setattr(sample_data, "RAW_DIR", raw_dir)
    monkeypatch.setattr(sample_data, "PORTFOLIOS_DIR", portfolios_dir)
    monkeypatch.setattr(sample_data, "ensure_project_dirs", lambda: None)
    parquet_path = tmp_path / "validated" / "prices.parquet"
    real_write_prices = duckdb_store.write_prices
    monkeypatch.setattr(
        duckdb_store,
        "write_prices",
        lambda prices: real_write_prices(prices, parquet_path),
    )

    price_csv, _ = sample_data.ensure_sample_files(config, force=True)
    persisted_csv = price_csv.read_text(encoding="utf-8")
    assert "'calendar_id': 'XETR'" not in persisted_csv
    persisted_identity = pd.read_csv(price_csv).loc[
        lambda frame: frame["etf_id"].eq("VWCE"), "calendar_identity"
    ].iloc[0]
    assert json.loads(persisted_identity)["identity_objects"][0]["fields"]["calendar_id"] == "XETR"

    duckdb_store.initialise_store(config, force_sample=True)
    prices = duckdb_store.load_prices(parquet_path)
    identity = prices.loc[prices["etf_id"].eq("VWCE"), "calendar_identity"].iloc[0]
    assert isinstance(identity, dict)
    assert identity["instrument_id"] == "VWCE"

    report = run_backtest(config, prices, rebalance_frequency_days=42)
    evidence = report.operational_evidence
    available = evidence.loc[evidence["evidence_status"].eq("available")]
    assert not available.empty
    assert all(value is False for value in available["execution_allowed"].tolist())
    instrument_id = str(available.iloc[0]["instrument_id"])
    panel = _operational_evidence_panel(report, instrument_id)
    assert panel["status"] == "available"
    assert panel["rows"]
    assert panel["execution_allowed"] is False

    malformed = pd.read_csv(price_csv)
    malformed.loc[malformed["etf_id"].eq("VWCE"), "calendar_identity"] = (
        "{'status': 'available'}"
    )
    malformed_path = tmp_path / "malformed.csv"
    malformed.to_csv(malformed_path, index=False)
    malformed_loaded = duckdb_store.read_price_csv(malformed_path)
    assert malformed_loaded.loc[malformed_loaded["etf_id"].eq("VWCE"), "calendar_identity"].isna().all()

    unavailable_identity = {
        "status": "unavailable",
        "instrument_id": "VWCE",
        "fields": {
            "mic": "XETR",
            "calendar_id": "XETR",
            "timezone": "Europe/Berlin",
            "listing_id": "listing:VWCE:XETR",
            "source_id": "unavailable-source",
            "known_at": "2026-01-01T00:00:00+00:00",
            "valid_from": "2020-01-01",
        },
    }
    contradictory = pd.read_csv(price_csv)
    contradictory.loc[contradictory["etf_id"].eq("VWCE"), "calendar_identity"] = json.dumps(
        unavailable_identity, sort_keys=True, separators=(",", ":")
    )
    contradictory_csv = tmp_path / "contradictory.csv"
    contradictory.to_csv(contradictory_csv, index=False)
    contradictory_parquet = tmp_path / "validated" / "contradictory.parquet"
    real_write_prices(
        duckdb_store.read_price_csv(contradictory_csv), contradictory_parquet
    )
    contradictory_report = run_backtest(
        config,
        duckdb_store.load_prices(contradictory_parquet),
        rebalance_frequency_days=42,
    )
    contradictory_panel = _operational_evidence_panel(contradictory_report, "VWCE")
    assert contradictory_panel["status"] == "unavailable"
    assert contradictory_panel["rows"] == []
    assert contradictory_panel["execution_allowed"] is False


def test_unreadable_identity_store_never_uses_sample_calendar_fallback(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "data" / "clean" / "instrument_identity.parquet",
    )
    database = services.storage_layout(tmp_path).transactional_path
    database.parent.mkdir(parents=True)
    database.write_bytes(b"corrupt identity store")
    store, resolver = services._open_backtest_calendar_identity_resolver()
    assert store is None
    assert resolver is not None
    config = load_config()
    prices = generate_sample_prices(
        config, periods=360, end_date=pd.Timestamp("2026-06-26").date()
    )

    report = run_backtest(
        config,
        prices,
        rebalance_frequency_days=42,
        calendar_identity_resolver=resolver,
    )

    assert not report.operational_evidence["evidence_status"].eq("available").any()
    assert report.operational_evidence["execution_allowed"].eq(False).all()


def test_identity_resolver_rejects_naive_point_in_time(tmp_path, monkeypatch) -> None:
    class Store:
        def projection(self, *_args, **_kwargs):
            raise AssertionError("naive cutoff must not query canonical identity")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "data" / "clean" / "instrument_identity.parquet",
    )
    database = services.storage_layout(tmp_path).transactional_path
    database.parent.mkdir(parents=True)
    database.write_bytes(b"store existence only")
    monkeypatch.setattr(services, "IdentityMasterStore", lambda _root, **_kwargs: Store())
    store, resolver = services._open_backtest_calendar_identity_resolver()
    assert store is not None
    assert resolver is not None

    projection = resolver("VWCE", "2026-06-01T00:00:00")

    assert projection == {
        "status": "unavailable",
        "instrument_id": "VWCE",
        "reason": "canonical_identity_point_in_time_unavailable",
        "execution_allowed": False,
    }


def test_missing_identity_store_remains_read_only_and_explicitly_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "data" / "clean" / "instrument_identity.parquet",
    )

    store, resolver = services._open_backtest_calendar_identity_resolver()

    assert store is None
    assert resolver is None


def test_identity_resolver_service_probe_never_mutates_source_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "data" / "clean" / "instrument_identity.parquet",
    )
    with services.IdentityMasterStore(tmp_path):
        pass
    database = services.storage_layout(tmp_path).transactional_path

    def source_state() -> dict[str, tuple[bytes, int]]:
        return {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in database.parent.iterdir()
            if path.is_file()
        }

    before = source_state()
    store, resolver = services._open_backtest_calendar_identity_resolver()
    try:
        assert store is not None
        assert resolver is not None
        assert source_state() == before
    finally:
        if store is not None:
            store.close()
    assert source_state() == before


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_identity_resolver_service_rejects_active_journal_without_mutation(
    tmp_path, monkeypatch, suffix
) -> None:
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "data" / "clean" / "instrument_identity.parquet",
    )
    with services.IdentityMasterStore(tmp_path):
        pass
    database = services.storage_layout(tmp_path).transactional_path
    journal = Path(f"{database}{suffix}")
    journal.write_bytes(b"active journal evidence")
    before = {path.name: path.read_bytes() for path in database.parent.iterdir() if path.is_file()}

    store, resolver = services._open_backtest_calendar_identity_resolver()

    assert store is None
    assert resolver is not None
    assert {path.name: path.read_bytes() for path in database.parent.iterdir() if path.is_file()} == before


def test_backtest_signal_replay_is_nonpublishing_and_deterministically_timestamped(monkeypatch) -> None:
    from etf_cockpit.backtest import engine as backtest_engine
    from etf_cockpit.signals import signal_pipeline

    published: list[object] = []
    observed: list[tuple[date, datetime | None]] = []
    original_generate_signals = backtest_engine.generate_signals

    def capture_signals(*args, **kwargs):
        signals = original_generate_signals(*args, **kwargs)
        observed.extend((signal.signal_date, signal.timestamp) for signal in signals)
        return signals

    monkeypatch.setattr(signal_pipeline, "append_jsonl", lambda *args, **kwargs: published.append((args, kwargs)))
    monkeypatch.setattr(backtest_engine, "generate_signals", capture_signals)
    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    identities = {
        instrument_id: prices.loc[prices["etf_id"].eq(instrument_id), "calendar_identity"].iloc[0]
        for instrument_id in config.universe.enabled_ids
    }

    report = run_backtest(config, prices, rebalance_frequency_days=42)
    class Store:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        services,
        "_open_backtest_calendar_identity_resolver",
        lambda: (
            Store(),
            lambda instrument_id, _timestamp: identities[instrument_id],
        ),
    )
    replay = services._replay_backtest_for_cache(config, prices, {})

    assert isinstance(report, BacktestReport)
    assert isinstance(replay, BacktestReport)
    assert published == []
    assert observed
    assert all(
        timestamp == datetime.combine(signal_date, datetime.min.time(), tzinfo=timezone.utc)
        for signal_date, timestamp in observed
    )


def test_backtest_resolves_canonical_identity_at_aware_signal_close() -> None:
    config = load_config()
    prices = generate_sample_prices(
        config, periods=360, end_date=pd.Timestamp("2026-06-26").date()
    )
    identities = {
        instrument_id: prices.loc[
            prices["etf_id"].eq(instrument_id), "calendar_identity"
        ].iloc[0]
        for instrument_id in config.universe.enabled_ids
    }
    cutoffs: list[pd.Timestamp] = []

    def resolve(instrument_id: str, signal_timestamp: object):
        cutoff = pd.Timestamp(signal_timestamp)
        cutoffs.append(cutoff)
        return identities[instrument_id]

    report = run_backtest(
        config,
        prices,
        rebalance_frequency_days=42,
        calendar_identity_resolver=resolve,
    )

    assert cutoffs
    assert all(cutoff.tzinfo is not None and cutoff.utcoffset() is not None for cutoff in cutoffs)
    assert report.operational_evidence["evidence_status"].eq("available").any()


def test_cached_operational_replay_normalises_only_producer_dates() -> None:
    replayed = [
        {
            "signal_date": date(2026, 6, 1),
            "execution_date": date(2026, 6, 2),
            "execution_delay_sessions": 1,
            "execution_allowed": False,
        }
    ]
    persisted = [
        {
            "signal_date": "2026-06-01",
            "execution_date": "2026-06-02",
            "execution_delay_sessions": 1,
            "execution_allowed": False,
        }
    ]

    assert services._operational_evidence_rows_match_replay(persisted, replayed)
    assert not services._operational_evidence_rows_match_replay(
        persisted,
        [{**replayed[0], "execution_delay_sessions": True}],
    )
    assert not services._operational_evidence_rows_match_replay(
        persisted,
        [replayed[0], replayed[0]],
    )


def test_sample_calendar_identity_config_rejects_non_mapping_yaml(
    tmp_path, monkeypatch
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "sample_calendar_identities.yaml").write_text(
        "- malformed\n", encoding="utf-8"
    )
    monkeypatch.setattr(sample_data, "CONFIG_DIR", config_dir)

    assert sample_data._sample_calendar_identities() == {}


def test_explicit_all_in_cost_does_not_masquerade_as_spread() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())

    report = run_backtest(
        config,
        prices,
        rebalance_frequency_days=42,
        transaction_cost_bps=23.0,
    )

    evidence = report.operational_evidence
    assert not evidence.empty
    assert evidence["cost_spread_assumption_bps"].isna().all()
    assert evidence["cost_spread_assumption_source"].isna().all()
    assert evidence["estimated_cost_bps"].eq(23.0).all()
    assert evidence["estimated_cost_bps_source"].eq("explicit_transaction_cost_bps").all()
    assert report.trade_log["estimated_cost_bps"].eq(23.0).all()


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
    assert "Instrument operational evidence" in source
    assert "Observed H-L proxy" in source
    assert "Cost spread bps" in source
    assert "Estimated all-in cost bps" in source
    assert "evidence_status" in source
    assert "evidence_reason" in source
    assert "fill_source" in source
    assert "latest_operational_rows" in source
    assert "validated_operational_rows[:12]" not in source
    assert "Operational evidence" in inspect.getsource(_signals_operational_evidence)
    assert "aggregate aliases are excluded" in inspect.getsource(_signals_operational_evidence)


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
    from etf_cockpit.app.selectors import instrument_detail as selector

    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "absent-identity-root" / "data" / "clean" / "instrument_identity.parquet",
    )
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
    # This test owns persistence/type round-trip behavior. Dedicated replay
    # adversarial tests exercise independent full derivation.
    monkeypatch.setattr(
        services,
        "_replay_backtest_for_cache",
        lambda *_args, **_kwargs: generated,
    )
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
    assert len(cached.operational_evidence) == len(generated.operational_evidence)
    assert cached.operational_evidence["fill_source"].eq("simulated_backtest").all()
    available = cached.operational_evidence.loc[
        cached.operational_evidence["evidence_status"].eq("available")
    ]
    assert not available.empty
    instrument_id = str(available.iloc[-1]["instrument_id"])
    panel = selector._operational_evidence_panel(cached, instrument_id)
    assert panel["status"] == "available"
    assert panel["rows"]
    assert panel["execution_allowed"] is False
    metadata_path = tmp_path / "backtest_metadata.json"
    metadata_sidecar_path = services._universe_cache_meta_path(metadata_path)
    original_metadata = metadata_path.read_bytes()
    original_metadata_sidecar = metadata_sidecar_path.read_bytes()

    def write_metadata(metadata: dict[str, object]) -> None:
        payload = json.dumps(metadata, sort_keys=True, indent=2).encode("utf-8")
        sidecar = json.loads(original_metadata_sidecar)
        sidecar["payload_sha256"] = hashlib.sha256(payload).hexdigest()
        metadata_path.write_bytes(payload)
        metadata_sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    metadata = json.loads(original_metadata)
    metadata["operational_evidence_rows"][0]["decision_price"] = 999_999.0
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert service._load_cached_backtest() is None
    metadata_path.write_bytes(original_metadata)

    for field, forged_value in (
        ("strategy", "forged_strategy"),
        ("signal_timestamp", "2000-01-01T00:00:00+00:00"),
        ("execution_timestamp", "2000-01-02T00:00:00+00:00"),
        ("cost_spread_assumption_bps", 123.0),
        ("cost_spread_assumption_source", "forged-cost-source"),
        ("estimated_cost_bps", 456.0),
        ("estimated_cost_bps_source", "forged-estimated-cost-source"),
    ):
        forged_metadata = json.loads(original_metadata)
        forged_row = next(
            item
            for item in forged_metadata["operational_evidence_rows"]
            if item["evidence_status"] == "available"
        )
        forged_row[field] = forged_value
        write_metadata(forged_metadata)
        assert service._load_cached_backtest() is None

    downgraded_metadata = json.loads(original_metadata)
    downgraded_row = next(
        item
        for item in downgraded_metadata["operational_evidence_rows"]
        if item["evidence_status"] == "available"
    )
    downgraded_row["evidence_status"] = "unavailable"
    downgraded_row["decision_price"] = 999_999.0
    write_metadata(downgraded_metadata)
    assert service._load_cached_backtest() is None
    metadata_path.write_bytes(original_metadata)
    metadata_sidecar_path.write_bytes(original_metadata_sidecar)

    forged_metadata = json.loads(original_metadata)
    forged_row = next(
        item
        for item in forged_metadata["operational_evidence_rows"]
        if item["evidence_status"] == "available"
    )
    forged_row["calendar_session_lineage_hash"] = "f" * 64
    forged_payload = json.dumps(forged_metadata).encode("utf-8")
    forged_sidecar = json.loads(original_metadata_sidecar)
    forged_sidecar["payload_sha256"] = hashlib.sha256(forged_payload).hexdigest()
    metadata_path.write_bytes(forged_payload)
    metadata_sidecar_path.write_text(json.dumps(forged_sidecar), encoding="utf-8")
    assert service._load_cached_backtest() is None
    metadata_path.write_bytes(original_metadata)
    metadata_sidecar_path.write_bytes(original_metadata_sidecar)

    metadata = json.loads(original_metadata)
    metadata["reference_identity"]["execution_allowed"] = 0
    malformed_metadata = json.dumps(metadata).encode("utf-8")
    metadata_sidecar = json.loads(original_metadata_sidecar)
    metadata_sidecar["payload_sha256"] = hashlib.sha256(malformed_metadata).hexdigest()
    metadata_path.write_bytes(malformed_metadata)
    metadata_sidecar_path.write_text(json.dumps(metadata_sidecar), encoding="utf-8")
    assert service._load_cached_backtest() is None
    metadata_path.write_bytes(original_metadata)
    metadata_sidecar_path.write_bytes(original_metadata_sidecar)

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

    metadata_path.write_bytes(original_metadata)
    metadata_sidecar_path.write_bytes(original_metadata_sidecar)
    results_path.write_bytes(original_results)
    sidecar_path.write_bytes(original_sidecar)
    empty_replay = BacktestReport(
        results=generated.results,
        equity_curves=generated.equity_curves,
        trade_log=generated.trade_log,
        signal_log=generated.signal_log,
        ai_added_value=generated.ai_added_value,
        quality_label=generated.quality_label,
        quality_notes=generated.quality_notes,
        metadata={**generated.metadata, "operational_evidence_rows": []},
        quality_momentum_evidence=generated.quality_momentum_evidence,
    )
    empty_metadata = json.loads(original_metadata)
    empty_metadata["operational_evidence_rows"] = []
    write_metadata(empty_metadata)
    monkeypatch.setattr(
        services,
        "_replay_backtest_for_cache",
        lambda *_args, **_kwargs: empty_replay,
    )
    assert service._load_cached_backtest() is not None
    monkeypatch.setattr(
        services,
        "_replay_backtest_for_cache",
        lambda *_args, **_kwargs: generated,
    )
    assert service._load_cached_backtest() is None


def test_backtest_service_reuses_mixed_availability_integer_diagnostics(
    tmp_path, monkeypatch
) -> None:
    from etf_cockpit.data.etf_structure import LocalStructuralEvidence

    config = load_config()
    prices = generate_sample_prices(config, periods=420, end_date=pd.Timestamp("2026-06-26").date())
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "absent-identity-root" / "data" / "clean" / "instrument_identity.parquet",
    )
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
    # Preserve the real persisted diagnostics while avoiding a second full
    # backtest in this type-round-trip test; replay has separate coverage.
    monkeypatch.setattr(
        services,
        "_replay_backtest_for_cache",
        lambda *_args, **_kwargs: generated,
    )
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


def test_backtest_service_round_trips_genuinely_unavailable_operational_rows(
    tmp_path, monkeypatch
) -> None:
    from etf_cockpit.data.etf_structure import LocalStructuralEvidence

    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    prices["calendar_identity"] = None
    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "absent-identity-root" / "data" / "clean" / "instrument_identity.parquet",
    )
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
    assert not generated.operational_evidence["evidence_status"].eq("available").any()
    cached = service._load_cached_backtest()

    assert cached is not None
    assert not cached.operational_evidence["evidence_status"].eq("available").any()
    assert cached.operational_evidence["execution_allowed"].eq(False).all()


def test_backtest_cache_reader_uses_one_complete_snapshot_under_interleaving(
    tmp_path, monkeypatch
) -> None:
    from etf_cockpit.data.etf_structure import LocalStructuralEvidence

    config = load_config()
    prices = generate_sample_prices(config, periods=360, end_date=pd.Timestamp("2026-06-26").date())
    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(
        services,
        "IDENTITY_PATH",
        tmp_path / "absent-identity-root" / "data" / "clean" / "instrument_identity.parquet",
    )
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
    # This test isolates one atomic cache-file snapshot. Full operational
    # evidence replay is validated independently.
    monkeypatch.setattr(
        services,
        "_replay_backtest_for_cache",
        lambda *_args, **_kwargs: generated,
    )

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
        "backtest_metadata.json.meta.json",
    }
    assert cached.results.loc[cached.results["strategy_name"] == "signal_strategy", "calmar"].iloc[0] != 999.0
