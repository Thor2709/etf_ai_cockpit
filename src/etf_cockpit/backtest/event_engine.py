"""Deterministic, local-only order-level backtest replay.

The replay contract is deliberately shared by future paper/proposal adapters:
orders are immutable requests, lifecycle events are timestamped, and the
result never grants external execution authority.  This module consumes
historical market events only; it does not fetch data or talk to a broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
from typing import Literal, Mapping, TypeAlias
from zoneinfo import ZoneInfo

from etf_cockpit.data.market_calendar import ClockContext, ListingCalendarEvidence, MarketCalendarService


OrderSide: TypeAlias = Literal["buy", "sell"]
OrderType: TypeAlias = Literal["market", "limit"]


class EventReplayError(ValueError):
    """Raised when historical events cannot be replayed safely."""


class UnsupportedExecutionDataError(EventReplayError):
    """Raised when the supplied historical data cannot support a fill."""


def _as_timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise EventReplayError("timestamp must be a datetime")
    if value.tzinfo is not None:
        raise EventReplayError("timezone-aware timestamps are not supported; normalise to local session time first")
    return value.replace(microsecond=value.microsecond)


def _number(value: float, *, field_name: str, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EventReplayError(f"{field_name} must be numeric") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise EventReplayError(f"{field_name} must be finite and >= {minimum}")
    return result


@dataclass(frozen=True)
class SessionCalendar:
    """Simple deterministic weekday session calendar for historical replay."""

    session_open: time = time(9, 30)
    session_close: time = time(16, 0)
    holidays: frozenset[date] = frozenset()

    def is_session(self, timestamp: datetime) -> bool:
        value = _as_timestamp(timestamp)
        return (
            value.weekday() < 5
            and value.date() not in self.holidays
            and self.session_open <= value.time() <= self.session_close
        )

    def require_session(self, timestamp: datetime, *, event_name: str) -> None:
        if not self.is_session(timestamp):
            raise EventReplayError(f"{event_name} is outside a valid market session: {timestamp.isoformat()}")


@dataclass(frozen=True)
class CertifiedSessionCalendar:
    """Backtest adapter using the canonical identity-certified market clock."""

    listing: ListingCalendarEvidence
    service: MarketCalendarService = field(default_factory=MarketCalendarService)
    knowledge_cutoff: datetime | None = None

    def is_session(self, timestamp: datetime) -> bool:
        local = _as_timestamp(timestamp).replace(tzinfo=ZoneInfo(self.listing.timezone))
        decision = local.astimezone(timezone.utc)
        cutoff = self.knowledge_cutoff or decision
        if cutoff.tzinfo is None:
            raise EventReplayError("certified calendar knowledge_cutoff must be timezone-aware")
        try:
            state = self.service.market_state(
                self.listing,
                ClockContext.at(decision, knowledge_cutoff=cutoff),
            )
        except ValueError as exc:
            raise EventReplayError(f"certified market calendar is unavailable: {exc}") from exc
        return state.certification == "certified" and state.phase in {
            "open",
            "opening_auction",
            "closing_auction",
        }

    def require_session(self, timestamp: datetime, *, event_name: str) -> None:
        if not self.is_session(timestamp):
            raise EventReplayError(
                f"{event_name} is outside an identity-certified market session: {timestamp.isoformat()}"
            )


@dataclass(frozen=True)
class MarketEvent:
    timestamp: datetime
    instrument_id: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    available_quantity: float | None = None
    listed: bool = True
    sequence: int = 0
    kind: Literal["market"] = "market"

    def __post_init__(self) -> None:
        _as_timestamp(self.timestamp)
        if not self.instrument_id.strip():
            raise EventReplayError("market instrument_id is required")
        values = {
            "open_price": _number(self.open_price, field_name="open_price", minimum=0.0),
            "high_price": _number(self.high_price, field_name="high_price", minimum=0.0),
            "low_price": _number(self.low_price, field_name="low_price", minimum=0.0),
            "close_price": _number(self.close_price, field_name="close_price", minimum=0.0),
        }
        if values["high_price"] < max(values["open_price"], values["close_price"]) or values["low_price"] > min(values["open_price"], values["close_price"]):
            raise EventReplayError("market high/low do not contain open and close")
        if self.available_quantity is not None:
            _number(self.available_quantity, field_name="available_quantity", minimum=0.0)


@dataclass(frozen=True)
class SignalEvent:
    timestamp: datetime
    signal_id: str
    instrument_id: str
    action: Literal["buy", "sell", "hold"]
    sequence: int = 0
    kind: Literal["signal"] = "signal"


@dataclass(frozen=True)
class TargetEvent:
    timestamp: datetime
    target_id: str
    instrument_id: str
    target_quantity: float
    sequence: int = 0
    kind: Literal["target"] = "target"

    def __post_init__(self) -> None:
        _as_timestamp(self.timestamp)
        _number(self.target_quantity, field_name="target_quantity", minimum=0.0)


@dataclass(frozen=True)
class ProposalEvent:
    timestamp: datetime
    proposal_id: str
    instrument_id: str
    side: OrderSide
    quantity: float
    order_type: OrderType = "market"
    limit_price: float | None = None
    sequence: int = 0
    kind: Literal["proposal"] = "proposal"

    def __post_init__(self) -> None:
        _as_timestamp(self.timestamp)
        _validate_side_type(self.side, self.order_type, self.quantity, self.limit_price)


@dataclass(frozen=True)
class OrderRequest:
    timestamp: datetime
    order_id: str
    instrument_id: str
    side: OrderSide
    quantity: float
    order_type: OrderType = "market"
    limit_price: float | None = None
    expires_at: datetime | None = None
    source_id: str | None = None
    sequence: int = 0
    kind: Literal["order"] = "order"

    def __post_init__(self) -> None:
        _as_timestamp(self.timestamp)
        if not self.order_id.strip() or not self.instrument_id.strip():
            raise EventReplayError("order_id and instrument_id are required")
        _validate_side_type(self.side, self.order_type, self.quantity, self.limit_price)
        if self.expires_at is not None:
            expiry = _as_timestamp(self.expires_at)
            if expiry <= self.timestamp:
                raise EventReplayError("expires_at must be after the order timestamp")


@dataclass(frozen=True)
class AcknowledgementEvent:
    timestamp: datetime
    order_id: str
    accepted: bool
    reason: str = "accepted"
    sequence: int = 0
    kind: Literal["acknowledgement"] = "acknowledgement"


@dataclass(frozen=True)
class FillEvent:
    timestamp: datetime
    order_id: str
    fill_id: str
    instrument_id: str
    side: OrderSide
    quantity: float
    price: float
    remaining_quantity: float
    sequence: int = 0
    kind: Literal["fill"] = "fill"


@dataclass(frozen=True)
class CancelEvent:
    timestamp: datetime
    order_id: str
    reason: str = "cancelled_by_policy"
    sequence: int = 0
    kind: Literal["cancel"] = "cancel"


@dataclass(frozen=True)
class ExpiryEvent:
    timestamp: datetime
    order_id: str
    reason: str = "order_expired"
    sequence: int = 0
    kind: Literal["expiry"] = "expiry"


ReplayInput: TypeAlias = MarketEvent | SignalEvent | TargetEvent | ProposalEvent | OrderRequest | CancelEvent | ExpiryEvent
ReplayEvent: TypeAlias = ReplayInput | AcknowledgementEvent | FillEvent


@dataclass(frozen=True)
class OrderState:
    order_id: str
    instrument_id: str
    side: OrderSide
    order_type: OrderType
    requested_quantity: float
    filled_quantity: float
    remaining_quantity: float
    status: Literal["accepted", "partially_filled", "filled", "cancelled", "expired"]


@dataclass(frozen=True)
class ReplayResult:
    events: tuple[ReplayEvent, ...]
    orders: tuple[OrderState, ...]
    ledger_hash: str
    execution_allowed: Literal[False] = False

    @property
    def fills(self) -> tuple[FillEvent, ...]:
        return tuple(event for event in self.events if isinstance(event, FillEvent))


def _validate_side_type(side: str, order_type: str, quantity: float, limit_price: float | None) -> None:
    if side not in {"buy", "sell"}:
        raise EventReplayError(f"unsupported order side: {side}")
    if order_type not in {"market", "limit"}:
        raise EventReplayError(f"unsupported order type: {order_type}")
    _number(quantity, field_name="quantity", minimum=0.0)
    if float(quantity) <= 0:
        raise EventReplayError("quantity must be > 0")
    if order_type == "limit":
        if limit_price is None:
            raise EventReplayError("limit_price is required for limit orders")
        _number(limit_price, field_name="limit_price", minimum=0.0)
    elif limit_price is not None:
        raise EventReplayError("limit_price is only valid for limit orders")


def proposal_to_order(proposal: ProposalEvent, *, order_id: str | None = None, expires_at: datetime | None = None) -> OrderRequest:
    """Convert the shared advisory proposal contract into an immutable order request."""

    return OrderRequest(
        timestamp=proposal.timestamp,
        order_id=order_id or f"order:{proposal.proposal_id}",
        instrument_id=proposal.instrument_id,
        side=proposal.side,
        quantity=proposal.quantity,
        order_type=proposal.order_type,
        limit_price=proposal.limit_price,
        expires_at=expires_at,
        source_id=proposal.proposal_id,
        sequence=proposal.sequence,
    )


def _priority(event: ReplayInput) -> int:
    # Market data is consumed before an order at the same timestamp.  This
    # prevents same-bar fills and keeps the next valid market event explicit.
    return {"market": 0, "signal": 1, "target": 2, "proposal": 3, "cancel": 4, "expiry": 4, "order": 5}[event.kind]


def _event_key(event: ReplayInput) -> tuple[datetime, int, str, str]:
    identifier = getattr(event, "order_id", None) or getattr(event, "proposal_id", None) or getattr(event, "signal_id", None) or getattr(event, "target_id", None) or getattr(event, "instrument_id", "")
    return (_as_timestamp(event.timestamp), _priority(event), str(identifier), str(event.sequence))


def _serialise_event(event: ReplayEvent, sequence: int) -> dict[str, object]:
    payload: dict[str, object] = {"kind": event.kind, "timestamp": _as_timestamp(event.timestamp).isoformat(), "sequence": sequence}
    for name in ("order_id", "instrument_id", "fill_id", "signal_id", "target_id", "proposal_id", "source_id", "side", "action", "order_type", "quantity", "price", "limit_price", "expires_at", "remaining_quantity", "requested_quantity", "filled_quantity", "accepted", "reason", "status"):
        if hasattr(event, name):
            value = getattr(event, name)
            if isinstance(value, datetime):
                value = value.isoformat()
            if isinstance(value, float):
                value = round(value, 12)
            payload[name] = value
    return payload


class EventDrivenBacktest:
    """Replay historical events with deterministic order lifecycle semantics."""

    execution_allowed: Literal[False] = False

    def __init__(
        self,
        *,
        calendars: Mapping[str, CertifiedSessionCalendar] | None = None,
    ) -> None:
        self.calendars = dict(calendars or {})
        for instrument_id, calendar in self.calendars.items():
            if instrument_id != calendar.listing.instrument_id:
                raise EventReplayError(
                    "certified calendar key must match listing instrument_id"
                )

    def replay(self, events: list[ReplayInput] | tuple[ReplayInput, ...]) -> ReplayResult:
        ordered = sorted(events, key=_event_key)
        seen_orders: set[str] = set()
        active: dict[str, dict[str, object]] = {}
        states: dict[str, OrderState] = {}
        output: list[ReplayEvent] = []

        for event in ordered:
            instrument_id = self._event_instrument_id(event, active, states)
            calendar = self.calendars.get(instrument_id)
            if calendar is None:
                raise EventReplayError(
                    f"missing identity-certified calendar for instrument: {instrument_id}"
                )
            calendar.require_session(event.timestamp, event_name=event.kind)
            if isinstance(event, MarketEvent):
                self._validate_market(event)
                self._fill_active_orders(event, active, states, output)
                continue
            if isinstance(event, OrderRequest):
                if event.order_id in seen_orders:
                    raise EventReplayError(f"duplicate order_id: {event.order_id}")
                seen_orders.add(event.order_id)
                active[event.order_id] = {"request": event, "filled": 0.0, "fill_count": 0}
                states[event.order_id] = _state_for(event, 0.0, "accepted")
                output.append(event)
                output.append(AcknowledgementEvent(event.timestamp, event.order_id, True))
                continue
            if isinstance(event, (CancelEvent, ExpiryEvent)):
                self._close_order(event, active, states, output)
                continue
            output.append(event)

        for record in active.values():
            state = _state_from_active(record)
            states[state.order_id] = state
        serialised = tuple(_serialise_event(event, index) for index, event in enumerate(output))
        ledger_hash = hashlib.sha256(json.dumps(serialised, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return ReplayResult(tuple(output), tuple(states[key] for key in sorted(states)), ledger_hash)

    @staticmethod
    def _event_instrument_id(
        event: ReplayInput,
        active: Mapping[str, dict[str, object]],
        states: Mapping[str, OrderState],
    ) -> str:
        value = getattr(event, "instrument_id", None)
        if isinstance(value, str) and value.strip():
            return value
        order_id = getattr(event, "order_id", None)
        record = active.get(str(order_id))
        request = record.get("request") if record is not None else None
        if isinstance(request, OrderRequest):
            return request.instrument_id
        state = states.get(str(order_id))
        if state is not None:
            return state.instrument_id
        raise EventReplayError(f"lifecycle event references unknown order: {order_id}")

    def _validate_market(self, event: MarketEvent) -> None:
        if not event.listed:
            raise UnsupportedExecutionDataError(f"instrument is not listed at {event.timestamp.date()}: {event.instrument_id}")
        if event.available_quantity is not None and event.available_quantity < 0:
            raise UnsupportedExecutionDataError("negative market liquidity is unsupported")

    def _fill_active_orders(
        self,
        market: MarketEvent,
        active: dict[str, dict[str, object]],
        states: dict[str, OrderState],
        output: list[ReplayEvent],
    ) -> None:
        for order_id in sorted(tuple(active)):
            record = active[order_id]
            request = record["request"]
            assert isinstance(request, OrderRequest)
            if request.instrument_id != market.instrument_id or request.timestamp >= market.timestamp:
                continue
            if request.expires_at is not None and market.timestamp >= request.expires_at:
                self._close_order(ExpiryEvent(market.timestamp, order_id), active, states, output)
                continue
            if not _market_crosses(request, market):
                continue
            filled = float(record["filled"])
            remaining = request.quantity - filled
            capacity = market.available_quantity if market.available_quantity is not None else remaining
            quantity = min(remaining, capacity)
            if quantity <= 0:
                continue
            price = _fill_price(request, market)
            count = int(record["fill_count"]) + 1
            record["filled"] = filled + quantity
            record["fill_count"] = count
            remaining = max(0.0, request.quantity - float(record["filled"]))
            fill = FillEvent(
                timestamp=market.timestamp,
                order_id=order_id,
                fill_id=f"fill:{order_id}:{count}",
                instrument_id=request.instrument_id,
                side=request.side,
                quantity=quantity,
                price=price,
                remaining_quantity=remaining,
                sequence=count,
            )
            output.append(fill)
            status = "filled" if remaining == 0 else "partially_filled"
            states[order_id] = _state_for(request, float(record["filled"]), status)
            if remaining == 0:
                del active[order_id]

    def _close_order(
        self,
        event: CancelEvent | ExpiryEvent,
        active: dict[str, dict[str, object]],
        states: dict[str, OrderState],
        output: list[ReplayEvent],
    ) -> None:
        record = active.pop(event.order_id, None)
        if record is None:
            if event.order_id in states:
                return
            raise EventReplayError(f"lifecycle event references unknown order: {event.order_id}")
        request = record["request"]
        assert isinstance(request, OrderRequest)
        filled = float(record["filled"])
        states[event.order_id] = _state_for(request, filled, "cancelled" if isinstance(event, CancelEvent) else "expired")
        output.append(event)


def _market_crosses(request: OrderRequest, market: MarketEvent) -> bool:
    if request.order_type == "market":
        return True
    assert request.limit_price is not None
    return market.low_price <= request.limit_price if request.side == "buy" else market.high_price >= request.limit_price


def _fill_price(request: OrderRequest, market: MarketEvent) -> float:
    if request.order_type == "market":
        return market.open_price
    assert request.limit_price is not None
    if request.side == "buy":
        return min(request.limit_price, market.open_price)
    return max(request.limit_price, market.open_price)


def _state_for(request: OrderRequest, filled: float, status: str) -> OrderState:
    remaining = max(0.0, request.quantity - filled)
    return OrderState(request.order_id, request.instrument_id, request.side, request.order_type, request.quantity, filled, remaining, status)  # type: ignore[arg-type]


def _state_from_active(record: dict[str, object]) -> OrderState:
    request = record["request"]
    assert isinstance(request, OrderRequest)
    return _state_for(request, float(record["filled"]), "partially_filled" if float(record["filled"]) else "accepted")


def event_engine_status() -> dict[str, object]:
    """Return the user-facing capability boundary for the Backtests page."""

    return {
        "mode": "deterministic_historical_event_replay",
        "order_types": ["market", "limit"],
        "lifecycle": ["acknowledgement", "partial_fill", "cancel", "expiry"],
        "execution_allowed": False,
        "external_broker": "not_supported",
        "message": "Historical event replay is local evidence only; no paper or broker order is transmitted.",
    }


__all__ = [
    "AcknowledgementEvent",
    "CancelEvent",
    "CertifiedSessionCalendar",
    "EventDrivenBacktest",
    "EventReplayError",
    "ExpiryEvent",
    "FillEvent",
    "MarketEvent",
    "OrderRequest",
    "OrderState",
    "OrderSide",
    "OrderType",
    "ProposalEvent",
    "ReplayResult",
    "SessionCalendar",
    "SignalEvent",
    "TargetEvent",
    "UnsupportedExecutionDataError",
    "event_engine_status",
    "proposal_to_order",
]
