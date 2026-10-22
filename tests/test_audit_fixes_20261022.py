"""Regressions for authoritative AUDFIX audit findings 1–6."""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.backtest import engine
from etf_cockpit.core.config import load_config
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio import paper_bots as bots
from etf_cockpit.portfolio import paper_bots_execution as execution
from etf_cockpit.portfolio import paper_bots_replay as replay
from etf_cockpit.portfolio import paper_bots_report as report
from etf_cockpit.portfolio.paper_trading import PaperLedger
from tests.test_paper_bots import _rows
from tests.test_paper_bots_execution import (
    RUN_AT, SESSIONS, _allow, _book, _decisions, _exec_config, _execute,
    _history_with_columns, _ready, _records, _write_fx,
)


def _backtest_panel(count=1, *, currency="EUR"):
    config = load_config()
    members = [item for item in config.universe.etfs if item.id in config.universe.enabled_ids][:count]
    members = [item.model_copy(update={"currency": currency}) for item in members]
    config = config.model_copy(update={"universe": config.universe.model_copy(update={"etfs": members})})
    days = pd.bdate_range("2024-01-01", periods=260)
    prices = pd.DataFrame([
        {"date": day, "etf_id": item.id, "adjusted_close": 100.0, "close": 100.0, "currency": currency, "volume": 1_000_000.0}
        for day in days for item in members
    ])
    return config, days, prices


@pytest.mark.parametrize("missing,adjusted_factor", [(False, 1.0), (False, 2.0), (True, 1.0)])
def test_finding_1_nav_uses_adjusted_eur_returns_without_zero_filling(missing, adjusted_factor):
    config, days, prices = _backtest_panel(currency="USD")
    prices.loc[prices["date"] >= days[221], "adjusted_close"] *= adjusted_factor
    fx = pd.DataFrame([
        {"as_of_date": day.date(), "base_currency": "EUR", "quote_currency": "USD",
         "rate": 1.25 if index <= 220 else 1.0, "source": "ECB",
         "ingested_at": f"{day.date()}T08:00:00Z"}
        for index, day in enumerate(days) if not missing or index <= 220
    ])
    result = engine.run_backtest(config, prices, fx_rates=fx, rebalance_frequency_days=10000, transaction_cost_bps=0)
    nav = result.equity_curves["buy_and_hold"]
    if missing:
        assert pd.isna(nav.iloc[-1])
    else:
        # Flat raw USD price, EUR per USD 0.8 -> 1.0: +25%, with
        # any corporate-action adjustment compounded on that same EUR basis.
        assert nav.iloc[-1] / nav.iloc[0] == pytest.approx(1.25 * adjusted_factor)
    assert result.metadata["missing_prices_zero_filled"] is False
    assert result.metadata["cost_model_execution_allowed"] is False


def test_finding_2_daily_marks_use_daily_fx_and_missing_fx_stays_unavailable(monkeypatch, tmp_path):
    assert _decisions(monkeypatch, tmp_path, eur=False).status == "available"
    _allow(tmp_path)
    _write_fx(tmp_path)
    opens = {instrument: {day: level for day in SESSIONS} for instrument, level in {"AAA": 100.0, "BBB": 22.0}.items()}
    book = _book(opens=opens, currencies={"AAA": "USD"})
    _execute(tmp_path, book)
    record = next(item for item in _records(tmp_path) if item["bot_family"] == "B1" and item["instrument_id"] == "AAA" and item["status"] == "filled")
    track = execution.forward_track(tmp_path)
    ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(record["bot_id"]))
    path = tmp_path / "data" / "clean" / "fx.parquet"
    fx = pd.read_parquet(path)
    fx = pd.concat([fx, pd.DataFrame([{"as_of_date": "2026-10-16", "base_currency": "EUR", "quote_currency": "USD",
                                    "rate": 1.0, "source": "ECB", "ingested_at": "2026-10-16T08:00:00Z"}])], ignore_index=True)
    fx.to_parquet(path)
    days = [date(2026, 10, 15), date(2026, 10, 16)]
    snapshots = report._ledger_snapshots(ledger, book, _exec_config(), RUN_AT, days, None, root=tmp_path)
    values = snapshots.set_index(pd.to_datetime(snapshots["date"]).dt.date)["total_value"]
    assert values[days[1]] - values[days[0]] == pytest.approx(float(record["quantity"]) * 100.2 * 0.2)
    # A revision ingested later cannot retrospectively change the 16 October mark.
    fx.loc[fx["as_of_date"] == "2026-10-16", "ingested_at"] = "2026-10-20T08:00:00Z"
    fx.to_parquet(path)
    causal = report._ledger_snapshots(ledger, book, _exec_config(), RUN_AT, days, None, root=tmp_path)
    values = causal.set_index(pd.to_datetime(causal["date"]).dt.date)["total_value"]
    assert values[days[1]] == pytest.approx(values[days[0]])
    # No FX evidence at all is unavailable, never the last fill's exchange rate.
    fx.iloc[:0].to_parquet(path)
    missing = report._ledger_snapshots(ledger, book, _exec_config(), RUN_AT, days, None, root=tmp_path)
    assert missing["total_value"].isna().all()
    assert set(missing["valuation_status"]) == {"unavailable"}


