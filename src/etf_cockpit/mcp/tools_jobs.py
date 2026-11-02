"""L0 session and job tools.

Open defaults: status detail is brief, job pages contain 25 records, and pages are capped
at 100 records. A job can be cancelled only when its originating tier is enabled.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from etf_cockpit.mcp.errors import AuthorizationError, InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.paging import CursorCodec, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, validate_page_size
from etf_cockpit.mcp.registry import current_call_context, tool
from etf_cockpit.mcp.tiers import normalise_tier


class HeadlessJobSession(Protocol):
    """Narrow contract for the parallel headless-session implementation."""

    def get_workflow(self, workflow_id: str) -> Any | None: ...

    def list_workflows(
        self,
        *,
        status: str | None,
        offset: int,
        limit: int,
    ) -> Sequence[Any]: ...

    def cancel_workflow(self, workflow_id: str, reason: str) -> Any: ...


_CURSORS = CursorCodec()


def _session() -> HeadlessJobSession:
    session = current_call_context().session
    if session is None:
        raise MCPToolError(
            "JOB_SERVICE_UNAVAILABLE",
            "The headless job service is not available",
            "Start the application services before requesting job data.",
        )
    return session


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


@tool(
    tier="read",
    description="Show cockpit freshness, readiness, gates, bots, active jobs, and enabled tiers.",
    read_only_hint=True,
    idempotent_hint=True,
    profiles=("core", "full"),
)
def cockpit_status(detail: str = "brief") -> dict[str, Any]:
    """Provide the L0 status stub until the application status aggregator is available."""

    if detail not in {"brief", "full"}:
        raise InvalidArgumentsError("detail must be 'brief' or 'full'")
    return {
        "status": "unavailable",
        "unavailable_reason": "Cockpit status aggregation is not available in the L0 foundation.",
    }


@tool(
    tier="read",
    description="Read one background job record, including its state and progress.",
    read_only_hint=True,
    idempotent_hint=True,
    profiles=("core", "full"),
)
def job_status(job_id: str) -> dict[str, Any]:
    """Read one workflow record without starting or changing work."""

    record = _session().get_workflow(job_id)
    if record is None:
        raise MCPToolError("JOB_NOT_FOUND", "No job matches that job_id", "Check job_list and retry with a current job_id.")
    return {"job": record}


@tool(
    tier="read",
    description="List recent and active jobs with a signed paging cursor.",
    read_only_hint=True,
    idempotent_hint=True,
)
def job_list(status: str | None = None, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    """Return a bounded page of jobs; cursor state is bound to the status filter."""

    try:
        page_size = validate_page_size(limit, maximum=MAX_PAGE_SIZE)
    except ValueError as exc:
        raise InvalidArgumentsError(str(exc)) from None
    offset = _CURSORS.decode(cursor, filters={"status": status}) if cursor else 0
    rows = list(_session().list_workflows(status=status, offset=offset, limit=page_size + 1))
    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = _CURSORS.encode(offset + page_size, filters={"status": status}) if has_more else None
    return {"jobs": page, "next_cursor": next_cursor}


@tool(
    tier="read",
    description="Cancel one running job when the job's originating tier is enabled.",
    read_only_hint=False,
    idempotent_hint=True,
    requires_confirmation=False,
)
def job_cancel(job_id: str, reason: str) -> dict[str, Any]:
    """Cancel a job without requiring a financial-write confirmation."""

    if not reason.strip():
        raise InvalidArgumentsError("reason must not be empty")
    context = current_call_context()
    service = _session()
    record = service.get_workflow(job_id)
    if record is None:
        raise MCPToolError("JOB_NOT_FOUND", "No job matches that job_id", "Check job_list and retry with a current job_id.")
    job_tier = _field(record, "tier")
    try:
        required_tier = normalise_tier(job_tier)
    except (ValueError, TypeError):
        raise AuthorizationError("The job tier is unavailable, so cancellation is refused") from None
    if required_tier not in context.enabled_tiers:
        raise AuthorizationError("The job's originating tier is not enabled for this client")
    result = service.cancel_workflow(job_id, reason.strip())
    return {"job_id": job_id, "cancelled": True, "result": result}
