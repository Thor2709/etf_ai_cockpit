"""K: read-only operations and gates plus confirmed local updates.

Open defaults: record pages contain 25 items and cap at 100; alert and activity
reads are capped at 500 source rows; report_export defaults to a review pack for
the configured snapshot date, and an explicit ``as_of`` must match that date.
Settings writes allow only non-secret provider metadata represented by the
canonical settings bundle.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, tool


_CURSORS = CursorCodec()
_SOURCE_ROW_CAP = 500


def _root() -> Path:
    from etf_cockpit.core.paths import ROOT

    session_root = getattr(current_call_context().session, "root", None)
    return Path(session_root or ROOT).resolve()


def _issue_token(payload: Mapping[str, object]) -> str:
    context = current_call_context()
    return context.confirmation_store.issue(
        dict(payload), store_revision=context.store_revision, client_id=context.client_id
    )


def _page_size(limit: int) -> int:
    try:
        return validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None


def _page(rows: list[Any], *, offset: int, limit: int, key: str, filters: Mapping[str, object]) -> dict[str, Any]:
    selected = rows[offset : offset + limit + 1]
    has_more = len(selected) > limit
    return {
        key: selected[:limit],
        "next_cursor": _CURSORS.encode(offset + limit, filters=dict(filters)) if has_more else None,
        "truncated": len(rows) >= _SOURCE_ROW_CAP,
    }


def _decode_cursor(cursor: str | None, filters: Mapping[str, object]) -> int:
    return _CURSORS.decode(cursor, filters=dict(filters)) if cursor else 0


@tool(tier="read", description="Show overall and per-gate local status with explicit unavailable reasons.", read_only_hint=True, idempotent_hint=True)
def gates_status(scope: str = "app") -> dict[str, Any]:
    """Aggregate canonical readiness, data-quality, certification, validation, security and paper-control views."""

    if scope not in {"app", "instrument", "proposal"}:
        raise InvalidArgumentsError("scope must be app, instrument, or proposal")
    from etf_cockpit.application.status_views import build_gate_status

    return build_gate_status(scope=scope, root=_root())


@tool(tier="read", description="List local alerts with a signed paging cursor.", read_only_hint=True, idempotent_hint=True)
def alerts_list(status: str | None = None, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    """Return a bounded alert page; the application service remains the canonical reader."""

    if status not in {None, "active", "snoozed", "dismissed", "expired"}:
        raise InvalidArgumentsError("status must be active, snoozed, dismissed, expired, or omitted")
    size = _page_size(limit)
    filters = {"status": status}
    offset = _decode_cursor(cursor, filters)
    from etf_cockpit.application.alerts import read_local_alerts

    result = read_local_alerts(_root(), include_inactive=True, limit=_SOURCE_ROW_CAP)
    if result.status != "available":
        return {"status": "unavailable", "unavailable_reason": "local alert store is unavailable", "alerts": [], "next_cursor": None}
    rows = [row for row in result.records if status is None or str(getattr(row.status, "value", row.status)) == status]
    return {"status": "available", **_page(rows, offset=offset, limit=size, key="alerts", filters=filters)}


@tool(tier="read", description="Preview dismissing or snoozing a local alert and issue a one-use confirmation token.", read_only_hint=True, idempotent_hint=True)
def alert_update_preview(
    alert_id: str,
    action: str,
    expected_revision: int,
    until: str | None = None,
) -> dict[str, Any]:
    """Read the current alert revision and bind the exact action fields into a confirmation token."""

    if action not in {"dismiss", "snooze"}:
        raise InvalidArgumentsError("action must be dismiss or snooze")
    if action == "snooze" and not until:
        raise InvalidArgumentsError("until is required for snooze")
    if action == "dismiss" and until is not None:
        raise InvalidArgumentsError("until is only valid for snooze")
    from etf_cockpit.application.alerts import list_local_alerts

    rows = list_local_alerts(_root(), include_inactive=True, limit=_SOURCE_ROW_CAP)
    alert = next((row for row in rows if row.alert_id == alert_id), None)
    if alert is None:
        raise MCPToolError("ALERT_NOT_FOUND", "No alert matches that alert_id", "Refresh alerts_list and retry with a current alert_id.")
    if alert.revision != expected_revision:
        raise MCPToolError("ALERT_REVISION_CONFLICT", "The alert changed since it was read", "Refresh alerts_list and preview the current revision.")
    if action == "snooze":
        _parse_aware_datetime(until or "", "until")
    payload = {"alert_id": alert_id, "action": action, "until": until, "expected_revision": expected_revision}
    return {
        "status": "valid",
        "alert_id": alert_id,
        "action": action,
        "expected_revision": expected_revision,
        "current_status": str(getattr(alert.status, "value", alert.status)),
        "confirm_token": _issue_token(payload),
        "execution_allowed": False,
    }


@tool(tier="edit", description="Dismiss or snooze one local alert after confirmation.", read_only_hint=False, idempotent_hint=True)
def alert_update(
    alert_id: str,
    action: str,
    expected_revision: int,
    confirm_token: str,
    until: str | None = None,
) -> dict[str, Any]:
    """Apply one revision-checked local alert transition; confirmation is enforced by the registry."""

    if action not in {"dismiss", "snooze"}:
        raise InvalidArgumentsError("action must be dismiss or snooze")
    from etf_cockpit.application.alerts import dismiss_local_alert, snooze_local_alert

    try:
        if action == "dismiss":
            if until is not None:
                raise InvalidArgumentsError("until is only valid for snooze")
            record = dismiss_local_alert(_root(), alert_id, expected_revision=expected_revision)
        else:
            if not until:
                raise InvalidArgumentsError("until is required for snooze")
            record = snooze_local_alert(
                _root(), alert_id, _parse_aware_datetime(until, "until"), expected_revision=expected_revision
            )
    except InvalidArgumentsError:
        raise
    except Exception as exc:
        raise MCPToolError("ALERT_UPDATE_FAILED", f"Alert update was refused ({type(exc).__name__})", "Refresh the alert and retry after reviewing its current revision.") from None
    return {"status": "updated", "alert": record, "execution_allowed": False}


@tool(tier="read", description="Show stored score, rank, data and model changes since a time or recent duration.", read_only_hint=True, idempotent_hint=True)
def what_changed(since: str = "7d", cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    """Compare stored runs through the canonical run-change service; never derive missing values."""

    from etf_cockpit.application.status_views import build_what_changed

    size = _page_size(limit)
    filters = {"since": since}
    offset = _decode_cursor(cursor, filters)
    try:
        result = build_what_changed(since=since, root=_root(), offset=offset, limit=size)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    if result.get("truncated") is True:
        result["next_cursor"] = _CURSORS.encode(offset + size, filters=filters)
    else:
        result["next_cursor"] = None
    return result


@tool(tier="read", description="Read recent local session and audit events with a signed paging cursor.", read_only_hint=True, idempotent_hint=True)
def activity_log(since: str | None = None, event_type: str | None = None, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    """Read the bounded session-log tail and in-memory MCP audit records."""

    size = _page_size(limit)
    filters = {"since": since, "event_type": event_type}
    offset = _decode_cursor(cursor, filters)
    from etf_cockpit.core.session_log import read_session_events

    rows: list[dict[str, object]] = []
    session_log_available = True
    try:
        rows.extend(read_session_events(_SOURCE_ROW_CAP))
    except Exception:
        session_log_available = False
    context = current_call_context()
    for record in getattr(context.audit, "records", ()):
        rows.append({
            "event_type": "mcp_tool_call",
            "occurred_at": record.occurred_at,
            "tool": record.tool,
            "tier": record.tier,
            "outcome": record.outcome,
            "reason_code": record.reason_code,
            "duration_ms": record.duration_ms,
            "client_id": record.client_id,
        })
    rows = [row for row in rows if event_type is None or str(row.get("event_type", "")) == event_type]
    try:
        cutoff = _parse_since(since) if since else None
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    if cutoff is not None:
        rows = [row for row in rows if _event_time(row) is not None and _event_time(row) >= cutoff]
    rows = rows[-_SOURCE_ROW_CAP:]
    if not session_log_available:
        if not rows:
            return {
                "status": "unavailable",
                "unavailable_reason": "the local session log is unavailable",
                "events": [],
                "next_cursor": None,
            }
        return {
            "status": "partial",
            "warnings": ["the local session log is unavailable; only current MCP audit events are shown"],
            **_page(rows, offset=offset, limit=size, key="events", filters=filters),
        }
    return {"status": "available", **_page(rows, offset=offset, limit=size, key="events", filters=filters)}


@tool(tier="read", description="Show local resource, parity, plugin and log diagnostics.", read_only_hint=True, idempotent_hint=True)
def diagnostics() -> dict[str, Any]:
    """Return compact diagnostics from the established application readers."""

    from etf_cockpit.application.status_views import build_local_diagnostics

    return build_local_diagnostics(_root())


@tool(tier="read_job", description="Submit a local review-pack or portfolio-review report and return its job id.", read_only_hint=False, idempotent_hint=False)
def report_export(kind: str = "review_pack", as_of: str | None = None) -> dict[str, Any]:
    """Submit one canonical local report export as a durable derived-artifact job."""

    if kind not in {"review_pack", "portfolio_review"}:
        raise InvalidArgumentsError("kind must be review_pack or portfolio_review")
    if as_of is not None:
        try:
            as_of = date.fromisoformat(as_of).isoformat()
        except ValueError:
            raise InvalidArgumentsError("as_of must be an ISO-8601 calendar date (YYYY-MM-DD)") from None
    session = current_call_context().session
    if session is None or not callable(getattr(session, "submit_workflow", None)):
        return {"status": "unavailable", "unavailable_reason": "headless report export service is unavailable", "execution_allowed": False}
    payload = {"kind": kind, "as_of": as_of}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    try:
        job_id = session.submit_workflow(
            "report_export",
            label=f"Export {kind.replace('_', ' ')}",
            input_payload=payload,
            dedupe_key=f"report-export:{fingerprint}",
        )
    except Exception as exc:
        raise MCPToolError("REPORT_EXPORT_UNAVAILABLE", f"Report export could not be submitted ({type(exc).__name__})", "Check the local headless job service and retry.") from None
    return {"status": "submitted", "job_id": str(job_id), "kind": kind, "as_of": as_of, "execution_allowed": False}


@tool(tier="read", description="Validate a local AI audit JSON or packet without importing it.", read_only_hint=True, idempotent_hint=True)
def audit_validate(path: str | None = None, text: str | None = None) -> dict[str, Any]:
    """Validate one local path or supplied JSON text; a valid path can be previewed for confirmed import."""

    if (path is None) == (text is None):
        raise InvalidArgumentsError("provide exactly one of path or text")
    try:
        from etf_cockpit.application.validation_report import validate_audit_input

        result = validate_audit_input(_root(), path=path, text=text)
        if result.pop("confirmable", False) and path is not None:
            result["confirm_token"] = _issue_token({"path": path})
        return result
    except Exception as exc:
        return {"status": "invalid", "findings": [f"{type(exc).__name__}: {str(exc)[:240]}"], "execution_allowed": False}


@tool(tier="edit", description="Import a validated local AI audit after confirmation.", read_only_hint=False, idempotent_hint=False)
def audit_import(path: str, confirm_token: str) -> dict[str, Any]:
    """Revalidate and import one local audit note through the canonical application bridge."""

    try:
        from etf_cockpit.application.validation_report import import_audit_input

        return import_audit_input(_root(), path)
    except Exception as exc:
        raise MCPToolError("AUDIT_IMPORT_FAILED", f"Audit import was refused ({type(exc).__name__})", "Run audit_validate on the exact path and retry with a fresh confirmation token.") from None


@tool(tier="read", description="Read the secret-stripped effective settings bundle.", read_only_hint=True, idempotent_hint=True)
def settings_get(section: str | None = None) -> dict[str, Any]:
    """Read the existing application settings bundle and preserve its canonical revision."""

    try:
        from etf_cockpit.application.validation_report import load_settings_view

        return load_settings_view(_root(), section)
    except Exception as exc:
        if getattr(exc, "code", None):
            raise MCPToolError(exc.code, str(exc), "Repair the local settings or policy source before retrying.") from None
        raise InvalidArgumentsError(str(exc)) from None


@tool(tier="read", description="Preview allow-listed provider metadata settings changes.", read_only_hint=True, idempotent_hint=True)
def settings_change_preview(changes: Mapping[str, object]) -> dict[str, Any]:
    """Validate only provider metadata fields that the canonical secret-free settings model supports."""

    try:
        from etf_cockpit.application.validation_report import preview_settings_changes

        preview = preview_settings_changes(_root(), changes)
    except Exception as exc:
        code = getattr(exc, "code", "SETTINGS_CHANGE_INVALID")
        raise MCPToolError(code, str(exc)[:240], "Use only supported non-secret provider metadata keys and retry.") from None
    if preview.get("valid") is True:
        preview["confirm_token"] = _issue_token({"changes": dict(changes), "expected_revision": preview["expected_revision"]})
    return preview


@tool(tier="edit", description="Save allow-listed provider metadata settings after confirmation.", read_only_hint=False, idempotent_hint=False)
def settings_change_commit(changes: Mapping[str, object], expected_revision: str, confirm_token: str) -> dict[str, Any]:
    """Repeat preview validation and save settings through the canonical atomic settings service."""

    try:
        from etf_cockpit.application.validation_report import save_settings_changes

        return save_settings_changes(_root(), changes, expected_revision)
    except Exception as exc:
        code = getattr(exc, "code", "SETTINGS_CHANGE_INVALID")
        raise MCPToolError(code, str(exc)[:240], "Refresh settings_get, preview the change, and retry with a fresh token.") from None


def _parse_aware_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidArgumentsError(f"{name} must be an ISO-8601 timezone-aware timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidArgumentsError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    match = re.fullmatch(r"(\d{1,4})d", value.strip(), flags=re.IGNORECASE)
    if match:
        from datetime import timedelta

        return datetime.now(timezone.utc) - timedelta(days=int(match.group(1)))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidArgumentsError("since must be an ISO date/time or duration such as 7d") from None
    if parsed.tzinfo is None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidArgumentsError("since timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _event_time(row: Mapping[str, object]) -> datetime | None:
    for key in ("occurred_at", "timestamp", "created_at", "at"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue
    return None


__all__ = [
    "activity_log", "alert_update", "alert_update_preview", "alerts_list", "audit_import", "audit_validate",
    "diagnostics", "gates_status", "report_export", "settings_change_commit", "settings_change_preview",
    "settings_get", "what_changed",
]
