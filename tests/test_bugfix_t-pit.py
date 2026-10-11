from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.analysis import stock_metrics
from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.analysis.fund_analysis import _point_in_time_fx
from etf_cockpit.application import signal_service
from etf_cockpit.application.ui_views.stock_research import build_stock_view
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityIssue, DataQualityReport
from etf_cockpit.data import stock_fundamentals
from etf_cockpit.data.fx_data import validate_fx_rates
from etf_cockpit.data.statement_normalisation import statement_view
from etf_cockpit.features.etf_economics import calculate_etf_liquidity
from etf_cockpit.features.feature_store import (
    FeatureDefinition,
    LocalFeatureStore,
    TargetDefinition,
    _forward_benchmark_return,
    _prepare_benchmark,
)
from etf_cockpit.models.coverage_audit import build_coverage_audit
from etf_cockpit.models.uncertainty import uncertainty_gate_reasons
from etf_cockpit.signals.canonical_scoring import canonical_score_from_signal_row
from etf_cockpit.validation.protocol import ValidationSpec, evaluate_trials


UTC = timezone.utc


def _prices(dates: pd.DatetimeIndex) -> pd.DataFrame:
    close = pd.Series(range(100, 100 + len(dates)), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "etf_id": "VWCE",
            "open": close - 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "adjusted_close": close,
            "volume": 10_000.0,
            "currency": "EUR",
        }
    )


def test_chat_p03_n002_backfilled_fx_is_known_at_decision_time() -> None:
    rates = pd.DataFrame(
        [{"as_of_date": "2026-01-01", "base_currency": "EUR", "quote_currency": "USD", "rate": 1.1, "source": "fixture", "ingested_at": "2026-02-05T09:00:00Z"}]
    )
    decision = datetime(2026, 2, 10, 12, tzinfo=UTC)
    start, end, _, _ = _point_in_time_fx(rates, "EUR", "USD", date(2026, 1, 1), date(2026, 1, 1), decision)
    late = rates.assign(ingested_at="2026-02-11T09:00:00Z")
    late_start, _, _, _ = _point_in_time_fx(late, "EUR", "USD", date(2026, 1, 1), date(2026, 1, 1), decision)

    assert float(start) == float(end) == pytest.approx(1.1)
    assert late_start is None


def test_chat_p08_n005_promotion_compares_final_scores_to_baseline_final_score() -> None:
    spec = ValidationSpec(n_splits=3, test_size=10, final_test_size=10, bootstrap_repetitions=30, seed=7)
    baseline = np.full(80, 0.2)
    challenger = np.full(80, 0.3)
    baseline[-10:] = 0.5
    challenger[-10:] = 0.25
    report = evaluate_trials({"baseline": baseline, "challenger": challenger}, spec=spec)
    missing_baseline = evaluate_trials({"challenger": challenger}, spec=spec)
    baseline_row = next(row for row in report.trials if row.trial_id == "baseline")

    assert report.selected_trial_id == "challenger"
    assert report.final_test_score == pytest.approx(0.25)
    assert baseline_row.final_test_score == pytest.approx(0.5)
    assert report.promotion_eligible is False
    assert "promotion_evidence_insufficient_or_unstable" not in report.warnings
    assert missing_baseline.promotion_eligible is False
    assert "baseline_final_score_unavailable" in missing_baseline.warnings


def test_p01_n005_future_fx_quote_is_rejected() -> None:
    rates = pd.DataFrame(
        [{"as_of_date": "2026-10-12", "base_currency": "EUR", "quote_currency": "USD", "rate": 1.1}]
    )

    result = validate_fx_rates(rates, today=date(2026, 10, 10))

    assert not result.ok
    assert "FX rates contain future-dated quotes." in result.errors


def test_p03_n001_etf_liquidity_uses_only_prices_through_as_of() -> None:
    past_dates = pd.date_range("2026-09-01", periods=30, freq="B")
    future_dates = pd.date_range(past_dates[-1] + pd.Timedelta(days=1), periods=20, freq="B")
    prices = _prices(past_dates.append(future_dates))
    report = calculate_etf_liquidity(load_config(), prices, "VWCE", as_of=past_dates[-1].date())
    future_only = calculate_etf_liquidity(load_config(), _prices(future_dates), "VWCE", as_of=past_dates[-1].date())

    assert report.status == "available"
    assert report.rows == 30
    assert pd.Timestamp(report.as_of).date() == past_dates[-1].date()
    assert future_only.status == "unavailable"


