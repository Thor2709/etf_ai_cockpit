"""Durable scheduler handlers for the headless application workflows.

Defaults: handlers are registered under the existing headless method names
``refresh``, ``rescore`` and ``publish``; resource estimates use the scheduler's
local ``auto`` profile, which performs no network calls and never grants execution.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from etf_cockpit.application.headless_session import HeadlessSession
from etf_cockpit.core.job_scheduler import JobContext
from etf_cockpit.core.resource_profiles import HardwareSnapshot, estimate_workflow_resources


_HEADLESS_WORKFLOWS = frozenset({"refresh", "rescore", "publish"})


def estimate_headless_workflow(
    workflow_type: str,
    *,
    requested_profile: str = "auto",
    snapshot: HardwareSnapshot | None = None,
) -> dict[str, object]:
    """Estimate resources with the same policy used by DurableJobScheduler."""

    selected = str(workflow_type).strip().casefold()
    if selected not in _HEADLESS_WORKFLOWS:
        raise ValueError(f"Unsupported headless workflow: {workflow_type}")
    return estimate_workflow_resources(selected, requested_profile=requested_profile, snapshot=snapshot)


def headless_workflow_handlers(
    session_factory: Callable[[], HeadlessSession],
) -> dict[str, Callable[[JobContext], dict[str, object]]]:
    """Build the bounded workflow runner mapping consumed by DurableJobScheduler."""

    def refresh(_context: JobContext) -> dict[str, object]:
        message = session_factory().refresh()
        return {"message": message, "execution_allowed": False}

    def rescore(_context: JobContext) -> dict[str, object]:
        message, path = session_factory().rescore()
        return {"message": message, "output_path": str(path), "execution_allowed": False}

    def publish(_context: JobContext) -> dict[str, object]:
        path: Path = session_factory().publish()
        return {"output_path": str(path), "execution_allowed": False}

    return {"refresh": refresh, "rescore": rescore, "publish": publish}


__all__ = ["estimate_headless_workflow", "headless_workflow_handlers"]
