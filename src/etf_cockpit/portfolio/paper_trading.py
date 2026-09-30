"""Local, append-only paper account ledger for ISSUE-0129.

The ledger is a simulation and evidence store, not a broker adapter.  It only
accepts a proposal that has already passed the non-executable proposal policy,
keeps the proposal snapshot immutable, and replays its hash-chained JSONL log
to derive cash, positions and performance after a restart.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from decimal import Decimal, InvalidOperation
from typing import Literal, Mapping

from etf_cockpit.core.config import load_config, load_settlement_config
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.trading.cash_reservation import CashReservationError
from etf_cockpit.trading.order_lifecycle import (
    ALLOWED_TRANSITIONS,
    OrderLifecycle,
    OrderLifecycleError,
    OrderState,
)
from etf_cockpit.trading.pre_trade_controls import PreTradeControlError, PreTradeControls


PAPER_SCHEMA_VERSION = "paper_ledger.v1"
EXECUTION_ALLOWED = False
NETWORK_ACCESS_ALLOWED = False
PriceBasis = Literal["execution_quote", "adjusted_close"]


class PaperLedgerError(ValueError):
    """A user-correctable paper-ledger request or integrity failure."""


class PaperLedgerIntegrityError(PaperLedgerError):
    """The append-only ledger cannot be trusted and must remain read-only."""


@dataclass(frozen=True)
class PaperPosition:
    instrument_id: str
    quantity: float
    average_cost: float
    mark_price: float | None
    mark_fx_rate: float
    currency: str
    realised_pnl: float
    unrealised_pnl: float | None

    def to_payload(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "quantity": round(self.quantity, 8),
            "average_cost": round(self.average_cost, 8),
            "mark_price": None if self.mark_price is None else round(self.mark_price, 8),
            "mark_fx_rate": round(self.mark_fx_rate, 8),
            "currency": self.currency,
            "realised_pnl": round(self.realised_pnl, 8),
            "unrealised_pnl": None if self.unrealised_pnl is None else round(self.unrealised_pnl, 8),
        }


@dataclass(frozen=True)
class PaperAccountSnapshot:
    account_id: str
    base_currency: str
    status: str
    cash: float
    equity: float
    pnl: float
    benchmark_return: float | None
    drawdown: float | None
    open_positions: int
    closed_trades: int
    win_rate: float | None
    payoff_ratio: float | None
    positions: tuple[PaperPosition, ...]
    order_count: int
    event_count: int
    ledger_hash: str
    reconciliation_status: str
    message: str
    matured_outcomes: int = 0
    operational_incidents: int = 0

    def to_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "base_currency": self.base_currency,
            "status": self.status,
            "cash": round(self.cash, 8),
            "equity": round(self.equity, 8),
            "pnl": round(self.pnl, 8),
            "benchmark_return": None if self.benchmark_return is None else round(self.benchmark_return, 8),
            "drawdown": None if self.drawdown is None else round(self.drawdown, 8),
            "open_positions": self.open_positions,
            "closed_trades": self.closed_trades,
            "win_rate": None if self.win_rate is None else round(self.win_rate, 8),
            "payoff_ratio": None if self.payoff_ratio is None else round(self.payoff_ratio, 8),
            "positions": [item.to_payload() for item in self.positions],
            "order_count": self.order_count,
            "event_count": self.event_count,
            "ledger_hash": self.ledger_hash,
            "reconciliation_status": self.reconciliation_status,
            "message": self.message,
            "matured_outcomes": self.matured_outcomes,
            "operational_incidents": self.operational_incidents,
            "execution_allowed": False,
        }


class PaperLedger:
    """Replayable local paper account with no external execution path."""

    ORDER_TRANSITIONS = ALLOWED_TRANSITIONS
    def __init__(self, root: Path, *, account_id: str = "local-paper") -> None:
        self.root = root
        self.account_id = _clean_id(account_id, "account_id")
        paper_root = root / "data" / "operations" / "paper"
        # Keep the original local-paper location compatible while ensuring
        # named paper accounts can never replay one another's events.
        self.path = (
            paper_root / "ledger.jsonl"
            if self.account_id == "local-paper"
            else paper_root / "accounts" / self.account_id / "ledger.jsonl"
        )
        self._lock = threading.RLock()
        self._lifecycle: OrderLifecycle | None = None

    def open_account(
        self,
        *,
        initial_cash: float,
        base_currency: str = "EUR",
        occurred_at: datetime | None = None,
    ) -> PaperAccountSnapshot:
        cash = _decimal_number(initial_cash, "initial_cash", non_negative=True)
        currency = _clean_id(base_currency, "base_currency").upper()
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            if state["opened"]:
                if state["base_currency"] != currency or state["initial_cash"] != cash:
                    raise PaperLedgerError("The paper account already exists with different opening terms.")
                return self._snapshot(events, state)
            self._append(
                "account_opened",
                {"initial_cash": str(cash), "base_currency": currency},
                occurred_at=occurred_at,
            )
            events = self._read_events()
            return self._snapshot(events, self._replay(events))

    def cash_balance(self, *, account_id: str, currency: str, as_of: datetime) -> Decimal:
        """Expose the simulated account cash projection to the reservation service."""

        if account_id != self.account_id:
            raise PaperLedgerError("Cash balance requested for a different paper account.")
        if not isinstance(as_of, datetime) or as_of.tzinfo is None:
            raise PaperLedgerError("A timezone-aware cash-balance time is required.")
        with self._lock:
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            if str(state["base_currency"]).upper() != currency.upper():
                raise PaperLedgerError("Paper cash is available only in the account base currency.")
            cash = state["cash"]
            if not isinstance(cash, Decimal):
                raise PaperLedgerIntegrityError("Paper cash projection is not an exact decimal.")
            return cash

    @property
    def cash_includes_unsettled_trades(self) -> bool:
        """Report whether every committed lifecycle fill is present in the cash projection."""

        try:
            events = self._read_events()
            projected = {
                str(event["payload"].get("fill_id"))
                for event in events
                if event.get("event_type") == "fill_recorded" and isinstance(event.get("payload"), Mapping)
            }
            return all(
                str(event.payload.get("fill_id")) in projected
                for event in self._order_lifecycle().fill_events()
            )
        except (OSError, PaperLedgerError, sqlite3.Error):
            return False

    def accept_proposal(
        self,
        proposal: Mapping[str, object],
        *,
        execution_price: float,
        fee: float = 0.0,
        fx_rate: float = 1.0,
        decision_mode: Literal["manual_accept", "auto_paper"] = "manual_accept",
        occurred_at: datetime | None = None,
        control_binding: object | None = None,
    ) -> dict[str, object]:
        """Accept one policy-approved proposal as a simulated open order.

        ``auto_paper`` is an explicit paper-only decision label.  It changes
        attribution, not authority: both modes remain local simulations and
        retain ``execution_allowed=false``.
        """

        self._validate_proposal(proposal)
        if decision_mode not in {"manual_accept", "auto_paper"}:
            raise PaperLedgerError("Unsupported paper decision mode.")
        price_decimal = _decimal_number(execution_price, "execution_price", positive=True)
        fee_decimal = _decimal_number(fee, "fee", non_negative=True)
        fx_decimal = _decimal_number(fx_rate, "fx_rate", positive=True)
        price = float(price_decimal)
        fee_value = float(fee_decimal)
        fx = float(fx_decimal)
        proposal_id = _clean_id(proposal.get("proposal_id"), "proposal_id")
        quantity_decimal = _decimal_number(proposal.get("quantity_delta"), "quantity_delta")
        quantity_delta = float(quantity_decimal)
        quantity = abs(quantity_delta)
        if quantity <= 0:
            raise PaperLedgerError("A zero-quantity proposal cannot be accepted.")
        instrument_id = _clean_id(proposal.get("instrument_id"), "instrument_id").upper()
        order_id = "order_" + _digest(
            {"account_id": self.account_id, "proposal_id": proposal_id, "quantity": quantity}
        )[:20]
        with self._lock, self._file_lock():
            self._recover_interrupted_fills()
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            self._require_order_pipeline_open()
            if proposal_id in state["rejections"]:
                raise PaperLedgerError("A rejected proposal cannot be accepted later.")
            if proposal_id in state["deferred"]:
                raise PaperLedgerError("A deferred proposal cannot be accepted later.")
            existing = state["orders"].get(order_id)
            if existing is not None:
                if any(
                    abs(float(existing.get(key, 0.0)) - value) > 1e-8
                    for key, value in (("execution_price", price), ("fee", fee_value), ("fx_rate", fx))
                ):
                    raise PaperLedgerError("The paper proposal was already accepted with different terms.")
                if existing.get("decision_mode", "manual_accept") != decision_mode:
                    raise PaperLedgerError("The paper proposal was already accepted with a different decision mode.")
                if existing.get("lifecycle_idempotency_key"):
                    lifecycle = self._order_lifecycle()
                    if lifecycle.get_state(order_id) in {OrderState.RESERVED, OrderState.SUBMITTING}:
                        lifecycle.transition(
                            order_id,
                            OrderState.ACKNOWLEDGED,
                            event_key=f"paper-ack:{order_id}",
                            event_type="paper_acknowledged",
                            occurred_at=occurred_at,
                        )
                return dict(existing)
            if quantity_delta < 0 and state["positions"].get(instrument_id, {}).get("quantity", 0.0) + 1e-8 < quantity:
                raise PaperLedgerError("A paper sell cannot exceed the current simulated position.")
            venue, instrument_type = self._order_market_terms(proposal, instrument_id)
            currency = _clean_id(proposal.get("currency", state["base_currency"]), "currency").upper()
            lifecycle_key = f"paper:{self.account_id}:{proposal_id}"
            try:
                control_decision = self._evaluate_pre_trade_controls(
                    proposal, state=state, events=events,
                    execution_price=price_decimal, quantity_delta=quantity_decimal, fx_rate=fx_decimal,
                    occurred_at=occurred_at,
                )
            except PreTradeControlError as exc:
                raise PaperLedgerError("Independent pre-trade control state is unavailable.") from exc
            if not control_decision.allowed:
                raise PaperLedgerError(control_decision.reason)
            control_binding_hash = None
            if control_binding is not None:
                control_binding_hash = self._verify_control_binding(
                    control_binding,
                    proposal_id=proposal_id,
                    decision=control_decision,
                    execution_terms=self._execution_terms(proposal, price_decimal, fee_decimal, fx_decimal),
                )
            if PreTradeControls(self.root, account_id=self.account_id).kill_switch_active():
                raise PaperLedgerError("The independent pre-trade kill switch is active.")
            try:
                intent = self._order_lifecycle().reserve_order(
                    account_id=self.account_id,
                    order_id=order_id,
                    idempotency_key=lifecycle_key,
                    currency=str(state["base_currency"]).upper(),
                    side="buy" if quantity_delta > 0 else "sell",
                    quantity=abs(quantity_decimal),
                    limit_price=price_decimal * fx_decimal,
                    fee_estimate=fee_decimal,
                    venue=venue,
                    instrument_type=instrument_type,
                    occurred_at=occurred_at,
                )
            except (OrderLifecycleError, CashReservationError) as exc:
                raise PaperLedgerError(str(exc)) from exc
            order = {
                "account_id": self.account_id,
                "order_id": order_id,
                "proposal_id": proposal_id,
                "instrument_id": instrument_id,
                "side": "buy" if quantity_delta > 0 else "sell",
                "quantity": round(quantity, 8),
                "filled_quantity": 0.0,
                "remaining_quantity": round(quantity, 8),
                "execution_price": price,
                "monetary_terms": self._execution_terms(proposal, price_decimal, fee_decimal, fx_decimal),
                "currency": currency,
                "status": "accepted",
                "fee": fee_value,
                "fx_rate": fx,
                "lifecycle_idempotency_key": lifecycle_key,
                "control_binding_hash": control_binding_hash,
                "lifecycle_state": OrderState.RESERVED.value,
                "settlement_date": None if intent.settlement_date is None else intent.settlement_date.isoformat(),
                "settlement_warning": intent.settlement_warning,
                "price_basis": "execution_quote",
                "proposal_snapshot": _json_copy(proposal),
                "proposal_evidence_hashes": _freeze_proposal_evidence(proposal),
                "decision_mode": decision_mode,
                "execution_allowed": False,
            }
            self._append("order_accepted", order, occurred_at=occurred_at)
            self._order_lifecycle().transition(
                order_id,
                OrderState.ACKNOWLEDGED,
                event_key=f"paper-ack:{order_id}",
                event_type="paper_acknowledged",
                occurred_at=occurred_at,
            )
            return order

    def evaluate_pre_trade_controls(
        self,
        proposal: Mapping[str, object],
        *,
        execution_price: object,
        fee: object = 0,
        fx_rate: object = 1,
        occurred_at: datetime | None = None,
    ):
        """Return the independent paper-ledger control result for a sealed canary binding."""

        self._validate_proposal(proposal)
        price = _decimal_number(execution_price, "execution_price", positive=True)
        _decimal_number(fee, "fee", non_negative=True)
        fx = _decimal_number(fx_rate, "fx_rate", positive=True)
        quantity = _decimal_number(proposal.get("quantity_delta"), "quantity_delta")
        with self._lock, self._file_lock():
            self._recover_interrupted_fills()
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            self._require_order_pipeline_open()
            return self._evaluate_pre_trade_controls(
                proposal,
                state=state,
                events=events,
                execution_price=price,
                quantity_delta=quantity,
                fx_rate=fx,
                occurred_at=occurred_at,
            )

    @staticmethod
    def _execution_terms(
        proposal: Mapping[str, object],
        execution_price: Decimal,
        fee: Decimal,
        fx_rate: Decimal,
    ) -> dict[str, str]:
        return {
            "execution_price": str(execution_price),
            "quantity_delta": str(_decimal_number(proposal.get("quantity_delta"), "quantity_delta")),
            "fee": str(fee),
            "fx_rate": str(fx_rate),
        }

    @staticmethod
    def _control_result_payload(decision: object) -> dict[str, object]:
        return {
            "allowed": bool(decision.allowed),
            "control": decision.control,
            "reason": decision.reason,
            "order_value": None if decision.order_value is None else str(decision.order_value),
            "position_exposure": None if decision.position_exposure is None else str(decision.position_exposure),
            "daily_turnover": None if decision.daily_turnover is None else str(decision.daily_turnover),
            "override_id": decision.override_id,
            "execution_allowed": False,
        }

    @staticmethod
    def _verify_control_binding(
        evidence: object,
        *,
        proposal_id: str,
        decision: object,
        execution_terms: Mapping[str, str],
    ) -> str:
        from etf_cockpit.trading.canary import _verified_payload

        payload = _verified_payload(evidence)
        if (
            payload is None
            or payload.get("proposal_id") != proposal_id
            or payload.get("paper_control_result") != PaperLedger._control_result_payload(decision)
            or payload.get("execution_terms") != dict(execution_terms)
            or payload.get("execution_allowed") is not False
        ):
            raise PaperLedgerError("The sealed independent control result or execution terms changed before acceptance.")
        seal = getattr(evidence, "sha256", None)
        if not isinstance(seal, str) or len(seal) != 64:
            raise PaperLedgerError("The sealed independent control binding is invalid.")
        return seal

    def _evaluate_pre_trade_controls(
        self,
        proposal: Mapping[str, object],
        *,
        state: Mapping[str, object],
        events: list[dict[str, object]],
        execution_price: Decimal,
        quantity_delta: Decimal,
        fx_rate: Decimal,
        occurred_at: datetime | None,
    ):
        try:
            return PreTradeControls(self.root, account_id=self.account_id).evaluate_order(
                proposal,
                execution_price=execution_price,
                quantity_delta=quantity_delta,
                fx_rate=fx_rate,
                positions=state["positions"],
                open_orders=state["orders"],
                paper_events=events,
                path="paper",
                who=self.account_id,
                occurred_at=occurred_at,
            )
        except PreTradeControlError as exc:
            raise PaperLedgerError("Independent pre-trade control state is unavailable.") from exc

    def reject_proposal(
        self,
        proposal: Mapping[str, object],
        *,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        self._validate_proposal_identity(proposal)
        text = str(reason).strip()
        if not text:
            raise PaperLedgerError("A rejection reason is required.")
        proposal_id = _clean_id(proposal.get("proposal_id"), "proposal_id")
        rejection_id = "rejection_" + _digest({"account_id": self.account_id, "proposal_id": proposal_id})[:20]
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            if any(item.get("proposal_id") == proposal_id for item in state["orders"].values()):
                raise PaperLedgerError("A proposal that has been accepted cannot also be rejected.")
            if proposal_id in state["rejections"]:
                return dict(state["rejections"][proposal_id])
            rejection = {
                "rejection_id": rejection_id,
                "proposal_id": proposal_id,
                "reason": text,
                "proposal_snapshot": _json_copy(proposal),
                "proposal_evidence_hashes": _freeze_proposal_evidence(proposal),
                "execution_allowed": False,
            }
            self._append("proposal_rejected", rejection, occurred_at=occurred_at)
            return rejection

    def defer_proposal(
        self,
        proposal: Mapping[str, object],
        *,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Persist a no-order decision until a later evidence window."""

        self._validate_proposal_identity(proposal)
        text = str(reason).strip()
        if not text:
            raise PaperLedgerError("A deferral reason is required.")
        proposal_id = _clean_id(proposal.get("proposal_id"), "proposal_id")
        deferred_id = "deferred_" + _digest({"account_id": self.account_id, "proposal_id": proposal_id})[:20]
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            if any(item.get("proposal_id") == proposal_id for item in state["orders"].values()):
                raise PaperLedgerError("A proposal that has been accepted cannot also be deferred.")
            if proposal_id in state["rejections"]:
                raise PaperLedgerError("A rejected proposal cannot also be deferred.")
            existing = state["deferred"].get(proposal_id)
            if existing is not None:
                if existing.get("reason") != text:
                    raise PaperLedgerError("The proposal was already deferred with a different reason.")
                return dict(existing)
            deferred = {
                "deferred_id": deferred_id,
                "proposal_id": proposal_id,
                "reason": text,
                "proposal_snapshot": _json_copy(proposal),
                "proposal_evidence_hashes": _freeze_proposal_evidence(proposal),
                "execution_allowed": False,
            }
            self._append("proposal_deferred", deferred, occurred_at=occurred_at)
            return deferred

    def auto_paper_proposal(
        self,
        proposal: Mapping[str, object],
        *,
        execution_price: float,
        fee: float = 0.0,
        fx_rate: float = 1.0,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Record an explicitly selected automatic paper decision.

        This is deliberately a convenience wrapper around the same guarded
        local order path; it never creates a broker or live execution route.
        """

        return self.accept_proposal(
            proposal,
            execution_price=execution_price,
            fee=fee,
            fx_rate=fx_rate,
            decision_mode="auto_paper",
            occurred_at=occurred_at,
        )

    def record_fill(
        self,
        order_id: str,
        *,
        fill_id: str | None = None,
        quantity: float,
        price: float,
        fee: float | None = None,
        fx_rate: float = 1.0,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        fill_quantity_decimal = _decimal_number(quantity, "quantity", positive=True)
        fill_price_decimal = _decimal_number(price, "price", positive=True)
        fill_fee_decimal = None if fee is None else _decimal_number(fee, "fee", non_negative=True)
        fill_fx_decimal = _decimal_number(fx_rate, "fx_rate", positive=True)
        fill_quantity = float(fill_quantity_decimal)
        fill_fee = None if fill_fee_decimal is None else float(fill_fee_decimal)
        with self._lock, self._file_lock():
            self._recover_interrupted_fills()
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            self._require_order_pipeline_open()
            order = state["orders"].get(_clean_id(order_id, "order_id"))
            if order is None:
                raise PaperLedgerError("The paper order does not exist.")
            supplied_fee = fill_fee
            if fill_id is None and fill_fee is None:
                fill_fee_decimal = (
                    _decimal_number(order.get("fee", 0.0), "fee", non_negative=True)
                    * fill_quantity_decimal
                    / _decimal_number(order["quantity"], "quantity", positive=True)
                )
                fill_fee = float(fill_fee_decimal)
            requested_fill_id = _clean_id(fill_id, "fill_id") if fill_id is not None else "fill_" + _digest(
                {
                    "order_id": order["order_id"], "quantity": str(fill_quantity_decimal),
                    "price": str(fill_price_decimal), "fee": None if fill_fee_decimal is None else str(fill_fee_decimal),
                    "fx_rate": str(fill_fx_decimal),
                }
            )[:20]
            for event in events:
                if event.get("event_type") == "fill_recorded" and isinstance(event.get("payload"), Mapping) and event["payload"].get("fill_id") == requested_fill_id:
                    previous_fill = event["payload"]
                    if previous_fill.get("order_id") != order["order_id"]:
                        raise PaperLedgerError("The fill ID was already used for another paper order.")
                    if any(
                        _decimal_number(previous_fill.get(key), key) != value
                        for key, value in (
                            ("quantity", fill_quantity_decimal),
                            ("price", fill_price_decimal),
                            ("fx_rate", fill_fx_decimal),
                        )
                    ):
                        raise PaperLedgerError("The fill ID was already used with different terms.")
                    if supplied_fee is not None and _decimal_number(previous_fill.get("fee"), "fee") != fill_fee_decimal:
                        raise PaperLedgerError("The fill ID was already used with different terms.")
                    return dict(state["orders"][order["order_id"]])
            if fill_fee is None:
                fill_fee_decimal = (
                    _decimal_number(order.get("fee", 0.0), "fee", non_negative=True)
                    * fill_quantity_decimal
                    / _decimal_number(order["quantity"], "quantity", positive=True)
                )
                fill_fee = float(fill_fee_decimal)
            if order["status"] in {"filled", "cancelled"}:
                raise PaperLedgerError(f"The paper order is already {order['status']}.")
            if fill_quantity > float(order["remaining_quantity"]) + 1e-8:
                raise PaperLedgerError("A fill cannot exceed the remaining paper order quantity.")
            value_decimal = fill_quantity_decimal * fill_price_decimal * fill_fx_decimal
            instrument_id = str(order["instrument_id"])
            position = state["positions"].get(instrument_id, {"quantity": 0.0, "average_cost": 0.0})
            if order["side"] == "buy" and state["cash"] < value_decimal + (fill_fee_decimal or Decimal("0")):
                raise PaperLedgerError("Insufficient paper cash for this fill.")
            if order["side"] == "sell" and position["quantity"] + 1e-8 < fill_quantity:
                raise PaperLedgerError("A paper sell fill exceeds the current simulated position.")
            if order.get("lifecycle_idempotency_key"):
                self._record_lifecycle_fill(
                    order,
                    fill_id=requested_fill_id,
                    quantity=fill_quantity_decimal,
                    price=fill_price_decimal,
                    fee=fill_fee_decimal or Decimal("0"),
                    fx_rate=fill_fx_decimal,
                    occurred_at=occurred_at,
                )
            fill = {
                "fill_id": requested_fill_id,
                "order_id": order["order_id"],
                "instrument_id": instrument_id,
                "side": order["side"],
                "quantity": str(fill_quantity_decimal),
                "price": str(fill_price_decimal),
                "fee": str(fill_fee_decimal or Decimal("0")),
                "fx_rate": str(fill_fx_decimal),
                "currency": order["currency"],
                "price_basis": "execution_quote",
                "execution_allowed": False,
            }
            self._append("fill_recorded", fill, occurred_at=occurred_at)
            events = self._read_events()
            return dict(self._replay(events)["orders"][order["order_id"]])

    def cancel_order(self, order_id: str, *, reason: str, occurred_at: datetime | None = None) -> dict[str, object]:
        text = str(reason).strip()
        if not text:
            raise PaperLedgerError("A cancellation reason is required.")
        with self._lock, self._file_lock():
            return self._cancel_order_locked(order_id, reason=text, occurred_at=occurred_at)

    def _cancel_order_locked(
        self, order_id: str, *, reason: str, occurred_at: datetime | None = None
    ) -> dict[str, object]:
        events = self._read_events()
        state = self._replay(events)
        self._require_open(state)
        self._require_order_pipeline_open()
        key = _clean_id(order_id, "order_id")
        order = state["orders"].get(key)
        if order is None:
            raise PaperLedgerError("The paper order does not exist.")
        if order["status"] in {"filled", "cancelled"}:
            if order["status"] == "cancelled" and order.get("lifecycle_idempotency_key"):
                try:
                    self._order_lifecycle().transition(
                        key,
                        OrderState.CANCELLED,
                        event_key=f"paper-cancel:{key}",
                        event_type="paper_cancelled",
                        payload={"reason": reason},
                        occurred_at=occurred_at,
                    )
                except OrderLifecycleError as exc:
                    raise PaperLedgerError(str(exc)) from exc
            return dict(order)
        if order.get("lifecycle_idempotency_key"):
            try:
                self._order_lifecycle().transition(
                    key,
                    OrderState.CANCELLED,
                    event_key=f"paper-cancel:{key}",
                    event_type="paper_cancelled",
                    payload={"reason": reason},
                    occurred_at=occurred_at,
                )
            except OrderLifecycleError as exc:
                raise PaperLedgerError(str(exc)) from exc
        self._append("order_cancelled", {"order_id": key, "reason": reason}, occurred_at=occurred_at)
        events = self._read_events()
        return dict(self._replay(events)["orders"][key])

    def mature_outcome(
        self,
        reference_id: str,
        *,
        adjusted_close: float,
        benchmark_return: float,
        cash_return: float,
        source_authority: str,
        source_checksum: str,
        horizon_days: int = 20,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Mature one filled proposal against adjusted-price, benchmark and cash evidence."""

        exit_price = _positive(adjusted_close, "adjusted_close")
        benchmark = _number(benchmark_return, "benchmark_return")
        cash = _number(cash_return, "cash_return")
        if not isinstance(horizon_days, int) or not 1 <= horizon_days <= 3_650:
            raise PaperLedgerError("horizon_days must be an integer between 1 and 3650.")
        provenance = _provenance(source_authority, source_checksum)
        reference = _clean_id(reference_id, "reference_id")
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            orders = state["orders"]
            fills = state["fills"]
            assert isinstance(orders, dict) and isinstance(fills, list)
            order = orders.get(reference)
            if order is None:
                order = next(
                    (candidate for candidate in orders.values() if candidate.get("proposal_id") == reference),
                    None,
                )
            if not isinstance(order, Mapping):
                raise PaperLedgerError("The paper order or proposal does not exist.")
            order_fills = [
                item
                for item in fills
                if isinstance(item, Mapping) and item.get("order_id") == order.get("order_id")
            ]
            if not order_fills:
                raise PaperLedgerError("A paper outcome requires at least one recorded fill.")
            quantity = sum(float(item["quantity"]) for item in order_fills)
            entry_value = sum(float(item["quantity"]) * float(item["price"]) * float(item.get("fx_rate", 1.0)) for item in order_fills)
            fees = sum(float(item.get("fee", 0.0)) for item in order_fills)
            entry_price = entry_value / quantity
            direction = 1.0 if order.get("side") == "buy" else -1.0
            gross_return = direction * (exit_price - entry_price) / entry_price
            cost_return = fees / entry_value if entry_value else 0.0
            net_return = gross_return - cost_return
            outcome_id = "outcome_" + _digest(
                {"account_id": self.account_id, "order_id": order["order_id"], "adjusted_close": exit_price, "benchmark_return": benchmark, "cash_return": cash, "horizon_days": horizon_days, "source_checksum": provenance["source_checksum"]}
            )[:20]
            existing = next(
                (
                    item
                    for item in state["outcomes"].values()
                    if item.get("order_id") == order["order_id"] and int(item.get("horizon_days", 20)) == horizon_days
                ),
                None,
            )
            if existing is not None:
                if any(
                    existing.get(key) != value
                    for key, value in (
                        ("adjusted_close", exit_price),
                        ("benchmark_return", benchmark),
                        ("cash_return", cash),
                        ("source_authority", provenance["source_authority"]),
                        ("source_checksum", provenance["source_checksum"]),
                    )
                ):
                    raise PaperLedgerError("The paper outcome was already matured with different evidence.")
                return dict(existing)
            outcome = {
                "outcome_id": outcome_id,
                "reference_id": reference,
                "order_id": str(order["order_id"]),
                "proposal_id": str(order["proposal_id"]),
                "instrument_id": str(order["instrument_id"]),
                "quantity": round(quantity, 8),
                "entry_price": round(entry_price, 8),
                "adjusted_close": exit_price,
                "fees": round(fees, 8),
                "gross_return": round(gross_return, 12),
                "net_return": round(net_return, 12),
                "benchmark_return": benchmark,
                "cash_return": cash,
                "horizon_days": horizon_days,
                "excess_return_vs_benchmark": round(net_return - benchmark, 12),
                "excess_return_vs_cash": round(net_return - cash, 12),
                "price_basis": "adjusted_close",
                "outcome_as_of": _timestamp(occurred_at),
                **provenance,
                "execution_allowed": False,
            }
            self._append("outcome_matured", outcome, occurred_at=occurred_at)
            return outcome

    def record_operational_error(
        self,
        code: str,
        *,
        message: str,
        related_id: str | None = None,
        requires_freeze: bool | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Record an incident and freeze uncertain order state without changing P&L."""

        code_text = _bounded_text(code, "code", 80)
        message_text = _bounded_text(message, "message", 500)
        related = None if related_id is None else _clean_id(related_id, "related_id")
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            from etf_cockpit.trading.incidents import (
                IncidentJournal,
                IncidentJournalError,
                IncidentJournalIntegrityError,
            )

            freeze = _incident_requires_freeze(code_text) or requires_freeze is True
            try:
                incident = IncidentJournal(self.root, account_id=self.account_id).record(
                    code_text,
                    message=message_text,
                    related_id=related,
                    requires_freeze=freeze,
                    occurred_at=occurred_at,
                )
            except IncidentJournalIntegrityError as exc:
                raise PaperLedgerIntegrityError("The operational incident journal is invalid.") from exc
            except IncidentJournalError as exc:
                raise PaperLedgerError(str(exc)) from exc
            existing = next(
                (
                    item
                    for item in state["operational_errors"]
                    if item.get("incident_id") == incident["incident_id"]
                ),
                None,
            )
            if existing is not None:
                if existing != incident:
                    raise PaperLedgerIntegrityError("A paper incident ID was reused with different content.")
                return dict(incident)
            self._append("operational_error", incident, occurred_at=occurred_at)
            return dict(incident)

    def reconcile_operational_state(self, observed_state: Mapping[str, object]) -> dict[str, object]:
        """Compare read-only observed paper state with the ledger before recovery."""

        from etf_cockpit.trading.incidents import (
            IncidentJournal,
            IncidentJournalError,
            IncidentJournalIntegrityError,
        )

        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            expected = self._reconciliation_state(state)
            try:
                return IncidentJournal(self.root, account_id=self.account_id).reconcile(observed_state, expected)
            except IncidentJournalIntegrityError as exc:
                raise PaperLedgerIntegrityError("The operational incident journal is invalid.") from exc
            except IncidentJournalError as exc:
                raise PaperLedgerError(str(exc)) from exc

    def reconciliation_state(self) -> dict[str, object]:
        """Return the current local paper state used by the recovery gate."""

        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            return self._reconciliation_state(state)

    def outcomes(self) -> tuple[dict[str, object], ...]:
        with self._lock, self._file_lock():
            state = self._replay(self._read_events())
            return tuple(dict(item) for item in state["outcomes"].values())

    def operational_errors(self) -> tuple[dict[str, object], ...]:
        with self._lock, self._file_lock():
            state = self._replay(self._read_events())
            return tuple(dict(item) for item in state["operational_errors"])

    def mark(
        self,
        instrument_id: str,
        *,
        adjusted_close: float,
        fx_rate: float = 1.0,
        benchmark_return: float | None = None,
        source_authority: str = "local_manual_adjusted_close",
        source_checksum: str = "",
        occurred_at: datetime | None = None,
    ) -> PaperAccountSnapshot:
        price = _positive(adjusted_close, "adjusted_close")
        fx = _positive(fx_rate, "fx_rate")
        benchmark = None if benchmark_return is None else _number(benchmark_return, "benchmark_return")
        provenance = _provenance(source_authority, source_checksum)
        with self._lock, self._file_lock():
            events = self._read_events()
            self._require_open(self._replay(events))
            self._append(
                "position_marked",
                {
                    "instrument_id": _clean_id(instrument_id, "instrument_id").upper(),
                    "price": price,
                    "fx_rate": fx,
                    "price_basis": "adjusted_close",
                    "benchmark_return": benchmark,
                    **provenance,
                },
                occurred_at=occurred_at,
            )
            events = self._read_events()
            return self._snapshot(events, self._replay(events))

    def apply_corporate_action(
        self,
        instrument_id: str,
        *,
        action_id: str | None = None,
        split_ratio: float,
        cash_dividend_per_unit: float = 0.0,
        source_authority: str = "local_manual_corporate_action",
        source_checksum: str = "",
        fx_rate: float = 1.0,
        occurred_at: datetime | None = None,
    ) -> PaperAccountSnapshot:
        ratio = _positive(split_ratio, "split_ratio")
        dividend_decimal = _decimal_number(cash_dividend_per_unit, "cash_dividend_per_unit", non_negative=True)
        dividend_fx_decimal = _decimal_number(fx_rate, "fx_rate", positive=True)
        provenance = _provenance(source_authority, source_checksum)
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            action_key = _clean_id(action_id, "action_id") if action_id is not None else "action_" + _digest(
                {
                    "instrument_id": instrument_id, "split_ratio": ratio,
                    "cash_dividend_per_unit": float(dividend_decimal),
                    "source_checksum": provenance["source_checksum"],
                }
            )[:20]
            if action_key in state["corporate_actions"]:
                existing = state["corporate_actions"][action_key]
                same_terms = (
                    _decimal_number(existing.get("split_ratio"), "split_ratio") == _decimal_number(ratio, "split_ratio")
                    and _decimal_number(existing.get("cash_dividend_per_unit"), "cash_dividend_per_unit") == dividend_decimal
                    and _decimal_number(existing.get("fx_rate", 1.0), "fx_rate") == dividend_fx_decimal
                    and existing.get("instrument_id") == _clean_id(instrument_id, "instrument_id").upper()
                    and existing.get("source_checksum") == provenance["source_checksum"]
                )
                if not same_terms:
                    raise PaperLedgerError("The corporate action ID was already used with different terms.")
                return self._snapshot(events, state)
            self._append(
                "corporate_action",
                {
                    "action_id": action_key,
                    "instrument_id": _clean_id(instrument_id, "instrument_id").upper(),
                    "split_ratio": ratio,
                    "cash_dividend_per_unit": str(dividend_decimal),
                    "fx_rate": str(dividend_fx_decimal),
                    **provenance,
                },
                occurred_at=occurred_at,
            )
            events = self._read_events()
            return self._snapshot(events, self._replay(events))

    def reconcile(self) -> dict[str, object]:
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            snapshot = self._snapshot(events, state)
            return {
                "status": snapshot.reconciliation_status if state["opened"] else "unavailable",
                "account_id": self.account_id,
                "event_count": len(events),
                "ledger_hash": snapshot.ledger_hash,
                "equity": snapshot.equity,
                "cash": snapshot.cash,
                "execution_allowed": False,
                "message": snapshot.message,
            }

    def snapshot(self) -> PaperAccountSnapshot:
        with self._lock, self._file_lock():
            events = self._read_events()
            return self._snapshot(events, self._replay(events))

    def orders(self) -> tuple[dict[str, object], ...]:
        with self._lock, self._file_lock():
            state = self._replay(self._read_events())
            return tuple(dict(item) for item in state["orders"].values())

    def trade_rows(self) -> tuple[dict[str, object], ...]:
        """Return fill rows suitable for the existing Instrument Detail panel."""

        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            orders = state["orders"]
            assert isinstance(orders, dict)
            rows: list[dict[str, object]] = []
            for event in events:
                if event["event_type"] != "fill_recorded" or not isinstance(event["payload"], Mapping):
                    continue
                fill = event["payload"]
                order = orders.get(str(fill.get("order_id")), {})
                rows.append(
                    {
                        "instrument_id": str(fill.get("instrument_id", "")),
                        "paper_trade_id": str(fill.get("fill_id", "")),
                        "order_id": str(fill.get("order_id", "")),
                        "status": str(order.get("status", "unknown")),
                        "side": str(fill.get("side", "")),
                        "quantity": float(fill.get("quantity", 0.0)),
                        "price": float(fill.get("price", 0.0)),
                        "fee": float(fill.get("fee", 0.0)),
                        "currency": str(fill.get("currency", state["base_currency"])),
                        "price_basis": str(fill.get("price_basis", "execution_quote")),
                        "as_of": str(event.get("occurred_at", "")),
                        "source_authority": "local_paper_ledger",
                        "execution_allowed": False,
                    }
                )
            return tuple(rows)

    def timeline_rows(self, instrument_id: str) -> tuple[dict[str, object], ...]:
        """Project the validated lifecycle history for one instrument.

        This is intentionally a read-only projection.  It reads one event
        list, replays that same list for lifecycle validation, and never
        acquires the write lock or repairs the ledger.  Proposal decisions
        resolve their instrument from the frozen proposal snapshot; fills and
        cancellations resolve it from the accepted order.
        """

        requested = str(instrument_id).strip()
        if not requested:
            raise PaperLedgerIntegrityError("An instrument ID is required for paper timeline projection.")
        events = self._read_events()
        state = self._replay(events)
        orders = state["orders"]
        assert isinstance(orders, dict)
        requested_key = requested.upper()
        rows: list[dict[str, object]] = []
        event_orders: dict[str, dict[str, object]] = {}

        def text_id(value: object, field: str) -> str:
            result = str(value or "").strip()
            if not result:
                raise PaperLedgerIntegrityError(f"Paper timeline event is missing {field}.")
            return result

        def frozen_snapshot(payload: Mapping[str, object]) -> Mapping[str, object]:
            snapshot = payload.get("proposal_snapshot")
            if not isinstance(snapshot, Mapping):
                raise PaperLedgerIntegrityError("Paper timeline proposal decision has no frozen proposal snapshot.")
            proposal_id = text_id(payload.get("proposal_id"), "proposal_id")
            if text_id(snapshot.get("proposal_id"), "proposal_snapshot.proposal_id") != proposal_id:
                raise PaperLedgerIntegrityError("Paper timeline proposal decision has a contradictory proposal association.")
            text_id(snapshot.get("instrument_id"), "proposal_snapshot.instrument_id")
            return snapshot

        def frozen_run_id(snapshot: Mapping[str, object]) -> str | object:
            value = snapshot.get("run_id")
            return value if isinstance(value, str) and value.strip() else "unavailable"

        def base_event(event: Mapping[str, object], payload: Mapping[str, object]) -> dict[str, object]:
            return {
                "schema_version": event.get("schema_version"),
                "account_id": event.get("account_id"),
                "sequence": event.get("sequence"),
                "event_sequence": event.get("sequence"),
                "event_id": event.get("event_id"),
                "event_hash": event.get("event_hash"),
                "prior_event_hash": event.get("prior_event_hash"),
                "occurred_at": event.get("occurred_at"),
                "event_type": event.get("event_type"),
                "source_authority": "local_paper_ledger",
                "execution_allowed": False,
                "payload": _json_copy(payload),
            }

        for event in events:
            kind = event.get("event_type")
            payload = event.get("payload")
            if kind not in {"proposal_rejected", "proposal_deferred", "order_accepted", "fill_recorded", "order_cancelled"}:
                continue
            if not isinstance(payload, Mapping):
                raise PaperLedgerIntegrityError("Paper timeline event payload is not an object.")

            row = base_event(event, payload)
            instrument: str
            proposal_snapshot: Mapping[str, object] | None = None
            order_id: str | None = None
            if kind in {"proposal_rejected", "proposal_deferred"}:
                proposal_snapshot = frozen_snapshot(payload)
                instrument = text_id(proposal_snapshot.get("instrument_id"), "proposal_snapshot.instrument_id")
                if instrument.upper() != requested_key:
                    continue
                row.update(
                    {
                        "instrument_id": instrument,
                        "proposal_id": text_id(payload.get("proposal_id"), "proposal_id"),
                        "rejection_id" if kind == "proposal_rejected" else "deferred_id": text_id(
                            payload.get("rejection_id" if kind == "proposal_rejected" else "deferred_id"),
                            "rejection_id" if kind == "proposal_rejected" else "deferred_id",
                        ),
                        "reason": text_id(payload.get("reason"), "reason"),
                        "proposal_evidence_hashes": _json_copy(payload.get("proposal_evidence_hashes")),
                        "run_id": frozen_run_id(proposal_snapshot),
                        "status": "rejected" if kind == "proposal_rejected" else "deferred",
                    }
                )
            elif kind == "order_accepted":
                order_id = text_id(payload.get("order_id"), "order_id")
                order = orders.get(order_id)
                if not isinstance(order, Mapping):
                    raise PaperLedgerIntegrityError("Paper timeline accepted order is missing from replay state.")
                instrument = text_id(payload.get("instrument_id"), "instrument_id")
                proposal_snapshot = frozen_snapshot(payload)
                snapshot_instrument = text_id(proposal_snapshot.get("instrument_id"), "proposal_snapshot.instrument_id")
                if snapshot_instrument.upper() != instrument.upper():
                    raise PaperLedgerIntegrityError("Paper timeline order has contradictory instrument associations.")
                event_orders[order_id] = {
                    "remaining_quantity": float(payload.get("quantity", 0.0)),
                    "status": str(payload.get("status", "accepted")),
                }
                if instrument.upper() != requested_key:
                    continue
                row.update(
                    {
                        "instrument_id": instrument,
                        "proposal_id": text_id(payload.get("proposal_id"), "proposal_id"),
                        "order_id": order_id,
                        "side": payload.get("side"),
                        "quantity": payload.get("quantity"),
                        "status": payload.get("status", "accepted"),
                        "proposal_evidence_hashes": _json_copy(payload.get("proposal_evidence_hashes")),
                        "run_id": frozen_run_id(proposal_snapshot),
                    }
                )
            elif kind == "fill_recorded":
                order_id = text_id(payload.get("order_id"), "order_id")
                order = orders.get(order_id)
                if not isinstance(order, Mapping):
                    raise PaperLedgerIntegrityError("Paper timeline fill references an unknown order.")
                instrument = text_id(order.get("instrument_id"), "order.instrument_id")
                fill_instrument = text_id(payload.get("instrument_id"), "instrument_id")
                if fill_instrument.upper() != instrument.upper():
                    raise PaperLedgerIntegrityError("Paper timeline fill has contradictory instrument associations.")
                if instrument.upper() != requested_key:
                    continue
                snapshot = order.get("proposal_snapshot")
                if not isinstance(snapshot, Mapping):
                    raise PaperLedgerIntegrityError("Paper timeline order has no frozen proposal snapshot.")
                event_order = event_orders.get(order_id)
                if event_order is None:
                    raise PaperLedgerIntegrityError("Paper timeline fill precedes its accepted order.")
                remaining = float(event_order["remaining_quantity"]) - float(payload.get("quantity", 0.0))
                event_status = "filled" if remaining <= 1e-8 else "partially_filled"
                event_order.update({"remaining_quantity": remaining, "status": event_status})
                row.update(
                    {
                        "instrument_id": instrument,
                        "proposal_id": text_id(order.get("proposal_id"), "proposal_id"),
                        "order_id": order_id,
                        "fill_id": text_id(payload.get("fill_id"), "fill_id"),
                        "paper_trade_id": text_id(payload.get("fill_id"), "fill_id"),
                        "side": payload.get("side"),
                        "quantity": payload.get("quantity"),
                        "price": payload.get("price"),
                        "fee": payload.get("fee"),
                        "status": event_status,
                        "event_time_status": event_status,
                        "current_order_status": order.get("status", "unknown"),
                        "proposal_evidence_hashes": _json_copy(order.get("proposal_evidence_hashes")),
                        "run_id": frozen_run_id(snapshot),
                    }
                )
            else:  # order_cancelled
                order_id = text_id(payload.get("order_id"), "order_id")
                order = orders.get(order_id)
                if not isinstance(order, Mapping):
                    raise PaperLedgerIntegrityError("Paper timeline cancellation references an unknown order.")
                instrument = text_id(order.get("instrument_id"), "order.instrument_id")
                if payload.get("instrument_id") is not None and text_id(payload.get("instrument_id"), "instrument_id").upper() != instrument.upper():
                    raise PaperLedgerIntegrityError("Paper timeline cancellation has contradictory instrument associations.")
                if instrument.upper() != requested_key:
                    continue
                snapshot = order.get("proposal_snapshot")
                if not isinstance(snapshot, Mapping):
                    raise PaperLedgerIntegrityError("Paper timeline order has no frozen proposal snapshot.")
                event_order = event_orders.get(order_id)
                if event_order is None:
                    raise PaperLedgerIntegrityError("Paper timeline cancellation precedes its accepted order.")
                event_order["status"] = "cancelled"
                row.update(
                    {
                        "instrument_id": instrument,
                        "proposal_id": text_id(order.get("proposal_id"), "proposal_id"),
                        "order_id": order_id,
                        "reason": text_id(payload.get("reason"), "reason"),
                        "status": "cancelled",
                        "event_time_status": "cancelled",
                        "current_order_status": order.get("status", "unknown"),
                        "proposal_evidence_hashes": _json_copy(order.get("proposal_evidence_hashes")),
                        "run_id": frozen_run_id(snapshot),
                    }
                )
            rows.append(row)
        return tuple(rows)

    def _append(self, event_type: str, payload: Mapping[str, object], *, occurred_at: datetime | None) -> None:
        events = self._read_events()
        sequence = len(events) + 1
        prior_hash = str(events[-1]["event_hash"]) if events else "0" * 64
        event = {
            "schema_version": PAPER_SCHEMA_VERSION,
            "account_id": self.account_id,
            "sequence": sequence,
            "event_type": event_type,
            "occurred_at": _timestamp(occurred_at),
            "payload": _json_copy(payload),
            "prior_event_hash": prior_hash,
        }
        event["event_id"] = "paper_event_" + _digest(event)[:20]
        event["event_hash"] = _digest(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _order_lifecycle(self) -> OrderLifecycle:
        if self._lifecycle is None:
            lifecycle_path = self.path.with_name("order_lifecycle.sqlite3")
            config_dir = self.root / "configs"
            if not (config_dir / "settlement_v1.yaml").exists():
                config_dir = CONFIG_DIR
            self._lifecycle = OrderLifecycle(
                lifecycle_path,
                self,
                settlement=load_settlement_config(config_dir),
            )
        return self._lifecycle

    def _recover_interrupted_fills(self) -> None:
        """Project every committed lifecycle fill absent from the paper ledger exactly once."""

        lifecycle = self._order_lifecycle()
        events = self._read_events()
        state = self._replay(events)
        recorded = {
            str(event["payload"].get("fill_id"))
            for event in events
            if event.get("event_type") == "fill_recorded" and isinstance(event.get("payload"), Mapping)
        }
        for lifecycle_event in lifecycle.fill_events():
            evidence = lifecycle_event.payload
            fill_id = str(evidence.get("fill_id", ""))
            if not fill_id or fill_id in recorded:
                continue
            order = state["orders"].get(lifecycle_event.order_id)
            if not isinstance(order, Mapping) or not order.get("lifecycle_idempotency_key"):
                raise PaperLedgerIntegrityError("A committed lifecycle fill has no matching paper order.")
            if lifecycle_event.event_type == "fill":
                quantity = evidence.get("quantity")
                price = evidence.get("price")
                fee = evidence.get("fee")
                fx_rate = evidence.get("fx_rate")
            else:
                quantity = evidence.get("fill_quantity")
                price = evidence.get("fill_price")
                fee = evidence.get("fill_fee")
                fx_rate = evidence.get("fill_fx_rate")
            fill = {
                "fill_id": fill_id,
                "order_id": lifecycle_event.order_id,
                "instrument_id": str(order["instrument_id"]),
                "side": str(order["side"]),
                "quantity": str(_decimal_number(quantity, "fill quantity", positive=True)),
                "price": str(_decimal_number(price, "fill price", positive=True)),
                "fee": str(_decimal_number(fee, "fill fee", non_negative=True)),
                "fx_rate": str(_decimal_number(fx_rate, "fill FX rate", positive=True)),
                "currency": str(order["currency"]),
                "price_basis": "execution_quote",
                "execution_allowed": False,
            }
            self._append("fill_recorded", fill, occurred_at=lifecycle_event.occurred_at)
            recorded.add(fill_id)
            events = self._read_events()
            state = self._replay(events)

    def _order_market_terms(self, proposal: Mapping[str, object], instrument_id: str) -> tuple[str | None, str | None]:
        venue_value = proposal.get("venue", proposal.get("exchange"))
        type_value = proposal.get("instrument_type")
        venue = str(venue_value).strip() if isinstance(venue_value, str) and venue_value.strip() else None
        instrument_type = str(type_value).strip() if isinstance(type_value, str) and type_value.strip() else None
        if venue is not None and instrument_type is not None:
            return venue, instrument_type
        try:
            config_dir = self.root / "configs"
            if not (config_dir / "universe.yaml").exists():
                config_dir = CONFIG_DIR
            configured = load_config(config_dir).universe.by_id().get(instrument_id)
        except Exception:
            configured = None
        if configured is not None:
            venue = venue or configured.exchange
            instrument_type = instrument_type or configured.instrument_type
        return venue, instrument_type

    def _record_lifecycle_fill(
        self,
        order: Mapping[str, object],
        *,
        fill_id: str,
        quantity: float,
        price: float,
        fee: float,
        fx_rate: float,
        occurred_at: datetime | None,
    ) -> None:
        try:
            self._order_lifecycle().record_fill(
                str(order["order_id"]),
                fill_id=fill_id,
                quantity=Decimal(str(quantity)),
                price=Decimal(str(price)),
                fee=Decimal(str(fee)),
                fx_rate=Decimal(str(fx_rate)),
                occurred_at=occurred_at,
            )
        except (OrderLifecycleError, CashReservationError) as exc:
            raise PaperLedgerError(str(exc)) from exc

    @contextmanager
    def _file_lock(self):
        """Serialise ledger critical sections across API instances/processes."""

        lock_path = self.path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_events(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            rows = self.path.read_bytes().splitlines()
        except OSError as exc:
            raise PaperLedgerIntegrityError(f"Paper ledger cannot be read: {exc}") from exc
        events: list[dict[str, object]] = []
        prior_hash = "0" * 64
        for index, row in enumerate(rows, start=1):
            try:
                payload = json.loads(row.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PaperLedgerIntegrityError(f"Paper ledger row {index} is malformed.") from exc
            if not isinstance(payload, dict):
                raise PaperLedgerIntegrityError(f"Paper ledger row {index} is not an object.")
            if payload.get("sequence") != index or payload.get("schema_version") != PAPER_SCHEMA_VERSION:
                raise PaperLedgerIntegrityError(f"Paper ledger row {index} has invalid identity.")
            if payload.get("account_id") != self.account_id:
                raise PaperLedgerIntegrityError(f"Paper ledger row {index} belongs to another account.")
            if payload.get("prior_event_hash") != prior_hash:
                raise PaperLedgerIntegrityError(f"Paper ledger hash chain breaks before row {index}.")
            event_hash = payload.get("event_hash")
            without_hash = {key: value for key, value in payload.items() if key != "event_hash"}
            if not isinstance(event_hash, str) or _digest(without_hash) != event_hash:
                raise PaperLedgerIntegrityError(f"Paper ledger row {index} has an invalid checksum.")
            events.append(payload)
            prior_hash = event_hash
        return events

    def _replay(self, events: list[dict[str, object]]) -> dict[str, object]:
        try:
            return self._replay_unchecked(events)
        except PaperLedgerIntegrityError:
            raise
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise PaperLedgerIntegrityError("Paper ledger payload is malformed and cannot be replayed safely.") from exc

    def _replay_unchecked(self, events: list[dict[str, object]]) -> dict[str, object]:
        state: dict[str, object] = {
            "opened": False,
            "base_currency": "EUR",
            "initial_cash": Decimal("0"),
            "cash": Decimal("0"),
            "equity_peak": 0.0,
            "orders": {},
            "rejections": {},
            "deferred": {},
            "corporate_actions": {},
            "fills": [],
            "outcomes": {},
            "operational_errors": [],
            "positions": {},
            "trade_pnls": [],
            "benchmark_return": None,
        }
        for event in events:
            kind = str(event["event_type"])
            payload = event["payload"]
            if not isinstance(payload, Mapping):
                raise PaperLedgerIntegrityError("Paper ledger event payload is not an object.")
            if kind == "account_opened":
                if state["opened"]:
                    raise PaperLedgerIntegrityError("Paper account was opened more than once.")
                state.update(
                    opened=True,
                    base_currency=str(payload["base_currency"]),
                    initial_cash=_decimal_number(payload["initial_cash"], "initial_cash", non_negative=True),
                    cash=_decimal_number(payload["initial_cash"], "initial_cash", non_negative=True),
                    equity_peak=float(payload["initial_cash"]),
                )
            elif not state["opened"]:
                raise PaperLedgerIntegrityError("Paper events precede account opening.")
            elif kind == "order_accepted":
                orders = state["orders"]
                assert isinstance(orders, dict)
                order_id = str(payload["order_id"])
                if order_id in orders:
                    raise PaperLedgerIntegrityError("A paper order was accepted twice.")
                _validate_frozen_evidence(payload.get("proposal_evidence_hashes"))
                if (
                    any(item.get("proposal_id") == payload.get("proposal_id") for item in orders.values())
                    or str(payload.get("proposal_id")) in state["rejections"]
                    or str(payload.get("proposal_id")) in state["deferred"]
                ):
                    raise PaperLedgerIntegrityError("A paper proposal has contradictory decisions.")
                orders[order_id] = dict(payload)
            elif kind == "proposal_rejected":
                rejections = state["rejections"]
                assert isinstance(rejections, dict)
                if any(item.get("proposal_id") == payload.get("proposal_id") for item in state["orders"].values()):
                    raise PaperLedgerIntegrityError("A paper proposal has contradictory decisions.")
                if str(payload.get("proposal_id")) in state["deferred"]:
                    raise PaperLedgerIntegrityError("A paper proposal has contradictory decisions.")
                _validate_frozen_evidence(payload.get("proposal_evidence_hashes"))
                rejections[str(payload["proposal_id"])] = dict(payload)
            elif kind == "proposal_deferred":
                deferred = state["deferred"]
                assert isinstance(deferred, dict)
                proposal_id = str(payload["proposal_id"])
                if (
                    proposal_id in deferred
                    or proposal_id in state["rejections"]
                    or any(item.get("proposal_id") == proposal_id for item in state["orders"].values())
                ):
                    raise PaperLedgerIntegrityError("A paper proposal has contradictory decisions.")
                _validate_frozen_evidence(payload.get("proposal_evidence_hashes"))
                deferred[proposal_id] = dict(payload)
            elif kind == "fill_recorded":
                self._apply_fill(state, payload)
            elif kind == "outcome_matured":
                outcomes = state["outcomes"]
                assert isinstance(outcomes, dict)
                outcome_id = str(payload["outcome_id"])
                outcome_key = (str(payload["order_id"]), int(payload.get("horizon_days", 20)))
                if outcome_id in outcomes or any(
                    (str(item.get("order_id")), int(item.get("horizon_days", 20))) == outcome_key
                    for item in outcomes.values()
                ):
                    raise PaperLedgerIntegrityError("A paper outcome was recorded twice.")
                try:
                    _provenance(payload.get("source_authority"), payload.get("source_checksum"))
                except PaperLedgerError as exc:
                    raise PaperLedgerIntegrityError("A paper outcome has invalid source provenance.") from exc
                outcomes[outcome_id] = dict(payload)
            elif kind == "operational_error":
                errors = state["operational_errors"]
                assert isinstance(errors, list)
                errors.append(dict(payload))
            elif kind == "order_cancelled":
                orders = state["orders"]
                assert isinstance(orders, dict)
                order = orders.get(str(payload["order_id"]))
                if order is None or order["status"] in {"filled", "cancelled"}:
                    raise PaperLedgerIntegrityError("A paper order cancellation is not valid.")
                order["status"] = "cancelled"
                order["cancellation_reason"] = str(payload["reason"])
            elif kind == "position_marked":
                instrument_id = str(payload["instrument_id"])
                positions = state["positions"]
                assert isinstance(positions, dict)
                position = positions.setdefault(instrument_id, {"quantity": 0.0, "average_cost": 0.0, "realised_pnl": 0.0, "currency": state["base_currency"]})
                position["mark_price"] = float(payload["price"])
                position["mark_fx_rate"] = float(payload["fx_rate"])
                try:
                    _provenance(payload.get("source_authority"), payload.get("source_checksum"))
                except PaperLedgerError as exc:
                    raise PaperLedgerIntegrityError("A paper mark has invalid source provenance.") from exc
                if payload.get("benchmark_return") is not None:
                    state["benchmark_return"] = float(payload["benchmark_return"])
            elif kind == "corporate_action":
                try:
                    _provenance(payload.get("source_authority"), payload.get("source_checksum"))
                except PaperLedgerError as exc:
                    raise PaperLedgerIntegrityError("A corporate action has invalid source provenance.") from exc
                actions = state["corporate_actions"]
                assert isinstance(actions, dict)
                action_id = str(payload.get("action_id", ""))
                if not action_id or action_id in actions:
                    raise PaperLedgerIntegrityError("A corporate action is missing a unique action ID.")
                actions[action_id] = dict(payload)
                self._apply_corporate_action(state, payload)
            else:
                raise PaperLedgerIntegrityError(f"Unsupported paper event type: {kind}")
            _update_equity_peak(state)
        return state

    @staticmethod
    def _apply_fill(state: dict[str, object], payload: Mapping[str, object]) -> None:
        orders = state["orders"]
        positions = state["positions"]
        assert isinstance(orders, dict) and isinstance(positions, dict)
        order = orders.get(str(payload["order_id"]))
        if order is None or order["status"] in {"filled", "cancelled"}:
            raise PaperLedgerIntegrityError("A paper fill references an invalid order.")
        quantity_decimal = _decimal_number(payload["quantity"], "quantity", positive=True)
        quantity = float(quantity_decimal)
        price_decimal = _decimal_number(payload["price"], "price", positive=True)
        fee_decimal = _decimal_number(payload["fee"], "fee", non_negative=True)
        fx_decimal = _decimal_number(payload["fx_rate"], "fx_rate", positive=True)
        value_decimal = quantity_decimal * price_decimal * fx_decimal
        value = float(value_decimal)
        fee = float(fee_decimal)
        instrument_id = str(order["instrument_id"])
        position = positions.setdefault(instrument_id, {"quantity": 0.0, "average_cost": 0.0, "realised_pnl": 0.0, "currency": order["currency"]})
        if quantity <= 0 or quantity > float(order["remaining_quantity"]) + 1e-8:
            raise PaperLedgerIntegrityError("A paper fill quantity is invalid.")
        if order["side"] == "buy":
            state["cash"] = state["cash"] - value_decimal - fee_decimal
            old_quantity = float(position["quantity"])
            total_cost = old_quantity * float(position["average_cost"]) + value + fee
            position["quantity"] = old_quantity + quantity
            position["average_cost"] = total_cost / position["quantity"]
        else:
            if float(position["quantity"]) + 1e-8 < quantity:
                raise PaperLedgerIntegrityError("A paper sell fill exceeds the position.")
            state["cash"] = state["cash"] + value_decimal - fee_decimal
            realised = value - fee - quantity * float(position["average_cost"])
            position["quantity"] = float(position["quantity"]) - quantity
            position["realised_pnl"] = float(position.get("realised_pnl", 0.0)) + realised
            trade_pnls = state["trade_pnls"]
            assert isinstance(trade_pnls, list)
            trade_pnls.append(realised)
            if position["quantity"] <= 1e-8:
                position["quantity"] = 0.0
                position["average_cost"] = 0.0
        order["filled_quantity"] = float(order["filled_quantity"]) + quantity
        order["remaining_quantity"] = float(order["remaining_quantity"]) - quantity
        order["status"] = "filled" if order["remaining_quantity"] <= 1e-8 else "partially_filled"
        fills = state["fills"]
        assert isinstance(fills, list)
        if any(str(item.get("fill_id")) == str(payload.get("fill_id")) for item in fills if isinstance(item, Mapping)):
            raise PaperLedgerIntegrityError("A paper fill ID was recorded twice.")
        fills.append(dict(payload))

    @staticmethod
    def _apply_corporate_action(state: dict[str, object], payload: Mapping[str, object]) -> None:
        positions = state["positions"]
        assert isinstance(positions, dict)
        position = positions.get(str(payload["instrument_id"]))
        if position is None:
            return
        ratio = float(payload["split_ratio"])
        dividend = _decimal_number(payload["cash_dividend_per_unit"], "cash_dividend_per_unit", non_negative=True)
        position["quantity"] = float(position["quantity"]) * ratio
        position["average_cost"] = float(position["average_cost"]) / ratio
        if position.get("mark_price") is not None:
            position["mark_price"] = float(position["mark_price"]) / ratio
        state["cash"] = state["cash"] + (
            Decimal(str(float(position["quantity"]) / ratio))
            * dividend
            * _decimal_number(payload.get("fx_rate", 1.0), "fx_rate", positive=True)
        )

    @staticmethod
    def _require_open(state: Mapping[str, object]) -> None:
        if not state.get("opened"):
            raise PaperLedgerError("Open the local paper account before submitting paper activity.")

    def _require_order_pipeline_open(self) -> None:
        from etf_cockpit.trading.incidents import (
            IncidentJournal,
            IncidentJournalError,
            IncidentJournalIntegrityError,
        )

        try:
            frozen = IncidentJournal(self.root, account_id=self.account_id).is_frozen
        except IncidentJournalIntegrityError as exc:
            raise PaperLedgerIntegrityError("The operational incident journal is invalid.") from exc
        except IncidentJournalError as exc:
            raise PaperLedgerError(str(exc)) from exc
        if frozen:
            raise PaperLedgerError("The paper order pipeline is frozen until clean reconciliation.")

    def _reconciliation_state(self, state: Mapping[str, object]) -> dict[str, object]:
        orders = state["orders"]
        positions = state["positions"]
        assert isinstance(orders, Mapping) and isinstance(positions, Mapping)
        return {
            "account_id": self.account_id,
            "cash": round(float(state["cash"]), 8),
            "orders": [
                {
                    "order_id": str(order_id),
                    "status": str(order.get("status", "unknown")),
                    "filled_quantity": round(float(order.get("filled_quantity", 0.0)), 8),
                    "remaining_quantity": round(float(order.get("remaining_quantity", 0.0)), 8),
                }
                for order_id, order in sorted(orders.items())
            ],
            "positions": [
                {
                    "instrument_id": str(instrument_id),
                    "quantity": round(float(position.get("quantity", 0.0)), 8),
                    "average_cost": round(float(position.get("average_cost", 0.0)), 8),
                }
                for instrument_id, position in sorted(positions.items())
                if float(position.get("quantity", 0.0)) > 1e-8
            ],
        }

    def _validate_proposal(self, proposal: Mapping[str, object]) -> None:
        self._validate_proposal_identity(proposal)
        if proposal.get("execution_allowed") is not False:
            raise PaperLedgerError("Paper activity requires execution_allowed=false.")
        if proposal.get("proposal_allowed") is not True or proposal.get("outcome") != "proposal_ready":
            raise PaperLedgerError("Only a proposal-ready, gate-approved proposal can enter the paper ledger.")
        if str(proposal.get("authority_stage")) not in {"shadow_proposal", "paper"}:
            raise PaperLedgerError("The proposal authority stage cannot enter the paper ledger.")
        gates = proposal.get("gates")
        from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES

        gate_ids = {str(item.get("gate_id")) for item in gates if isinstance(item, Mapping)} if isinstance(gates, list) else set()
        if not isinstance(gates, list) or not gates or set(REQUIRED_GATES) - gate_ids or any(not isinstance(item, Mapping) or item.get("passed") is not True for item in gates):
            raise PaperLedgerError("Every proposal gate must pass before paper acceptance.")
        expires_at = proposal.get("expires_at")
        if not isinstance(expires_at, str):
            raise PaperLedgerError("Proposal expiry is missing.")
        try:
            if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                raise PaperLedgerError("The proposal has expired.")
        except ValueError as exc:
            raise PaperLedgerError("Proposal expiry is malformed.") from exc

    @staticmethod
    def _validate_proposal_identity(proposal: Mapping[str, object]) -> None:
        if proposal.get("schema_version") != "proposal.v1":
            raise PaperLedgerError("The proposal schema is unsupported.")
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        input_checksum = str(proposal.get("input_checksum", "")).strip()
        input_material = proposal.get("input_material")
        decision_checksum = str(proposal.get("decision_checksum", "")).strip()
        if not proposal_id or len(input_checksum) != 64 or not isinstance(input_material, Mapping):
            raise PaperLedgerError("The proposal identity is incomplete.")
        if proposal_id != f"proposal_{input_checksum[:20]}" or _digest(input_material) != input_checksum:
            raise PaperLedgerError("The proposal input checksum is invalid.")
        if len(decision_checksum) != 64:
            raise PaperLedgerError("The proposal decision checksum is missing.")
        without_decision_checksum = {key: value for key, value in proposal.items() if key != "decision_checksum"}
        if _digest(without_decision_checksum) != decision_checksum:
            raise PaperLedgerError("The proposal decision checksum is invalid.")

    def _snapshot(self, events: list[dict[str, object]], state: dict[str, object]) -> PaperAccountSnapshot:
        positions_state = state["positions"]
        assert isinstance(positions_state, dict)
        positions: list[PaperPosition] = []
        market_value = 0.0
        unrealised = 0.0
        for instrument_id, raw in sorted(positions_state.items()):
            quantity = float(raw.get("quantity", 0.0))
            if quantity <= 1e-8:
                continue
            mark_price = raw.get("mark_price")
            mark_fx = float(raw.get("mark_fx_rate", 1.0))
            position_unrealised = None if mark_price is None else (float(mark_price) * mark_fx - float(raw["average_cost"])) * quantity
            if position_unrealised is not None:
                market_value += float(mark_price) * mark_fx * quantity
                unrealised += position_unrealised
            positions.append(
                PaperPosition(
                    instrument_id=instrument_id,
                    quantity=quantity,
                    average_cost=float(raw["average_cost"]),
                    mark_price=None if mark_price is None else float(mark_price),
                    mark_fx_rate=mark_fx,
                    currency=str(raw.get("currency", state["base_currency"])),
                    realised_pnl=float(raw.get("realised_pnl", 0.0)),
                    unrealised_pnl=position_unrealised,
                )
            )
        cash = float(state["cash"])
        equity = cash + market_value
        initial_cash = float(state["initial_cash"])
        pnl = equity - initial_cash
        trade_pnls = [float(value) for value in state["trade_pnls"]]
        wins = [value for value in trade_pnls if value > 0]
        losses = [value for value in trade_pnls if value < 0]
        win_rate = None if not trade_pnls else len(wins) / len(trade_pnls)
        payoff_ratio = None if not wins or not losses else sum(wins) / abs(sum(losses))
        peak = max(initial_cash, float(state.get("equity_peak", initial_cash)))
        drawdown = None if peak <= 0 else (equity - peak) / peak
        try:
            from etf_cockpit.trading.incidents import IncidentJournal

            journal = IncidentJournal(self.root, account_id=self.account_id)
            frozen = journal.is_frozen
        except (OSError, ValueError):
            frozen = True
        return PaperAccountSnapshot(
            account_id=self.account_id,
            base_currency=str(state["base_currency"]),
            status="ready" if state["opened"] else "unavailable",
            cash=cash,
            equity=equity,
            pnl=pnl,
            benchmark_return=None if state["benchmark_return"] is None else float(state["benchmark_return"]),
            drawdown=drawdown,
            open_positions=len(positions),
            closed_trades=len(trade_pnls),
            win_rate=win_rate,
            payoff_ratio=payoff_ratio,
            positions=tuple(positions),
            order_count=len(state["orders"]),
            event_count=len(events),
            ledger_hash="" if not events else str(events[-1]["event_hash"]),
            reconciliation_status="frozen" if frozen else "ready",
            message=(
                "Paper order pipeline frozen until clean reconciliation; execution_allowed=false."
                if frozen
                else "Local paper simulation only; execution_allowed=false."
            ),
            matured_outcomes=len(state["outcomes"]),
            operational_incidents=len(state["operational_errors"]),
        )


def _update_equity_peak(state: dict[str, object]) -> None:
    positions = state.get("positions")
    if not isinstance(positions, Mapping):
        return
    marked_value = 0.0
    for position in positions.values():
        if not isinstance(position, Mapping) or position.get("mark_price") is None:
            continue
        marked_value += float(position.get("quantity", 0.0)) * float(position["mark_price"]) * float(position.get("mark_fx_rate", 1.0))
    equity = float(state.get("cash", 0.0)) + marked_value
    state["equity_peak"] = max(float(state.get("equity_peak", 0.0)), equity)


def _provenance(source_authority: object, source_checksum: object) -> dict[str, str]:
    authority = _clean_id(source_authority, "source_authority")
    checksum = str(source_checksum or "").strip().lower()
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        raise PaperLedgerError("A 64-character source checksum is required for paper marks and corporate actions.")
    return {"source_authority": authority, "source_checksum": checksum}


def _clean_id(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PaperLedgerError(f"{label} must not be blank.")
    if len(text) > 128 or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text or _is_reserved_windows_name(text):
        raise PaperLedgerError(f"{label} contains an unsafe identifier.")
    return text


def _bounded_text(value: object, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise PaperLedgerError(f"{label} must not be blank.")
    if len(text) > maximum:
        raise PaperLedgerError(f"{label} must be at most {maximum} characters.")
    return text


def _number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PaperLedgerError(f"{label} must be numeric.") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise PaperLedgerError(f"{label} must be finite.")
    return number


def _decimal_number(
    value: object,
    label: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> Decimal:
    if isinstance(value, bool):
        raise PaperLedgerError(f"{label} must be numeric.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise PaperLedgerError(f"{label} must be numeric.") from exc
    if not number.is_finite():
        raise PaperLedgerError(f"{label} must be finite.")
    if positive and number <= 0:
        raise PaperLedgerError(f"{label} must be greater than zero.")
    if non_negative and number < 0:
        raise PaperLedgerError(f"{label} must not be negative.")
    return number


def _positive(value: object, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise PaperLedgerError(f"{label} must be greater than zero.")
    return number


def _non_negative(value: object, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise PaperLedgerError(f"{label} must not be negative.")
    return number


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    aware = current if current.tzinfo is not None else current.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _json_copy(value: object) -> object:
    try:
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    except (TypeError, ValueError) as exc:
        raise PaperLedgerError("Paper evidence must be JSON serialisable.") from exc


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _is_reserved_windows_name(value: str) -> bool:
    stem = value.rstrip(" .").split(".", 1)[0].upper()
    return stem in {"CON", "PRN", "AUX", "NUL"} or (
        len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789"
    )


def _freeze_proposal_evidence(proposal: Mapping[str, object]) -> dict[str, str]:
    """Derive stable, immutable evidence hashes from the proposal manifest."""

    groups = {
        "data": ("data_checksum", "data_revision", "input_checksum"),
        "formula": ("formula_checksum", "formula_version", "strategy_id"),
        "model": ("model_checksum", "model_revision", "model_id"),
        "portfolio": ("portfolio_checksum", "portfolio_revision", "account_id"),
        "policy": (
            "policy_checksum",
            "authority_policy_checksum",
            "gate_policy_checksum",
            "policy_version",
            "gate_policy_version",
        ),
    }
    frozen: dict[str, str] = {}
    for name, fields in groups.items():
        values = {field: proposal.get(field) for field in fields if proposal.get(field) is not None}
        explicit = next(
            (str(values[field]).lower() for field in fields if field.endswith("checksum") and _is_checksum(str(values.get(field, "")))),
            None,
        )
        frozen[name] = explicit or _digest({"evidence_type": name, "fields": fields, "values": values})
    return frozen


def _validate_frozen_evidence(value: object) -> None:
    if value is None:
        return  # Backward-compatible replay for ISSUE-0031 ledger rows.
    if not isinstance(value, Mapping) or set(value) != {"data", "formula", "model", "portfolio", "policy"}:
        raise PaperLedgerIntegrityError("Frozen paper proposal evidence is incomplete.")
    if any(not isinstance(item, str) or not _is_checksum(item) for item in value.values()):
        raise PaperLedgerIntegrityError("Frozen paper proposal evidence has an invalid checksum.")


def _is_checksum(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _incident_requires_freeze(code: str) -> bool:
    return code.strip().lower() in {"unknown_state", "order_state_unknown", "disconnect", "order_break"}


def load_proposal_for_paper(root: Path, proposal_id: str) -> dict[str, object]:
    """Load one validated proposal record for an explicit paper action."""

    from etf_cockpit.portfolio.proposal_policy import load_proposal_records

    expected = _clean_id(proposal_id, "proposal_id")
    for proposal in load_proposal_records(directory=root / "data" / "operations" / "proposals"):
        if proposal.get("proposal_id") == expected:
            return proposal
    raise PaperLedgerError(f"Validated proposal not found: {expected}")


__all__ = [
    "EXECUTION_ALLOWED",
    "NETWORK_ACCESS_ALLOWED",
    "PAPER_SCHEMA_VERSION",
    "PaperAccountSnapshot",
    "PaperLedger",
    "PaperLedgerError",
    "PaperLedgerIntegrityError",
    "PaperPosition",
    "load_proposal_for_paper",
]