def test_p03_n002_future_quote_is_excluded_from_quote_context() -> None:
    prices = _prices(pd.date_range("2026-10-01", periods=8, freq="B"))
    cutoff = prices["date"].max().date()
    quotes = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "quote_timestamp": f"{cutoff.isoformat()}T10:00:00Z", "bid": 100.0, "ask": 102.0, "nav": 101.0, "currency": "EUR"},
            {"instrument_id": "VWCE", "quote_timestamp": "2026-10-20T10:00:00Z", "bid": 200.0, "ask": 202.0, "nav": 201.0, "currency": "EUR"},
        ]
    )
    report = calculate_etf_liquidity(load_config(), prices, "VWCE", quote_evidence=quotes, as_of=cutoff)
    future_only = calculate_etf_liquidity(load_config(), prices, "VWCE", quote_evidence=quotes.iloc[[1]], as_of=cutoff)

    assert report.quote_status == "available"
    assert report.bid_eur == 100.0
    assert future_only.quote_status == "unavailable"


def test_p03_n003_non_eur_untyped_quote_values_are_not_published_as_eur() -> None:
    prices = _prices(pd.date_range("2026-10-01", periods=8, freq="B"))
    cutoff = prices["date"].max().date()
    quote = {
        "instrument_id": "VWCE",
        "quote_timestamp": f"{cutoff.isoformat()}T10:00:00Z",
        "currency": "GBP",
        "bid": 80.0,
        "ask": 82.0,
        "nav": 81.0,
    }

    report = calculate_etf_liquidity(load_config(), prices, "VWCE", quote_evidence=quote, as_of=cutoff)

    assert report.bid_eur is None
    assert report.ask_eur is None
    assert report.nav_eur is None
    assert "quote_currency_not_eur" in report.missing_evidence


def test_p03_n004_equal_known_at_periods_use_official_source_deterministically() -> None:
    known_at = datetime(2026, 2, 1, tzinfo=UTC)
    official = stock_metrics.Period(date(2025, 12, 31), "FY", known_at, "EUR", "sec_edgar", {"revenue": 120.0}, source_ref="filing-2")
    vendor = stock_metrics.Period(date(2025, 12, 31), "FY", known_at, "EUR", "yfinance", {"revenue": 100.0}, source_ref="vendor-1")

    first = stock_metrics.known_periods([vendor, official], known_at)
    second = stock_metrics.known_periods([official, vendor], known_at)

    assert first == second
    assert first[0].source == "sec_edgar"
    assert first[0].values["revenue"] == 120.0


def test_p03_n008_second_universe_pass_keeps_each_instruments_analyst(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, float | None]] = []
    empty_periods = pd.DataFrame(columns=stock_fundamentals.PERIOD_COLUMNS)
    empty_snapshots = pd.DataFrame(columns=stock_fundamentals.SNAPSHOT_COLUMNS)
    monkeypatch_values = {"A": 1.0, "B": 2.0}

    def fake_build(instrument_id, periods, decision, market, analyst, config, **kwargs):
        captured.append((instrument_id, None if analyst is None else analyst.revisions_up_30d))
        return SimpleNamespace(metrics={})

    records = [su.StockRecord("A", "A", "A", "EUR", "EU", "Technology"), su.StockRecord("B", "B", "B", "EUR", "EU", "Technology")]
    prices = pd.DataFrame(columns=["etf_id", "date", "close", "currency"])
    decision = datetime(2026, 10, 10, tzinfo=UTC)
    su._CACHE.clear()
    monkeypatch.setattr(stock_fundamentals, "read_fundamentals", lambda _root: empty_periods)
    monkeypatch.setattr(stock_fundamentals, "read_snapshots", lambda _root: empty_snapshots)
    monkeypatch.setattr(stock_fundamentals, "read_fx", lambda _root: pd.DataFrame(columns=stock_fundamentals.FX_COLUMNS))
    monkeypatch.setattr(stock_fundamentals, "periods_for", lambda _iid, _frame, _chain: [])
    monkeypatch.setattr(stock_fundamentals, "latest_snapshot", lambda _iid, _frame, _decision: None)
    monkeypatch.setattr(stock_fundamentals, "latest_analyst", lambda iid, _frame, _decision: {"revisions_up_30d": monkeypatch_values[iid]})
    monkeypatch.setattr(stock_fundamentals, "no_data_reason", lambda *_args: None)
    monkeypatch.setattr(su, "load_user_peers", lambda _root: {})
    monkeypatch.setattr(su, "market_inputs", lambda *_args: su.MarketInputs())
    monkeypatch.setattr(su, "_profile", lambda record, *_args: SimpleNamespace(instrument_id=record.instrument_id))
    monkeypatch.setattr(su, "auto_peers", lambda *_args: [])
    monkeypatch.setattr(su, "effective_peers", lambda *_args: [])
    monkeypatch.setattr(su, "build_stock_evidence", fake_build)
    for order in (records, list(reversed(records))):
        captured.clear()
        su.build_universe_evidence(order, prices, decision, config={"sources": {"chain": ["sec_edgar", "yfinance"]}})
        assert captured[len(order):] == [(record.instrument_id, monkeypatch_values[record.instrument_id]) for record in order]
    su._CACHE.clear()


