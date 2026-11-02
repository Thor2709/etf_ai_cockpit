"""Durable scheduler handlers for the headless application workflows.

Defaults: handlers are registered under the existing headless method names
``refresh``, ``rescore`` and ``publish``. Paper bot and replay handlers are opt-in
for the MCP headless worker. Resource estimates use the scheduler's local
``auto`` profile, which performs no network calls and never grants execution.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import os
import subprocess
import sys

from etf_cockpit.application.headless_session import HeadlessSession
from etf_cockpit.core.job_scheduler import JobContext
from etf_cockpit.core.resource_profiles import HardwareSnapshot, estimate_workflow_resources


_HEADLESS_WORKFLOWS = frozenset({"refresh", "rescore", "publish", "paper_bots_run", "paper_replay_run"})


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
    *,
    include_paper: bool = False,
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

    handlers: dict[str, Callable[[JobContext], dict[str, object]]] = {
        "refresh": refresh,
        "rescore": rescore,
        "publish": publish,
    }
    if include_paper:
        def inputs(context: JobContext) -> tuple[HeadlessSession, dict[str, object]]:
            session = session_factory()
            workflow = session.get_workflow(context.workflow_id)
            raw = getattr(workflow, "inputs", None)
            return session, dict(raw) if isinstance(raw, dict) else {}

        def paper_bots_run(context: JobContext) -> dict[str, object]:
            session, payload = inputs(context)
            from etf_cockpit.portfolio.paper_bots import run_paper_bots
            from etf_cockpit.application.paper_manual_order import load_paper_controls_status

            result = run_paper_bots(payload.get("as_of", ""), root=session.root)
            execution: dict[str, object]
            if result.status not in {"available", "partial"}:
                execution = {"status": "unavailable", "reason": "stage_a_unavailable"}
            else:
                controls = load_paper_controls_status(session.root, "local-paper")
                if controls.get("status") != "available":
                    execution = {"status": "blocked", "reason": "paper_controls_unavailable"}
                elif controls.get("kill_switch_active") is True:
                    execution = {"status": "blocked", "reason": "paper_kill_switch_active"}
                else:
                    from etf_cockpit.portfolio.paper_bots_execution import run_paper_bot_execution

                    stage_b = run_paper_bot_execution(payload.get("as_of", ""), root=session.root)
                    execution = {
                        "status": stage_b.status,
                        "as_of": stage_b.as_of,
                        "appended": stage_b.appended,
                        "reason": stage_b.reason,
                        "warnings": list(stage_b.warnings),
                    }
            return {
                "status": result.status,
                "as_of": result.as_of,
                "appended": result.appended,
                "reason": result.reason,
                "warnings": list(result.warnings),
                "execution": execution,
                "execution_allowed": False,
            }

        def paper_replay_run(context: JobContext) -> dict[str, object]:
            session, payload = inputs(context)
            from etf_cockpit.data.replay_membership import STRICT_MODE, UNVERIFIED_DELISTINGS_MODE
            from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

            survivorship = payload.get("survivorship", "strict")
            mode = STRICT_MODE if survivorship == "strict" else UNVERIFIED_DELISTINGS_MODE if survivorship == "unverified" else None
            if mode is None:
                raise ValueError("survivorship must be 'strict' or 'unverified'.")
            result = run_historical_replay(
                payload.get("as_of", ""), root=session.root, survivorship_mode=mode
            )
            export_result: dict[str, object] | None = None
            if payload.get("export", False):
                if result.status not in {"available", "partial"} or not result.as_of:
                    raise ValueError("Replay export requires an available replay result.")
                script = Path(__file__).resolve().parents[3] / "scripts" / "export_replay_ledger.py"
                if not script.is_file():
                    raise FileNotFoundError("The replay export script is unavailable.")
                environment = dict(os.environ)
                environment["ETF_COCKPIT_ROOT"] = str(session.root.resolve())
                command = [
                    sys.executable,
                    str(script),
                    "--root", str(session.root.resolve()),
                    "--as-of", result.as_of[:10],
                    "--survivorship-mode", "strict" if survivorship == "strict" else UNVERIFIED_DELISTINGS_MODE,
                ]
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=environment,
                )
                if completed.returncode != 0:
                    raise RuntimeError(f"Replay ledger export failed with exit code {completed.returncode}.")
                export_result = {
                    "status": "exported",
                    "output_directory": str(session.root / "data" / "paper_bots_replay" / "exports"),
                    "execution_allowed": False,
                }
            return {
                "status": result.status,
                "track": result.track,
                "as_of": result.as_of,
                "appended": result.appended,
                "reason": result.reason,
                "warnings": list(result.warnings),
                "survivorship_unverified": result.survivorship_unverified,
                "export": export_result,
                "execution_allowed": False,
            }

        handlers.update({"paper_bots_run": paper_bots_run, "paper_replay_run": paper_replay_run})
    return handlers


__all__ = ["estimate_headless_workflow", "headless_workflow_handlers"]
