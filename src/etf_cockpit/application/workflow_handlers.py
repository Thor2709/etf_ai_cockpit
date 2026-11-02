"""Durable scheduler handlers for the headless application workflows.

Defaults: handlers are registered under the existing headless method names
``refresh``, ``rescore``, ``publish`` and ``report_export``; report exports default
to a review pack for the configured snapshot date, and an explicit ``as_of`` must
match that date. Paper bot and replay handlers are opt-in for the MCP headless
worker. Resource estimates use the scheduler's local ``auto`` profile, which
performs no network calls and never grants execution.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import os
import subprocess
import sys
from urllib.parse import quote

from etf_cockpit.application.headless_session import HeadlessSession
from etf_cockpit.core.job_scheduler import JobContext
from etf_cockpit.core.resource_profiles import HardwareSnapshot, estimate_workflow_resources


_HEADLESS_WORKFLOWS = frozenset({"refresh", "rescore", "publish", "report_export", "paper_bots_run", "paper_replay_run"})


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

    def inputs(context: JobContext) -> tuple[HeadlessSession, dict[str, object]]:
        session = session_factory()
        workflow = session.get_workflow(context.workflow_id)
        raw = getattr(workflow, "inputs", None)
        return session, dict(raw) if isinstance(raw, dict) else {}

    handlers: dict[str, Callable[[JobContext], dict[str, object]]] = {
        "refresh": refresh,
        "rescore": rescore,
        "publish": publish,
    }

    def report_export(context: JobContext) -> dict[str, object]:
        session, payload = inputs(context)
        kind = payload.get("kind", "review_pack")
        if kind not in {"review_pack", "portfolio_review"}:
            raise ValueError("kind must be review_pack or portfolio_review")
        snapshot = session.snapshot
        data_report = getattr(snapshot, "data_report", None)
        if data_report is None or getattr(data_report, "as_of_date", None) is None:
            raise ValueError("report export is unavailable because the snapshot has no data-quality as-of date")
        requested_as_of = payload.get("as_of")
        actual_as_of = data_report.as_of_date
        if requested_as_of is not None and str(requested_as_of) != actual_as_of.isoformat():
            raise ValueError("requested as_of does not match the configured headless snapshot; point-in-time report rebuild is unavailable")

        if kind == "portfolio_review":
            from etf_cockpit.application.portfolio_views import create_portfolio_review_report
            from etf_cockpit.core.types import latest_signal

            signals = list(getattr(snapshot, "signals", ()))
            newest_signal = latest_signal(signals)
            report = create_portfolio_review_report(
                signals,
                data_report,
                run_id=newest_signal.run_id if newest_signal is not None else "manual_trade_proposal",
            )
            path = Path(str(report["path"]))
            report_status = str(report.get("status", "unavailable"))
        else:
            session.publish()
            snapshot = session.snapshot
            data_report = getattr(snapshot, "data_report", None)
            ensure_backtest = getattr(snapshot, "ensure_backtest", None)
            if data_report is None or not callable(ensure_backtest):
                raise ValueError("review pack export is unavailable because the snapshot or canonical backtest service is missing")
            from etf_cockpit.application.chatgpt_review import ChatGPTBridge

            path = ChatGPTBridge(snapshot.config).export_review_pack(
                data_report.as_of_date,
                snapshot.holdings,
                snapshot.features,
                snapshot.signals,
                ensure_backtest(),
                data_report,
                publish_guard=session.activity_publication,
            )
            report_status = "exported"

        resource_path = path
        if path.suffix.casefold() == ".zip":
            resource_path = path.with_suffix("") / "combined_review_packet.md"
            if not resource_path.is_file():
                raise ValueError("review pack summary is unavailable as a text resource")
        try:
            relative = path.resolve().relative_to(session.root.resolve()).as_posix()
            resource_relative = resource_path.resolve().relative_to(session.root.resolve()).as_posix()
        except ValueError:
            raise ValueError("report export path is outside the configured data root") from None
        resource_link = {
            "uri": f"cockpit://exports/{quote(resource_relative, safe='/')}",
            "name": resource_path.name,
            "mimeType": "application/json",
        }
        return {
            "status": report_status,
            "kind": kind,
            "as_of": actual_as_of.isoformat(),
            "path": relative,
            "resource_link": resource_link,
            "execution_allowed": False,
        }

    if include_paper:
        handlers["report_export"] = report_export

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
