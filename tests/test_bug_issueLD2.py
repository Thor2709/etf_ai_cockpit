"""LD2: paper-ledger durability, cash reservation, NAV snapshot binding and appendix findings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError, PaperLedgerIntegrityError, _digest
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _proposal(
    *, quantity_delta: float = 10.0, source: str = "ld2", expires_at: str = "2099-01-02T00:00:00+00:00"
) -> dict[str, object]:
    input_material = {"instrument_id": "VWCE", "target_quantity": quantity_delta, "source": source}
    input_checksum = _digest(input_material)
    gate_policy = load_gate_policy()
    assert gate_policy.policy is not None
    payload: dict[str, object] = {
        "schema_version": "proposal.v1",
        "proposal_id": f"proposal_{input_checksum[:20]}",
        "instrument_id": "VWCE",
        "outcome": "proposal_ready",
        "proposal_allowed": True,
        "authority_stage": "paper",
        "execution_allowed": False,
        "quantity_delta": quantity_delta,
        "rationale": "All required paper evidence passed.",
        "gates": [{"gate_id": gate_id, "passed": True, "reason": "passed", "blocker": True} for gate_id in REQUIRED_GATES],
        "alternatives": [],
        "as_of": "2099-01-01T00:00:00+00:00",
        "expires_at": expires_at,
        "policy_version": "proposal-policy.v1",
        "authority_policy_checksum": current_authority_policy_checksum(),
        "gate_policy_version": gate_policy.policy.policy_version,
        "gate_policy_checksum": gate_policy.checksum,
        "input_checksum": input_checksum,
        "input_material": input_material,
    }
    payload["decision_checksum"] = _digest(payload)
    return payload


def _ledger(tmp_path: Path, cash: float = 1_000) -> PaperLedger:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=cash, occurred_at=START)
    return ledger


NOW = datetime.now(timezone.utc)


# --- required behaviour 1: cash reservation across open proposals -------------------------------------------------


def test_two_proposals_each_within_cash_but_together_above_second_is_rejected(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    first = ledger.accept_proposal(_proposal(quantity_delta=60, source="a"), execution_price=10)
    assert first["status"] == "accepted"
    with pytest.raises(PaperLedgerError, match="buying power"):
        ledger.accept_proposal(_proposal(quantity_delta=60, source="b"), execution_price=10)
    assert [order["order_id"] for order in ledger.orders()] == [first["order_id"]]
    assert ledger._order_lifecycle().available_buying_power(account_id="local-paper", currency="EUR") == Decimal("400")


def test_reservations_plus_fills_never_exceed_cash_and_cancel_releases(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    first = ledger.accept_proposal(_proposal(quantity_delta=60, source="a"), execution_price=10)
    ledger.record_fill(str(first["order_id"]), quantity=30, price=10, fee=0)
    lifecycle = ledger._order_lifecycle()
    # 300 spent + 300 still reserved for the open remainder.
    assert lifecycle.available_buying_power(account_id="local-paper", currency="EUR") == Decimal("400")
    with pytest.raises(PaperLedgerError, match="buying power"):
        ledger.accept_proposal(_proposal(quantity_delta=41, source="b"), execution_price=10)
    ledger.cancel_order(str(first["order_id"]), reason="operator cancelled")
    assert lifecycle.available_buying_power(account_id="local-paper", currency="EUR") == Decimal("700")
    assert ledger.accept_proposal(_proposal(quantity_delta=70, source="b"), execution_price=10)["status"] == "accepted"


def test_interrupted_acceptance_reservation_is_idempotent_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path)
    proposal = _proposal(quantity_delta=60, source="orphan")
    original_append = ledger._append

    def fail_acceptance(event_type, payload, *, occurred_at):
        if event_type == "order_accepted":
            raise OSError("simulated crash after reservation")
        return original_append(event_type, payload, occurred_at=occurred_at)

    monkeypatch.setattr(ledger, "_append", fail_acceptance)
    with pytest.raises(OSError):
        ledger.accept_proposal(proposal, execution_price=10)
    monkeypatch.setattr(ledger, "_append", original_append)
    assert ledger._order_lifecycle().available_buying_power(account_id="local-paper", currency="EUR") == Decimal("400")
    order = ledger.accept_proposal(proposal, execution_price=10)
    assert order["status"] == "accepted"
    # Retrying must not reserve the cash twice.
    assert ledger._order_lifecycle().available_buying_power(account_id="local-paper", currency="EUR") == Decimal("400")


def test_expired_orphan_reservation_is_released_but_live_one_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D.C4.S15.N001: a reservation whose acceptance never reached the ledger must not hold cash past expiry."""

    ledger = _ledger(tmp_path)
    soon = (NOW + timedelta(hours=1)).isoformat()
    expired_proposal = _proposal(quantity_delta=60, source="expiring", expires_at=soon)
    live_proposal = _proposal(quantity_delta=10, source="live")
    original_append = ledger._append

    def fail_acceptance(event_type, payload, *, occurred_at):
        if event_type == "order_accepted":
            raise OSError("simulated crash after reservation")
        return original_append(event_type, payload, occurred_at=occurred_at)

    monkeypatch.setattr(ledger, "_append", fail_acceptance)
    for proposal in (expired_proposal, live_proposal):
        with pytest.raises(OSError):
            ledger.accept_proposal(proposal, execution_price=10)
    monkeypatch.setattr(ledger, "_append", original_append)
    lifecycle = ledger._order_lifecycle()
    assert lifecycle.available_buying_power(account_id="local-paper", currency="EUR") == Decimal("300")

    released = ledger.release_expired_reservations(
        {str(p["proposal_id"]): p for p in (expired_proposal, live_proposal)}, reference=NOW + timedelta(hours=2)
    )
    assert len(released) == 1
    later = NOW + timedelta(hours=3)
    assert lifecycle.available_buying_power(account_id="local-paper", currency="EUR", as_of=later) == Decimal("900")
    # Calling again is a no-op; the live proposal can still be accepted by retry.
    assert ledger.release_expired_reservations({}, reference=NOW + timedelta(hours=2)) == ()
    assert ledger.accept_proposal(live_proposal, execution_price=10)["status"] == "accepted"


