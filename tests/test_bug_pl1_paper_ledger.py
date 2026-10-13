"""Issue #961: PaperLedger accounting correctness (as_of cash, FX, maturity, marks, head anchor, cancel)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from etf_cockpit.application.contracts import PaperFillRequest, PaperProposalAcceptRequest
from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import (
    PaperLedger,
    PaperLedgerError,
    PaperLedgerIntegrityError,
    _digest,
)
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _day(days: float) -> datetime:
    return T0 + timedelta(days=days)


def _proposal(
    *,
    quantity_delta: float = 10.0,
    source: str = "pl1",
    expires_at: str = "2099-01-02T00:00:00+00:00",
    extra_material: dict[str, object] | None = None,
) -> dict[str, object]:
    material: dict[str, object] = {"instrument_id": "VWCE", "target_quantity": quantity_delta, "source": source}
    material.update(extra_material or {})
    checksum = _digest(material)
    policy = load_gate_policy()
    assert policy.policy is not None
    payload: dict[str, object] = {
        "schema_version": "proposal.v1",
        "proposal_id": f"proposal_{checksum[:20]}",
        "instrument_id": "VWCE",
        "outcome": "proposal_ready",
        "proposal_allowed": True,
        "authority_stage": "paper",
        "execution_allowed": False,
        "quantity_delta": quantity_delta,
        "rationale": "All required paper evidence passed.",
        "gates": [{"gate_id": gate, "passed": True, "reason": "passed", "blocker": True} for gate in REQUIRED_GATES],
        "alternatives": [],
        "as_of": "2099-01-01T00:00:00+00:00",
        "expires_at": expires_at,
        "policy_version": "proposal-policy.v1",
        "authority_policy_checksum": current_authority_policy_checksum(),
        "gate_policy_version": policy.policy.policy_version,
        "gate_policy_checksum": policy.checksum,
        "input_checksum": checksum,
        "input_material": material,
    }
    payload["decision_checksum"] = _digest(payload)
    return payload


def _ledger(tmp_path: Path, cash: float = 1_000.0) -> PaperLedger:
    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=cash, occurred_at=T0)
    return ledger


def _buy(ledger: PaperLedger, quantity: float, price: float, *, source: str, at: float, fill: float | None = None) -> dict:
    order = ledger.accept_proposal(
        _proposal(quantity_delta=quantity, source=source), execution_price=price, occurred_at=_day(at)
    )
    ledger.record_fill(str(order["order_id"]), quantity=quantity, price=price, occurred_at=_day(at if fill is None else fill))
    return order


def _evidence(**extra: object) -> dict[str, object]:
    return dict(
        adjusted_close=11, benchmark_return=0, cash_return=0, source_authority="fixture", source_checksum="b" * 64, **extra
    )


def _cash(ledger: PaperLedger, as_of: datetime) -> float:
    return float(ledger.cash_balance(account_id=ledger.account_id, currency="EUR", as_of=as_of))


# D014-N001
def test_historical_cash_excludes_later_events(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _buy(ledger, 5, 100, source="cash", at=10)
    assert _cash(ledger, _day(5)) == pytest.approx(1_000)
    assert _cash(ledger, _day(0)) == pytest.approx(1_000)
    assert _cash(ledger, _day(11)) == pytest.approx(500)
    with pytest.raises(PaperLedgerError):
        ledger.cash_balance(account_id=ledger.account_id, currency="EUR", as_of=datetime(2026, 5, 5))  # naive


# D014-N002 / D014-N003
def test_partial_or_young_fill_cannot_mature(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    order = ledger.accept_proposal(_proposal(source="mature"), execution_price=10, occurred_at=_day(1))
    oid = str(order["order_id"])
    ledger.record_fill(oid, quantity=4, price=10, occurred_at=_day(2))
    with pytest.raises(PaperLedgerError, match="fully filled"):
        ledger.mature_outcome(oid, **_evidence(occurred_at=_day(40)))
    ledger.record_fill(oid, quantity=6, price=10, occurred_at=_day(3))
    with pytest.raises(PaperLedgerError, match="horizon"):
        ledger.mature_outcome(oid, **_evidence(occurred_at=_day(3) + timedelta(minutes=1)))
    with pytest.raises(PaperLedgerError, match="horizon"):
        ledger.mature_outcome(oid, **_evidence(occurred_at=_day(22)))
    result = ledger.mature_outcome(oid, **_evidence(occurred_at=_day(23)))
    assert result["quantity"] == pytest.approx(10)


# D114-N003 / D024-N003
def test_foreign_currency_without_fx_rate_is_rejected(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(PaperLedgerError, match="fx_rate"):
        ledger.accept_proposal(_proposal(source="usd"), execution_price=10, quote_currency="USD", occurred_at=_day(1))
    order = ledger.accept_proposal(
        _proposal(source="usd"), execution_price=10, quote_currency="USD", fx_rate=0.9, occurred_at=_day(1)
    )
    assert order["currency"] == "USD"
    with pytest.raises(PaperLedgerError, match="fx_rate"):
        ledger.record_fill(str(order["order_id"]), quantity=1, price=10, occurred_at=_day(2))
    ledger.record_fill(str(order["order_id"]), quantity=1, price=10, fx_rate=0.9, occurred_at=_day(2))
    assert _cash(ledger, _day(3)) == pytest.approx(1_000 - 9)


def test_contract_fx_rate_has_no_silent_default() -> None:
    assert PaperFillRequest.model_fields["fx_rate"].default is None
    assert PaperProposalAcceptRequest.model_fields["fx_rate"].default is None


# D114-N005 / D114-N004
def test_reopened_holding_does_not_reuse_old_mark_and_subprecision_is_rejected(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _buy(ledger, 1, 100, source="a", at=1)
    ledger.mark("VWCE", adjusted_close=100, source_checksum="c" * 64, occurred_at=_day(2))
    sell = ledger.accept_proposal(_proposal(quantity_delta=-1, source="b"), execution_price=100, occurred_at=_day(3))
    ledger.record_fill(str(sell["order_id"]), quantity=1, price=100, occurred_at=_day(3))
    _buy(ledger, 1, 200, source="c", at=4)
    snapshot = ledger.snapshot()
    assert snapshot.positions[0].mark_price is None
    assert snapshot.equity is None
    with pytest.raises(PaperLedgerError, match="precision"):
        ledger.accept_proposal(_proposal(quantity_delta=4e-9, source="tiny"), execution_price=10, occurred_at=_day(5))


# D119-N001
def test_deleting_the_last_event_is_detected(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _buy(ledger, 5, 100, source="anchor", at=1)
    assert ledger.snapshot().cash == pytest.approx(500)
    lines = ledger.path.read_text(encoding="utf-8").splitlines(keepends=True)
    ledger.path.write_text("".join(lines[:-1]), encoding="utf-8")
    with pytest.raises(PaperLedgerIntegrityError):
        ledger.snapshot()


# D024-N001
def test_cancel_after_durable_unprojected_partial_fill_replays(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    order = ledger.accept_proposal(_proposal(source="cancel"), execution_price=10, occurred_at=_day(1))
    ledger._record_lifecycle_fill(
        order, fill_id="fill_crash", quantity=Decimal("4"), price=Decimal("10"), fee=Decimal("0"),
        fx_rate=Decimal("1"), occurred_at=_day(2),
    )
    cancelled = ledger.cancel_order(str(order["order_id"]), reason="test", occurred_at=_day(3))
    assert cancelled["status"] == "cancelled"
    assert cancelled["filled_quantity"] == pytest.approx(4)
    reopened = PaperLedger(tmp_path)
    assert reopened.snapshot().positions[0].quantity == pytest.approx(4)
    assert reopened.snapshot().cash == pytest.approx(960)


# D014-N004
def test_existing_order_retry_returns_before_expiry_check(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    accepted = ledger.accept_proposal(_proposal(source="retry"), execution_price=10, occurred_at=_day(1))
    expired = _proposal(source="retry", expires_at="2020-01-01T00:00:00+00:00")
    assert ledger.accept_proposal(expired, execution_price=10, occurred_at=_day(1))["order_id"] == accepted["order_id"]
    with pytest.raises(PaperLedgerError, match="expired"):
        ledger.accept_proposal(
            _proposal(source="other", expires_at="2020-01-01T00:00:00+00:00"), execution_price=10, occurred_at=_day(1)
        )


# D106-N003
def test_corporate_action_credits_ex_date_quantity(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _buy(ledger, 5, 100, source="held", at=1)
    sell = ledger.accept_proposal(_proposal(quantity_delta=-5, source="sold"), execution_price=100, occurred_at=_day(3))
    ledger.record_fill(str(sell["order_id"]), quantity=5, price=100, occurred_at=_day(4))
    cash_before = ledger.snapshot().cash
    ledger.apply_corporate_action(
        "VWCE", split_ratio=1, cash_dividend_per_unit=1, source_authority="fixture", source_checksum="a" * 64,
        occurred_at=_day(2),
    )
    assert ledger.snapshot().cash == pytest.approx(cash_before + 5)


# D114-N002
def test_win_rate_counts_closed_orders_not_fills(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _buy(ledger, 10, 10, source="open", at=1)
    sell = ledger.accept_proposal(_proposal(quantity_delta=-10, source="close"), execution_price=10, occurred_at=_day(2))
    oid = str(sell["order_id"])
    ledger.record_fill(oid, quantity=5, price=12, occurred_at=_day(3))  # +10
    ledger.record_fill(oid, quantity=5, price=2, occurred_at=_day(4))  # -40
    snapshot = ledger.snapshot()
    assert snapshot.closed_trades == 1
    assert snapshot.win_rate == pytest.approx(0.0)


# D024-N002
def test_stale_target_cannot_create_two_overshooting_proposals(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    extra = {"current_quantity": 0.0}
    ledger.accept_proposal(_proposal(source="first", extra_material=extra), execution_price=10, occurred_at=_day(1))
    with pytest.raises(PaperLedgerError, match="target"):
        ledger.accept_proposal(_proposal(source="second", extra_material=extra), execution_price=10, occurred_at=_day(1))
