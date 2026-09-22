from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Literal, Mapping

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import OPERATIONS_DIR
from etf_cockpit.data.event_calendar import EVENT_CLEAN_PATH
from etf_cockpit.portfolio.event_controls import EventBlockPolicy, evaluate_event_control, verify_event_control

OperationEnvironment = Literal["paper", "live"]
OperationStatus = Literal["preview", "queued", "running", "completed", "cancelled", "failed", "blocked"]


@dataclass(frozen=True)
class OperationRecord:
    """Durable, local projection of a proposed state-changing operation.

    The record is deliberately a proposal and workflow trace, never a broker
    order.  Its four separate sections make the decision boundary visible to
    both the UI and later audit/export consumers.
    """

    operation_id: str
    environment: OperationEnvironment
    action: str
    instrument_id: str
    quantity: float
    currency: str
    status: OperationStatus
    preview: dict[str, object]
    authority: dict[str, object]
    result: dict[str, object]
    audit: dict[str, object]

    def with_update(self, **changes: object) -> "OperationRecord":
        return replace(self, **changes)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": "operations.v1",
            "operation_id": self.operation_id,
            "environment": self.environment,
            "action": self.action,
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "currency": self.currency,
            "status": self.status,
            "preview": self.preview,
            "authority": self.authority,
            "result": self.result,
            "audit": self.audit,
        }


def build_operation_preview(
    *,
    environment: OperationEnvironment,
    instrument_id: str,
    quantity: float,
    currency: str = "EUR",
    event_policy: EventBlockPolicy | None = None,
    decision_time: datetime | None = None,
    event_calendar_path: Path = EVENT_CLEAN_PATH,
) -> OperationRecord:
    """Create a deterministic proposal before any workflow is submitted."""

    instrument = str(instrument_id).strip().upper()
    if not instrument:
        raise ValueError("An instrument is required for an operation preview.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if environment not in {"paper", "live"}:
        raise ValueError(f"Unsupported operation environment: {environment}")

    if event_policy is not None and decision_time is None:
        raise ValueError("Explicit event policy requires an aware decision time")
    event_decision = evaluate_event_control(policy=event_policy, target="order_preview", instrument_id=instrument,
        decision_time=decision_time, calendar_path=event_calendar_path)
    operation_id = _preview_id(environment, instrument, quantity, currency, event_decision.to_payload())
    live = environment == "live"
    authority: dict[str, object] = {
        "stage": "live_disabled" if live else "paper_preview",
        "execution_allowed": False,
        "submission_allowed": not live and not event_decision.blocks,
        "reason": "Live order submission is disabled by product policy." if live else event_decision.reason if event_decision.blocks else "Paper preview only; no order is transmitted.",
    }
    status: OperationStatus = "blocked" if live or event_decision.blocks else "preview"
    message = authority["reason"]
    return OperationRecord(
        operation_id=operation_id,
        environment=environment,
        action="proposal_preview",
        instrument_id=instrument,
        quantity=float(quantity),
        currency=str(currency).strip().upper() or "EUR",
        status=status,
        preview={
            "instrument_id": instrument,
            "quantity": float(quantity),
            "currency": str(currency).strip().upper() or "EUR",
            "estimated_notional": None,
            "assumptions": ["No live quote or broker fill is requested.", "Paper preview is evidence, not an order."],
        },
        authority=authority,
        result={"status": status, "message": message},
        audit={"record_id": operation_id, "workflow_id": None, "event_chain": "local_durable_scheduler", "event_control": event_decision.to_payload()},
    )


def save_operation_record(record: OperationRecord, *, directory: Path = OPERATIONS_DIR) -> Path:
    path = directory / f"{record.operation_id}.json"
    atomic_write_json(path, record.to_payload())
    return path


def _preview_id(environment: str, instrument: str, quantity: float, currency: str, event_control: dict) -> str:
    identity = json.dumps(
        {"action": "proposal_preview", "environment": environment, "instrument_id": instrument,
         "quantity": float(quantity), "currency": str(currency).strip().upper() or "EUR", "event_control": event_control},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return f"op_{hashlib.sha256(identity).hexdigest()[:20]}"


def validate_operation_record(payload: Mapping[str, object], *, for_submission: bool = False) -> None:
    """Verify preview identity and restrictions; legacy records are read-only."""
    if payload.get("schema_version") != "operations.v1" or payload.get("action") != "proposal_preview":
        raise ValueError("Unsupported operation schema or action")
    environment = payload.get("environment")
    instrument = payload.get("instrument_id")
    currency = payload.get("currency")
    quantity = payload.get("quantity")
    authority = payload.get("authority")
    audit = payload.get("audit")
    if environment not in {"paper", "live"} or not isinstance(environment, str):
        raise ValueError("Invalid operation environment")
    if not isinstance(instrument, str) or not instrument or instrument != instrument.strip().upper():
        raise ValueError("Invalid operation instrument")
    if not isinstance(currency, str) or not currency or currency != currency.strip().upper():
        raise ValueError("Invalid operation currency")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Invalid operation quantity")
    if not isinstance(authority, Mapping) or not isinstance(audit, Mapping):
        raise ValueError("Missing operation authority or audit")
    if authority.get("execution_allowed") is not False or audit.get("record_id") != payload.get("operation_id"):
        raise ValueError("Invalid operation authority or audit identity")
    blocked = environment == "live"
    if "event_control" in audit:
        event = audit["event_control"]
        if not isinstance(event, dict):
            raise ValueError("Missing event-control evidence")
        decision = verify_event_control(event, target="order_preview", instrument_id=instrument)
        if payload.get("operation_id") != _preview_id(environment, instrument, quantity, currency, event):
            raise ValueError("Operation identity does not match event evidence")
        blocked = blocked or decision.blocks
    else:
        # Original v1 IDs hashed these exact fields before quantity was stored
        # as float. Accept either original numeric representation, never an
        # arbitrary op_* ID or a new event-bound ID stripped of its audit.
        quantities = [float(quantity)]
        if float(quantity).is_integer():
            quantities.append(int(quantity))
        legacy_ids = set()
        for original_quantity in quantities:
            identity = json.dumps({"action": "proposal_preview", "environment": environment,
                "instrument_id": instrument, "quantity": original_quantity, "currency": currency},
                sort_keys=True, separators=(",", ":")).encode("utf-8")
            legacy_ids.add(f"op_{hashlib.sha256(identity).hexdigest()[:20]}")
        if payload.get("operation_id") not in legacy_ids or for_submission:
            raise ValueError("Legacy identity cannot be verified; create a fresh preview")
    if authority.get("stage") != ("live_disabled" if environment == "live" else "paper_preview"):
        raise ValueError("Operation authority stage mismatch")
    if authority.get("submission_allowed") is not (not blocked):
        raise ValueError("Operation submission authority mismatch")
    if blocked and payload.get("status") != "blocked":
        raise ValueError("Blocked operation status mismatch")
    if for_submission and (blocked or payload.get("status") != "preview"):
        raise ValueError("Operation policy blocks workflow submission")


def load_operation_records(*, directory: Path = OPERATIONS_DIR) -> tuple[dict[str, object], ...]:
    if not directory.exists():
        return ()
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("op_*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            try:
                validate_operation_record(payload)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            records.append(payload)
    return tuple(records)


__all__ = ["OperationRecord", "build_operation_preview", "load_operation_records", "save_operation_record", "validate_operation_record"]
