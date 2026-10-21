"""Bughunt C (#973): backtest engine mechanics, one native test per HIGH finding."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.backtest import engine as engine_module
from etf_cockpit.backtest.engine import (
    _next_signal_weights,
    _signal_weight_action,
    run_backtest,
)
from etf_cockpit.backtest.event_engine import (
    CancelEvent,
    CertifiedSessionCalendar,
    EventDrivenBacktest,
    EventReplayError,
    ExpiryEvent,
    MarketEvent,
    OrderRequest,
    TargetEvent,
)
from etf_cockpit.backtest.metrics import performance_metrics
from etf_cockpit.core.config import load_config
from etf_cockpit.data.market_calendar import ListingCalendarEvidence

UTC = timezone.utc


def _calendar() -> CertifiedSessionCalendar:
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
            known_at=datetime(2020, 1, 2, tzinfo=UTC),
        )
    )


def _engine() -> EventDrivenBacktest:
    return EventDrivenBacktest(calendars={"ETF-A": _calendar()})


def _at(minute: int) -> datetime:
    return datetime(2026, 7, 17, 10, minute)


def _market(minute: int, *, open_price: float = 100.0, quantity: float | None = None) -> MarketEvent:
    return MarketEvent(
        _at(minute),
        "ETF-A",
        open_price=open_price,
        high_price=max(102.0, open_price),
        low_price=min(98.0, open_price),
        close_price=min(max(101.0, 98.0), max(102.0, open_price)),
        available_quantity=quantity,
    )


def _order(order_id: str, minute: int, quantity: float = 5.0, **kwargs: object) -> OrderRequest:
    return OrderRequest(_at(minute), order_id, "ETF-A", "buy", quantity, **kwargs)


# --- event engine -------------------------------------------------------------------------------


def test_c016_n001_order_priority_is_submit_time_not_lexical_id() -> None:
    result = _engine().replay(
        [_order("z-first", 0), _order("a-second", 1), _market(2, quantity=5.0)]
    )

    assert [fill.order_id for fill in result.fills] == ["z-first"]
    states = {state.order_id: state for state in result.orders}
    assert states["z-first"].status == "filled"
    assert states["a-second"].filled_quantity == 0.0


def test_c016_n001_same_timestamp_orders_use_sequence_not_lexical_id() -> None:
    result = _engine().replay(
        [_order("a", 0, sequence=1), _order("z", 0, sequence=0), _market(1, quantity=5.0)]
    )

    assert [fill.order_id for fill in result.fills] == ["z"]


def test_c016_n002_conflicting_same_key_market_events_are_rejected_in_any_order() -> None:
    first, second = _market(1, open_price=100.0), _market(1, open_price=90.0)
    for events in ([first, second], [second, first]):
        with pytest.raises(EventReplayError, match="conflicting market events"):
            _engine().replay([_order("o", 0), *events])


def test_c016_n003_cancel_at_the_same_timestamp_precedes_the_fill() -> None:
    result = _engine().replay([_order("o", 0), CancelEvent(_at(1), "o"), _market(1)])

    assert result.fills == ()
    assert result.orders[0].status == "cancelled"


def test_c016_n004_order_expires_at_its_expiry_time_not_the_next_matching_bar() -> None:
    result = _engine().replay(
        [
            _order("o", 0, order_type="limit", limit_price=50.0, expires_at=_at(3)),
            _market(1),
            _market(6),
        ]
    )

    expiries = [event for event in result.events if isinstance(event, ExpiryEvent)]
    assert [event.timestamp for event in expiries] == [_at(3)]
    assert result.orders[0].status == "expired"


def test_c116_n001_duplicate_identical_bar_does_not_double_liquidity() -> None:
    bar = _market(1, quantity=5.0)
    result = _engine().replay([_order("o", 0, quantity=10.0), bar, _market(1, quantity=5.0)])

    assert sum(fill.quantity for fill in result.fills) == 5.0
    assert result.orders[0].remaining_quantity == 5.0


@pytest.mark.parametrize(
    "build",
    [
        lambda: MarketEvent(_at(1), "ETF-A", "100", 102.0, 98.0, 101.0),
        lambda: MarketEvent(_at(1), "ETF-A", 100.0, 102.0, 98.0, 101.0, available_quantity="5"),
        lambda: OrderRequest(_at(0), "o", "ETF-A", "buy", "5"),
        lambda: OrderRequest(_at(0), "o", "ETF-A", "buy", 5.0, "limit", "99"),
        lambda: TargetEvent(_at(0), "t", "ETF-A", "3"),
        lambda: OrderRequest(_at(0), "o", "ETF-A", "buy", True),
    ],
)
def test_c116_n002_numeric_strings_are_rejected_at_ingest(build) -> None:
    with pytest.raises(EventReplayError):
        build()


# --- backtest engine ----------------------------------------------------------------------------


def test_c017_n003_implicit_cash_stays_in_the_weights_after_a_sell() -> None:
    current = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})
    target = current.copy()

    after = _next_signal_weights(current, target, {"B": "sell"})

    assert after["B"] == 0.0
    assert after["A"] == 0.5 and after["C"] == 0.2  # no silent pro-rata reallocation
    assert float(after.sum()) == pytest.approx(0.7)  # the remaining 30% is explicit cash
    scaled = _next_signal_weights(current, target, {"A": "add", "B": "add"})
    assert float(scaled.sum()) <= 1.0 + 1e-12  # leverage is never created


def test_c020_n001_sell_advisory_is_an_explicit_exit_not_a_two_percent_trim() -> None:
    # advisory_action publishes both trim and sell as ``trim_candidate``; the sell carries new weight 0.
    sell = SimpleNamespace(etf_id="B", action="trim_candidate", suggested_new_weight=0.0)
    trim = SimpleNamespace(etf_id="B", action="trim_candidate", suggested_new_weight=0.25)
    unknown = SimpleNamespace(etf_id="B", action="trim_candidate", suggested_new_weight=None)

    assert _signal_weight_action(sell) == "sell"
    assert _signal_weight_action(trim) == "trim"
    assert _signal_weight_action(unknown) == "trim"
    assert _signal_weight_action(SimpleNamespace(action="sell")) == "sell"
    assert _signal_weight_action(SimpleNamespace(action="add_candidate")) == "add"
    assert _signal_weight_action(SimpleNamespace(action="hold")) == "hold"
    current = pd.Series({"A": 0.6, "B": 0.4})
    assert _next_signal_weights(current, current, {"B": _signal_weight_action(sell)})["B"] == 0.0
    assert _next_signal_weights(current, current, {"B": _signal_weight_action(trim)})["B"] == pytest.approx(0.38)


def _two_asset_prices(ids: list[str], doubling_at: int) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=260)
    rows = []
    for j, day in enumerate(dates):
        rows.append((day, ids[0], 100.0))
        rows.append((day, ids[1], 200.0 if j >= doubling_at else 100.0))
    return pd.DataFrame(rows, columns=["date", "etf_id", "adjusted_close"]).assign(volume=1_000_000.0)


def test_c017_n002_signals_see_drifted_holdings_not_the_stale_target(monkeypatch) -> None:
    config = load_config()
    ids = config.universe.enabled_ids[:2]
    seen: list[pd.DataFrame] = []

    def fake_generate_signals(_config, _latest, holdings, *_args, **_kwargs):
        seen.append(holdings.copy())
        return []

    monkeypatch.setattr(engine_module, "generate_signals", fake_generate_signals)
    run_backtest(config, _two_asset_prices(ids, doubling_at=225), rebalance_frequency_days=10, transaction_cost_bps=0)

    target = np.array([0.5, 0.5])  # shipped targets are all zero: equal-weight fallback
    drifted = target * np.array([1.0, 2.0])
    drifted = drifted / drifted.sum()
    # The first rebalance (index 230) follows the doubling at 225: the held mix has drifted from the target.
    held = seen[0].set_index("etf_id")["current_weight"]
    assert float(held[ids[1]]) == pytest.approx(float(drifted[1]), rel=1e-6)
    assert float(held[ids[1]]) != pytest.approx(float(target[1]), rel=1e-3)


def test_c017_n001_zero_target_fallback_is_recorded_not_silent() -> None:
    config = load_config()
    ids = config.universe.enabled_ids[:2]
    prices = _two_asset_prices(ids, doubling_at=10_000)

    fallback = run_backtest(config, prices, transaction_cost_bps=0)
    assert fallback.metadata["target_weight_source"] == "equal_weight_fallback_no_targets"

    positions = {
        key: value.model_copy(update={"target_weight": 0.7 if key == ids[0] else 0.3 if key == ids[1] else 0.0})
        for key, value in config.targets.positions.items()
    }
    configured = config.model_copy(update={"targets": config.targets.model_copy(update={"positions": positions})})
    assert run_backtest(configured, prices, transaction_cost_bps=0).metadata["target_weight_source"] == "configured"


def test_c119_n001_weekly_and_daily_series_cagr_use_calendar_time() -> None:
    values = 100.0 * 1.005 ** np.arange(260)
    weekly = pd.Series(values, index=pd.date_range("2020-01-03", periods=260, freq="W-FRI"))
    daily = pd.Series(values, index=pd.bdate_range("2020-01-01", periods=260))

    days = (weekly.index[-1] - weekly.index[0]).days
    expected_weekly = float((values[-1] / values[0]) ** (365.25 / days) - 1)
    assert performance_metrics(weekly)["cagr"] == pytest.approx(expected_weekly)
    # 260 weekly rows are ~5 years, not the 1.03 years the session count would imply.
    assert performance_metrics(weekly)["cagr"] < 0.3
    # Daily session series keep the sessions / 252 convention.
    assert performance_metrics(daily)["cagr"] == pytest.approx(float((values[-1] / values[0]) ** (252 / 259) - 1))


def test_c119_n002_worst_12m_is_unavailable_below_252_sessions_not_zero() -> None:
    config = load_config()
    ids = config.universe.enabled_ids[:2]
    report = run_backtest(config, _two_asset_prices(ids, doubling_at=10_000), transaction_cost_bps=0)

    # 260 sessions leave 40 equity observations after the 220-session warm-up.
    assert len(report.equity_curves) == 40
    assert report.results["worst_12m_return"].isna().all()
    assert (report.results["worst_12m_return_status"] == "unavailable").all()
    assert report.results["worst_12m_return_reason"].str.contains("253").all()
