from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.pages.operations import operations_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.core.config import load_config
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio.ledger import Ledger
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError
from etf_cockpit.portfolio.rebalancing import RebalanceConstraints, build_rebalance_report
from etf_cockpit.portfolio.reconciliation import source_entry_id
from etf_cockpit.trading.incidents import IncidentJournal, IncidentJournalError, IncidentJournalIntegrityError
from tests.test_paper_trading import _proposal
from tests.test_portfolio_reconciliation import _application_with_trade, _cutoff, _map_account


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S1-01: Rejecting a deferred proposal makes the ledger unreadable")
def test_s1_01_reject_after_defer(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1000)
    proposal = _proposal()
    ledger.defer_proposal(proposal, reason="Wait")
    rejected_without_error = True
    try:
        ledger.reject_proposal(proposal, reason="Decline")
    except PaperLedgerError:
        rejected_without_error = False
    assert not rejected_without_error, "a deferred proposal was rejected"
    assert ledger.snapshot().status == "ready"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S1-05: Matured returns compare incompatible execution and adjusted prices")
def test_s1_05_split_neutral_outcome(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1000)
    order = ledger.accept_proposal(_proposal(), execution_price=10)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10)
    ledger.apply_corporate_action("VWCE", split_ratio=2, cash_dividend_per_unit=0, source_authority="fixture", source_checksum="a" * 64)
    result = ledger.mature_outcome(
        str(order["order_id"]), adjusted_close=5, benchmark_return=0, cash_return=0, source_authority="fixture", source_checksum="b" * 64
    )
    assert result["gross_return"] == pytest.approx(0)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S1-06: Unmarked holdings are valued as zero in account totals")
def test_s1_06_unmarked_position_valuation_unknown(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1000)
    order = ledger.accept_proposal(_proposal(), execution_price=10)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10)
    snapshot = ledger.snapshot()
    assert snapshot.positions[0].mark_price is None
    assert snapshot.equity is None
    assert snapshot.pnl is None
    assert snapshot.drawdown is None


