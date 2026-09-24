"""Explicit local calendar blackout policy; never an investment signal."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from etf_cockpit.application.contracts import EventBlockPolicy

from etf_cockpit.data.event_calendar import (
    EVENT_CLEAN_PATH, events_available_as_of,
    load_calendar_events_strict, calendar_frame_checksum,
)

EventTarget = Literal["proposal_preview", "order_preview"]


def _checksum(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EventControlDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    target: EventTarget
    instrument_id: str
    decision_time: str | None
    status: Literal["context_only", "clear", "blocked", "evidence_unavailable"]
    policy: EventBlockPolicy | None
    policy_checksum: str
    frame_checksum: str
    matched_events: tuple[tuple[str, str], ...] = ()
    reason: str
    execution_allowed: Literal[False] = False
    executable_authority: Literal[False] = False

    @property
    def blocks(self) -> bool:
        return self.policy is not None and self.status in {"blocked", "evidence_unavailable"}

    def to_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload["decision_checksum"] = _checksum(payload)
        return payload


def evaluate_event_control(*, policy: EventBlockPolicy | None, target: EventTarget,
                           instrument_id: str, decision_time: datetime | None,
                           calendar_path: Path = EVENT_CLEAN_PATH) -> EventControlDecision:
    if decision_time is not None and (decision_time.tzinfo is None or decision_time.utcoffset() is None):
        raise ValueError("Event decision time must include a timezone")
    if policy is not None and decision_time is None:
        raise ValueError("Explicit event policy requires a decision time")
    if target not in {"proposal_preview", "order_preview"} or not instrument_id.strip():
        raise ValueError("Unsupported event target or empty instrument")
    if policy is not None:
        policy = EventBlockPolicy.model_validate(policy.model_dump())
    identity = dict(target=target, instrument_id=instrument_id.strip().upper(),
                    decision_time=decision_time.astimezone(timezone.utc).isoformat() if decision_time is not None else None,
                    policy=policy, policy_checksum=policy.checksum if policy else "")
    if policy is None or target not in policy.targets:
        return EventControlDecision(**identity, status="context_only", frame_checksum="",
                                    reason="No event block policy applies to this preview.")
    if decision_time is None:
        raise ValueError("Explicit event policy requires a decision time")
    try:
        frame = load_calendar_events_strict(calendar_path)
        visible = events_available_as_of(frame, decision_time, identity["instrument_id"])
        matched = []
        for row in visible.to_dict("records"):
            if row["event_type"] not in policy.event_types or row["risk_level"] not in policy.risk_levels:
                continue
            if row["precision"] == "date":
                start = datetime.fromisoformat(row["event_date"]).replace(tzinfo=ZoneInfo(row["timezone_name"]))
                end = start + timedelta(days=1)
            else:
                start = datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))
                end = start
            start = start.astimezone(timezone.utc) - timedelta(minutes=policy.pre_minutes)
            end = end.astimezone(timezone.utc) + timedelta(minutes=policy.post_minutes)
            within = start <= decision_time < end if row["precision"] == "date" else start <= decision_time <= end
            if within:
                matched.append((row["event_id"], row["event_checksum"]))
        return EventControlDecision(**identity, status="blocked" if matched else "clear",
                                    frame_checksum=calendar_frame_checksum(visible), matched_events=tuple(sorted(matched)),
                                    reason="Explicit event policy blackout matched." if matched else "No available event matches the explicit blackout policy.")
    except (OSError, ValueError, KeyError, OverflowError):
        return EventControlDecision(**identity, status="evidence_unavailable", frame_checksum="",
                                    reason="Required canonical calendar evidence is missing or invalid.")


def verify_event_control(payload: dict, *, target: EventTarget, instrument_id: str,
                         decision_time: datetime | None = None) -> EventControlDecision:
    """Verify stored bindings without consulting today's calendar during replay."""
    if not isinstance(payload, dict):
        raise ValueError("Event decision must be an object")
    material = {key: value for key, value in payload.items() if key != "decision_checksum"}
    if payload.get("decision_checksum") != _checksum(material):
        raise ValueError("Event decision checksum mismatch")
    decision = EventControlDecision.model_validate(material)
    if decision.decision_time is not None:
        stored_time = datetime.fromisoformat(decision.decision_time)
        if stored_time.tzinfo is None or stored_time.utcoffset() is None:
            raise ValueError("Stored event decision time must include a timezone")
    elif decision.policy is not None:
        raise ValueError("Policy decision timestamp missing")
    if decision.target != target or decision.instrument_id != instrument_id.strip().upper():
        raise ValueError("Event decision target or instrument mismatch")
    if decision_time is not None:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None or decision.decision_time != decision_time.astimezone(timezone.utc).isoformat():
            raise ValueError("Event decision time mismatch")
    if decision.policy_checksum != (decision.policy.checksum if decision.policy else ""):
        raise ValueError("Event policy checksum mismatch")
    applies = decision.policy is not None and target in decision.policy.targets
    if (decision.status == "context_only") == applies:
        raise ValueError("Event policy applicability mismatch")
    if decision.status in {"clear", "blocked"} and len(decision.frame_checksum) != 64:
        raise ValueError("Event frame checksum missing")
    if bool(decision.matched_events) != (decision.status == "blocked"):
        raise ValueError("Event match evidence mismatch")
    return decision