# --- required behaviour 2: fills record the valuation snapshot id --------------------------------------------------


def test_fill_carries_valuation_snapshot_id_and_replay_reproduces_it(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    order = ledger.accept_proposal(_proposal(quantity_delta=20, source="snap"), execution_price=10, occurred_at=START)
    at = START + timedelta(hours=1)
    ledger.record_fill(str(order["order_id"]), fill_id="f1", quantity=10, price=10, fee=0, occurred_at=at)
    ledger.record_fill(str(order["order_id"]), fill_id="f2", quantity=10, price=11, fee=0, occurred_at=at)
    fills = [event["payload"] for event in ledger._read_events() if event["event_type"] == "fill_recorded"]
    ids = [fill["valuation_snapshot_id"] for fill in fills]
    assert all(isinstance(value, str) and value.startswith("valsnap_") for value in ids)
    assert ids[0] != ids[1]  # different price evidence -> different snapshot
    rows = PaperLedger(tmp_path).trade_rows()
    assert [row["valuation_snapshot_id"] for row in rows] == ids
    assert PaperLedger(tmp_path).snapshot().to_payload() == ledger.snapshot().to_payload()
    # Idempotent retry of the same fill returns the order and does not add a fill.
    ledger.record_fill(str(order["order_id"]), fill_id="f1", quantity=10, price=10, fee=0, occurred_at=at)
    assert len([e for e in ledger._read_events() if e["event_type"] == "fill_recorded"]) == 2


def test_tampered_fill_snapshot_id_fails_replay_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    order = ledger.accept_proposal(_proposal(quantity_delta=20, source="tamper"), execution_price=10, occurred_at=START)
    ledger.record_fill(str(order["order_id"]), fill_id="f1", quantity=10, price=10, fee=0, occurred_at=START)
    events = ledger._read_events()
    fill = next(e for e in events if e["event_type"] == "fill_recorded")
    fill["payload"]["valuation_snapshot_id"] = "valsnap_" + "0" * 24
    with pytest.raises(PaperLedgerIntegrityError, match="snapshot"):
        ledger._replay(events)


# --- required behaviour 3: crash safety -----------------------------------------------------------------------------


def test_crash_between_lifecycle_fill_and_ledger_row_recovers_consistently_with_snapshot_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path)
    order = ledger.accept_proposal(_proposal(quantity_delta=20, source="crash"), execution_price=10, occurred_at=START)
    original_append = ledger._append

    def crash(event_type, payload, *, occurred_at):
        if event_type == "fill_recorded":
            raise OSError("simulated crash")
        return original_append(event_type, payload, occurred_at=occurred_at)

    monkeypatch.setattr(ledger, "_append", crash)
    at = START + timedelta(hours=2)
    with pytest.raises(OSError):
        ledger.record_fill(str(order["order_id"]), fill_id="c1", quantity=10, price=10, fee=0, occurred_at=at)
    monkeypatch.setattr(ledger, "_append", original_append)

    restarted = PaperLedger(tmp_path)
    recovered = restarted.record_fill(str(order["order_id"]), fill_id="c1", quantity=10, price=10, fee=0, occurred_at=at)
    assert recovered["status"] == "partially_filled"
    fills = [e["payload"] for e in restarted._read_events() if e["event_type"] == "fill_recorded"]
    assert len(fills) == 1 and fills[0]["valuation_snapshot_id"].startswith("valsnap_")
    assert len(restarted._order_lifecycle().fill_events()) == 1
    assert restarted.reconcile()["status"] == "ready"


