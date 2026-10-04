"""Activity result contract: readable unavailable results, the legacy string-return path and typed failure messages (application; ADR-0002)."""

from __future__ import annotations

from etf_cockpit.operations.event_store import (
    current_activity_view as current_activity_view,
    load_events_with_tail_recovery as load_events_with_tail_recovery,
)


class ActivityUnavailableError(RuntimeError):
    """A local action returned a readable unavailable result without raising."""


def _legacy_unavailable(state: object, message: str, cause: BaseException | None = None) -> str:
    """Keep lightweight direct callers on the historical string-return contract."""

    if not hasattr(state, "_activity_lock"):
        return message
    if cause is None:
        raise ActivityUnavailableError(message)
    raise ActivityUnavailableError(message) from cause


def activity_result_error(result: object) -> str | None:
    """Return a bounded typed failure message for normal-return result objects."""

    ok = getattr(result, "ok", None)
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", status)
    failed = ok is False or status_value in {"failed", "unavailable", "error", "blocked"}
    if not failed:
        return None
    message = getattr(result, "error", None) or getattr(result, "message", None) or status_value
    return str(message or "Action was unavailable.").strip()