@pytest.mark.parametrize("action,blocked_by", [("hold", []), ("add_candidate", ["risk_gate"])])
def test_finding_3_gated_size_is_consumed_and_hold_never_rebalances_drift(monkeypatch, action, blocked_by):
    current = pd.Series({"A": 0.1, "B": 0.6})
    sized = engine._next_signal_weights(current, pd.Series({"A": 0.1025}), {"A": "add"})
    assert sized["A"] == 0.1025  # canonical 10.25%, not the old 12%
    assert sized["B"] == 0.6
    for invalid in (None, float("nan"), float("inf"), -0.1, 1.1):
        assert engine._next_signal_weights(current, pd.Series({"A": invalid}), {"A": "add"}).equals(current)
        trim_action = engine._signal_weight_action(SimpleNamespace(action="trim_candidate", suggested_new_weight=invalid))
        assert engine._next_signal_weights(current, pd.Series({"A": invalid}), {"A": trim_action}).equals(current)
    limited = engine._next_signal_weights(current, pd.Series({"A": 0.8}), {"A": "add"})
    assert limited["B"] == 0.6 and limited.sum() == pytest.approx(1.0)
    config, days, prices = _backtest_panel(2)
    instrument = config.universe.enabled_ids[0]
    prices.loc[(prices["etf_id"] == instrument) & (prices["date"] >= days[221]), "adjusted_close"] = 200.0
    prices.loc[(prices["etf_id"] == instrument) & (prices["date"] >= days[226]), "adjusted_close"] = 300.0

    def holds(*args, **kwargs):
        return [SimpleNamespace(etf_id=key, action=action, total_score=5.0, canonical_score=None,
                                blocked_by=blocked_by, suggested_new_weight=0.9) for key in config.universe.enabled_ids]

    monkeypatch.setattr(engine, "generate_signals", holds)
    result = engine.run_backtest(config, prices, rebalance_frequency_days=5, transaction_cost_bps=0)
    assert result.signal_log["action"].eq(action).all() and not result.signal_log.empty
    assert result.trade_log.loc[result.trade_log["strategy"] == "signal_strategy"].empty
    pd.testing.assert_series_equal(result.equity_curves["signal_strategy"], result.equity_curves["buy_and_hold"], check_names=False)


def test_finding_4_replay_uses_later_success_for_all_four_families_and_preserves_cadence(tmp_path):
    first = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    usable = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    november = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    future = datetime(2027, 1, 4, 12, tzinfo=timezone.utc)
    history = pd.DataFrame(_history_with_columns(
        _rows(first) + _rows(usable, run_id="later", snapshot="b")
        + _rows(november, run_id="november", snapshot="c") + _rows(future, run_id="future", snapshot="d")
    ))
    config = bots._load_config(bots.PAPER_BOTS_CONFIG_PATH)[1]
    track = execution.replay_track(tmp_path, _exec_config())
    cutoff = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    book = _book(sessions=[day for day in SESSIONS if day > first.date()], known_at=cutoff)
    with TransactionalStore(track.store_root) as store:
        replay._write_replay_decisions(store, track, config, "audit-test", book, history, cutoff, [])
        decisions = [dict(item.payload) for item in store.list(track.decision_type)]
        october = [item for item in decisions if item["decision_month"] == "2026-10"]
        assert {item["bot_family"] for item in october} == {"B0", "B1", "B2", "B3"}
        assert all(item["snapshot_hash"] == "b" * 64 for item in october)
        assert all(item["execution_allowed"] is False for item in decisions)
        for item in october:
            spec = next(spec for spec in config["bots"] if spec["family_id"] == item["bot_family"])
            expected = bots._cadence_due(spec, "2026-11", "2026-10")
            assert any(row["bot_id"] == item["bot_id"] and row["decision_month"] == "2026-11" for row in decisions) == expected
        assert all(item["decision_month"] < "2027-01" for item in decisions)
        before = len(decisions)
        replay._write_replay_decisions(store, track, config, "audit-test", book, history, cutoff, [])
        assert len(store.list(track.decision_type)) == before