def test_p03_n009_cache_key_changes_when_price_content_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "stock_config.yaml"
    config_path.write_text("sources: {}\n", encoding="utf-8")
    monkeypatch.setattr(stock_fundamentals, "store_paths", lambda _root: {})
    monkeypatch.setattr(stock_fundamentals, "config_path", lambda _root: config_path)
    built: list[float] = []

    def build(_records, prices, decision, *, root=None):
        built.append(float(prices.iloc[0]["close"]))
        return su.UniverseEvidence(decision)

    monkeypatch.setattr(su, "build_universe_evidence", build)
    su._CACHE.clear()
    records = [su.StockRecord("A", "A", "A", "EUR", "EU", "Technology")]
    decision = datetime(2026, 10, 10, tzinfo=UTC)
    first = pd.DataFrame({"date": ["2026-10-09"], "etf_id": ["A"], "close": [10.0], "volume": [100.0], "currency": ["EUR"]})
    changed = first.assign(close=11.0)

    su.get_universe_evidence(records, first, decision, root=tmp_path)
    su.get_universe_evidence(records, changed, decision, root=tmp_path)

    assert built == [10.0, 11.0]
    su._CACHE.clear()


def test_p03_n010_statement_cutoff_keeps_same_day_intraday_facts() -> None:
    common = {
        "instrument_id": "ABC",
        "canonical_metric": "revenue",
        "concept": "Revenue",
        "unit": "USD",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "filed": "2025-02-10",
        "form": "10-K",
        "accession": "filing-1",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "source_id": "sec_edgar:filing-1",
        "mapping_status": "mapped",
        "mapping_confidence": "high",
        "manual_review_required": False,
        "restatement_kind": "reported",
        "currency": "USD",
        "period_type": "duration",
    }
    facts = pd.DataFrame(
        [
            {**common, "value": 100.0, "available_at": "2025-02-10T12:00:00Z", "known_at": "2025-02-10T12:00:00Z", "source_id": "sec_edgar:morning"},
            {**common, "value": 110.0, "available_at": "2025-02-10T16:00:00Z", "known_at": "2025-02-10T16:00:00Z", "source_id": "sec_edgar:afternoon"},
        ]
    )

    view = statement_view(facts, "as_known_at", as_known_at="2025-02-10T15:00:00Z")
    before_available = statement_view(facts, "as_known_at", as_known_at="2025-02-10T11:00:00Z")

    assert list(view["value"]) == [100.0]
    assert before_available.empty


def test_p03_n011_future_snapshot_does_not_set_historical_no_data_reason() -> None:
    snapshots = pd.DataFrame(
        [{"instrument_id": "ABC", "known_at": "2026-10-11T09:00:00Z", "status": "error", "reason": "future provider error"}]
    ).reindex(columns=stock_fundamentals.SNAPSHOT_COLUMNS)

    reason = stock_fundamentals.no_data_reason("ABC", snapshots, datetime(2026, 10, 10, tzinfo=UTC), False)

    assert reason is not None
    assert "future provider error" not in reason


