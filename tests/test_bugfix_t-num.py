from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from etf_cockpit.analysis.sparebank.valuation import executable_order
from etf_cockpit.analysis.stock_peers import size_band
from etf_cockpit.application.data_service import DataService
from etf_cockpit.application.forecast_service import ForecastService
from etf_cockpit.backtest.engine import BacktestDataUnavailableError, _price_pivot, run_backtest
from etf_cockpit.backtest.event_engine import (
    CertifiedSessionCalendar,
    EventDrivenBacktest,
    EventReplayError,
    MarketEvent,
    OrderRequest,
    SignalEvent,
    _event_key,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityReport
from etf_cockpit.core.values import years_before
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.evidence_ledger import EvidenceSource, ledger_entry_for_component
from etf_cockpit.data.market_adjustments import CorporateAction, MarketAdjustmentError, apply_total_return_adjustments
from etf_cockpit.data.providers import ManualLocalFileProvider, ProviderResult
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.features.feature_pipeline import compute_features
from etf_cockpit.models.baseline_models import baseline_forecast
from etf_cockpit.models.coverage_audit import _observed_price_ids
from etf_cockpit.models.forecast_scores import _choose_horizon_row_for, _latest_row
from etf_cockpit.portfolio.attribution import build_performance_attribution
from etf_cockpit.portfolio.robust_risk import _liquidity_adjusted_risk
from etf_cockpit.portfolio.stress_testing import StressScenario, run_stress_scenario
from etf_cockpit.signals.canonical_scoring import (
    CanonicalComponent,
    CanonicalScoreError,
    build_canonical_score,
    load_score_policy,
)
from etf_cockpit.signals.gates import evaluate_risk_gates
from etf_cockpit.signals.quality_momentum import quality_momentum_weights
from etf_cockpit.signals.scoring import component_scores
from etf_cockpit.trading.pre_trade_controls import PreTradeControls
from etf_cockpit.app.components.kit.data import ScoreBar
from etf_cockpit.data.market_calendar import ListingCalendarEvidence


def _action(action_id: str, *, ex_date: str = "2024-01-11") -> CorporateAction:
    return CorporateAction(
        action_id=action_id,
        instrument_id="ETF-A",
        action_type="split",
        announced_at="2023-12-15T00:00:00Z",
        effective_at="2024-01-10T00:00:00Z",
        ex_date=ex_date,
        payable_at=None,
        known_at="2023-12-15T00:00:00Z",
        revision=1,
        source="fixture:official-actions",
        source_id=f"fixture:{action_id}:r1",
        source_checksum=f"sha256:{action_id}:1",
        ratio=2.0,
    )


def _canonical_component(key: str, raw: float) -> CanonicalComponent:
    return CanonicalComponent(
        key=key,
        raw_metric=raw,
        score_role="attractiveness",
        peer_group="synthetic",
        source_id=f"source:{key}",
        source_authority="vendor_unofficial",
        freshness_status="ok",
        uncertainty="low",
        status="ok",
        explanation=f"{key} evidence",
    )


def _event_calendar() -> CertifiedSessionCalendar:
    return CertifiedSessionCalendar(
        ListingCalendarEvidence(
            listing_id="listing:ETF-A:XNYS",
            instrument_id="ETF-A",
            mic="XNYS",
            calendar_id="XNYS",
            timezone="America/New_York",
            source_id="identity:test-calendar",
            source_checksum="a" * 64,
            valid_from=date(2020, 1, 1),
            known_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )


def test_p01_n001() -> None:
    for invalid in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(MarketAdjustmentError):
            apply_total_return_adjustments(
                raw_prices=pd.DataFrame({"date": ["2024-01-10", "2024-01-11"], "close": [100.0, invalid]})
            )


def test_p01_n002() -> None:
    result = apply_total_return_adjustments(
        raw_prices=pd.DataFrame({"date": ["2024-01-10", "2024-01-12"], "close": [100.0, 50.0]}),
        actions=(_action("WEEKEND-SPLIT"),),
    )

    assert result.status == "quarantined"
    assert "unmatched_action_date:WEEKEND-SPLIT" in result.warnings


def test_p01_n003(tmp_path: Path) -> None:
    path = tmp_path / "invalid-date.csv"
    pd.DataFrame(
        {
            "date": ["geen-datum"],
            "etf_id": ["ETF-A"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "adjusted_close": [100.0],
            "volume": [1000.0],
            "currency": ["EUR"],
        }
    ).to_csv(path, index=False)

    result = ManualLocalFileProvider().import_file(path, "prices")
    report = validate_prices(result.data, as_of_date=date(2024, 1, 12))

    assert result.ok
    assert "invalid_dates" in {issue.code for issue in report.issues}


def test_p01_n004(monkeypatch: pytest.MonkeyPatch) -> None:
    assert years_before(date(2028, 2, 29), 5) == date(2023, 2, 28)
    captured: list[tuple[date, date]] = []

    class FrozenDate(date):
        @classmethod
        def today(cls) -> FrozenDate:
            return cls(2028, 2, 29)

    class UnavailableProvider:
        def fetch_prices(self, _symbols: list[str], start_date: date, end_date: date) -> ProviderResult:
            captured.append((start_date, end_date))
            return ProviderResult("fixture", "prices", "unavailable", "fixture unavailable")

    import etf_cockpit.application.data_service as data_service

    provider = UnavailableProvider()
    monkeypatch.setattr(data_service, "date", FrozenDate)
    monkeypatch.setattr(data_service, "YFinanceProvider", SimpleNamespace(from_config=lambda _config: provider))
    DataService(load_config()).refresh_yfinance_data(include_reference_data=False)

    assert captured == [(date(2023, 2, 28), date(2028, 2, 29))]


def test_p02_n005() -> None:
    for invalid in (float("nan"), float("inf"), float("-inf")):
        source = EvidenceSource("prices", "source:fixture", SourceAuthority.VENDOR, "2026-10-01", "fresh")
        entry = ledger_entry_for_component("ETF-A", "score", invalid, source)
        assert entry.score_eligible is False


def test_p02_n006() -> None:
    for freshness in ("fresh", "ok", "current", "warning"):
        for quality in ("high", "medium", "good", "ok"):
            source = EvidenceSource(
                "prices", "source:fixture", SourceAuthority.VENDOR, "2026-10-01", freshness, quality=quality
            )
            assert ledger_entry_for_component("ETF-A", "score", 7.0, source).score_eligible
    for invalid in ("future", "garbled"):
        source = EvidenceSource("prices", "source:fixture", SourceAuthority.VENDOR, "2026-10-01", invalid)
        assert ledger_entry_for_component("ETF-A", "score", 7.0, source).score_eligible is False


def test_p03_n005() -> None:
    for invalid_price in (-15.0, 0.0):
        result = executable_order(1.0, [{"price": invalid_price, "quantity": 1.0}])
        assert result["status"] == "unavailable"
        assert result["reason_code"] == "INVALID_ORDER_BOOK"


def test_chat_p03_n007() -> None:
    for invalid in (float("nan"), float("inf"), -1.0):
        assert size_band(invalid, (2.0, 10.0, 50.0)) is None


def test_p04_n004() -> None:
    for return_count in (0, 1, 19):
        prices = pd.Series(np.exp(np.arange(return_count + 1, dtype=float) * 0.01))
        assert baseline_forecast("ETF-A", prices, [1], date(2026, 10, 1), "run:fixture") == []

    prices = pd.Series(np.exp(np.arange(21, dtype=float) * 0.01))
    forecasts = baseline_forecast("ETF-A", prices, [1], date(2026, 10, 1), "run:fixture")

    assert len(forecasts) == 1
    assert all(math.isfinite(float(value)) for value in (
        forecasts[0].expected_return,
        forecasts[0].expected_excess_return,
        forecasts[0].q10_return,
        forecasts[0].q50_return,
        forecasts[0].q90_return,
        forecasts[0].forecast_vol,
    ))


def test_p04_n005(monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.application.forecast_service as forecast_service

    monkeypatch.setattr(forecast_service, "current_settings_identity", lambda: {"settings_revision": "a" * 64})
    monkeypatch.setattr(forecast_service, "settings_bound_run_id", lambda run_id, *, settings_identity: run_id)
    monkeypatch.setattr(forecast_service, "ensure_run_manifest", lambda *_args, **_kwargs: None)
    context = SimpleNamespace(resolution=None, benchmark_data_id="BENCH", identity={})
    service = ForecastService(load_config(), reference_context=context)
    monkeypatch.setattr(service, "_run_timesfm_forecasts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_run_toto_forecasts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_write_forecasts", lambda *_args, **_kwargs: None)
    dates = pd.bdate_range("2026-08-01", periods=30)
    prices = pd.DataFrame({"date": dates, "etf_id": "BENCH", "adjusted_close": np.exp(np.arange(30) * 0.01)})

    forecasts = service.run_forecasts(dates[-1].date(), ["BENCH"], prices, horizons=[1], live_optional_models=False)

    assert len(forecasts) == 1
    assert forecasts[0].expected_excess_return == pytest.approx(0.0, abs=1e-12)


def test_p04_n006() -> None:
    frame = pd.DataFrame(
        {
            "forecast_date": ["2026-09-01", "2026-09-03", "2026-09-03"],
            "run_id": ["run-z", "run-a", "run-b"],
            "horizon_days": [30, 30, 30],
            "expected_return": [0.1, 0.2, 0.3],
        }
    )

    for candidate in (frame, frame.iloc[::-1]):
        assert _latest_row(candidate)["run_id"] == "run-b"
        assert _choose_horizon_row_for(candidate, 30)["run_id"] == "run-b"


def test_p04_n007() -> None:
    features = pd.DataFrame(
        [
            {"etf_id": "A", "momentum_20d": .1, "momentum_60d": .1, "momentum_120d": .1, "momentum_180d": .1,
             "trend_slope": .1, "trend_100": 1.0, "trend_200": 1.0, "vol_60d_ann": .1, "ewma_vol_ann": .1,
             "drawdown_60d_max": -.01, "relative_strength_60d": .1},
            {"etf_id": "B", "momentum_20d": -.1, "momentum_60d": -.1, "momentum_120d": -.1, "momentum_180d": -.1,
             "trend_slope": -.1, "trend_100": 0.0, "trend_200": 0.0, "vol_60d_ann": .3, "ewma_vol_ann": .3,
             "drawdown_60d_max": -.2, "relative_strength_60d": -.1},
        ]
    )
    allocation = pd.DataFrame(
        [{"etf_id": item, "current_weight": 0.0, "target_weight": 0.0, "hard_band": .05, "soft_band": .03, "max_weight": .25}
         for item in ("A", "B")]
    )

    scored = component_scores(features, allocation, load_config(), forecast_scores={"baseline": {"A": 0.0, "B": float("nan")}})
    by_id = scored.set_index("etf_id")

    assert by_id.loc["A", "score_baseline_ml"] == 0.0
    assert by_id.loc["B", "score_baseline_ml"] == pytest.approx(
        0.55 * by_id.loc["B", "score_momentum"] + 0.45 * by_id.loc["B", "score_trend"]
    )


def test_p04_n008(tmp_path: Path) -> None:
    config_path = Path(__file__).parents[1] / "configs" / "score_engine_v3.yaml"
    payload = deepcopy(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    payload["asset_policies"]["ETF"]["attractiveness"]["momentum"] = float("inf")
    invalid_path = tmp_path / "score_engine_v3.yaml"
    invalid_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(CanonicalScoreError):
        load_score_policy("ETF", path=invalid_path)


def test_p04_n009() -> None:
    policy = load_score_policy("ETF")
    single = build_canonical_score(
        instrument_id="ETF-A", asset_type="ETF", decision_time="2026-10-01",
        components=[_canonical_component("momentum", .4)], policy=policy,
    )
    duplicate = build_canonical_score(
        instrument_id="ETF-A", asset_type="ETF", decision_time="2026-10-01",
        components=[_canonical_component("momentum", .4), _canonical_component("momentum", -.4)], policy=policy,
    )

    assert duplicate.coverage == pytest.approx(single.coverage)
    assert "duplicate_component:momentum" in duplicate.warnings


def test_p04_n011() -> None:
    prices = pd.DataFrame(
        {"date": pd.bdate_range("2026-01-01", periods=20), "etf_id": "ETF-A",
         "adjusted_close": np.arange(100.0, 120.0), "volume": 1000.0}
    )
    features = compute_features(prices)
    latest = features.iloc[-1]
    blocked, _warnings = evaluate_risk_gates(
        load_config(), latest, DataQualityReport(as_of_date=date(2026, 1, 30), issues=[]),
        candidate_action="buy", projected_weight=None, cash_weight=1.0,
    )

    assert pd.isna(latest["trend_100"]) and pd.isna(latest["trend_200"])
    assert "trend_evidence_unavailable" in blocked
    assert "below_sma_200" not in blocked


def test_p04_n015() -> None:
    prices = pd.DataFrame(
        {"etf_id": ["ETF-A", "ETF-A"], "date": ["2026-10-01", "2026-10-01"], "adjusted_close": [100.0, 101.0]}
    )

    assert _observed_price_ids(prices, None, minimum_history_observations=2) == set()


def test_p04_n016() -> None:
    evidence = pd.DataFrame(
        {"instrument_id": ["A", "B"], "status": ["available", "available"], "composite_score": [2.0, 8.0]}
    )

    weights = quality_momentum_weights(evidence, ["A"])

    assert weights.loc["A"] == 1.0
    assert weights.sum() == 1.0


def test_p05_n001() -> None:
    calendar = _event_calendar()
    events = [
        OrderRequest(datetime(2026, 7, 17, 9, 59), "order-a", "ETF-A", "buy", 80.0),
        OrderRequest(datetime(2026, 7, 17, 9, 59), "order-b", "ETF-A", "buy", 80.0),
        MarketEvent(datetime(2026, 7, 17, 10, 1), "ETF-A", 100.0, 102.0, 98.0, 101.0, available_quantity=100.0),
    ]

    result = EventDrivenBacktest(calendars={"ETF-A": calendar}).replay(events)

    assert [(fill.order_id, fill.quantity) for fill in result.fills] == [("order-a", 80.0), ("order-b", 20.0)]


def test_p05_n002() -> None:
    prices = pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02", "2026-01-03"], "etf_id": ["ETF-A"] * 3,
         "adjusted_close": [100.0, 0.0, 120.0]}
    )

    with pytest.raises(BacktestDataUnavailableError, match=r"invalid_price_data: ETF-A 2026-01-02"):
        _price_pivot(prices)


def test_p05_n004(tmp_path: Path) -> None:
    controls = PreTradeControls(tmp_path)
    decision = controls.evaluate_order(
        {"proposal_id": "proposal:fixture", "instrument_id": "VWCE"},
        execution_price=10.0,
        quantity_delta=-3.0,
        fx_rate=1.0,
        positions={"VWCE": {"quantity": 1.0, "average_cost": 10.0}},
        open_orders={},
        paper_events=[],
        path="paper",
        occurred_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )

    assert decision.allowed is False
    assert decision.control == "sell_quantity_within_holding"


def test_p05_n005() -> None:
    for invalid in (-20.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="transaction_cost_bps"):
            run_backtest(None, pd.DataFrame(), transaction_cost_bps=invalid)


def test_p05_n006() -> None:
    for invalid in (0, -5, -100):
        with pytest.raises(ValueError, match="rebalance_frequency_days"):
            run_backtest(None, pd.DataFrame(), rebalance_frequency_days=invalid)
    for invalid in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="initial_value_eur"):
            run_backtest(None, pd.DataFrame(), initial_value_eur=invalid)


def test_p05_n007() -> None:
    with pytest.raises(EventReplayError, match="strictly positive"):
        MarketEvent(datetime(2026, 7, 17, 10, 0), "ETF-A", 0.0, 102.0, 98.0, 101.0)


def test_chat_p05_n003() -> None:
    timestamp = datetime(2026, 7, 17, 10, 0)
    events = [
        SignalEvent(timestamp, "signal:fixture", "ETF-A", "buy", sequence=10),
        SignalEvent(timestamp, "signal:fixture", "ETF-A", "buy", sequence=2),
    ]

    assert [event.sequence for event in sorted(events, key=_event_key)] == [2, 10]


def test_chat_p05_n004() -> None:
    allocation = pd.DataFrame({"instrument_id": ["ETF-A"], "weight": [1.0], "asset_class": ["equity"]})
    returns = pd.DataFrame(
        {"instrument_id": ["ETF-A", "ETF-A"], "date": ["2026-01-02", "2026-01-02"], "adjusted_return": [-0.1, 0.1]}
    )
    scenario = StressScenario("history", "Historical", {"equity": -0.5}, historical_date="2026-01-02")

    first = run_stress_scenario(scenario, allocation, historical_returns=returns)
    second = run_stress_scenario(scenario, allocation, historical_returns=returns.iloc[::-1])

    assert first.status == "unavailable"
    assert first.total_pnl is None
    assert "conflicting_history:ETF-A" in first.limitations
    assert first.to_payload() == second.to_payload()


def test_chat_p05_n005() -> None:
    prices = pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02"], "etf_id": ["ETF-A", "ETF-A"], "adjusted_close": [100.0, 101.0]}
    )
    allocation = pd.DataFrame({"etf_id": ["ETF-A"], "current_weight": [1.0]})
    cashflows = pd.DataFrame({"date": ["2026-01-02"], "amount": [-100.0]})

    report = build_performance_attribution(prices, allocation, cashflows=cashflows)

    assert report["money_weighted_return"] is None
    assert report["money_weighted_status"] == "unavailable_no_xirr_root"


def test_chat_p05_n006() -> None:
    prices = pd.DataFrame(
        {"date": ["2026-01-01"], "etf_id": ["ETF-A"], "adjusted_close": [10.0], "volume": [float("inf")]}
    )
    returns = pd.DataFrame({"ETF-A": [0.01]})

    assert _liquidity_adjusted_risk(prices, None, returns, np.array([1.0]))["status"] == "unavailable"


def test_p06_n011() -> None:
    for invalid in (float("nan"), float("inf"), float("-inf")):
        bar = ScoreBar(invalid)
        assert bar.data["label"] == "—"
        assert bar.data["value"] is None
