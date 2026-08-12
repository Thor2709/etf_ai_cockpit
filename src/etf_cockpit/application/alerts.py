"""Presentation-safe application seam for local alerts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

from etf_cockpit.data.alerts import (
    AlertConfidence,
    AlertRecord,
    AlertRevisionConflict,
    AlertSeverity,
    AlertStatus,
    AlertStore,
    AlertType,
    IncidentDomain,
    build_alert,
)


TRIGGER_THRESHOLDS: dict[AlertType, float] = {
    AlertType.MATERIAL_SCORE_CHANGE: 1.0,
    AlertType.RANK_CHANGE: 5.0,
    AlertType.STALE_DATA: 2.0,
    AlertType.RISK_LIMIT_BREACHED: 1.0,
    AlertType.TARGET_DRIFT_EXCEEDED: 0.05,
}


def _utc(value: datetime | str, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise TypeError(f"{field} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class AlertTriggerObservation:
    """Strict typed observation consumed by the bounded alert generator."""

    alert_type: AlertType | str
    subject_id: str
    occurred_at: datetime | str
    available_at: datetime | str
    dedupe_key: str
    trigger_value: float | int | bool | date | str | None = None
    severity: AlertSeverity | str | None = None
    confidence: AlertConfidence | str = AlertConfidence.MEDIUM
    incident_domain: IncidentDomain | str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            alert_type = self.alert_type if isinstance(self.alert_type, AlertType) else AlertType(self.alert_type)
        except (TypeError, ValueError) as exc:
            raise ValueError("alert_type must be an accepted AlertType") from exc
        if not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise ValueError("subject_id must be non-empty")
        if not isinstance(self.dedupe_key, str) or not self.dedupe_key.strip():
            raise ValueError("dedupe_key must be non-empty")
        occurred_at = _utc(self.occurred_at, "occurred_at")
        available_at = _utc(self.available_at, "available_at")
        if occurred_at > available_at:
            raise ValueError("available_at cannot precede occurred_at")
        if not isinstance(self.evidence, Mapping):
            raise TypeError("evidence must be a mapping")
        try:
            json.dumps(dict(self.evidence), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("evidence must be JSON-serialisable and finite") from exc
        self._validate_trigger_value(alert_type)
        object.__setattr__(self, "alert_type", alert_type)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "available_at", available_at)

    def _validate_trigger_value(self, alert_type: AlertType) -> None:
        value = self.trigger_value
        if alert_type in {AlertType.NEWS_CONFLICT, AlertType.MODEL_FORECAST_FAILURE}:
            if not isinstance(value, bool):
                raise TypeError("boolean trigger_value required")
        elif alert_type is AlertType.RANK_CHANGE:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("integer trigger_value required for rank_change")
        elif alert_type is AlertType.REVIEW_DATE_ARRIVED:
            if isinstance(value, datetime):
                value = value.date()
            elif isinstance(value, str):
                try:
                    value = date.fromisoformat(value.strip())
                except ValueError as exc:
                    raise ValueError("review_date_arrived requires an ISO date") from exc
            if not isinstance(value, date):
                raise TypeError("date trigger_value required for review_date_arrived")
            object.__setattr__(self, "trigger_value", value)
        else:
            _finite_number(value, field="trigger_value")
        if self.severity is not None:
            try:
                object.__setattr__(self, "severity", self.severity if isinstance(self.severity, AlertSeverity) else AlertSeverity(self.severity))
            except (TypeError, ValueError) as exc:
                raise ValueError("severity must be an AlertSeverity") from exc
        try:
            object.__setattr__(self, "confidence", self.confidence if isinstance(self.confidence, AlertConfidence) else AlertConfidence(self.confidence))
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be an AlertConfidence") from exc
        if self.incident_domain is not None:
            try:
                domain = self.incident_domain if isinstance(self.incident_domain, IncidentDomain) else IncidentDomain(self.incident_domain)
            except (TypeError, ValueError) as exc:
                raise ValueError("incident_domain must be an IncidentDomain") from exc
            object.__setattr__(self, "incident_domain", domain)


def _triggered(observation: AlertTriggerObservation) -> bool:
    value = observation.trigger_value
    if observation.alert_type in {AlertType.NEWS_CONFLICT, AlertType.MODEL_FORECAST_FAILURE}:
        return value is True
    if observation.alert_type is AlertType.REVIEW_DATE_ARRIVED:
        return value <= observation.occurred_at.date()
    number = float(value)
    threshold = TRIGGER_THRESHOLDS[observation.alert_type]
    return abs(number) >= threshold if observation.alert_type in {AlertType.MATERIAL_SCORE_CHANGE, AlertType.RANK_CHANGE, AlertType.TARGET_DRIFT_EXCEEDED} else number >= threshold


def _generated_copy(observation: AlertTriggerObservation) -> tuple[str, str, AlertSeverity, str]:
    alert_type = observation.alert_type
    value = observation.trigger_value
    threshold = TRIGGER_THRESHOLDS.get(alert_type)
    if alert_type is AlertType.MATERIAL_SCORE_CHANGE:
        return "Material score change", f"Absolute score delta {float(value):.2f} reached threshold {threshold:.2f}.", AlertSeverity.WARNING, "score_delta"
    if alert_type is AlertType.RANK_CHANGE:
        return "Material rank change", f"Absolute rank delta {abs(int(value))} reached threshold {int(threshold)}.", AlertSeverity.WARNING, "rank_delta"
    if alert_type is AlertType.NEWS_CONFLICT:
        return "News conflict", "Local news sources disagree for this subject.", AlertSeverity.WARNING, "conflict"
    if alert_type is AlertType.STALE_DATA:
        return "Stale data", f"Data age {float(value):.1f} days reached threshold {threshold:.1f} days.", AlertSeverity.WARNING, "stale_days"
    if alert_type is AlertType.MODEL_FORECAST_FAILURE:
        return "Model forecast failure", "The optional local forecast failed; deterministic baseline evidence remains available.", AlertSeverity.WARNING, "forecast_failed"
    if alert_type is AlertType.REVIEW_DATE_ARRIVED:
        return "Review date arrived", f"Scheduled review date {value.isoformat()} has arrived.", AlertSeverity.INFO, "review_date"
    if alert_type is AlertType.RISK_LIMIT_BREACHED:
        return "Risk limit breached", f"Risk ratio {float(value):.2f} reached the review threshold {threshold:.2f}.", AlertSeverity.CRITICAL, "risk_ratio"
    return "Target drift exceeded", f"Absolute target drift {abs(float(value)):.2%} reached threshold {threshold:.2%}.", AlertSeverity.WARNING, "target_drift"


def generate_local_alert(root: Path, observation: AlertTriggerObservation) -> AlertRecord | None:
    """Generate and persist one alert without importing presentation code."""

    if not isinstance(observation, AlertTriggerObservation):
        raise TypeError("generate_local_alert expects AlertTriggerObservation")
    if not _triggered(observation):
        return None
    title, message, default_severity, metric = _generated_copy(observation)
    evidence = {
        **dict(observation.evidence),
        "metric": metric,
        "observed_value": observation.trigger_value.isoformat() if isinstance(observation.trigger_value, date) else observation.trigger_value,
        "threshold": TRIGGER_THRESHOLDS.get(observation.alert_type, True),
        "generation": "issue-0033-local-thresholds-v1",
    }
    alert = build_alert(
        observation.alert_type,
        subject_id=observation.subject_id,
        title=title,
        message=message,
        severity=default_severity if observation.severity is None else observation.severity,
        confidence=observation.confidence,
        occurred_at=observation.occurred_at,
        available_at=observation.available_at,
        dedupe_key=observation.dedupe_key,
        incident_domain=observation.incident_domain,
        evidence=evidence,
    )
    with AlertStore(root) as store:
        return store.create(alert)


def generate_local_alerts(root: Path, observations: Sequence[AlertTriggerObservation]) -> tuple[AlertRecord, ...]:
    if isinstance(observations, (str, bytes)):
        raise TypeError("observations must be a sequence of typed observations")
    generated = [generate_local_alert(root, observation) for observation in observations]
    return tuple(item for item in generated if item is not None)


@dataclass(frozen=True)
class AlertReadback:
    status: str
    records: tuple[AlertRecord, ...] = ()


def read_local_alerts(
    root: Path,
    *,
    subject_id: str | None = None,
    as_of: datetime | str | None = None,
    include_inactive: bool = False,
    limit: int | None = 8,
) -> AlertReadback:
    try:
        return AlertReadback(
            "available",
            list_local_alerts(
                root,
                subject_id=subject_id,
                as_of=as_of,
                include_inactive=include_inactive,
                limit=limit,
            ),
        )
    except Exception:
        return AlertReadback("unavailable")


def list_local_alerts(
    root: Path,
    *,
    subject_id: str | None = None,
    as_of: datetime | str | None = None,
    include_inactive: bool = False,
    limit: int | None = 8,
) -> tuple[AlertRecord, ...]:
    with AlertStore(root) as store:
        return store.list(
            subject_id=subject_id,
            as_of=as_of,
            include_inactive=include_inactive,
            limit=limit,
        )


def dismiss_local_alert(root: Path, alert_id: str, *, expected_revision: int) -> AlertRecord:
    with AlertStore(root) as store:
        return store.dismiss(alert_id, expected_revision=expected_revision)


def snooze_local_alert(
    root: Path,
    alert_id: str,
    until: datetime,
    *,
    expected_revision: int,
) -> AlertRecord:
    with AlertStore(root) as store:
        return store.snooze(alert_id, until, expected_revision=expected_revision)


__all__ = [
    "AlertConfidence",
    "AlertReadback",
    "AlertRecord",
    "AlertRevisionConflict",
    "AlertSeverity",
    "AlertStatus",
    "AlertTriggerObservation",
    "AlertType",
    "TRIGGER_THRESHOLDS",
    "dismiss_local_alert",
    "generate_local_alert",
    "generate_local_alerts",
    "list_local_alerts",
    "read_local_alerts",
    "snooze_local_alert",
]