def test_torn_final_ledger_row_still_fails_closed_and_lifecycle_fill_is_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A torn tail is not silently dropped (owner decision needed); the committed fill stays in the lifecycle journal."""

    ledger = _ledger(tmp_path)
    order = ledger.accept_proposal(_proposal(quantity_delta=20, source="torn"), execution_price=10, occurred_at=START)
    original_append = ledger._append

    def torn_write(event_type, payload, *, occurred_at):
        if event_type == "fill_recorded":
            with ledger.path.open("ab") as handle:
                handle.write(b'{"account_id":"local-paper","event_type":"fill_rec')
            raise OSError("simulated power loss mid-row")
        return original_append(event_type, payload, occurred_at=occurred_at)

    monkeypatch.setattr(ledger, "_append", torn_write)
    with pytest.raises(OSError):
        ledger.record_fill(str(order["order_id"]), fill_id="t1", quantity=10, price=10, fee=0, occurred_at=START)
    monkeypatch.setattr(ledger, "_append", original_append)
    with pytest.raises(PaperLedgerIntegrityError):
        PaperLedger(tmp_path).snapshot()
    assert len(ledger._order_lifecycle().fill_events()) == 1


def test_malformed_middle_row_is_still_an_integrity_failure(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.accept_proposal(_proposal(quantity_delta=20, source="mid"), execution_price=10)
    lines = ledger.path.read_bytes().splitlines()
    ledger.path.write_bytes(lines[0][:-8] + b"\n" + b"\n".join(lines[1:]) + b"\n")
    with pytest.raises(PaperLedgerIntegrityError):
        PaperLedger(tmp_path).snapshot()


def test_anchor_is_written_with_the_atomic_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.portfolio.paper_trading as module

    calls: list[Path] = []
    original = module.atomic_write_bytes

    def spy(destination, payload, validator):
        calls.append(destination)
        return original(destination, payload, validator)

    monkeypatch.setattr(module, "atomic_write_bytes", spy)
    ledger = _ledger(tmp_path)
    assert calls and calls[-1] == ledger._anchor_path
    assert not list(ledger.path.parent.glob("*.tmp"))


# --- appendix -----------------------------------------------------------------------------------------------------


def test_corporate_action_on_distinct_dates_with_equal_terms_is_not_collapsed(tmp_path: Path) -> None:
    """C.C4.S17.N001."""

    ledger = _ledger(tmp_path)
    order = ledger.accept_proposal(_proposal(quantity_delta=10, source="ca"), execution_price=10, occurred_at=START)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10, fee=0, occurred_at=START)
    first = START + timedelta(days=1)
    second = START + timedelta(days=2)
    kwargs = dict(split_ratio=1.0, cash_dividend_per_unit=1.0, source_checksum="a" * 64)
    ledger.apply_corporate_action("VWCE", occurred_at=first, **kwargs)
    ledger.apply_corporate_action("VWCE", occurred_at=second, **kwargs)
    actions = [e for e in ledger._read_events() if e["event_type"] == "corporate_action"]
    assert len(actions) == 2
    assert actions[0]["payload"]["action_id"] != actions[1]["payload"]["action_id"]
    # A retry of the same dated action stays idempotent.
    ledger.apply_corporate_action("VWCE", occurred_at=first, **kwargs)
    assert len([e for e in ledger._read_events() if e["event_type"] == "corporate_action"]) == 2
    assert ledger.snapshot().cash == pytest.approx(900 + 20)


def test_valuation_snapshot_rows_carry_a_stable_snapshot_id() -> None:
    """D.C3.S01.N001."""

    from etf_cockpit.portfolio.valuation import SNAPSHOT_ID_COLUMN, build_daily_portfolio_snapshots

    holdings = pd.DataFrame({"date": ["2026-01-05", "2026-01-06"], "instrument_id": ["A", "A"], "quantity": [1.0, 1.0]})
    prices = pd.DataFrame({"date": ["2026-01-05", "2026-01-06"], "instrument_id": ["A", "A"], "price": [10.0, 11.0]})
    cash = pd.DataFrame({"date": ["2026-01-05", "2026-01-06"], "cash_value": [5.0, 5.0]})
    events = pd.DataFrame({"date": [], "event_type": [], "amount": []})
    first = build_daily_portfolio_snapshots(holdings, prices, cash, events, decision_time="2026-01-07")
    again = build_daily_portfolio_snapshots(holdings, prices, cash, events, decision_time="2026-01-07")
    assert list(first[SNAPSHOT_ID_COLUMN]) == list(again[SNAPSHOT_ID_COLUMN])
    assert first[SNAPSHOT_ID_COLUMN].str.startswith("valsnap_").all()
    assert first[SNAPSHOT_ID_COLUMN].nunique() == 2
    changed = prices.assign(price=[10.0, 12.0])
    other = build_daily_portfolio_snapshots(holdings, changed, cash, events, decision_time="2026-01-07")
    assert other[SNAPSHOT_ID_COLUMN].iloc[0] == first[SNAPSHOT_ID_COLUMN].iloc[0]
    assert other[SNAPSHOT_ID_COLUMN].iloc[1] != first[SNAPSHOT_ID_COLUMN].iloc[1]


def test_portfolio_view_binding_carries_snapshot_id_and_rejects_conflicting_ids() -> None:
    from etf_cockpit.application import portfolio_views

    frame = pd.DataFrame(
        {"date": ["2026-01-05"], "snapshot_id": ["valsnap_x"], "total_value": [1.0]}
    )
    selected = portfolio_views._performance_snapshot_for(frame, "2026-01-05")
    assert selected is not None and selected["snapshot_id"] == "valsnap_x"
    duplicated = pd.concat([frame, frame.assign(snapshot_id="valsnap_y")], ignore_index=True)
    assert portfolio_views._performance_snapshot_for(duplicated, "2026-01-05") is None


def _daily_snapshots(dates: list[str], values: list[float]) -> pd.DataFrame:
    from etf_cockpit.portfolio.valuation import SNAPSHOT_COLUMNS

    rows = []
    for index, (day, value) in enumerate(zip(dates, values)):
        rows.append(
            {
                "date": pd.Timestamp(day), "cash_value": 0.0, "securities_value": value, "total_value": value,
                "external_flow": 0.0, "invested_capital": values[0],
                "dividends": 0.0, "coupons": 0.0, "fees": 0.0, "taxes": 0.0,
                "investment_pnl": float("nan") if index == 0 else value - values[index - 1],
                "period_return": float("nan") if index == 0 else value / values[index - 1] - 1.0,
                "valuation_status": "available", "flow_status": "available",
                "availability_evidence": "timestamped", "missing_reasons": "", "execution_allowed": False,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SNAPSHOT_COLUMNS)


def test_daily_twr_return_across_a_missing_session_is_unavailable() -> None:
    """D.C4.S05.N001: the day after a missing session must not present a two-session return as one day."""

    from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series

    # 2026-01-06 (Tuesday, an XNYS session) has no snapshot.
    gapped = _daily_snapshots(["2026-01-05", "2026-01-07", "2026-01-08"], [100.0, 110.0, 121.0])
    series = build_portfolio_performance_series(gapped, metric="twr_return", date_range="inception", aggregation="day")
    by_day = {point.period_end: point for point in series.points}
    after_gap = by_day[pd.Timestamp("2026-01-07").date()]
    assert after_gap.value is None and after_gap.status in {"unavailable", "partial"}
    assert "2026-01-06" in str(after_gap.reason)
    # The next consecutive session is a genuine one-day return and stays available.
    consecutive = by_day[pd.Timestamp("2026-01-08").date()]
    assert consecutive.value == pytest.approx(0.1)

    complete = _daily_snapshots(["2026-01-05", "2026-01-06", "2026-01-07"], [100.0, 105.0, 110.0])
    full = build_portfolio_performance_series(complete, metric="twr_return", date_range="inception", aggregation="day")
    assert [point.value for point in full.points][1] == pytest.approx(0.05)


def test_disabled_held_instrument_cannot_take_a_positive_target_but_may_be_sold_to_zero() -> None:
    """D.C3.S13.N003."""

    from etf_cockpit.core.config import load_config
    from etf_cockpit.portfolio.sandbox import create_candidate

    config = load_config().model_copy(deep=True)
    disabled = next(item for item in config.universe.etfs if item.id == "LYP6")
    enabled = next(item for item in config.universe.etfs if item.id == "VWCE" and item.enabled)
    disabled.enabled = False
    holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.5, "market_value_eur": 50_000.0},
            {"etf_id": "LYP6", "current_weight": 0.5, "market_value_eur": 50_000.0},
        ]
    )
    kwargs = dict(name="plan", analysis_notional_eur=100_000, source_revision="r1")
    with pytest.raises(ValueError, match="disabled instrument: LYP6"):
        create_candidate(config, holdings, target_weights={"VWCE": 0.5, "LYP6": 0.5}, cash_weight=0.0, **kwargs)
    sold = create_candidate(config, holdings, target_weights={"VWCE": 1.0, "LYP6": 0.0}, cash_weight=0.0, **kwargs)
    assert dict(sold.target_weights) == {enabled.id: 1.0}
    unheld = pd.DataFrame([{"etf_id": "VWCE", "current_weight": 1.0, "market_value_eur": 100_000.0}])
    with pytest.raises(ValueError, match="disabled instrument: LYP6"):
        create_candidate(config, unheld, target_weights={"VWCE": 0.5, "LYP6": 0.5}, cash_weight=0.0, **kwargs)


def test_account_mappings_are_namespaced_by_provider(tmp_path: Path) -> None:
    """D.C3.S12.N001: two providers reusing one account id keep separate ledger mappings."""

    from etf_cockpit.application.portfolio_imports import PortfolioImportApplication
    from etf_cockpit.data.local_storage import TransactionalStore
    from etf_cockpit.portfolio.ledger import Ledger
    from etf_cockpit.portfolio.reconciliation import load_account_mappings, lookup_account_mapping

    with TransactionalStore(tmp_path) as store:
        ledger = Ledger(store.connection)
        for suffix in ("A1", "B1"):
            ledger.create_account(f"CASH-{suffix}", name="cash", account_type="asset", account_role="cash", authority="broker")
            ledger.create_account(f"POS-{suffix}", name="pos", account_type="asset", account_role="position", authority="broker")
            ledger.create_account(f"CLR-{suffix}", name="clr", account_type="equity", authority="broker")
    app = PortfolioImportApplication(tmp_path)
    for provider, suffix in (("broker-a", "A1"), ("Broker-B", "B1")):
        app.map_source_account(
            authority="broker", source_account_id="ACC-1", provider_id=provider,
            cash_account_id=f"CASH-{suffix}", position_account_id=f"POS-{suffix}", clearing_account_id=f"CLR-{suffix}",
            reviewer="operator", reason="Provider statement account explicitly matched to the ledger",
        )
    with TransactionalStore(tmp_path) as store:
        mappings = load_account_mappings(store, authority="broker")
    assert len(mappings) == 2
    assert lookup_account_mapping(mappings, {"provider_id": "broker-a", "account_id": "ACC-1"}).cash_account_id == "CASH-A1"
    assert lookup_account_mapping(mappings, {"provider_id": "BROKER-B", "account_id": "ACC-1"}).cash_account_id == "CASH-B1"
    # No provider-specific mapping and no legacy provider-less one: unmapped, never another provider's.
    assert lookup_account_mapping(mappings, {"provider_id": "broker-c", "account_id": "ACC-1"}) is None
    assert lookup_account_mapping(mappings, {"account_id": "ACC-1"}) is None
