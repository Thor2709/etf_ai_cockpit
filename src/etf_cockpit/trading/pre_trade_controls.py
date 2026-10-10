"""Independent, fail-closed controls for local paper and read-only orders.

Order value is absolute quantity times the supplied execution price and FX
rate, excluding fees. Position exposure is the long market value (mark price,
then cost basis) plus open buy orders; pending sells do not reduce exposure.
Daily turnover counts accepted order notional on the current UTC date, including
cancelled orders, which is a conservative pre-trade ceiling.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Mapping, Protocol, Sequence

import yaml

from etf_cockpit.core.paths import CONFIG_DIR


PRE_TRADE_LIMITS_FILE = "pre_trade_limits_v1.yaml"
PRE_TRADE_AUDIT_SCHEMA = "pre_trade_controls_audit.v1"
_ZERO_HASH = "0" * 64
_OVERRIDEABLE_CONTROLS = frozenset(
    {"max_order_value", "max_position_exposure", "max_daily_turnover", "allowed_instruments"}
)


class PreTradeControlError(ValueError):
    """Invalid limits, audit history, or control operation."""


@dataclass(frozen=True)
class PreTradeLimits:
    max_order_value: Decimal
    max_position_exposure: Decimal
    max_daily_turnover: Decimal
    allowed_instruments: frozenset[str]
    cancel_open_paper_orders_on_kill_switch: bool
    max_override_ttl_seconds: int


@dataclass(frozen=True)
class PreTradeDecision:
    allowed: bool
    control: str | None
    reason: str
    order_value: Decimal | None = None
    position_exposure: Decimal | None = None
    daily_turnover: Decimal | None = None
    override_id: str | None = None
    execution_allowed: bool = False


class _PaperOrderLedger(Protocol):
    def orders(self) -> tuple[dict[str, object], ...]: ...

    def _cancel_order_locked(
        self, order_id: str, *, reason: str, occurred_at: datetime | None = None
    ) -> dict[str, object]: ...


class PreTradeControls:
    """Evaluate pre-trade limits and keep a hash-chained local audit journal."""

    def __init__(
        self,
        root: Path,
        *,
        account_id: str = "local-paper",
        limits_path: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.account_id = _clean_text(account_id, "account_id", 120)
        if limits_path is not None:
            self.limits_path = Path(limits_path)
        else:
            local_config = self.root / "configs" / PRE_TRADE_LIMITS_FILE
            packaged_config = CONFIG_DIR / PRE_TRADE_LIMITS_FILE
            source_config = CONFIG_DIR / PRE_TRADE_LIMITS_FILE
            self.limits_path = next(
                (candidate for candidate in (local_config, packaged_config, source_config) if candidate.is_file()),
                local_config,
            )
        self.audit_path = self.root / "data" / "operations" / "pre_trade" / self.account_id / "audit.jsonl"
        self._lock = threading.RLock()

    def evaluate_order(
        self,
        proposal: Mapping[str, object],
        *,
        execution_price: float,
        quantity_delta: float,
        fx_rate: float,
        positions: Mapping[str, object] | None = None,
        open_orders: Mapping[str, object] | None = None,
        paper_events: Sequence[Mapping[str, object]] | None = None,
        daily_turnover: float | None = None,
        broker_state: object | None = None,
        path: str = "read_only",
        who: str = "pre_trade_controls",
        occurred_at: datetime | None = None,
        override_id: str | None = None,
    ) -> PreTradeDecision:
        """Check immutable limits independently of a model proposal decision.

        The paper path supplies replayed local positions, orders, and events.
        Read-only callers must supply a reconciled broker state and the current
        exposure and turnover observations; absent observations fail closed.
        """

        at = _aware_utc(occurred_at or datetime.now(timezone.utc), "occurred_at")
        try:
            actor = _clean_text(who, "who", 120)
        except PreTradeControlError:
            actor = "pre_trade_controls"
        try:
            if not isinstance(proposal, Mapping):
                raise PreTradeControlError("Proposal state is unavailable.")
            proposal_id = _clean_text(proposal.get("proposal_id"), "proposal_id", 160)
            instrument_id = _clean_text(proposal.get("instrument_id"), "instrument_id", 80).upper()
        except PreTradeControlError as exc:
            return self._block("order_state_unknown", str(exc), actor, at)

        try:
            events = self._read_events()
        except PreTradeControlError:
            raise
        self._audit_expired_overrides(events, at)
        events = self._read_events()
        try:
            limits = self.load_limits()
        except PreTradeControlError as exc:
            return self._block(
                "limits_config", str(exc), actor, at, proposal_id=proposal_id, instrument_id=instrument_id
            )

        if self._kill_switch_active(events):
            return self._block(
                "kill_switch", "The independent pre-trade kill switch is active.", actor, at,
                proposal_id=proposal_id, instrument_id=instrument_id,
            )
        if path not in {"paper", "read_only"}:
            return self._block("path_unknown", "The order path is unknown.", actor, at, proposal_id=proposal_id)
        if broker_state is not None:
            if not _broker_state_is_current(broker_state, at):
                return self._block(
                    "broker_state_stale", "Broker reconciliation is not current at the evaluation instant.", actor, at,
                    proposal_id=proposal_id, instrument_id=instrument_id,
                )
            if not _broker_state_is_known(broker_state, at):
                return self._block(
                    "broker_state_unknown", "Broker or account reconciliation is not fully known.", actor, at,
                    proposal_id=proposal_id, instrument_id=instrument_id,
                )
        if path == "read_only" and broker_state is None:
            return self._block(
                "broker_state_unknown", "A reconciled broker state is required for the read-only path.", actor, at,
                proposal_id=proposal_id, instrument_id=instrument_id,
            )
        if not isinstance(proposal, Mapping) or not instrument_id:
            return self._block("order_state_unknown", "Proposal identity is unavailable.", actor, at)

        try:
            quantity = _finite_number(quantity_delta, "quantity_delta")
            price = _positive_number(execution_price, "execution_price")
            fx = _positive_number(fx_rate, "fx_rate")
            if quantity == 0:
                raise PreTradeControlError("A zero-quantity order is not valid.")
            order_value = abs(quantity) * price * fx
            positions_value, open_orders_value = _current_exposure(instrument_id, positions, open_orders)
            current_turnover = _daily_turnover(at, paper_events, daily_turnover, path)
            sell_quantity_within_holding = True
            if quantity < 0:
                position = positions.get(instrument_id, {})
                assert isinstance(position, Mapping)
                held_quantity = _finite_number(position.get("quantity", 0), "position quantity")
                open_sell_quantity = Decimal("0")
                for order in open_orders.values():
                    assert isinstance(order, Mapping)
                    if (
                        str(order.get("instrument_id", "")).upper() != instrument_id
                        or str(order.get("status")) not in {"accepted", "partially_filled"}
                        or str(order.get("side")) != "sell"
                    ):
                        continue
                    remaining = _finite_number(order.get("remaining_quantity"), "open sell remaining quantity")
                    if remaining < 0:
                        raise PreTradeControlError("An open sell order has invalid remaining quantity.")
                    open_sell_quantity += remaining
                sell_quantity_within_holding = abs(quantity) <= held_quantity - open_sell_quantity
        except PreTradeControlError as exc:
            return self._block(
                "order_state_unknown", str(exc), actor, at, proposal_id=proposal_id, instrument_id=instrument_id
            )

        current_exposure = positions_value + open_orders_value
        proposed_exposure = max(Decimal("0"), current_exposure + (order_value if quantity > 0 else -order_value))
        checks = (
            ("sell_quantity_within_holding", sell_quantity_within_holding,
             "Sell quantity exceeds holdings after open sell orders."),
            ("allowed_instruments", instrument_id in limits.allowed_instruments,
             f"Instrument {instrument_id} is not in the independently configured allowlist."),
            ("max_order_value", order_value <= limits.max_order_value,
             f"Order value {order_value:.8f} exceeds the hard limit {limits.max_order_value:.8f}."),
            ("max_position_exposure", proposed_exposure <= limits.max_position_exposure,
             f"Position exposure {proposed_exposure:.8f} exceeds the hard limit {limits.max_position_exposure:.8f}."),
            ("max_daily_turnover", current_turnover + order_value <= limits.max_daily_turnover,
             f"Daily turnover {current_turnover + order_value:.8f} exceeds the hard limit {limits.max_daily_turnover:.8f}."),
        )
        overrides_to_record: list[Mapping[str, object]] = []
        for control, passes, reason in checks:
            if passes:
                continue
            grant = self._find_override(events, control, proposal_id, at, override_id)
            if grant is None:
                return self._block(
                    control, reason, actor, at, proposal_id=proposal_id, instrument_id=instrument_id,
                    order_value=order_value, position_exposure=proposed_exposure,
                    daily_turnover=current_turnover + order_value,
                )
            overrides_to_record.append(grant)
        for grant in overrides_to_record:
            grant_payload = grant["details"]
            self._append_event(
                "override_used", who=actor, when=at, why=str(grant_payload["why"]),
                expiry=str(grant_payload["expiry"]), details={
                    "override_id": str(grant_payload["override_id"]),
                    "control": str(grant_payload["control"]),
                    "proposal_id": proposal_id,
                    "maker": str(grant_payload["maker"]),
                    "checker": str(grant_payload["checker"]),
                },
            )
        used_override_id = None if not overrides_to_record else str(
            overrides_to_record[0]["details"]["override_id"]
        )
        reason = (
            "All independent pre-trade controls passed."
            if not overrides_to_record
            else "Independent controls passed under explicit, maker/checker overrides."
        )
        return PreTradeDecision(
            True, None if not overrides_to_record else str(overrides_to_record[0]["details"]["control"]),
            reason, order_value, proposed_exposure, current_turnover + order_value,
            used_override_id, False,
        )

    def grant_override(
        self,
        override_id: str,
        *,
        control: str,
        proposal_id: str,
        maker: str,
        checker: str,
        reason: str,
        expires_at: datetime,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Record a one-order exception approved by two distinct people."""

        at = _aware_utc(occurred_at or datetime.now(timezone.utc), "occurred_at")
        override_key = _clean_text(override_id, "override_id", 160)
        proposal_key = _clean_text(proposal_id, "proposal_id", 160)
        maker_key = _clean_text(maker, "maker", 120)
        checker_key = _clean_text(checker, "checker", 120)
        why = _clean_text(reason, "reason", 500)
        control_key = _clean_text(control, "control", 80)
        expiry = _aware_utc(expires_at, "expires_at")
        expiry_text = _iso(expiry)
        details = {
            "override_id": override_key, "control": control_key, "proposal_id": proposal_key,
            "maker": maker_key, "checker": checker_key,
        }
        if maker_key == checker_key:
            return self._reject_override(
                "self-approved overrides are forbidden", maker_key, at, why, expiry_text, details
            )
        if control_key not in _OVERRIDEABLE_CONTROLS:
            return self._reject_override("the requested control cannot be overridden", maker_key, at, why, expiry_text, details)
        if expiry <= at:
            return self._reject_override("override expiry must be in the future", maker_key, at, why, expiry_text, details)
        try:
            limits = self.load_limits()
        except PreTradeControlError as exc:
            return self._reject_override(str(exc), maker_key, at, why, expiry_text, details)
        if (expiry - at) > timedelta(seconds=limits.max_override_ttl_seconds):
            return self._reject_override("override expiry exceeds the configured maximum TTL", maker_key, at, why, expiry_text, details)

        events = self._read_events()
        if any(
            event.get("event_type") == "override_granted"
            and isinstance(event.get("details"), Mapping)
            and event["details"].get("override_id") == override_key
            for event in events
        ):
            return self._reject_override("override ID has already been used", maker_key, at, why, expiry_text, details)
        payload = {**details, "why": why, "expiry": expiry_text}
        return self._append_event(
            "override_granted", who=maker_key, when=at, why=why, expiry=expiry_text,
            details=payload,
        )

    def activate_kill_switch(
        self,
        *,
        who: str,
        reason: str,
        paper_ledger: _PaperOrderLedger,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Activate the persisted kill switch and cancel open paper orders."""

        at = _aware_utc(occurred_at or datetime.now(timezone.utc), "occurred_at")
        actor = _clean_text(who, "who", 120)
        why = _clean_text(reason, "reason", 500)
        try:
            limits = self.load_limits()
        except PreTradeControlError as exc:
            return self._block("limits_config", str(exc), actor, at)
        with paper_ledger._lock, paper_ledger._file_lock():
            activated = self._append_event(
                "kill_switch_activated", who=actor, when=at, why=why, expiry=None,
                details={"cancel_open_paper_orders": limits.cancel_open_paper_orders_on_kill_switch},
            )
            if limits.cancel_open_paper_orders_on_kill_switch:
                events = paper_ledger._read_events()
                state = paper_ledger._replay(events)
                orders = state["orders"]
                if isinstance(orders, Mapping):
                    for order in orders.values():
                        if not isinstance(order, Mapping):
                            raise PreTradeControlError("Paper order state is invalid during kill-switch cancellation.")
                        status = str(order.get("status", "unknown"))
                        if status not in {"filled", "cancelled"}:
                            paper_ledger._cancel_order_locked(
                                str(order["order_id"]), reason=f"Kill switch: {why}", occurred_at=at
                            )
        return activated

    def clear_kill_switch(
        self, *, who: str, reason: str, occurred_at: datetime | None = None
    ) -> dict[str, object]:
        at = _aware_utc(occurred_at or datetime.now(timezone.utc), "occurred_at")
        return self._append_event(
            "kill_switch_cleared", who=_clean_text(who, "who", 120),
            when=at, why=_clean_text(reason, "reason", 500), expiry=None, details={},
        )

    def kill_switch_active(self) -> bool:
        """Return the current persisted switch state for a caller already in its order lock."""

        return self._kill_switch_active(self._read_events())

    def load_limits(self) -> PreTradeLimits:
        """Load a complete separate config; missing or malformed data is fatal."""

        if not self.limits_path.is_file():
            raise PreTradeControlError("Pre-trade limits configuration is missing.")
        try:
            document = yaml.safe_load(self.limits_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PreTradeControlError("Pre-trade limits configuration cannot be read.") from exc
        if not isinstance(document, Mapping) or document.get("schema_version") != "pre_trade_limits.v1":
            raise PreTradeControlError("Pre-trade limits configuration has an unsupported schema.")
        allowed = document.get("allowed_instruments")
        if not isinstance(allowed, list) or not allowed or any(not isinstance(item, str) for item in allowed):
            raise PreTradeControlError("Pre-trade instrument allowlist is missing or invalid.")
        allowed_set = frozenset(_clean_text(item, "allowed instrument", 80).upper() for item in allowed)
        if len(allowed_set) != len(allowed):
            raise PreTradeControlError("Pre-trade instrument allowlist contains duplicates.")
        cancel = document.get("cancel_open_paper_orders_on_kill_switch")
        ttl = document.get("max_override_ttl_seconds")
        if not isinstance(cancel, bool) or isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise PreTradeControlError("Pre-trade operational limits are missing or invalid.")
        return PreTradeLimits(
            _positive_number(document.get("max_order_value"), "max_order_value"),
            _positive_number(document.get("max_position_exposure"), "max_position_exposure"),
            _positive_number(document.get("max_daily_turnover"), "max_daily_turnover"),
            allowed_set, cancel, ttl,
        )

    def audit_events(self) -> tuple[dict[str, object], ...]:
        """Return verified immutable control-audit entries for local inspection."""

        return tuple(self._read_events())

    def _block(
        self,
        control: str,
        reason: str,
        who: str,
        at: datetime,
        *,
        proposal_id: str | None = None,
        instrument_id: str | None = None,
        order_value: float | None = None,
        position_exposure: float | None = None,
        daily_turnover: float | None = None,
    ) -> PreTradeDecision:
        details: dict[str, object] = {"control": control}
        if proposal_id is not None:
            details["proposal_id"] = proposal_id
        if instrument_id is not None:
            details["instrument_id"] = instrument_id
        self._append_event("order_blocked", who=who, when=at, why=reason, expiry=None, details=details)
        return PreTradeDecision(
            False, control, reason, order_value, position_exposure, daily_turnover, None, False
        )

    def _reject_override(
        self,
        reason: str,
        who: str,
        at: datetime,
        why: str,
        expiry: str,
        details: Mapping[str, object],
    ) -> dict[str, object]:
        return self._append_event(
            "override_rejected", who=who, when=at, why=f"{why}: {reason}", expiry=expiry,
            details={**details, "rejection_reason": reason},
        )

    def _audit_expired_overrides(self, events: Sequence[Mapping[str, object]], at: datetime) -> None:
        expired = {
            str(event.get("details", {}).get("override_id"))
            for event in events
            if event.get("event_type") == "override_expired" and isinstance(event.get("details"), Mapping)
        }
        for event in events:
            details = event.get("details")
            if event.get("event_type") != "override_granted" or not isinstance(details, Mapping):
                continue
            override_id = str(details.get("override_id", ""))
            try:
                expiry = _aware_utc(datetime.fromisoformat(str(details["expiry"])), "expiry")
            except (KeyError, ValueError, PreTradeControlError) as exc:
                raise PreTradeControlError("Override audit entry has invalid expiry.") from exc
            if override_id not in expired and expiry <= at:
                self._append_event(
                    "override_expired", who="pre_trade_controls", when=at,
                    why="The approved override reached its expiry.", expiry=_iso(expiry),
                    details={"override_id": override_id, "proposal_id": str(details["proposal_id"]),
                             "control": str(details["control"]), "maker": str(details["maker"]),
                             "checker": str(details["checker"])},
                )
                expired.add(override_id)

    def _find_override(
        self,
        events: Sequence[Mapping[str, object]],
        control: str,
        proposal_id: str,
        at: datetime,
        requested_override_id: str | None,
    ) -> Mapping[str, object] | None:
        expired = {
            str(event.get("details", {}).get("override_id"))
            for event in events
            if event.get("event_type") == "override_expired" and isinstance(event.get("details"), Mapping)
        }
        used = {
            str(event.get("details", {}).get("override_id"))
            for event in events
            if event.get("event_type") == "override_used" and isinstance(event.get("details"), Mapping)
        }
        for event in reversed(events):
            details = event.get("details")
            if event.get("event_type") != "override_granted" or not isinstance(details, Mapping):
                continue
            override_key = str(details.get("override_id", ""))
            if (
                override_key in expired or override_key in used
                or (requested_override_id is not None and override_key != requested_override_id)
                or details.get("control") != control or details.get("proposal_id") != proposal_id
            ):
                continue
            expiry = _aware_utc(datetime.fromisoformat(str(details["expiry"])), "override expiry")
            if expiry > at:
                return event
        return None

    @staticmethod
    def _kill_switch_active(events: Sequence[Mapping[str, object]]) -> bool:
        active = False
        for event in events:
            if event.get("event_type") == "kill_switch_activated":
                active = True
            elif event.get("event_type") == "kill_switch_cleared":
                active = False
        return active

    def _read_events(self) -> list[dict[str, object]]:
        if not self.audit_path.exists():
            return []
        try:
            rows = self.audit_path.read_bytes().splitlines()
        except OSError as exc:
            raise PreTradeControlError("Pre-trade audit journal cannot be read.") from exc
        events: list[dict[str, object]] = []
        prior_hash = _ZERO_HASH
        for sequence, row in enumerate(rows, start=1):
            try:
                event = json.loads(row)
                if (
                    not isinstance(event, dict)
                    or event.get("schema_version") != PRE_TRADE_AUDIT_SCHEMA
                    or event.get("sequence") != sequence
                    or event.get("prior_event_hash") != prior_hash
                    or not isinstance(event.get("details"), dict)
                    or any(not event.get(field) for field in ("event_type", "who", "when", "why"))
                    or "expiry" not in event
                ):
                    raise ValueError("invalid event shape")
                supplied_hash = event.get("event_hash")
                canonical = {key: value for key, value in event.items() if key != "event_hash"}
                expected_hash = _digest(canonical)
                if supplied_hash != expected_hash:
                    raise ValueError("invalid event hash")
                prior_hash = str(supplied_hash)
                events.append(event)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise PreTradeControlError("Pre-trade audit journal is malformed or changed.") from exc
        return events

    def _append_event(
        self,
        event_type: str,
        *,
        who: str,
        when: datetime,
        why: str,
        expiry: str | None,
        details: Mapping[str, object],
    ) -> dict[str, object]:
        payload = _json_copy(details)
        with self._lock, self._file_lock():
            events = self._read_events()
            event: dict[str, object] = {
                "schema_version": PRE_TRADE_AUDIT_SCHEMA,
                "sequence": len(events) + 1,
                "event_type": _clean_text(event_type, "event_type", 80),
                "who": _clean_text(who, "who", 120),
                "when": _iso(_aware_utc(when, "when")),
                "why": _clean_text(why, "why", 500),
                "expiry": expiry,
                "details": payload,
                "prior_event_hash": str(events[-1]["event_hash"]) if events else _ZERO_HASH,
            }
            event["event_hash"] = _digest(event)
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return event

    @contextmanager
    def _file_lock(self):
        lock_path = self.audit_path.with_suffix(".lock")
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


def _broker_state_is_current(state: object, at: datetime) -> bool:
    value = getattr(state, "as_of", None)
    try:
        if isinstance(value, datetime):
            observed = _aware_utc(value, "broker reconciliation as_of")
        elif isinstance(value, str):
            observed = _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")), "broker reconciliation as_of")
        else:
            return False
    except (TypeError, ValueError, PreTradeControlError):
        return False
    return observed == at


def _broker_state_is_known(state: object, at: datetime) -> bool:
    statuses = (
        getattr(state, "account_status", None),
        getattr(state, "positions_status", None),
        getattr(state, "cash_status", None),
        getattr(state, "orders_status", None),
    )
    return (
        getattr(state, "connected", None) is True
        and _broker_state_is_current(state, at)
        and all(str(status).lower() == "reconciled" for status in statuses)
        and not getattr(state, "breaks", (None,))
    )


def _current_exposure(
    instrument_id: str,
    positions: Mapping[str, object] | None,
    open_orders: Mapping[str, object] | None,
) -> tuple[Decimal, Decimal]:
    if not isinstance(positions, Mapping) or not isinstance(open_orders, Mapping):
        raise PreTradeControlError("Current positions or open orders are unavailable.")
    position = positions.get(instrument_id, {})
    if not isinstance(position, Mapping):
        raise PreTradeControlError("Current position state is invalid.")
    quantity = _finite_number(position.get("quantity", 0), "position quantity")
    if quantity < 0:
        raise PreTradeControlError("Short position state is unsupported and blocks orders.")
    if quantity == 0:
        position_value = Decimal("0")
    else:
        mark = position.get("mark_price")
        price = _positive_number(position.get("average_cost") if mark is None else mark, "position price")
        fx = _positive_number(position.get("mark_fx_rate", 1), "position FX rate")
        position_value = quantity * price * fx

    pending_value = Decimal("0")
    for order in open_orders.values():
        if not isinstance(order, Mapping):
            raise PreTradeControlError("An open order has invalid state.")
        if str(order.get("instrument_id", "")).upper() != instrument_id or str(order.get("status")) not in {
            "accepted", "partially_filled"
        }:
            continue
        if str(order.get("side")) != "buy":
            continue
        remaining = _finite_number(order.get("remaining_quantity"), "open order remaining quantity")
        terms = order.get("monetary_terms")
        if not isinstance(terms, Mapping):
            terms = order
        order_price = _positive_number(terms.get("execution_price"), "open order price")
        order_fx = _positive_number(terms.get("fx_rate", 1), "open order FX rate")
        if remaining < 0:
            raise PreTradeControlError("An open order has invalid remaining quantity.")
        pending_value += remaining * order_price * order_fx
    return position_value, pending_value


def _daily_turnover(
    at: datetime,
    paper_events: Sequence[Mapping[str, object]] | None,
    supplied_turnover: object | None,
    path: str,
) -> Decimal:
    if path == "paper":
        if not isinstance(paper_events, Sequence):
            raise PreTradeControlError("Paper order history is unavailable.")
        today = at.date()
        turnover = Decimal("0")
        for event in paper_events:
            if not isinstance(event, Mapping):
                raise PreTradeControlError("Paper order history is invalid.")
            if event.get("event_type") != "order_accepted":
                continue
            try:
                event_time = _aware_utc(datetime.fromisoformat(str(event["occurred_at"])), "paper event time")
                payload = event["payload"]
                if not isinstance(payload, Mapping):
                    raise PreTradeControlError("Paper order history is invalid.")
                terms = payload.get("monetary_terms")
                if isinstance(terms, Mapping):
                    accepted_quantity = abs(_finite_number(terms.get("quantity_delta"), "accepted order quantity"))
                    accepted_price = _positive_number(terms.get("execution_price"), "accepted order price")
                    accepted_fx = _positive_number(terms.get("fx_rate", 1), "accepted order FX rate")
                else:
                    accepted_quantity = _positive_number(payload.get("quantity"), "accepted order quantity")
                    accepted_price = _positive_number(payload.get("execution_price"), "accepted order price")
                    accepted_fx = _positive_number(payload.get("fx_rate", 1), "accepted order FX rate")
                value = accepted_quantity * accepted_price * accepted_fx
            except (KeyError, ValueError) as exc:
                raise PreTradeControlError("Paper order history is invalid.") from exc
            if event_time.date() == today:
                turnover += value
        return turnover
    if supplied_turnover is None:
        raise PreTradeControlError("Current daily turnover is unavailable.")
    value = _finite_number(supplied_turnover, "daily_turnover")
    if value < 0:
        raise PreTradeControlError("Current daily turnover cannot be negative.")
    return value


def _clean_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise PreTradeControlError(f"{label} must be text.")
    text = value.strip()
    if not text or len(text) > maximum or any(ord(char) < 32 for char in text):
        raise PreTradeControlError(f"{label} is invalid.")
    return text


def _finite_number(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise PreTradeControlError(f"{label} must be numeric.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise PreTradeControlError(f"{label} must be numeric.") from exc
    if not number.is_finite():
        raise PreTradeControlError(f"{label} must be finite.")
    return number


def _positive_number(value: object, label: str) -> Decimal:
    number = _finite_number(value, label)
    if number <= 0:
        raise PreTradeControlError(f"{label} must be positive.")
    return number


def _aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PreTradeControlError(f"{label} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _json_copy(value: Mapping[str, object]) -> dict[str, object]:
    try:
        copied = json.loads(json.dumps(dict(value), sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise PreTradeControlError("Audit details must be JSON serializable.") from exc
    if not isinstance(copied, dict):
        raise PreTradeControlError("Audit details must be a JSON object.")
    return copied


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["PreTradeControlError", "PreTradeControls", "PreTradeDecision", "PreTradeLimits"]
