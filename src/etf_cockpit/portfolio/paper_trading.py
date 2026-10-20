"""Local, append-only paper account ledger for ISSUE-0129.

The ledger is a simulation and evidence store, not a broker adapter.  It only
accepts a proposal that has already passed the non-executable proposal policy,
keeps the proposal snapshot immutable, and replays its hash-chained JSONL log
to derive cash, positions and performance after a restart.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Literal, Mapping

import pandas as pd

from etf_cockpit.core.config import load_config, load_settlement_config
from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.portfolio.benchmark_reference import (
    VWCE_QUOTE_CURRENCY,
    VwceReferenceSeriesCheck,
    vwce_series_source_hash,
)
from etf_cockpit.portfolio.valuation import build_daily_portfolio_snapshots
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
MIN_QUANTITY = Decimal("0.00000001")


class PaperLedgerError(ValueError):
    """A user-correctable paper-ledger request or integrity failure."""


class PaperLedgerIntegrityError(PaperLedgerError):
    """The append-only ledger cannot be trusted and must remain read-only."""


SHADOW_ACCOUNT_TYPE = "benchmark_shadow_account"
_SHADOW_FLOW_KINDS = ("contribution", "withdrawal")


@dataclass(frozen=True)
class ShadowCostPolicy:
    """Costs and lot policy a benchmark shadow account shares with the active account it mirrors.

    ``commission`` is a flat fee per trade in the account base currency; ``adverse_bps`` is the combined
    spread and slippage applied against the trade price; ``lot_size`` is the smallest tradable quantity step
    (``1`` for whole units). The same instance (compared by digest) must drive both accounts.
    """

    commission: Decimal = Decimal("0")
    adverse_bps: Decimal = Decimal("0")
    lot_size: Decimal = MIN_QUANTITY

    def __post_init__(self) -> None:
        object.__setattr__(self, "commission", _decimal_number(self.commission, "commission", non_negative=True))
        object.__setattr__(self, "adverse_bps", _decimal_number(self.adverse_bps, "adverse_bps", non_negative=True))
        object.__setattr__(self, "lot_size", _decimal_number(self.lot_size, "lot_size", positive=True))

    def to_payload(self) -> dict[str, str]:
        return {
            "commission": format(self.commission.normalize(), "f"),
            "adverse_bps": format(self.adverse_bps.normalize(), "f"),
            "lot_size": format(self.lot_size.normalize(), "f"),
        }

    def digest(self) -> str:
        return _digest(self.to_payload())


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
    equity: float | None
    pnl: float | None
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
            "equity": None if self.equity is None else round(self.equity, 8),
            "pnl": None if self.pnl is None else round(self.pnl, 8),
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
        cost_policy: ShadowCostPolicy | None = None,
        occurred_at: datetime | None = None,
    ) -> PaperAccountSnapshot:
        if cost_policy is not None and (not isinstance(cost_policy, ShadowCostPolicy) or base_currency != "EUR" or initial_cash != 0):
            raise PaperLedgerError("Matched active accounts require explicit policy, EUR and zero opening cash; record external flows separately.")
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
                {"initial_cash": str(cash), "base_currency": currency, **({"cost_policy": cost_policy.to_payload(), "cost_policy_digest": cost_policy.digest()} if cost_policy is not None else {})},
                occurred_at=occurred_at,
            )
            events = self._read_events()
            return self._snapshot(events, self._replay(events))

    def record_external_flow(
        self, *, flow_id: str, kind: Literal["contribution", "withdrawal"], amount: object,
        flow_at: datetime, source_authority: str, source_checksum: str, effective_at: datetime | None = None,
    ) -> dict[str, object]:
        """Record canonical active-account cash evidence in the existing append-only ledger."""
        if kind not in _SHADOW_FLOW_KINDS or not isinstance(flow_at, datetime) or flow_at.tzinfo is None:
            raise PaperLedgerError("External flows require a supported kind and aware effective time.")
        effective = effective_at or flow_at
        if effective.tzinfo is None or effective < flow_at or (kind == "contribution" and effective != flow_at):
            raise PaperLedgerError("Active flow effective time must be aware and cannot precede its request.")
        payload = {"flow_id": _clean_id(flow_id, "flow_id"), "flow_kind": kind,
                   "amount": str(_decimal_number(amount, "amount", positive=True)), "flow_at": _timestamp(flow_at), "effective_at": _timestamp(effective),
                   **_provenance(source_authority, source_checksum), "execution_allowed": False}
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            if state["shadow"] is not None or state["cost_policy"] is None:
                raise PaperLedgerError("Canonical active flows require an active account with an explicit cost policy.")
            existing = state["external_flows"].get(payload["flow_id"])
            if existing is not None:
                if existing != payload:
                    raise PaperLedgerError("The active flow was already recorded with different terms.")
                return dict(existing)
            if any(_event_time(event) > effective for event in events):
                raise PaperLedgerError("Backdated active flows are unsupported.")
            if kind == "withdrawal" and state["cash"] < Decimal(payload["amount"]):
                raise PaperLedgerError("The active withdrawal exceeds available cash.")
            self._append("external_flow_recorded", payload, occurred_at=effective)
            return payload

    def external_flows(self) -> tuple[dict[str, object], ...]:
        """Return the recorded external cash flows (oldest first) with the time each was recorded."""

        with self._lock:
            return tuple(
                {**dict(event["payload"]), "recorded_at": str(event["occurred_at"])}
                for event in self._read_events()
                if event.get("event_type") == "external_flow_recorded" and isinstance(event.get("payload"), Mapping)
            )

    def cash_balance(self, *, account_id: str, currency: str, as_of: datetime) -> Decimal:
        """Expose the simulated account cash projection to the reservation service."""

        if account_id != self.account_id:
            raise PaperLedgerError("Cash balance requested for a different paper account.")
        if not isinstance(as_of, datetime) or as_of.tzinfo is None:
            raise PaperLedgerError("A timezone-aware cash-balance time is required.")
        with self._lock:
            state = self._replay(self._events_through(as_of))
            self._require_open(state)
            if str(state["base_currency"]).upper() != currency.upper():
                raise PaperLedgerError("Paper cash is available only in the account base currency.")
            cash = state["cash"]
            if not isinstance(cash, Decimal):
                raise PaperLedgerIntegrityError("Paper cash projection is not an exact decimal.")
            return cash

    def projected_fill_ids(self, *, account_id: str, as_of: datetime) -> frozenset[str]:
        """Return the fills ``cash_balance`` at ``as_of`` contains, so unsettled cash is applied per fill."""

        if account_id != self.account_id:
            raise PaperLedgerError("Projected fills requested for a different paper account.")
        if not isinstance(as_of, datetime) or as_of.tzinfo is None:
            raise PaperLedgerError("A timezone-aware projection time is required.")
        with self._lock:
            return frozenset(
                str(event["payload"].get("fill_id"))
                for event in self._events_through(as_of)
                if event.get("event_type") == "fill_recorded" and isinstance(event.get("payload"), Mapping)
            )

    def confirmed_fill_ids(self, *, account_id: str, as_of: datetime) -> frozenset[str]:
        """Confirm actual paper cash postings from the same verified prefix as cash_balance.

        Paper cash posts at fill_recorded; settlement still governs when sale
        proceeds can be spent. A lifecycle-only fill is never confirmed here.
        """

        return self.projected_fill_ids(account_id=account_id, as_of=as_of)

    def _events_through(self, as_of: datetime) -> list[dict[str, object]]:
        """Return the log prefix up to the first event dated after ``as_of`` (shared by cash and fill projections).

        The ledger does not enforce monotonic ``occurred_at``, so both projections must cut the same prefix.
        """

        cutoff = as_of.astimezone(timezone.utc)
        events: list[dict[str, object]] = []
        for event in self._read_events():
            if _event_time(event) > cutoff:
                break
            events.append(event)
        return events

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
        fx_rate: float | None = None,
        decision_mode: Literal["manual_accept", "auto_paper"] = "manual_accept",
        occurred_at: datetime | None = None,
        control_binding: object | None = None,
        quote_currency: str | None = None,
        expiry_reference: datetime | None = None,
    ) -> dict[str, object]:
        """Accept one policy-approved proposal as a simulated open order.

        ``auto_paper`` is an explicit paper-only decision label.  It changes
        attribution, not authority: both modes remain local simulations and
        retain ``execution_allowed=false``.

        ``fx_rate`` may be omitted only when the quote currency is the account base currency; a foreign
        quote currency requires an explicit rate. The quote currency is ``quote_currency``, else the
        proposal's ``currency``, else the configured instrument currency, else the account base currency.

        ``expiry_reference`` is the clock the proposal expiry is checked against (default: the real UTC clock); a
        simulation passes its own simulated time so a historical session is not refused as expired.
        """

        # Expiry is checked after the read-only idempotent lookup so a retry of an accepted order still returns it.
        self._validate_proposal(proposal, check_expiry=False)
        if decision_mode not in {"manual_accept", "auto_paper"}:
            raise PaperLedgerError("Unsupported paper decision mode.")
        price_decimal = _decimal_number(execution_price, "execution_price", positive=True)
        fee_decimal = _decimal_number(fee, "fee", non_negative=True)
        explicit_fx = None if fx_rate is None else _decimal_number(fx_rate, "fx_rate", positive=True)
        price = float(price_decimal)
        fee_value = float(fee_decimal)
        proposal_id = _clean_id(proposal.get("proposal_id"), "proposal_id")
        quantity_decimal = _decimal_number(proposal.get("quantity_delta"), "quantity_delta")
        quantity_delta = float(quantity_decimal)
        quantity = abs(quantity_delta)
        if quantity <= 0:
            raise PaperLedgerError("A zero-quantity proposal cannot be accepted.")
        if abs(quantity_decimal) < MIN_QUANTITY:
            raise PaperLedgerError("The proposal quantity is below the paper ledger precision of 1e-8.")
        instrument_id = _clean_id(proposal.get("instrument_id"), "instrument_id").upper()
        order_id = "order_" + _digest(
            {"account_id": self.account_id, "proposal_id": proposal_id, "quantity": quantity}
        )[:20]
        with self._lock, self._file_lock():
            self._recover_interrupted_fills()
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            if state["account_type"] != "paper":
                raise PaperLedgerError("A benchmark shadow account cannot accept proposals.")
            self._require_order_pipeline_open()
            if proposal_id in state["rejections"]:
                raise PaperLedgerError("A rejected proposal cannot be accepted later.")
            if proposal_id in state["deferred"]:
                raise PaperLedgerError("A deferred proposal cannot be accepted later.")
            currency = self._quote_currency(proposal, instrument_id, quote_currency, state)
            fx_decimal = self._resolve_fx(explicit_fx, currency, state)
            fx = float(fx_decimal)
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
            self._require_unexpired(proposal, expiry_reference)
            self._require_within_target(proposal, state, instrument_id, quantity_delta)
            if quantity_delta < 0 and state["positions"].get(instrument_id, {}).get("quantity", 0.0) + 1e-8 < quantity:
                raise PaperLedgerError("A paper sell cannot exceed the current simulated position.")
            venue, instrument_type = self._order_market_terms(proposal, instrument_id)
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

    def _quote_currency(
        self,
        proposal: Mapping[str, object],
        instrument_id: str,
        explicit: str | None,
        state: Mapping[str, object],
    ) -> str:
        if explicit is not None:
            return _clean_id(explicit, "quote_currency").upper()
        if proposal.get("currency") is not None:
            return _clean_id(proposal.get("currency"), "currency").upper()
        try:
            config_dir = self.root / "configs"
            if not (config_dir / "universe.yaml").exists():
                config_dir = CONFIG_DIR
            configured = load_config(config_dir).universe.by_id().get(instrument_id)
        except Exception as exc:
            raise PaperLedgerError(
                "The instrument quote currency is unavailable: the universe configuration could not be loaded; "
                "supply an explicit quote_currency."
            ) from exc
        if configured is None or not getattr(configured, "currency", None):
            raise PaperLedgerError(
                f"The quote currency of {instrument_id} cannot be resolved from the universe; "
                "supply an explicit quote_currency or a proposal currency."
            )
        return str(configured.currency).strip().upper()

    @staticmethod
    def _resolve_fx(fx_rate: Decimal | None, currency: str, state: Mapping[str, object]) -> Decimal:
        """Return the explicit FX rate; the implicit 1 is allowed only for the account base currency."""

        if fx_rate is not None:
            return fx_rate
        base = str(state["base_currency"]).upper()
        if currency.upper() != base:
            raise PaperLedgerError(
                f"An explicit fx_rate is required for {currency.upper()} quotes in a {base} paper account."
            )
        return Decimal("1")

    @staticmethod
    def _position_fx(
        fx_rate: Decimal | None, instrument_id: str, state: Mapping[str, object]
    ) -> Decimal:
        """Return the explicit FX rate; the implicit 1 is allowed only for a base-currency (or absent) position."""

        positions = state["positions"]
        assert isinstance(positions, Mapping)
        position = positions.get(instrument_id)
        currency = str(position["currency"]) if isinstance(position, Mapping) and position.get("currency") else str(state["base_currency"])
        return PaperLedger._resolve_fx(fx_rate, currency, state)

    @staticmethod
    def _require_within_target(
        proposal: Mapping[str, object],
        state: Mapping[str, object],
        instrument_id: str,
        quantity_delta: float,
    ) -> None:
        """Refuse a policy proposal whose delta would overshoot its target given the ledger position and open orders."""

        material = proposal.get("input_material")
        if not isinstance(material, Mapping) or "current_quantity" not in material or "target_quantity" not in material:
            return
        try:
            target = float(material["target_quantity"])
        except (TypeError, ValueError):
            return
        position = state["positions"].get(instrument_id, {}).get("quantity", 0.0)
        pending = sum(
            (1.0 if order.get("side") == "buy" else -1.0) * float(order.get("remaining_quantity", 0.0))
            for order in state["orders"].values()
            if str(order.get("instrument_id")) == instrument_id and order.get("status") in {"accepted", "partially_filled"}
        )
        projected = float(position) + pending + quantity_delta
        if (quantity_delta > 0 and projected > target + 1e-8) or (quantity_delta < 0 and projected < target - 1e-8):
            raise PaperLedgerError(
                "The proposal target is stale: the ledger position plus open orders plus this delta would overshoot the target."
            )

    def evaluate_pre_trade_controls(
        self,
        proposal: Mapping[str, object],
        *,
        execution_price: object,
        fee: object = 0,
        fx_rate: object | None = None,
        occurred_at: datetime | None = None,
        quote_currency: str | None = None,
    ):
        """Return the independent paper-ledger control result for a sealed canary binding.

        ``fx_rate`` may be omitted only when the quote currency is the account base currency.
        """

        self._validate_proposal(proposal)
        price = _decimal_number(execution_price, "execution_price", positive=True)
        _decimal_number(fee, "fee", non_negative=True)
        explicit_fx = None if fx_rate is None else _decimal_number(fx_rate, "fx_rate", positive=True)
        quantity = _decimal_number(proposal.get("quantity_delta"), "quantity_delta")
        with self._lock, self._file_lock():
            self._recover_interrupted_fills()
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            self._require_order_pipeline_open()
            if explicit_fx is None:
                instrument_id = _clean_id(proposal.get("instrument_id"), "instrument_id").upper()
                currency = self._quote_currency(proposal, instrument_id, quote_currency, state)
                fx = self._resolve_fx(None, currency, state)
            else:
                fx = explicit_fx
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
            if proposal_id in state["deferred"]:
                raise PaperLedgerError("A deferred proposal cannot also be rejected.")
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
        fx_rate: float | None = None,
        occurred_at: datetime | None = None,
        quote_currency: str | None = None,
        expiry_reference: datetime | None = None,
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
            quote_currency=quote_currency,
            expiry_reference=expiry_reference,
        )

    def record_fill(
        self,
        order_id: str,
        *,
        fill_id: str | None = None,
        quantity: float,
        price: float,
        fee: float | None = None,
        fx_rate: float | None = None,
        occurred_at: datetime | None = None,
        reference_price: object | None = None,
    ) -> dict[str, object]:
        fill_quantity_decimal = _decimal_number(quantity, "quantity", positive=True)
        if fill_quantity_decimal < MIN_QUANTITY:
            raise PaperLedgerError("The fill quantity is below the paper ledger precision of 1e-8.")
        fill_price_decimal = _decimal_number(price, "price", positive=True)
        fill_fee_decimal = None if fee is None else _decimal_number(fee, "fee", non_negative=True)
        explicit_fx = None if fx_rate is None else _decimal_number(fx_rate, "fx_rate", positive=True)
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
            fill_fx_decimal = self._resolve_fx(explicit_fx, str(order.get("currency", state["base_currency"])), state)
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
            policy_payload = state["cost_policy"]
            if policy_payload is not None:
                policy = ShadowCostPolicy(**{key: Decimal(str(value)) for key, value in policy_payload.items()})
                base_currency = str(state["base_currency"]).upper()
                # A foreign-currency order keeps the explicit rate it was accepted with; a base-currency fill is unit-rate.
                expected_fx = (
                    Decimal(1) if str(order["currency"]).upper() == base_currency
                    else _decimal_number(order.get("fx_rate"), "fx_rate", positive=True)
                )
                if (fill_quantity_decimal % policy.lot_size != 0 or fill_fee_decimal != policy.commission
                        or fill_fx_decimal != expected_fx or base_currency != "EUR"):
                    raise PaperLedgerError("The active fill conflicts with the canonical cost, FX or lot policy.")
                if reference_price is None:
                    raise PaperLedgerError("A canonical-policy fill requires its reference price.")
                reference = _decimal_number(reference_price, "reference_price", positive=True)
                expected = reference * (Decimal(1) + policy.adverse_bps / Decimal(10000) * (1 if order["side"] == "buy" else -1))
                if fill_price_decimal != expected:
                    raise PaperLedgerError("The active fill conflicts with canonical adverse-price policy.")
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

    def cancel_paper_order(self, order_id: str, *, reason: str, occurred_at: datetime | None = None) -> dict[str, object]:
        """Internal paper-ledger cancellation (rolls back an unfilled local paper order); the one entry for in-package callers."""

        return self.cancel_order(order_id, reason=reason, occurred_at=occurred_at)

    def _cancel_order_locked(
        self, order_id: str, *, reason: str, occurred_at: datetime | None = None
    ) -> dict[str, object]:
        # A durable lifecycle fill not yet projected must enter the ledger before the cancellation,
        # otherwise a later recovery would replay a fill against an already-cancelled order.
        self._recover_interrupted_fills()
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
        exit_fx_rate: float | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Mature one filled proposal against adjusted-price, benchmark and cash evidence.

        Entry and exit are compared on one basis: fills are restated for every split recorded after them
        (the adjusted close is on the post-split basis) and the exit is converted with ``exit_fx_rate``.
        Fills with a non-unit FX rate require ``exit_fx_rate``; without it maturation is blocked.
        """

        exit_price = _positive(adjusted_close, "adjusted_close")
        exit_fx = None if exit_fx_rate is None else _positive(exit_fx_rate, "exit_fx_rate")
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
            last_fill_at: datetime | None = None
            for event in events:
                event_payload = event.get("payload")
                if (
                    event.get("event_type") == "fill_recorded"
                    and isinstance(event_payload, Mapping)
                    and event_payload.get("order_id") == order.get("order_id")
                ):
                    fill_time = _event_time(event)
                    last_fill_at = fill_time if last_fill_at is None else max(last_fill_at, fill_time)
            if exit_fx is None and any(_decimal_number(item.get("fx_rate", 1.0), "fx_rate") != 1 for item in order_fills):
                raise PaperLedgerError("Exit FX evidence (exit_fx_rate) is required to mature an outcome with converted fills.")
            # Restate each fill for the splits recorded after it so entry and exit share the adjusted-price basis.
            instrument = str(order["instrument_id"]).upper()
            split_factor: dict[str, float] = {}
            for event in events:
                event_payload = event.get("payload")
                if not isinstance(event_payload, Mapping):
                    continue
                if event.get("event_type") == "fill_recorded" and event_payload.get("order_id") == order.get("order_id"):
                    split_factor[str(event_payload["fill_id"])] = 1.0
                elif event.get("event_type") == "corporate_action" and str(event_payload.get("instrument_id", "")).upper() == instrument:
                    for fill_key in split_factor:
                        split_factor[fill_key] *= float(event_payload["split_ratio"])
            quantity = sum(float(item["quantity"]) * split_factor.get(str(item["fill_id"]), 1.0) for item in order_fills)
            entry_value = sum(float(item["quantity"]) * float(item["price"]) * float(item.get("fx_rate", 1.0)) for item in order_fills)
            fees = sum(float(item.get("fee", 0.0)) for item in order_fills)
            entry_price = entry_value / quantity
            exit_value_price = exit_price * (1.0 if exit_fx is None else exit_fx)
            direction = 1.0 if order.get("side") == "buy" else -1.0
            gross_return = direction * (exit_value_price - entry_price) / entry_price
            cost_return = fees / entry_value if entry_value else 0.0
            net_return = gross_return - cost_return
            outcome_id = "outcome_" + _digest(
                {"account_id": self.account_id, "order_id": order["order_id"], "adjusted_close": exit_price, "benchmark_return": benchmark, "cash_return": cash, "horizon_days": horizon_days, "source_checksum": provenance["source_checksum"],
                 **({} if exit_fx is None else {"exit_fx_rate": exit_fx})}
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
                        ("exit_fx_rate", exit_fx),
                        ("source_authority", provenance["source_authority"]),
                        ("source_checksum", provenance["source_checksum"]),
                    )
                ):
                    raise PaperLedgerError("The paper outcome was already matured with different evidence.")
                return dict(existing)
            if order.get("status") != "filled":
                raise PaperLedgerError(
                    "A paper outcome requires a fully filled order; later fills would make it stale."
                )
            assert last_fill_at is not None
            matured_at = datetime.fromisoformat(_timestamp(occurred_at))
            if matured_at < last_fill_at + timedelta(days=horizon_days):
                raise PaperLedgerError(
                    f"The {horizon_days}-day horizon has not elapsed since the last fill at {last_fill_at.isoformat()}."
                )
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
                **({} if exit_fx is None else {"exit_fx_rate": exit_fx}),
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
        fx_rate: float | None = None,
        benchmark_return: float | None = None,
        source_authority: str = "local_manual_adjusted_close",
        source_checksum: str = "",
        occurred_at: datetime | None = None,
    ) -> PaperAccountSnapshot:
        price = _positive(adjusted_close, "adjusted_close")
        explicit_fx = None if fx_rate is None else _decimal_number(fx_rate, "fx_rate", positive=True)
        benchmark = None if benchmark_return is None else _number(benchmark_return, "benchmark_return")
        provenance = _provenance(source_authority, source_checksum)
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            mark_id = _clean_id(instrument_id, "instrument_id").upper()
            fx = float(self._position_fx(explicit_fx, mark_id, state))
            self._append(
                "position_marked",
                {
                    "instrument_id": mark_id,
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
        fx_rate: float | None = None,
        occurred_at: datetime | None = None,
    ) -> PaperAccountSnapshot:
        ratio = _positive(split_ratio, "split_ratio")
        dividend_decimal = _decimal_number(cash_dividend_per_unit, "cash_dividend_per_unit", non_negative=True)
        explicit_fx = None if fx_rate is None else _decimal_number(fx_rate, "fx_rate", positive=True)
        provenance = _provenance(source_authority, source_checksum)
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            dividend_fx_decimal = self._position_fx(explicit_fx, _clean_id(instrument_id, "instrument_id").upper(), state)
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

    def open_benchmark_shadow_account(
        self,
        *,
        cost_policy: ShadowCostPolicy,
        active_account: PaperLedger | None = None,
        base_currency: str = "EUR",
        instrument_id: str = "VWCE",
        occurred_at: datetime | None = None,
    ) -> PaperAccountSnapshot:
        """Open the cash-flow-matched benchmark shadow account (same ledger, ``benchmark_shadow_account`` type).

        It holds only the benchmark instrument and is funded solely by the external flows copied from the
        active account (``record_shadow_flow``); it never accepts proposals.
        """

        if not isinstance(cost_policy, ShadowCostPolicy):
            raise PaperLedgerError("A shadow cost policy is required.")
        currency = _clean_id(base_currency, "base_currency").upper()
        if currency != "EUR":
            raise PaperLedgerError("Benchmark shadow accounts support EUR only.")
        if not isinstance(active_account, PaperLedger) or active_account.account_id == self.account_id or active_account.root != self.root:
            raise PaperLedgerError("A canonical active account in the same ledger root is required.")
        active_events = active_account._read_events()
        active_state = active_account._replay(active_events)
        if (active_state["shadow"] is not None or active_state["base_currency"] != "EUR"
                or active_state["cost_policy"] != cost_policy.to_payload()):
            raise PaperLedgerError("The active account has unavailable or conflicting cost policy.")
        instrument = _clean_id(instrument_id, "instrument_id").upper()
        if instrument != "VWCE":
            raise PaperLedgerError("The benchmark shadow instrument must be VWCE.")
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            if state["opened"]:
                shadow = state["shadow"]
                if (
                    not isinstance(shadow, Mapping)
                    or state["base_currency"] != currency
                    or shadow["instrument_id"] != instrument
                    or shadow["cost_policy_digest"] != cost_policy.digest()
                ):
                    raise PaperLedgerError("The paper account already exists with different opening terms.")
                return self._snapshot(events, state)
            self._append(
                "account_opened",
                {
                    "initial_cash": "0",
                    "base_currency": currency,
                    "account_type": SHADOW_ACCOUNT_TYPE,
                    "active_account_id": active_account.account_id,
                    "active_opening_hash": active_events[0]["event_hash"],
                    "instrument_id": instrument,
                    "cost_policy": cost_policy.to_payload(),
                    "cost_policy_digest": cost_policy.digest(),
                },
                occurred_at=occurred_at,
            )
            events = self._read_events()
            return self._snapshot(events, self._replay(events))

    def record_shadow_flow(
        self,
        *,
        flow_id: str,
        kind: Literal["contribution", "withdrawal"],
        amount: object,
        flow_at: datetime,
        prices: pd.DataFrame,
        series_check: VwceReferenceSeriesCheck,
        cost_policy: ShadowCostPolicy,
        fx_rate: object | None = None,
        decision_time: datetime | None = None,
        source_authority: str = "vwce_reference_series",
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Mirror one external flow of the active account into the benchmark shadow account.

        The cash enters at the first session on or after the flow date and buys (contribution) or sells
        (withdrawal) the benchmark at the close of the first session strictly after the flow date, so no
        same-day close is used. Costs and lot policy come from ``cost_policy``, which must equal the policy the
        account was opened with. The price series must have passed the VWCE series contract; otherwise nothing
        is recorded. A re-submitted ``flow_id`` with identical terms returns the recorded flow.
        """

        flow = _clean_id(flow_id, "flow_id")
        if kind not in _SHADOW_FLOW_KINDS:
            raise PaperLedgerError("A shadow flow must be a contribution or a withdrawal.")
        amount_decimal = _decimal_number(amount, "amount", positive=True)
        explicit_fx = None if fx_rate is None else _decimal_number(fx_rate, "fx_rate", positive=True)
        if not isinstance(flow_at, datetime) or flow_at.tzinfo is None:
            raise PaperLedgerError("A timezone-aware flow time is required.")
        if not isinstance(series_check, VwceReferenceSeriesCheck) or series_check.status != "available":
            raise PaperLedgerError("The benchmark shadow account requires a source-backed VWCE price series.")
        if not isinstance(prices, pd.DataFrame) or series_check.source_hash != vwce_series_source_hash(prices):
            raise PaperLedgerError("The price series does not match its verified source hash.")
        cutoff = decision_time or occurred_at
        if cutoff is None or cutoff.tzinfo is None or series_check.known_at is None or pd.Timestamp(series_check.known_at) > pd.Timestamp(cutoff):
            raise PaperLedgerError("Reference known_at is unavailable at the requested decision cutoff.")
        if explicit_fx is not None and explicit_fx != 1:
            raise PaperLedgerError("EUR shadow accounts require identity FX.")
        sessions = pd.to_datetime(prices["date"]).dt.normalize()
        flow_day = pd.Timestamp(flow_at.astimezone(timezone.utc).date())
        entry = sessions[sessions >= flow_day].min()
        executed = sessions[sessions > flow_day].min()
        if pd.isna(entry) or pd.isna(executed):
            raise PaperLedgerError("No eligible benchmark session exists after the flow date yet.")
        if executed.date() >= cutoff.astimezone(timezone.utc).date():
            raise PaperLedgerError("Benchmark execution close is unavailable at the decision cutoff.")
        close = prices.loc[sessions == executed, "close"]
        if len(close) != 1:
            raise PaperLedgerError("The benchmark session price is missing or ambiguous.")
        close_price = _decimal_number(close.iloc[0], "close", positive=True)
        checksum = series_check.source_hash
        prefix_hash = _shadow_prefix_hash(prices, executed)
        with self._lock, self._file_lock():
            events = self._read_events()
            state = self._replay(events)
            self._require_open(state)
            shadow = state["shadow"]
            if not isinstance(shadow, Mapping):
                raise PaperLedgerError("The account is not a benchmark shadow account.")
            if cost_policy.digest() != shadow["cost_policy_digest"]:
                raise PaperLedgerError("The shadow account must use the cost and lot policy it was opened with.")
            existing = state["shadow_flows"].get(flow)
            if existing is not None:
                if (
                    existing["flow_kind"] != kind
                    or Decimal(existing["amount"]) != amount_decimal
                    or existing["entry_session"] != entry.date().isoformat()
                ):
                    raise PaperLedgerError("The shadow flow was already recorded with different terms.")
                return dict(existing)
            active = PaperLedger(self.root, account_id=str(shadow.get("active_account_id", "")))
            active_events = active._read_events()
            active_state = active._replay(active_events)
            matched = [event for event in active_events if event["event_type"] == "external_flow_recorded" and event["payload"]["flow_id"] == flow]
            if (not active_events or active_events[0]["event_hash"] != shadow.get("active_opening_hash")
                    or active_state["cost_policy"] != cost_policy.to_payload() or len(matched) != 1):
                raise PaperLedgerError("Canonical active flow and policy evidence is unavailable.")
            active_flow = matched[0]["payload"]
            if (active_flow["flow_kind"] != kind or Decimal(active_flow["amount"]) != amount_decimal
                    or pd.Timestamp(active_flow["flow_at"]) != pd.Timestamp(flow_at)):
                raise PaperLedgerError("The shadow flow conflicts with canonical active flow terms.")
            if pd.Timestamp(matched[0]["occurred_at"]) > pd.Timestamp(cutoff):
                raise PaperLedgerError("Active flow evidence is unavailable at the decision cutoff.")
            prior = list(state["shadow_flows"].values())
            if any(pd.Timestamp(item["executed_session"]) >= entry for item in prior):
                raise PaperLedgerError("Overlapping or backdated shadow execution chronology is unsupported.")
            active_entry = pd.Timestamp(active_flow["effective_at"]).tz_convert("UTC").tz_localize(None).normalize()
            if kind == "withdrawal" and active_entry == executed:
                entry = executed
            elif active_entry != entry:
                raise PaperLedgerError("Canonical active flow effective session does not match the shadow session.")
            if kind == "withdrawal" and entry < executed and state["cash"] < amount_decimal:
                raise PaperLedgerError("Withdrawal chronology requires canonical settlement at the execution session.")
            fx = self._resolve_fx(explicit_fx, VWCE_QUOTE_CURRENCY, state)
            policy = cost_policy
            adverse = policy.adverse_bps / Decimal(10000)
            cash = state["cash"]
            units = state["shadow_units"]
            side, quantity, price, fee = "none", Decimal("0"), close_price, Decimal("0")
            if kind == "contribution":
                price = close_price * (Decimal(1) + adverse)
                budget = amount_decimal - policy.commission
                if budget > 0:
                    lots = (budget / (price * fx) / policy.lot_size).to_integral_value(rounding=ROUND_FLOOR)
                    quantity = lots * policy.lot_size
                if quantity > 0:
                    side, fee = "buy", policy.commission
                else:
                    quantity = Decimal("0")
            elif cash < amount_decimal:
                price = close_price * (Decimal(1) - adverse)
                needed = amount_decimal - cash + policy.commission
                lots = (needed / (price * fx) / policy.lot_size).to_integral_value(rounding=ROUND_CEILING)
                quantity = lots * policy.lot_size
                if quantity > units:
                    raise PaperLedgerError("The withdrawal exceeds the value of the benchmark shadow account.")
                side, fee = "sell", policy.commission
            payload = {
                "flow_id": flow,
                "active_flow_hash": matched[0]["event_hash"],
                "reference_known_at": series_check.known_at,
                "decision_time": _timestamp(cutoff),
                "flow_kind": kind,
                "amount": str(amount_decimal),
                "flow_at": _timestamp(flow_at),
                "entry_session": entry.date().isoformat(),
                "executed_session": executed.date().isoformat(),
                "executed_close": str(close_price),
                "prefix_hash": prefix_hash,
                "instrument_id": shadow["instrument_id"],
                "side": side,
                "quantity": str(quantity),
                "price": str(price),
                "fx_rate": str(fx),
                "fee": str(fee),
                "cost_policy_digest": policy.digest(),
                "execution_allowed": False,
                **_provenance(source_authority, checksum),
            }
            self._append("shadow_flow_executed", payload, occurred_at=occurred_at)
            return payload

    def shadow_daily_snapshots(
        self,
        prices: pd.DataFrame,
        *,
        series_check: VwceReferenceSeriesCheck,
        through: date,
        decision_time: datetime | None = None,
    ) -> pd.DataFrame:
        """Value the shadow account per session through the canonical daily-snapshot builder.

        The result has the standard ``SNAPSHOT_COLUMNS`` so TWR, XIRR and the performance series run on the same
        canonical path as the active account. External flows appear on their entry session; trades and fees on
        their execution session.
        """

        if not isinstance(series_check, VwceReferenceSeriesCheck) or series_check.status != "available":
            raise PaperLedgerError("The benchmark shadow account requires a source-backed VWCE price series.")
        if not isinstance(prices, pd.DataFrame) or series_check.source_hash != vwce_series_source_hash(prices):
            raise PaperLedgerError("The price series does not match its verified source hash.")
        if (decision_time is None or decision_time.tzinfo is None or series_check.known_at is None
                or pd.Timestamp(series_check.known_at) > pd.Timestamp(decision_time)):
            raise PaperLedgerError("Reference known_at is unavailable at the requested decision cutoff.")
        with self._lock:
            state = self._replay(self._read_events())
        shadow = state["shadow"]
        if not isinstance(shadow, Mapping):
            raise PaperLedgerError("The account is not a benchmark shadow account.")
        flows = list(state["shadow_flows"].values())
        if any(pd.Timestamp(flow.get("decision_time")) > pd.Timestamp(decision_time) for flow in flows):
            raise PaperLedgerError("Shadow flow evidence is unavailable at the requested decision cutoff.")
        if not flows:
            raise PaperLedgerError("The benchmark shadow account has no recorded flows.")
        sessions = pd.to_datetime(prices["date"]).dt.normalize()
        # ``source_checksum`` is provenance only: appending newer sessions changes the whole-series hash. Each flow
        # instead binds the history up to its own execution session (prefix hash plus raw close).
        for flow in flows:
            executed_day = pd.Timestamp(str(flow["executed_session"]))
            recorded_close = flow.get("executed_close")
            current = prices.loc[sessions == executed_day, "close"]
            if (
                not flow.get("prefix_hash")
                or recorded_close is None
                or len(current) != 1
                or _decimal_number(current.iloc[0], "close", positive=True) != Decimal(str(recorded_close))
                or _shadow_prefix_hash(prices, executed_day) != flow["prefix_hash"]
            ):
                raise PaperLedgerError(f"historical_price_revised:{flow['flow_id']}")
        closes = dict(zip(sessions.dt.date, prices["close"], strict=True))
        start = min(date.fromisoformat(str(flow["entry_session"])) for flow in flows)
        end = through if isinstance(through, date) else date.fromisoformat(str(through))
        if end >= decision_time.astimezone(timezone.utc).date():
            raise PaperLedgerError("Benchmark close is unavailable at the decision cutoff.")
        days = sorted(day for day in closes if start <= day <= end)
        if not days or days[-1] != end:
            raise PaperLedgerError("The requested end date is not a benchmark session.")
        instrument = str(shadow["instrument_id"])
        holdings, price_rows, cash_rows, events = [], [], [], []
        for day in days:
            cash = Decimal("0")
            units = Decimal("0")
            for flow in flows:
                sign = Decimal(1) if flow["flow_kind"] == "contribution" else Decimal(-1)
                if date.fromisoformat(str(flow["entry_session"])) <= day:
                    cash += sign * Decimal(flow["amount"])
                if date.fromisoformat(str(flow["executed_session"])) <= day and flow["side"] != "none":
                    gross = Decimal(flow["quantity"]) * Decimal(flow["price"]) * Decimal(flow["fx_rate"])
                    traded = Decimal(flow["quantity"]) * (1 if flow["side"] == "buy" else -1)
                    cash += (-gross if flow["side"] == "buy" else gross) - Decimal(flow["fee"])
                    units += traded
            holdings.append({"date": day, "instrument_id": instrument, "quantity": float(units)})
            price_rows.append({"date": day, "instrument_id": instrument, "price": float(closes[day])})
            cash_rows.append({"date": day, "cash_value": float(cash)})
        for flow in flows:
            entry = date.fromisoformat(str(flow["entry_session"]))
            executed = date.fromisoformat(str(flow["executed_session"]))
            if start <= entry <= end:
                events.append({"date": entry, "event_type": flow["flow_kind"], "amount": float(Decimal(flow["amount"]))})
            if start <= executed <= end and Decimal(flow["fee"]) > 0:
                events.append({"date": executed, "event_type": "fee", "amount": float(Decimal(flow["fee"]))})
        inputs = [pd.DataFrame(holdings), pd.DataFrame(price_rows), pd.DataFrame(cash_rows),
                  pd.DataFrame(events, columns=["date", "event_type", "amount"])]
        for frame in inputs:
            frame["available_at"] = series_check.known_at
        result = build_daily_portfolio_snapshots(
            *inputs,
            decision_time=decision_time,
            calendar="XETR",
        )
        result.attrs.update(benchmark_id="benchmark:ftse-all-world", source_hash=series_check.source_hash,
                            known_at=series_check.known_at, active_account_id=shadow["active_account_id"],
                            shadow_account_id=self.account_id, execution_allowed=False, calendar="XETR")
        return result

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
        self._write_anchor(event)

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

    @property
    def _anchor_path(self) -> Path:
        return self.path.with_name("ledger.head.json")

    def _write_anchor(self, event: Mapping[str, object]) -> None:
        """Durably record the log head (last sequence + hash) so a deleted final event is detectable."""

        record: dict[str, object] = {
            "schema_version": PAPER_SCHEMA_VERSION,
            "account_id": self.account_id,
            "sequence": event["sequence"],
            "event_hash": event["event_hash"],
        }
        record["anchor_hash"] = _digest(record)
        temporary = self._anchor_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._anchor_path)

    def _verify_anchor(self, events: list[dict[str, object]]) -> None:
        """Fail closed when the log is shorter than, or diverges from, its recorded head.

        A ledger written before anchors existed has no head file and stays readable; the first append creates it.
        The anchor may trail the log by exactly one event (a crash between the append and the anchor update).
        """

        if not self._anchor_path.exists():
            return
        try:
            record = json.loads(self._anchor_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaperLedgerIntegrityError("The paper ledger head anchor is unreadable.") from exc
        if not isinstance(record, dict):
            raise PaperLedgerIntegrityError("The paper ledger head anchor is malformed.")
        body = {key: value for key, value in record.items() if key != "anchor_hash"}
        sequence = record.get("sequence")
        head_hash = record.get("event_hash")
        if (
            record.get("anchor_hash") != _digest(body)
            or record.get("account_id") != self.account_id
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or not isinstance(head_hash, str)
        ):
            raise PaperLedgerIntegrityError("The paper ledger head anchor is invalid.")
        count = len(events)
        if count == sequence and events[-1]["event_hash"] == head_hash:
            return
        if count == sequence + 1 and events[sequence - 1]["event_hash"] == head_hash:
            return
        raise PaperLedgerIntegrityError(
            "The paper ledger does not match its head anchor; events were removed or replaced."
        )

    def _read_events(self) -> list[dict[str, object]]:
        events = self._read_chain()
        self._verify_anchor(events)
        return events

    def _read_chain(self) -> list[dict[str, object]]:
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
            "order_pnls": {},
            "timeline": {},
            "benchmark_return": None,
            "account_type": "paper",
            "shadow": None,
            "shadow_flows": {},
            "shadow_units": Decimal("0"),
            "cost_policy": None,
            "external_flows": {},
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
                    account_type=str(payload.get("account_type", "paper")),
                )
                state["cost_policy"] = payload.get("cost_policy")
                if state["account_type"] == SHADOW_ACCOUNT_TYPE:
                    state["shadow"] = {
                        "instrument_id": str(payload["instrument_id"]),
                        "active_account_id": payload.get("active_account_id"),
                        "active_opening_hash": payload.get("active_opening_hash"),
                        "cost_policy_digest": str(payload["cost_policy_digest"]),
                    }
                elif state["account_type"] != "paper":
                    raise PaperLedgerIntegrityError("Paper account type is unsupported.")
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
                self._apply_fill(state, payload, occurred_at=_event_time(event))
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
            elif kind == "external_flow_recorded":
                flow_id = str(payload["flow_id"])
                amount = _decimal_number(payload["amount"], "amount", positive=True)
                if flow_id in state["external_flows"] or payload["flow_kind"] not in _SHADOW_FLOW_KINDS:
                    raise PaperLedgerIntegrityError("An active external flow is duplicated or invalid.")
                state["cash"] += amount if payload["flow_kind"] == "contribution" else -amount
                if state["cash"] < 0:
                    raise PaperLedgerIntegrityError("An active external flow overdrew cash.")
                state["external_flows"][flow_id] = dict(payload)
            elif kind == "shadow_flow_executed":
                self._apply_shadow_flow(state, payload)
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
                self._apply_corporate_action(state, payload, occurred_at=_event_time(event))
            else:
                raise PaperLedgerIntegrityError(f"Unsupported paper event type: {kind}")
            _update_equity_peak(state)
        # A closed trade is one completed sell order (all of its fills together), never one fill.
        order_pnls = state["order_pnls"]
        assert isinstance(order_pnls, dict) and isinstance(state["orders"], dict)
        state["trade_pnls"] = [
            pnl
            for order_id, pnl in order_pnls.items()
            if state["orders"][order_id]["status"] == "filled"
            or (state["orders"][order_id]["status"] == "cancelled" and float(state["orders"][order_id]["filled_quantity"]) > 0)
        ]
        return state

    @staticmethod
    def _apply_fill(
        state: dict[str, object], payload: Mapping[str, object], *, occurred_at: datetime | None = None
    ) -> None:
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
            order_pnls = state["order_pnls"]
            assert isinstance(order_pnls, dict)
            order_pnls[str(order["order_id"])] = float(order_pnls.get(str(order["order_id"]), 0.0)) + realised
            if position["quantity"] <= 1e-8:
                position["quantity"] = 0.0
                position["average_cost"] = 0.0
                # A flat holding has no valid mark: a later re-purchase must not inherit it.
                position.pop("mark_price", None)
                position.pop("mark_fx_rate", None)
        order["filled_quantity"] = float(order["filled_quantity"]) + quantity
        order["remaining_quantity"] = float(order["remaining_quantity"]) - quantity
        order["status"] = "filled" if order["remaining_quantity"] <= 1e-8 else "partially_filled"
        if occurred_at is not None:
            timeline = state["timeline"]
            assert isinstance(timeline, dict)
            timeline.setdefault(instrument_id, []).append(
                (occurred_at, "fill", quantity if order["side"] == "buy" else -quantity)
            )
        fills = state["fills"]
        assert isinstance(fills, list)
        if any(str(item.get("fill_id")) == str(payload.get("fill_id")) for item in fills if isinstance(item, Mapping)):
            raise PaperLedgerIntegrityError("A paper fill ID was recorded twice.")
        fills.append(dict(payload))

    @staticmethod
    def _apply_shadow_flow(state: dict[str, object], payload: Mapping[str, object]) -> None:
        """Apply one external flow and the benchmark trade it triggered to a shadow account's replay state."""

        shadow = state["shadow"]
        flows = state["shadow_flows"]
        positions = state["positions"]
        assert isinstance(flows, dict) and isinstance(positions, dict)
        if not isinstance(shadow, Mapping):
            raise PaperLedgerIntegrityError("A shadow flow was recorded on a non-shadow paper account.")
        flow_id = str(payload["flow_id"])
        kind = str(payload["flow_kind"])
        side = str(payload["side"])
        if flow_id in flows or kind not in _SHADOW_FLOW_KINDS or side not in {"buy", "sell", "none"}:
            raise PaperLedgerIntegrityError("A shadow flow is duplicated or malformed.")
        if str(payload["cost_policy_digest"]) != shadow["cost_policy_digest"]:
            raise PaperLedgerIntegrityError("A shadow flow used a different cost policy than the account.")
        _provenance(payload.get("source_authority"), payload.get("source_checksum"))
        amount = _decimal_number(payload["amount"], "amount", positive=True)
        quantity = _decimal_number(payload["quantity"], "quantity", non_negative=True)
        price = _decimal_number(payload["price"], "price", positive=True)
        fx = _decimal_number(payload["fx_rate"], "fx_rate", positive=True)
        fee = _decimal_number(payload["fee"], "fee", non_negative=True)
        cash = state["cash"] + (amount if kind == "contribution" else -amount)
        units = state["shadow_units"]
        instrument_id = str(shadow["instrument_id"])
        position = positions.setdefault(
            instrument_id,
            {"quantity": 0.0, "average_cost": 0.0, "realised_pnl": 0.0, "currency": state["base_currency"]},
        )
        gross = quantity * price * fx
        if side == "buy":
            cash -= gross + fee
            total_cost = float(units) * float(position["average_cost"]) + float(gross + fee)
            units += quantity
            position["average_cost"] = total_cost / float(units)
        elif side == "sell":
            if quantity > units:
                raise PaperLedgerIntegrityError("A shadow sale exceeds the benchmark position.")
            cash += gross - fee
            position["realised_pnl"] = float(position.get("realised_pnl", 0.0)) + float(
                gross - fee - quantity * Decimal(str(position["average_cost"]))
            )
            units -= quantity
            if units == 0:
                position["average_cost"] = 0.0
        if cash < 0:
            raise PaperLedgerIntegrityError("A shadow flow overdrew the benchmark account cash.")
        position["quantity"] = float(units)
        state["cash"] = cash
        state["shadow_units"] = units
        flows[flow_id] = dict(payload)

    @staticmethod
    def _apply_corporate_action(
        state: dict[str, object], payload: Mapping[str, object], *, occurred_at: datetime | None = None
    ) -> None:
        positions = state["positions"]
        assert isinstance(positions, dict)
        instrument_id = str(payload["instrument_id"])
        position = positions.get(instrument_id)
        if position is None:
            return
        ratio = float(payload["split_ratio"])
        dividend = _decimal_number(payload["cash_dividend_per_unit"], "cash_dividend_per_unit", non_negative=True)
        timeline = state["timeline"]
        assert isinstance(timeline, dict)
        history = timeline.setdefault(instrument_id, [])
        if occurred_at is None:
            entitled = float(position["quantity"])
        else:
            # Entitlement is the share count held at the ex-date (the event time), not the count held when
            # the action happens to be recorded.
            entitled = 0.0
            for moment, kind, amount in history:
                if moment <= occurred_at:
                    entitled = entitled * amount if kind == "split" else entitled + amount
            entitled = max(entitled, 0.0)
            history.append((occurred_at, "split", ratio))
        position["quantity"] = float(position["quantity"]) * ratio
        position["average_cost"] = float(position["average_cost"]) / ratio
        if position.get("mark_price") is not None:
            position["mark_price"] = float(position["mark_price"]) / ratio
        state["cash"] = state["cash"] + (
            Decimal(str(entitled))
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

    def _validate_proposal(self, proposal: Mapping[str, object], *, check_expiry: bool = True) -> None:
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
        if check_expiry:
            self._require_unexpired(proposal)

    @staticmethod
    def _require_unexpired(proposal: Mapping[str, object], reference: datetime | None = None) -> None:
        expires_at = proposal.get("expires_at")
        if not isinstance(expires_at, str):
            raise PaperLedgerError("Proposal expiry is missing.")
        if reference is not None and reference.tzinfo is None:
            raise PaperLedgerError("The expiry reference time must be timezone-aware.")
        try:
            expiry = datetime.fromisoformat(expires_at)
            expired = expiry <= (datetime.now(timezone.utc) if reference is None else reference)
        except ValueError as exc:
            raise PaperLedgerError("Proposal expiry is malformed.") from exc
        if expired:
            raise PaperLedgerError("The proposal has expired.")

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
        unmarked: list[str] = []
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
            else:
                unmarked.append(instrument_id)
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
        initial_cash = float(state["initial_cash"])
        # A nonzero position without a mark has an unknown value: equity, P&L and drawdown are unavailable,
        # never a total that silently counts the holding as zero.
        equity = None if unmarked else cash + market_value
        pnl = None if equity is None else equity - initial_cash
        trade_pnls = [float(value) for value in state["trade_pnls"]]
        wins = [value for value in trade_pnls if value > 0]
        losses = [value for value in trade_pnls if value < 0]
        win_rate = None if not trade_pnls else len(wins) / len(trade_pnls)
        payoff_ratio = None if not wins or not losses else sum(wins) / abs(sum(losses))
        peak = max(initial_cash, float(state.get("equity_peak", initial_cash)))
        drawdown = None if equity is None or peak <= 0 else (equity - peak) / peak
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
            )
            + (
                f" Valuation unavailable: no mark for {', '.join(unmarked)}."
                if unmarked
                else ""
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
        if not isinstance(position, Mapping) or float(position.get("quantity", 0.0)) <= 1e-8:
            continue
        if position.get("mark_price") is None:
            # Incomplete valuation: the peak only moves on complete valuations.
            return
        marked_value += float(position.get("quantity", 0.0)) * float(position["mark_price"]) * float(position.get("mark_fx_rate", 1.0))
    equity = float(state.get("cash", 0.0)) + marked_value
    state["equity_peak"] = max(float(state.get("equity_peak", 0.0)), equity)


def _shadow_prefix_hash(prices: pd.DataFrame, executed: pd.Timestamp) -> str:
    """Hash the VWCE rows up to and including ``executed`` so later appended sessions do not change it."""

    sessions = pd.to_datetime(prices["date"]).dt.normalize()
    return vwce_series_source_hash(prices.loc[sessions <= executed].reset_index(drop=True))


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


def _event_time(event: Mapping[str, object]) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(event["occurred_at"]))
    except (KeyError, ValueError) as exc:
        raise PaperLedgerIntegrityError("A paper ledger event has no valid timestamp.") from exc
    return (parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


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
    "SHADOW_ACCOUNT_TYPE",
    "ShadowCostPolicy",
    "PaperAccountSnapshot",
    "PaperLedger",
    "PaperLedgerError",
    "PaperLedgerIntegrityError",
    "PaperPosition",
    "load_proposal_for_paper",
]
