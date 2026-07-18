from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Literal

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import OPERATIONS_DIR

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
) -> OperationRecord:
    """Create a deterministic proposal before any workflow is submitted."""

    instrument = str(instrument_id).strip().upper()
    if not instrument:
        raise ValueError("An instrument is required for an operation preview.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if environment not in {"paper", "live"}:
        raise ValueError(f"Unsupported operation environment: {environment}")

    identity = json.dumps(
        {"action": "proposal_preview", "environment": environment, "instrument_id": instrument, "quantity": quantity, "currency": currency},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    operation_id = f"op_{hashlib.sha256(identity).hexdigest()[:20]}"
    live = environment == "live"
    authority = {
        "stage": "live_disabled" if live else "paper_preview",
        "execution_allowed": False,
        "submission_allowed": False if live else True,
        "reason": "Live order submission is disabled by product policy." if live else "Paper preview only; no order is transmitted.",
    }
    status: OperationStatus = "blocked" if live else "preview"
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
        audit={"record_id": operation_id, "workflow_id": None, "event_chain": "local_durable_scheduler"},
    )


def save_operation_record(record: OperationRecord, *, directory: Path = OPERATIONS_DIR) -> Path:
    path = directory / f"{record.operation_id}.json"
    atomic_write_json(path, record.to_payload())
    return path


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
            records.append(payload)
    return tuple(records)


__all__ = ["OperationRecord", "build_operation_preview", "load_operation_records", "save_operation_record"]