def test_p04_n001_intraday_availability_is_compared_with_exact_decision_time(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    features = pd.DataFrame(
        {
            "etf_id": ["A"],
            "date": ["2026-01-01"],
            "available_at": ["2026-01-02T16:00:00Z"],
            "signal": [1.0],
        }
    )
    intraday = store.materialise(features, ["2026-01-02T10:00:00Z"], feature_ids=["signal"])
    date_only = store.materialise(features.assign(available_at="2026-01-02"), ["2026-01-02"], feature_ids=["signal"])

    assert pd.isna(intraday.loc[0, "signal"])
    assert bool(intraday.loc[0, "missing_signal"])
    assert date_only.loc[0, "signal"] == 1.0


def test_p04_n002_forward_benchmark_never_uses_a_row_after_target_date() -> None:
    benchmark = pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02", "2026-01-05"], "adjusted_close": [100.0, 101.0, 110.0]}
    )
    prepared = _prepare_benchmark(benchmark, "date", "adjusted_close")
    no_in_range = prepared.iloc[[0, 2]]

    assert _forward_benchmark_return(prepared, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")) == pytest.approx(0.01)
    assert _forward_benchmark_return(no_in_range, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")) is None


def test_p04_n003_unknown_embargo_is_counted_as_overlap(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_target(TargetDefinition("return_2d", 2, embargo_days=1))
    targets = pd.DataFrame(
        {"decision_time": ["2026-01-01"], "return_2d": [0.01], "return_2d__embargo_until": [pd.NaT]}
    )

    check = store.leakage_check(targets, "return_2d", validation_start="2026-01-03")

    assert check.safe is False
    assert check.overlapping_rows == 1
    assert check.message == "embargo_unknown"


def test_p04_n010_forecasts_older_than_configured_maximum_are_blocked() -> None:
    settings = {"minimum_confidence": 0.4, "maximum_forecast_age_days": 5}
    reasons = {
        age: uncertainty_gate_reasons(
            {"status": "available", "forecast_age_days": age, "disagreement_flagged": False},
            settings,
            effective_confidence=0.8,
        )
        for age in (4, 5, 6, 31)
    }
    missing_age = uncertainty_gate_reasons(
        {"status": "available", "forecast_age_days": None, "disagreement_flagged": False},
        settings,
        effective_confidence=0.8,
    )

    assert "forecast_stale" not in reasons[4]
    assert "forecast_stale" not in reasons[5]
    assert "forecast_stale" in reasons[6]
    assert "forecast_stale" in reasons[31]
    assert "forecast_stale" in missing_age


def test_p04_n012_signal_adapter_uses_report_staleness_for_component_eligibility(monkeypatch: pytest.MonkeyPatch) -> None:
    service_module = signal_service
    date_value = date(2026, 1, 2)
    captured: dict[str, pd.DataFrame] = {}
    report = DataQualityReport(date_value, [DataQualityIssue("A", "block", "stale_data", "old prices", date_value)])
    latest = pd.DataFrame(
        [{"etf_id": "A", "score_momentum": 0.2, "score_trend": 0.3, "score_relative_strength": 0.1, "score_risk": 0.4, "score_rebalance": 0.0}]
    )
    monkeypatch.setattr(service_module, "load_prices", lambda: pd.DataFrame({"date": pd.to_datetime([date_value]), "etf_id": ["A"]}))
    monkeypatch.setattr(service_module, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(service_module, "_benchmark_reference_snapshot_inputs", lambda *_args: object())
    monkeypatch.setattr(service_module, "_reference_context_from_inputs", lambda *_args, **_kwargs: SimpleNamespace(identity={"id": "test"}))
    monkeypatch.setattr(service_module, "_calculation_window", lambda *_args: object())
    monkeypatch.setattr(service_module, "_price_snapshot_binding", lambda *_args, **_kwargs: {"binding": "test"})
    monkeypatch.setattr(service_module, "_current_universe_revision", lambda: "revision")
    monkeypatch.setattr(service_module, "current_settings_revision", lambda: "settings")
    monkeypatch.setattr(service_module, "configured_forecast_request_identity", lambda _config: "request")
    monkeypatch.setattr(service_module, "load_features", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(service_module.FeatureService, "compute_features", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(service_module, "latest_features", lambda *_args: latest.copy())
    monkeypatch.setattr(service_module.DataService, "validate_prices", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(service_module, "model_availability", lambda _config: {"toto": False, "timesfm": False})
    monkeypatch.setattr(service_module, "load_latest_forecasts", lambda **_kwargs: pd.DataFrame())
    monkeypatch.setattr(service_module, "_load_structure_caps", lambda *_args: None)
    monkeypatch.setattr(service_module, "forecast_component_maps", lambda _frame: {})
    monkeypatch.setattr(service_module, "forecast_return_distributions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(service_module, "load_forecast_history", lambda: pd.DataFrame())
    monkeypatch.setattr(service_module, "_run_decision_shadow_guard", lambda *_args, **_kwargs: None)

    def capture(_config, latest_rows, *_args, **_kwargs):
        captured["latest"] = latest_rows.copy()
        return []

    monkeypatch.setattr(service_module, "generate_signals", capture)
    service_module.SignalService(load_config()).generate_signals(date_value)
    score = canonical_score_from_signal_row(captured["latest"].iloc[0], load_config(), date_value)

    assert captured["latest"].loc[0, "price_freshness"] == "stale"
    momentum = next(component for component in score.components if component["key"] == "momentum")
    assert momentum["freshness_status"] == "stale"
    assert momentum["score_eligible"] is False


def test_p04_n014_future_forecast_vintage_is_not_counted() -> None:
    universe = [{"id": "A", "enabled": True, "region": "EU", "sector": "Technology", "currency": "EUR", "exchange": "XETRA"}]
    prices = pd.DataFrame({"etf_id": ["A"], "date": ["2026-01-03"], "adjusted_close": [100.0]})
    forecasts = pd.DataFrame(
        [
            {"etf_id": "A", "forecast_date": "2026-01-02", "model_name": "baseline", "horizon_days": 1, "expected_return": 0.01, "status": "ok"},
            {"etf_id": "A", "forecast_date": "2026-01-04", "model_name": "baseline", "horizon_days": 1, "expected_return": 0.02, "status": "ok"},
        ]
    )

    report = build_coverage_audit(universe, prices, forecasts, as_of_date="2026-01-03")

    assert max(group.forecast_count for group in report.groups) == 1


def test_p07_n011_stale_forecast_vintage_is_anchored_and_marked_stale() -> None:
    dates = pd.date_range("2026-01-01", periods=31, freq="D")
    prices = pd.DataFrame({"etf_id": "A", "date": dates, "close": range(100, 131), "adjusted_close": range(100, 131)})
    forecasts = pd.DataFrame(
        [{"etf_id": "A", "model_name": "baseline", "forecast_date": dates[0], "horizon_days": 30, "q10_return": -0.1, "q50_return": 0.0, "q90_return": 0.1}]
    )

    view = build_stock_view(prices, forecasts, "A", "1M")

    assert view.baseline is None
    assert view.forecasts == []
    assert view.forecast_note == "forecast stale"

    fresh = forecasts.assign(forecast_date=dates[-5])
    fresh_view = build_stock_view(prices, fresh, "A", "1M")
    assert fresh_view.baseline is not None
    assert fresh_view.baseline.dates == [dates[-5] + pd.Timedelta(days=30)]
    assert fresh_view.baseline.q50 == [126.0]


def test_int_pit_1_intraday_feature_time_defaults_availability_exactly(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal"))
    features = pd.DataFrame({"etf_id": ["A"], "date": ["2026-01-02T16:00:00Z"], "signal": [1.0]})
    for candidate in (features, features.assign(available_at="2026-01-02T08:00:00Z")):
        early = store.materialise(candidate, ["2026-01-02T10:00:00Z"], feature_ids=["signal"])
        eligible = store.materialise(candidate, ["2026-01-02T16:00:00Z"], feature_ids=["signal"])
        assert pd.isna(early.loc[0, "signal"]) and bool(early.loc[0, "missing_signal"])
        assert eligible.loc[0, "signal"] == 1.0
    store.register_feature(FeatureDefinition("delayed", "signal", availability_delay_days=1))
    delayed = store.materialise(features, ["2026-01-03T10:00:00Z"], feature_ids=["delayed"])
    assert delayed.loc[0, "delayed"] == 1.0


@pytest.mark.parametrize("timestamp", [None, "invalid"])
def test_int_pit_2_unverifiable_quote_timestamps_are_unavailable(timestamp) -> None:
    prices = _prices(pd.date_range("2026-10-01", periods=8, freq="B"))
    quote = {"instrument_id": "VWCE", "currency": "EUR", "bid": 100.0, "ask": 102.0, "nav": 101.0}
    if timestamp is not None:
        quote["quote_timestamp"] = timestamp
    for candidate in (quote, pd.DataFrame([quote])):
        report = calculate_etf_liquidity(load_config(), prices, "VWCE", quote_evidence=candidate, as_of=prices["date"].max().date())
        assert report.quote_status == "unavailable"
        assert all(getattr(report, name) is None for name in ("bid_eur", "ask_eur", "nav_eur", "quoted_spread_bps", "premium_discount_bps"))
        assert "quote_timestamp" in report.missing_evidence


def test_int_pit_3_stale_forecast_rejection_is_separate_from_quantile_passthrough() -> None:
    prices = _prices(pd.bdate_range("2026-01-01", periods=90)).assign(etf_id="AAA")
    row = {"etf_id": "AAA", "model_name": "toto", "horizon_days": 21, "q10_return": -0.03,
           "q25_return": -0.015, "q50_return": 0.0, "q75_return": 0.015, "q90_return": 0.03}
    eligible = build_stock_view(prices, pd.DataFrame([{**row, "forecast_date": prices["date"].iloc[-1]}]), "AAA", "1Y")
    assert len(eligible.forecasts) == 1 and len(eligible.forecasts[0].dates) == 1
    stale = build_stock_view(prices, pd.DataFrame([{**row, "forecast_date": prices["date"].iloc[0]}]), "AAA", "1Y")
    assert stale.forecasts == [] and stale.baseline is None
    assert stale.forecast_note == "forecast stale"
