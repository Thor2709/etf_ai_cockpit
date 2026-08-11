"""Local, typed alerts and review reminders.

Alerts are informational local records.  This module deliberately does not
send notifications, mutate orders, or make scores/models authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StoredRecord,
    TransactionalStore,
)


ALERT_ENTITY_TYPE = "local_alert"
EXECUTION_ALLOWED = False


class AlertType(str, Enum):
    MATERIAL_SCORE_CHANGE = "material_score_change"
    RANK_CHANGE = "rank_change"
    NEWS_CONFLICT = "news_conflict"
    STALE_DATA = "stale_data"
    MODEL_FORECAST_FAILURE = "model_forecast_failure"
    REVIEW_DATE_ARRIVED = "review_date_arrived"
    RISK_LIMIT_BREACHED = "risk_limit_breached"
    TARGET_DRIFT_EXCEEDED = "target_drift_exceeded"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AlertStatus(str, Enum):
    ACTIVE = "active"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class IncidentDomain(str, Enum):
    GENERAL = "general"
    PORTFOLIO = "portfolio"
    ORDER = "order"
    MODEL = "model"


INCIDENT_RULES: dict[IncidentDomain, frozenset[AlertType]] = {
    IncidentDomain.GENERAL: frozenset(
        {
            AlertType.MATERIAL_SCORE_CHANGE,
            AlertType.RANK_CHANGE,
            AlertType.NEWS_CONFLICT,
            AlertType.STALE_DATA,
            AlertType.REVIEW_DATE_ARRIVED,
        }
    ),
    IncidentDomain.PORTFOLIO: frozenset(
        {AlertType.RISK_LIMIT_BREACHED, AlertType.TARGET_DRIFT_EXCEEDED}
    ),
    IncidentDomain.ORDER: frozenset({AlertType.RISK_LIMIT_BREACHED}),
    IncidentDomain.MODEL: frozenset({AlertType.MODEL_FORECAST_FAILURE}),
}


_ALERT_FIELDS = frozenset(
    {
        "alert_id",
        "dedupe_key",
        "alert_type",
        "subject_id",
        "title",
        "message",
        "severity",
        "confidence",
        "occurred_at",
        "available_at",
        "expires_at",
        "status",
        "snoozed_at",
        "snoozed_until",
        "snooze_history",
        "dismissed_at",
        "incident_domain",
        "evidence",
        "execution_allowed",
    }
)


def _utc_datetime(value: datetime | str, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    else:
        raise TypeError(f"{field} must be a timezone-aware datetime or ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _optional_datetime(value: datetime | str | None, *, field: str) -> datetime | None:
    if value is None:
        return None
    return _utc_datetime(value, field=field)


def _enum(value: Any, enum_type: type[Enum], *, field: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field} must be one of: {allowed}") from exc


def _text(value: Any, *, field: str, max_length: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return result


def _canonical_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _alert_id(alert_type: AlertType, subject_id: str, dedupe_key: str) -> str:
    identity = json.dumps(
        [alert_type.value, subject_id, dedupe_key],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


@dataclass(frozen=True)
class _SnoozeInterval:
    snoozed_at: datetime
    snoozed_until: datetime

    def __post_init__(self) -> None:
        snoozed_at = _utc_datetime(self.snoozed_at, field="snoozed_at")
        snoozed_until = _utc_datetime(self.snoozed_until, field="snoozed_until")
        object.__setattr__(self, "snoozed_at", snoozed_at)
        object.__setattr__(self, "snoozed_until", snoozed_until)
        if snoozed_at >= snoozed_until:
            raise ValueError("snoozed_at must be before snoozed_until")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "_SnoozeInterval":
        if not isinstance(data, Mapping):
            raise TypeError("snooze history entries must be mappings")
        fields = {"snoozed_at", "snoozed_until"}
        if set(data) != fields:
            raise ValueError("snooze history entries require exactly snoozed_at and snoozed_until")
        return cls(snoozed_at=data["snoozed_at"], snoozed_until=data["snoozed_until"])

    def to_dict(self) -> dict[str, str]:
        return {
            "snoozed_at": _canonical_datetime(self.snoozed_at),
            "snoozed_until": _canonical_datetime(self.snoozed_until),
        }


@dataclass(frozen=True)
class Alert:
    alert_id: str
    dedupe_key: str
    alert_type: AlertType
    subject_id: str
    title: str
    message: str
    severity: AlertSeverity
    confidence: AlertConfidence
    occurred_at: datetime
    available_at: datetime
    expires_at: datetime | None = None
    status: AlertStatus = AlertStatus.ACTIVE
    snoozed_at: datetime | None = None
    snoozed_until: datetime | None = None
    snooze_history: tuple[_SnoozeInterval, ...] = ()
    dismissed_at: datetime | None = None
    incident_domain: IncidentDomain = IncidentDomain.GENERAL
    evidence: Mapping[str, Any] = field(default_factory=dict)
    execution_allowed: bool = EXECUTION_ALLOWED

    def __post_init__(self) -> None:
        alert_type = _enum(self.alert_type, AlertType, field="alert_type")
        severity = _enum(self.severity, AlertSeverity, field="severity")
        confidence = _enum(self.confidence, AlertConfidence, field="confidence")
        status = _enum(self.status, AlertStatus, field="status")
        domain = _enum(self.incident_domain, IncidentDomain, field="incident_domain")
        object.__setattr__(self, "alert_type", alert_type)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "incident_domain", domain)
        subject_id = _text(self.subject_id, field="subject_id", max_length=256)
        dedupe_key = _text(self.dedupe_key, field="dedupe_key", max_length=512)
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "dedupe_key", dedupe_key)
        object.__setattr__(self, "title", _text(self.title, field="title"))
        object.__setattr__(self, "message", _text(self.message, field="message", max_length=4000))
        occurred_at = _utc_datetime(self.occurred_at, field="occurred_at")
        available_at = _utc_datetime(self.available_at, field="available_at")
        expires_at = _optional_datetime(self.expires_at, field="expires_at")
        snoozed_at = _optional_datetime(self.snoozed_at, field="snoozed_at")
        snoozed_until = _optional_datetime(self.snoozed_until, field="snoozed_until")
        if not isinstance(self.snooze_history, Sequence) or isinstance(self.snooze_history, (str, bytes)):
            raise TypeError("snooze_history must be a sequence")
        snooze_history = tuple(
            item if isinstance(item, _SnoozeInterval) else _SnoozeInterval.from_dict(item)
            for item in self.snooze_history
        )
        dismissed_at = _optional_datetime(self.dismissed_at, field="dismissed_at")
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "snoozed_at", snoozed_at)
        object.__setattr__(self, "snoozed_until", snoozed_until)
        object.__setattr__(self, "snooze_history", snooze_history)
        object.__setattr__(self, "dismissed_at", dismissed_at)
        if occurred_at > available_at:
            raise ValueError("available_at cannot precede occurred_at")
        if expires_at is not None and expires_at <= available_at:
            raise ValueError("expires_at must be after available_at")
        if not isinstance(self.alert_id, str) or self.alert_id != _alert_id(alert_type, subject_id, dedupe_key):
            raise ValueError("alert_id is not the deterministic ID for this alert identity")
        if not isinstance(self.execution_allowed, bool) or self.execution_allowed:
            raise ValueError("local alerts must keep execution_allowed=false")
        if not isinstance(self.evidence, Mapping):
            raise TypeError("evidence must be a mapping")
        try:
            json.dumps(dict(self.evidence), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("evidence must be JSON-serialisable and finite") from exc
        if alert_type not in INCIDENT_RULES[domain]:
            raise ValueError(f"{alert_type.value} is not valid for incident domain {domain.value}")
        if (snoozed_at is None) != (snoozed_until is None):
            raise ValueError("snoozed_at and snoozed_until must be provided together")
        if snoozed_at is not None and snoozed_until is not None:
            if snoozed_at >= snoozed_until:
                raise ValueError("snoozed_at must be before snoozed_until")
            if snoozed_at < available_at:
                raise ValueError("snoozed_at cannot precede available_at")
        if any(interval.snoozed_at < available_at for interval in snooze_history):
            raise ValueError("snooze history cannot precede available_at")
        if status is AlertStatus.SNOOZED and (snoozed_at is None or snoozed_until is None):
            raise ValueError("snoozed alerts require snoozed_at and snoozed_until")
        if status is AlertStatus.DISMISSED and dismissed_at is None:
            raise ValueError("dismissed alerts require dismissed_at")
        if status is not AlertStatus.DISMISSED and dismissed_at is not None:
            raise ValueError("dismissed_at is only valid for dismissed alerts")
        if dismissed_at is not None and dismissed_at < available_at:
            raise ValueError("dismissed_at cannot precede available_at")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Alert":
        if not isinstance(data, Mapping):
            raise TypeError("alert data must be a mapping")
        unknown = set(data) - _ALERT_FIELDS
        missing = _ALERT_FIELDS - set(data)
        if unknown:
            raise ValueError(f"unknown alert fields: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing alert fields: {sorted(missing)}")
        return cls(
            alert_id=data["alert_id"],
            dedupe_key=data["dedupe_key"],
            alert_type=data["alert_type"],
            subject_id=data["subject_id"],
            title=data["title"],
            message=data["message"],
            severity=data["severity"],
            confidence=data["confidence"],
            occurred_at=data["occurred_at"],
            available_at=data["available_at"],
            expires_at=data["expires_at"],
            status=data["status"],
            snoozed_at=data["snoozed_at"],
            snoozed_until=data["snoozed_until"],
            snooze_history=data["snooze_history"],
            dismissed_at=data["dismissed_at"],
            incident_domain=data["incident_domain"],
            evidence=data["evidence"],
            execution_allowed=data["execution_allowed"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "dedupe_key": self.dedupe_key,
            "alert_type": self.alert_type.value,
            "subject_id": self.subject_id,
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "confidence": self.confidence.value,
            "occurred_at": _canonical_datetime(self.occurred_at),
            "available_at": _canonical_datetime(self.available_at),
            "expires_at": _canonical_datetime(self.expires_at),
            "status": self.status.value,
            "snoozed_at": _canonical_datetime(self.snoozed_at),
            "snoozed_until": _canonical_datetime(self.snoozed_until),
            "snooze_history": [interval.to_dict() for interval in self.snooze_history],
            "dismissed_at": _canonical_datetime(self.dismissed_at),
            "incident_domain": self.incident_domain.value,
            "evidence": dict(self.evidence),
            "execution_allowed": False,
        }

    def is_blocked(self, policy: "AlertBlockPolicy | None" = None) -> bool:
        """Return true only when a caller supplies an explicit block policy."""

        return bool(self.status is AlertStatus.ACTIVE and policy is not None and policy.blocks(self))


def build_alert(
    alert_type: AlertType | str,
    *,
    subject_id: str,
    title: str,
    message: str,
    severity: AlertSeverity | str,
    confidence: AlertConfidence | str,
    occurred_at: datetime | str,
    available_at: datetime | str,
    dedupe_key: str,
    expires_at: datetime | str | None = None,
    incident_domain: IncidentDomain | str | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> Alert:
    typed_type = _enum(alert_type, AlertType, field="alert_type")
    typed_domain = (
        IncidentDomain.GENERAL
        if incident_domain is None
        else _enum(incident_domain, IncidentDomain, field="incident_domain")
    )
    if incident_domain is None:
        typed_domain = next(domain for domain, types in INCIDENT_RULES.items() if typed_type in types)
    subject = _text(subject_id, field="subject_id", max_length=256)
    dedupe = _text(dedupe_key, field="dedupe_key", max_length=512)
    return Alert(
        alert_id=_alert_id(typed_type, subject, dedupe),
        dedupe_key=dedupe,
        alert_type=typed_type,
        subject_id=subject,
        title=title,
        message=message,
        severity=_enum(severity, AlertSeverity, field="severity"),
        confidence=_enum(confidence, AlertConfidence, field="confidence"),
        occurred_at=_utc_datetime(occurred_at, field="occurred_at"),
        available_at=_utc_datetime(available_at, field="available_at"),
        expires_at=_optional_datetime(expires_at, field="expires_at"),
        incident_domain=typed_domain,
        evidence={} if evidence is None else evidence,
    )


@dataclass(frozen=True)
class AlertBlockPolicy:
    """An explicit, caller-owned policy; no default policy blocks anything."""

    policy_id: str
    alert_types: frozenset[AlertType] = frozenset()
    incident_domains: frozenset[IncidentDomain] = frozenset()
    severities: frozenset[AlertSeverity] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("policy_id must be non-empty")
        object.__setattr__(self, "alert_types", frozenset(_enum(value, AlertType, field="alert_types") for value in self.alert_types))
        object.__setattr__(self, "incident_domains", frozenset(_enum(value, IncidentDomain, field="incident_domains") for value in self.incident_domains))
        object.__setattr__(self, "severities", frozenset(_enum(value, AlertSeverity, field="severities") for value in self.severities))

    def blocks(self, alert: Alert) -> bool:
        return bool(
            alert.status is AlertStatus.ACTIVE
            and (
                alert.alert_type in self.alert_types
                or alert.incident_domain in self.incident_domains
                or alert.severity in self.severities
            )
        )


@dataclass(frozen=True)
class AlertRecord:
    alert: Alert
    revision: int
    created_at: str
    updated_at: str

    @property
    def alert_id(self) -> str:
        return self.alert.alert_id

    @property
    def status(self) -> AlertStatus:
        return self.alert.status


AlertRevisionConflict = StorageRevisionConflict


def evaluate_alerts_as_of(alerts: Iterable[Alert], as_of: datetime | str) -> tuple[Alert, ...]:
    """Evaluate only records available by ``as_of``; future evidence is excluded."""

    cutoff = _utc_datetime(as_of, field="as_of")
    result = []
    for alert in alerts:
        if not isinstance(alert, Alert):
            raise TypeError("historical evaluation accepts Alert values only")
        if alert.available_at > cutoff:
            continue
        status = alert.status
        if (
            alert.expires_at is not None
            and alert.expires_at <= cutoff
            and (alert.dismissed_at is None or alert.expires_at <= alert.dismissed_at)
        ):
            status = AlertStatus.EXPIRED
        elif alert.dismissed_at is not None and alert.dismissed_at <= cutoff:
            status = AlertStatus.DISMISSED
        elif any(
            interval.snoozed_at <= cutoff < interval.snoozed_until
            for interval in (
                *alert.snooze_history,
                *(
                    (_SnoozeInterval(alert.snoozed_at, alert.snoozed_until),)
                    if alert.snoozed_at is not None and alert.snoozed_until is not None
                    else ()
                ),
            )
        ):
            status = AlertStatus.SNOOZED
        else:
            status = AlertStatus.ACTIVE
        result.append(
            replace(
                alert,
                status=status,
                dismissed_at=None if status is not AlertStatus.DISMISSED else alert.dismissed_at,
            )
        )
    return tuple(sorted(result, key=lambda item: (item.occurred_at, item.alert_id)))


class AlertStore:
    """CAS-backed local persistence for alerts, reminders, snoozes and dismissals."""

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None):
        self.root = Path(root)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._store = TransactionalStore(self.root)

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "AlertStore":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    @staticmethod
    def _record(stored: StoredRecord) -> AlertRecord:
        return AlertRecord(
            alert=Alert.from_dict(stored.payload),
            revision=stored.revision,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )

    def create(self, alert: Alert) -> AlertRecord:
        if not isinstance(alert, Alert):
            raise TypeError("create expects an Alert")
        if alert.status is not AlertStatus.ACTIVE:
            raise ValueError("new alerts must start active")
        existing = self._store.get(ALERT_ENTITY_TYPE, alert.alert_id)
        if existing is not None:
            current = self._record(existing)
            if current.alert.dedupe_key != alert.dedupe_key or current.alert.alert_type is not alert.alert_type or current.alert.subject_id != alert.subject_id:
                raise AlertRevisionConflict("deterministic alert identity collides with different content")
            return current
        try:
            return self._record(self._store.put(ALERT_ENTITY_TYPE, alert.alert_id, alert.to_dict(), expected_revision=0))
        except StorageRevisionConflict:
            raced = self._store.get(ALERT_ENTITY_TYPE, alert.alert_id)
            if raced is None:
                raise
            return self._record(raced)

    def _get_raw(self, alert_id: str) -> AlertRecord:
        stored = self._store.get(ALERT_ENTITY_TYPE, _text(alert_id, field="alert_id", max_length=128))
        if stored is None:
            raise KeyError(f"unknown alert: {alert_id}")
        return self._record(stored)

    def get(self, alert_id: str) -> AlertRecord:
        record = self._get_raw(alert_id)
        now = _utc_datetime(self._clock(), field="clock")
        if record.alert.available_at > now:
            raise KeyError(f"alert is not yet available: {alert_id}")
        return self._refresh(record, now)

    def _refresh(self, record: AlertRecord, now: datetime) -> AlertRecord:
        if record.alert.status in {AlertStatus.ACTIVE, AlertStatus.SNOOZED} and record.alert.expires_at is not None and record.alert.expires_at <= now:
            return self._transition(record, replace(record.alert, status=AlertStatus.EXPIRED), expected_revision=record.revision)
        if record.alert.status is AlertStatus.SNOOZED and record.alert.snoozed_until is not None and record.alert.snoozed_until <= now:
            return self._transition(record, replace(record.alert, status=AlertStatus.ACTIVE), expected_revision=record.revision)
        return record

    def list(
        self,
        *,
        subject_id: str | None = None,
        as_of: datetime | str | None = None,
        include_inactive: bool = False,
        limit: int | None = None,
    ) -> tuple[AlertRecord, ...]:
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ValueError("limit must be a positive integer")
        records = [self._record(item) for item in self._store.list(ALERT_ENTITY_TYPE)]
        if subject_id is not None:
            subject = _text(subject_id, field="subject_id", max_length=256)
            records = [item for item in records if item.alert.subject_id == subject]
        if as_of is not None:
            evaluated = evaluate_alerts_as_of((item.alert for item in records), as_of)
            by_id = {item.alert_id: item for item in records}
            records = [replace(by_id[item.alert_id], alert=item) for item in evaluated]
        else:
            now = _utc_datetime(self._clock(), field="clock")
            records = [item for item in records if item.alert.available_at <= now]
            refreshed: list[AlertRecord] = []
            for item in records:
                try:
                    refreshed.append(self._refresh(item, now))
                except StorageRevisionConflict:
                    refreshed.append(self._get_raw(item.alert_id))
            records = refreshed
        if not include_inactive:
            records = [item for item in records if item.alert.status is AlertStatus.ACTIVE]
        records.sort(key=lambda item: (item.alert.occurred_at, item.alert.alert_id), reverse=True)
        return tuple(records if limit is None else records[:limit])

    def _transition(self, record: AlertRecord, alert: Alert, *, expected_revision: int) -> AlertRecord:
        if expected_revision != record.revision:
            raise StorageRevisionConflict(
                f"expected revision {expected_revision}, current revision is {record.revision}"
            )
        return self._record(self._store.put(ALERT_ENTITY_TYPE, alert.alert_id, alert.to_dict(), expected_revision=expected_revision))

    def snooze(self, alert_id: str, until: datetime | str, *, expected_revision: int) -> AlertRecord:
        record = self.get(alert_id)
        until_dt = _utc_datetime(until, field="until")
        now = _utc_datetime(self._clock(), field="clock")
        if until_dt <= now:
            raise ValueError("snooze until must be in the future")
        if record.alert.status not in {AlertStatus.ACTIVE, AlertStatus.SNOOZED}:
            raise ValueError("only active alerts can be snoozed")
        if record.alert.expires_at is not None and until_dt >= record.alert.expires_at:
            raise ValueError("snooze until must be before alert expiry")
        history = record.alert.snooze_history
        if record.alert.snoozed_at is not None and record.alert.snoozed_until is not None:
            history = (*history, _SnoozeInterval(record.alert.snoozed_at, record.alert.snoozed_until))
        updated = replace(
            record.alert,
            status=AlertStatus.SNOOZED,
            snoozed_at=now,
            snoozed_until=until_dt,
            snooze_history=history,
        )
        return self._transition(record, updated, expected_revision=expected_revision)

    def dismiss(self, alert_id: str, *, expected_revision: int) -> AlertRecord:
        record = self.get(alert_id)
        if record.alert.status in {AlertStatus.DISMISSED, AlertStatus.EXPIRED}:
            raise ValueError("only active alerts can be dismissed")
        dismissed_at = _utc_datetime(self._clock(), field="clock")
        updated = replace(record.alert, status=AlertStatus.DISMISSED, dismissed_at=dismissed_at)
        return self._transition(record, updated, expected_revision=expected_revision)


__all__ = [
    "ALERT_ENTITY_TYPE",
    "Alert",
    "AlertBlockPolicy",
    "AlertConfidence",
    "AlertRecord",
    "AlertRevisionConflict",
    "AlertSeverity",
    "AlertStatus",
    "AlertStore",
    "AlertType",
    "EXECUTION_ALLOWED",
    "INCIDENT_RULES",
    "IncidentDomain",
    "build_alert",
    "evaluate_alerts_as_of",
]