@pytest.mark.xfail(strict=True, raises=IncidentJournalIntegrityError, reason="S1-02: Interrupted incident append permanently invalidates its integrity anchor")
def test_s1_02_failed_anchor_update_leaves_readable_journal(tmp_path: Path) -> None:
    journal = IncidentJournal(tmp_path)
    journal.record("baseline", message="Baseline", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    with patch("etf_cockpit.trading.incidents.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(IncidentJournalError):
            journal.record(
                "disconnect", message="Disconnected", requires_freeze=True, occurred_at=datetime(2026, 1, 2, tzinfo=timezone.utc)
            )
    assert len(journal.events()) in (1, 2)


_AS_OF = "2025-01-01T00:00:00Z"


def _posted_application(tmp_path: Path):
    app, event_id = _application_with_trade(tmp_path)
    _map_account(app)
    app.apply_adjustment(event_id, authority="broker", as_of=_AS_OF, known_at=_cutoff(), reviewer="operator", reason="Post")
    return app, event_id


def test_s1_03_future_reversal_does_not_change_historical_match(tmp_path: Path) -> None:
    app, event_id = _posted_application(tmp_path)
    query = dict(authority="broker", as_of=_AS_OF, known_at=_cutoff())
    assert app.reconcile(**query).matched_source_rows == 1
    with TransactionalStore(tmp_path) as store:
        with store.transaction():
            with patch("etf_cockpit.portfolio.ledger._utc_now", return_value="2100-01-01T00:00:00Z"):
                Ledger(store.connection).reverse(
                    source_entry_id(event_id), entry_id="future-reversal", effective_at="2025-01-02T00:00:00Z", authority="broker"
                )
    assert app.reconcile(**query).matched_source_rows == 1


def test_s1_04_future_mapping_does_not_replace_historical_mapping(tmp_path: Path) -> None:
    app, _event_id = _posted_application(tmp_path)
    query = dict(authority="broker", as_of=_AS_OF, known_at=_cutoff())
    before = app.reconcile(**query)
    with TransactionalStore(tmp_path) as store:
        with store.transaction():
            Ledger(store.connection).create_account(
                "CASH-A2", name="New cash", account_type="asset", account_role="cash", authority="broker"
            )
    with patch("etf_cockpit.data.local_storage._utc_now", return_value="2100-01-01T00:00:00Z"):
        app.map_source_account(
            authority="broker", source_account_id="A1", cash_account_id="CASH-A2", position_account_id="POSITION-A1",
            clearing_account_id="CLEARING-A1", reviewer="operator", reason="Remap to a new cash account",
        )
    after = app.reconcile(**query)
    assert after.account_mappings == before.account_mappings
    assert after.matched_source_rows == 1


def test_s1_08_final_trades_respect_minimum() -> None:
    holdings = pd.DataFrame([dict(etf_id="VWCE", current_weight=0.9, market_value_eur=900, quantity=900, price_eur=1)])
    constraints = RebalanceConstraints(cash_buffer_weight=0.095, min_trade_eur=50)
    report = build_rebalance_report(load_config(), holdings, {"VWCE": 1}, portfolio_value_eur=1000, constraints=constraints)
    assert [t.trade_value_eur for t in report.trades if t.trade_value_eur != 0 and abs(t.trade_value_eur) < 50] == []


def test_s1_03_posting_recorded_after_known_at_does_not_satisfy_match(tmp_path: Path) -> None:
    app, event_id = _application_with_trade(tmp_path)
    _map_account(app)
    before_posting = _cutoff()
    app.apply_adjustment(event_id, authority="broker", as_of=_AS_OF, known_at=_cutoff(), reviewer="operator", reason="Post")
    historical = app.reconcile(authority="broker", as_of=_AS_OF, known_at=before_posting)
    assert historical.matched_source_rows == 0
    assert "source_without_ledger_entry" in {item.kind for item in historical.discrepancies}
    assert app.reconcile(authority="broker", as_of=_AS_OF, known_at=_cutoff()).matched_source_rows == 1


def test_s1_04_mapping_recorded_after_known_at_is_not_selected(tmp_path: Path) -> None:
    app, event_id = _application_with_trade(tmp_path)
    before_mapping = _cutoff()
    _map_account(app)
    report = app.reconcile(authority="broker", as_of=_AS_OF, known_at=before_mapping)
    assert report.account_mappings == ()
    with pytest.raises(ValueError, match="mapping"):
        app.apply_adjustment(event_id, authority="broker", as_of=_AS_OF, known_at=before_mapping, reviewer="operator", reason="Post")


def test_s1_08_lot_rounding_below_minimum_is_deferred() -> None:
    holdings = pd.DataFrame([dict(etf_id="VWCE", current_weight=0.9, market_value_eur=900, quantity=900, price_eur=1)])
    constraints = RebalanceConstraints(min_trade_eur=50, lot_size=40)
    report = build_rebalance_report(load_config(), holdings, {"VWCE": 0.96}, target_cash_weight=0.04, portfolio_value_eur=1000, constraints=constraints)
    assert [t.trade_value_eur for t in report.trades if t.trade_value_eur != 0 and abs(t.trade_value_eur) < 50] == []
    assert [t.status for t in report.trades] == ["deferred_below_minimum"]


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S1-07: Equal partial fills from separate UI actions are discarded")
def test_s1_07_equal_partial_fill_actions_not_silently_dropped(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=1000)
    order = ledger.accept_proposal(_proposal(), execution_price=10)
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    state.application_api = type(state.application_api)(lambda: state.snapshot, root=tmp_path)
    rendered = operations_page(None, state)
    controls = {getattr(item, "key", None): item for item in _walk(rendered)}
    controls["operations.paper-order-id"].value = str(order["order_id"])
    controls["operations.paper-fill-quantity"].value = "5"
    controls["operations.paper-fill-price"].value = "10"

    def message() -> str:
        return " | ".join(str(item.value) for item in _walk(rendered) if isinstance(item, ft.Text) and "Paper fill" in str(item.value))

    controls["operations.paper-fill"].on_click(None)
    first = message()
    controls["operations.paper-fill"].on_click(None)
    second = message()
    fills = [event for event in ledger._read_events() if event["event_type"] == "fill_recorded"]
    assert "Paper fill recorded" in first
    # Either the second action is recorded, or the user is told it was not; silently reporting success is the defect.
    assert len(fills) == 2 or second != first