def test_finding_5_turnover_uses_immutable_fill_fx_and_missing_evidence_is_unavailable():
    fill = {"fill_id": "audit-fill", "quantity": "10", "price": "100", "fx_rate": "0.1", "fee": "1", "side": "buy", "currency": "USD"}
    state = {"fills": [fill], "cost_policy": {"adverse_bps": "10"}}
    ledger = SimpleNamespace(_read_events=lambda: [], _replay=lambda events: state)
    shadow = SimpleNamespace(_read_events=lambda: [], _replay=lambda events: {"shadow_flows": {}})
    strategy = pd.DataFrame({"date": pd.to_datetime(["2026-10-15", "2026-10-16"]), "external_flow": [1000.0, 0.0], "total_value": [1000.0, 1000.0]})
    relative = SimpleNamespace(strategy_twr=None, benchmark_twr=None, strategy_mwr=None, period_excess_return=None,
                               period_excess_return_label=None, compounded_relative_wealth=None,
                               compounded_relative_wealth_label=None, status="unavailable", reasons=[])
    # The stale projection is deliberately wrong: the report must read the durable fill.
    records = [{"fill_id": "audit-fill", "status": "filled", "quantity": "10", "fill_price": "100", "fee": "1", "spread_slippage_cost": "0", "traded_notional_eur": "1000"}]
    metrics = report._metrics(strategy, strategy.copy(), relative, records, shadow, {}, ledger=ledger)
    assert metrics["traded_notional_eur"] == 100.0 and metrics["turnover"] == 0.1
    records[0]["fill_id"] = "missing-evidence"
    missing = report._metrics(strategy, strategy.copy(), relative, records, shadow, {}, ledger=ledger)
    assert missing["traded_notional_eur"] is None and missing["turnover"] is None


def test_finding_6_lost_record_recovers_cost_without_reference_bar(monkeypatch, tmp_path):
    book = _ready(monkeypatch, tmp_path)
    real_store = execution._store_record
    lost = []

    def lose_first_fill(context, record):
        if record["status"] == "filled" and not lost:
            lost.append(dict(record))
            raise OSError("lost record write after durable ledger fill")
        real_store(context, record)

    monkeypatch.setattr(execution, "_store_record", lose_first_fill)
    _execute(tmp_path, book)
    assert len(lost) == 1
    original = lost[0]
    assert Decimal(original["spread_slippage_cost"]) > 0
    monkeypatch.setattr(execution, "_store_record", real_store)
    changed = book._frame.loc[~((book._frame["_instrument"] == original["instrument_id"])
                               & (book._frame["date"].dt.date == date.fromisoformat(original["session"])))]
    missing_book = execution.PriceBook(changed, known_at=RUN_AT)
    assert missing_book.bar(original["instrument_id"], date.fromisoformat(original["session"])) is None
    _execute(tmp_path, missing_book)
    recovered = next(item for item in _records(tmp_path) if item.get("fill_id") == original["fill_id"])
    for key in ("quantity", "reference_open", "fill_price", "fx_rate", "traded_notional_eur", "spread_slippage_cost"):
        assert Decimal(recovered[key]) == Decimal(original[key])
    track = execution.forward_track(tmp_path)
    ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(original["bot_id"]))
    assert sum(row["paper_trade_id"] == original["fill_id"] for row in ledger.trade_rows()) == 1
    state = ledger._replay(ledger._read_events())
    fill = next(item for item in state["fills"] if item["fill_id"] == original["fill_id"])
    unknown = execution._fill_evidence_fields(fill, None)
    assert unknown["reference_open"] is None and unknown["spread_slippage_cost"] is None


def test_an_exchange_session_missing_from_the_price_book_still_gets_a_daily_snapshot(monkeypatch, tmp_path):
    assert _decisions(monkeypatch, tmp_path, eur=True).status == "available"
    _allow(tmp_path)
    _write_fx(tmp_path)
    book = _book()
    _execute(tmp_path, book)
    record = next(item for item in _records(tmp_path) if item["bot_family"] == "B1" and item["status"] == "filled")
    ledger = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.account_id_for(record["bot_id"]))
    # 2026-10-16 (Friday) is an XETR session that the book calendar lacks: it is valued with the carried mark, not skipped.
    snapshots = report._ledger_snapshots(ledger, book, _exec_config(), RUN_AT, [date(2026, 10, 15), date(2026, 10, 19)], None, root=tmp_path)
    assert date(2026, 10, 16) in set(pd.to_datetime(snapshots["date"]).dt.date)
    row = snapshots[pd.to_datetime(snapshots["date"]).dt.date == date(2026, 10, 16)].iloc[0]
    assert row["valuation_status"] == "available"
