"""Read-only view model for the error and recovery centre."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


@dataclass(frozen=True)
class RecoveryPolicyCard:
    title: str
    symptom: str
    guarantee: str
    steps: str


RECOVERY_POLICIES: tuple[RecoveryPolicyCard, ...] = (
    RecoveryPolicyCard(
        "Provider outage",
        "A provider is unavailable or times out.",
        "The last clean local data is kept; no live orders are sent.",
        "Check the provider later and retry the failed workflow when it is explicitly retryable.",
    ),
    RecoveryPolicyCard(
        "Failed import",
        "An input file is malformed, incomplete, or fails validation.",
        "The previous clean data remains unchanged and no partial import is published.",
        "Correct the file, validate it again, and start a new import.",
    ),
    RecoveryPolicyCard(
        "Failed model or forecast run",
        "A model run fails before its outputs are published.",
        "Previously published forecasts remain available byte-for-byte.",
        "Review the error, correct its cause, and retry the run when offered.",
    ),
    RecoveryPolicyCard(
        "Corrupt local store",
        "A local store cannot be read or fails integrity checks.",
        "The application blocks unsafe writes and does not fabricate replacement data.",
        "Inspect the diagnostic detail in developer mode, then validate and restore a local backup from Import/Export.",
    ),
    RecoveryPolicyCard(
        "Interrupted job",
        "The application stops before a workflow reaches a terminal state.",
        "Incomplete work is not presented as published; existing clean artifacts are retained.",
        "Review the activity log and restart the workflow if a retry is available.",
    ),
)


@dataclass(frozen=True)
class RecoveryReadModel:
    forecasts_last_known_good: str
    data_last_known_good: str
    jobs: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]


def developer_mode_enabled() -> bool:
    return os.getenv("ETF_COCKPIT_DEVELOPER_MODE") == "1"


def build_recovery_read_model(state: Any, jobs: Any = None) -> RecoveryReadModel:
    snapshot = getattr(state, "snapshot", state)
    forecasts = _explicit_timestamp(snapshot, ("last_successful_forecast_at", "forecasts_last_known_good"))
    if forecasts is None:
        forecasts = _latest_forecast_date(getattr(snapshot, "forecasts", None))
    data = _explicit_timestamp(snapshot, ("last_successful_data_at", "data_last_known_good"))
    if data is None:
        data = _explicit_timestamp(getattr(snapshot, "data_report", None), ("as_of_date",))
    reasons: list[str] = []
    if forecasts is None:
        forecasts = "unavailable"
        reasons.append("No published-forecast timestamp is exposed by the current read APIs.")
    if data is None:
        data = "unavailable"
        reasons.append("No published-data timestamp is exposed by the current read APIs.")

    job_statuses: list[str] = []
    api = getattr(state, "application_api", None)
    get_jobs = getattr(api, "get_jobs", None)
    if jobs is not None:
        _append_jobs(jobs, job_statuses)
    elif callable(get_jobs):
        store_status = getattr(api, "jobs_store_status", None)
        readable, store_reason = store_status() if callable(store_status) else (True, None)
        if not readable:
            reasons.append(f"The job store is unavailable ({store_reason}); job status is not shown.")
            return RecoveryReadModel(forecasts, data, (), tuple(reasons))
        try:
            result = get_jobs()
            _append_jobs(getattr(result, "items", ()), job_statuses)
        except Exception:
            reasons.append("The job read API was unavailable.")
    else:
        reasons.append("No resumable-job read API is exposed by the current application boundary.")
    return RecoveryReadModel(forecasts, data, tuple(job_statuses), tuple(reasons))


def _append_jobs(items: Any, output: list[str]) -> None:
    for job in items or ():
        status = str(job.get("status", "unknown")) if isinstance(job, dict) else str(getattr(job, "status", "unknown"))
        label = (str(job.get("label") or job.get("workflow_id") or "job") if isinstance(job, dict) else str(getattr(job, "label", getattr(job, "workflow_id", "job"))))
        if status in {"queued", "running", "interrupted", "expired", "failed"}:
            output.append(f"{label}: {status}")


def _explicit_timestamp(source: Any, names: tuple[str, ...]) -> str | None:
    if source is None:
        return None
    for name in names:
        value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
        text = str(value).strip() if value is not None else ""
        if text and text.lower() not in {"none", "unknown", "unavailable"}:
            return text
    return None


def _latest_forecast_date(value: Any) -> str | None:
    if value is None:
        return None
    values: list[str] = []
    if hasattr(value, "iterrows"):
        try:
            values = [str(row.get("forecast_date")) for _, row in value.iterrows()]
        except Exception:
            values = []
    elif isinstance(value, (list, tuple)):
        values = [
            str(item.get("forecast_date"))
            for item in value
            if isinstance(item, dict) and item.get("forecast_date") is not None
        ]
    cleaned = [item.strip() for item in values if item and item.strip().lower() not in {"none", "nan", "nat"}]
    return max(cleaned) if cleaned else None


__all__ = [
    "RECOVERY_POLICIES",
    "RecoveryPolicyCard",
    "RecoveryReadModel",
    "build_recovery_read_model",
    "developer_mode_enabled",
]
