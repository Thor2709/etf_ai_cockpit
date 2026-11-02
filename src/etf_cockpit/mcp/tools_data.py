"""MCP data and point-in-time history tools.

Open defaults: health staleness is three days, refresh lookback is five years,
score-history cadence is five sessions, workers is one, and pages contain 25 rows.
Refreshes require an injected application workflow service; no tool performs a
provider write before the registry accepts a valid confirmation token.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping

from etf_cockpit.application import mcp_data_views
from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, issue_confirmation_token, tool
from etf_cockpit.mcp.serialise import normalise


_CURSORS = CursorCodec()
_REFRESH_SOURCES = frozenset({"prices", "fundamentals", "etf_holdings", "sparebanks", "euronext_listing", "pit_history"})


def _paged(rows: list[Any], *, cursor: str | None, filters: Mapping[str, object], limit: int = DEFAULT_PAGE_SIZE) -> dict[str, object]:
    try:
        size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters=dict(filters)) if cursor else 0
    page = rows[offset : offset + size + 1]
    has_more = len(page) > size
    return {"rows": normalise(page[:size]), "next_cursor": _CURSORS.encode(offset + size, filters=dict(filters)) if has_more else None}


def _submit_workflow(workflow_type: str, label: str, payload: Mapping[str, object]) -> str:
    session = current_call_context().session
    if session is None:
        raise MCPToolError("JOB_SERVICE_UNAVAILABLE", "The local workflow service is not available", "Start the MCP server with its headless application workflow service.")
    api = getattr(session, "application_api", None) or getattr(session, "api", None)
    submit = getattr(session, "submit_workflow", None)
    if callable(submit):
        result = submit(workflow_type=workflow_type, label=label, input_payload=dict(payload))
        job_id = getattr(result, "resource_id", None) or getattr(result, "workflow_id", None)
        if job_id:
            return str(job_id)
    execute = getattr(api, "execute", None)
    if callable(execute):
        from uuid import uuid4

        from etf_cockpit.application.contracts import SubmitWorkflowCommand

        command = SubmitWorkflowCommand(
            idempotency_key=f"mcp-{uuid4().hex}",
            workflow_type=workflow_type,
            label=label,
            input_payload=dict(payload),
            job_keys=("start",),
        )
        result = execute(command)
        job_id = getattr(result, "resource_id", None)
        status = getattr(getattr(result, "status", None), "value", getattr(result, "status", None))
        if status in {"accepted", "replayed"} and job_id:
            return str(job_id)
        raise MCPToolError("WORKFLOW_SUBMIT_FAILED", "The workflow was not accepted", "Review the local workflow service status and retry after correcting the reported issue.")
    raise MCPToolError("JOB_SERVICE_UNAVAILABLE", "The local workflow service is not available", "Start the MCP server with its headless application workflow service.")


def _preview_refresh(source: str, ids: list[str] | None = None, years: int = 5, rescore: bool = True) -> dict[str, object]:
    source_key = str(source).strip().lower()
    if source_key not in _REFRESH_SOURCES:
        raise InvalidArgumentsError(f"source must be one of {', '.join(sorted(_REFRESH_SOURCES))}")
    if years < 1 or years > 30:
        raise InvalidArgumentsError("years must be between 1 and 30")
    if source_key == "prices" and ids:
        raise InvalidArgumentsError("price refresh is universe-wide; ids are not supported")
    return {"source": source_key, "ids": ids or [], "years": years, "rescore": bool(rescore), "network_calls": "only after confirmation", "execution_allowed": False}


@tool(tier="read", description="Read dataset freshness, status and quarantine rows.", read_only_hint=True, idempotent_hint=True, profiles=("core", "full"))
def data_health(dataset: str | None = None, stale_after_days: int = 3, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, object]:
    if stale_after_days < 0:
        raise InvalidArgumentsError("stale_after_days must be non-negative")
    view = mcp_data_views.data_health_view(dataset=dataset, stale_after_days=stale_after_days)
    paged = _paged(list(view["rows"]), cursor=cursor, filters={"dataset": dataset, "stale_after_days": stale_after_days}, limit=limit)
    return {"as_of": view["as_of"], "rows": paged["rows"], "next_cursor": paged["next_cursor"], "unavailable_reason": "No data health rows match the requested filter." if not view["rows"] else None}


@tool(tier="read", description="Evaluate point-in-time data readiness across an interval.", read_only_hint=True, idempotent_hint=True)
def data_readiness(start: date, end: date, every: int | None = None, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, object]:
    try:
        result = mcp_data_views.data_readiness_view(start, end, every=every)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    page = _paged(list(result["failed_dates"]), cursor=cursor, filters={"start": start.isoformat(), "end": end.isoformat(), "every": every}, limit=limit)
    summary = {key: value for key, value in result["summary"].items() if key != "failed_dates"}
    return normalise({**result, "summary": summary, "failed_dates": page["rows"], "next_cursor": page["next_cursor"]})


@tool(tier="read", description="Read configured provider capabilities and redacted credential status; probe is off by default.", read_only_hint=True, idempotent_hint=True, open_world_hint=True)
def data_provider_status(probe: bool = False, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, object]:
    rows = list(mcp_data_views.data_provider_status_view(probe=probe))
    paged = _paged(rows, cursor=cursor, filters={"probe": probe}, limit=limit)
    return {"rows": paged["rows"], "next_cursor": paged["next_cursor"], "probed": bool(probe)}


@tool(tier="read", description="Run the canonical stored-price quality validation without committing data.", read_only_hint=True, idempotent_hint=True)
def data_validate_prices() -> dict[str, object]:
    return normalise(mcp_data_views.validate_prices_view())


@tool(tier="edit", description="Refresh one configured data source and optionally rescore; the dry run is side-effect-free.", read_only_hint=False, open_world_hint=True, preview=_preview_refresh)
def data_refresh(source: str, ids: list[str] | None = None, years: int = 5, rescore: bool = True, confirm_token: str | None = None) -> dict[str, object]:
    preview = _preview_refresh(source, ids, years, rescore)
    source_key = str(source).strip().lower()
    workflow = "refresh" if source_key in {"prices", "fundamentals", "etf_holdings"} else f"{source_key}_refresh"
    payload = {"source": source_key, "ids": ids or [], "years": years, "rescore": bool(rescore)}
    job_id = _submit_workflow(workflow, f"Refresh {source_key}", payload)
    return {"job_id": job_id, "source": source_key, "preview": preview, "execution_allowed": False}


def _preview_rollback(reason: str) -> dict[str, object]:
    if not reason.strip():
        raise InvalidArgumentsError("reason must not be empty")
    result = mcp_data_views.rollback_preview()
    if result.get("available") is not True:
        raise MCPToolError("ROLLBACK_UNAVAILABLE", str(result.get("unavailable_reason") or "No previous price snapshot is available"), "Create a validated price import before requesting rollback.")
    return {"reason": reason.strip(), **result, "would_write": False}


@tool(tier="edit", description="Restore the previous validated clean-price snapshot.", read_only_hint=False, destructive_hint=True, preview=_preview_rollback)
def data_rollback_prices(reason: str, confirm_token: str | None = None) -> dict[str, object]:
    _preview_rollback(reason)
    return {"message": mcp_data_views.rollback_prices(), "execution_allowed": False}


@tool(tier="edit", description="Validate a local file import and issue a confirmation token for data_import_commit.", read_only_hint=True, idempotent_hint=True)
def data_import_preview(path: str, dataset_type: str = "prices") -> dict[str, object]:
    try:
        report = mcp_data_views.preview_local_import(Path(path), dataset_type)
    except (OSError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from None
    report["confirm_token"] = issue_confirmation_token({"path": path, "dataset_type": dataset_type})
    return normalise(report)


def _preview_import(path: str, dataset_type: str = "prices") -> dict[str, object]:
    try:
        return mcp_data_views.preview_local_import(Path(path), dataset_type)
    except (OSError, ValueError) as exc:
        raise InvalidArgumentsError(str(exc)) from None


@tool(tier="edit", description="Commit a validated local price or reference-data import.", read_only_hint=False, destructive_hint=True, preview=_preview_import)
def data_import_commit(path: str, dataset_type: str = "prices", confirm_token: str | None = None) -> dict[str, object]:
    return normalise(mcp_data_views.commit_local_import(Path(path), dataset_type))


def _preview_filing(path: str, jurisdiction: str, instrument_id: str, source_url: str, period: str, sha256: str) -> dict[str, object]:
    candidate = Path(path)
    if jurisdiction.strip().upper() != "NO":
        raise InvalidArgumentsError("The local filing importer currently supports jurisdiction NO")
    if not candidate.is_file():
        raise InvalidArgumentsError("filing path is not a local file")
    import hashlib

    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if digest.casefold() != sha256.casefold():
        raise InvalidArgumentsError("filing checksum does not match sha256")
    return {"path_name": candidate.name, "jurisdiction": "NO", "instrument_id": instrument_id, "period": period, "sha256": digest, "bytes": candidate.stat().st_size, "network_calls": False, "would_write": True}


@tool(tier="edit", description="Import a locally supplied official filing using the application filing importer.", read_only_hint=False, destructive_hint=True, preview=_preview_filing)
def filing_import(path: str, jurisdiction: str, instrument_id: str, source_url: str, period: str, sha256: str, confirm_token: str | None = None) -> dict[str, object]:
    preview = _preview_filing(path, jurisdiction, instrument_id, source_url, period, sha256)
    from etf_cockpit.application.official_filing_import import import_official_filing

    session_root = getattr(current_call_context().session, "root", None)
    if session_root is None:
        raise MCPToolError("DATA_ROOT_UNAVAILABLE", "The configured session data root is unavailable", "Start the MCP server with its configured headless session.")
    root = Path(session_root).resolve()
    output = (root / "evidence" / "norway" / f"{instrument_id}-{period[:4]}").resolve()
    if not output.is_relative_to(root):
        raise InvalidArgumentsError("filing evidence output must remain inside the configured data root")
    result = import_official_filing(Path(path), jurisdiction=jurisdiction, instrument_id=instrument_id, source_url=source_url, expected_period=period, expected_sha256=sha256, output_dir=output, universe_root=root)
    return {"preview": preview, "result": result, "execution_allowed": False}


def _preview_score_history(start: date, end: date, every: int = 5, workers: int = 1, force: bool = False) -> dict[str, object]:
    if end < start or every < 1 or workers < 1:
        raise InvalidArgumentsError("start/end, every and workers must define a valid interval and positive work limits")
    return {"start": start.isoformat(), "end": end.isoformat(), "every": every, "workers": workers, "force": force, "writes": "derived PIT score history only", "execution_allowed": False}


@tool(tier="read_job", description="Submit canonical point-in-time score-history backfill to the local workflow service.", read_only_hint=False, requires_confirmation=False, idempotent_hint=True)
def score_history_backfill(start: date, end: date, every: int = 5, workers: int = 1, force: bool = False) -> dict[str, object]:
    preview = _preview_score_history(start, end, every, workers, force)
    job_id = _submit_workflow("score_history_backfill", "Point-in-time score history backfill", preview)
    return {"job_id": job_id, "preview": preview, "execution_allowed": False}


__all__ = ["data_health", "data_readiness", "data_provider_status", "data_validate_prices", "data_refresh", "data_rollback_prices", "data_import_preview", "data_import_commit", "filing_import", "score_history_backfill"]
