from __future__ import annotations

from datetime import datetime, timezone
import threading

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import DurableJobScheduler, JobSpec, JobStatus
from etf_cockpit.core.paths import ROOT


def jobs_page(page: ft.Page, _state: AppState) -> ft.Control:
    scheduler = DurableJobScheduler(ROOT, max_concurrency=1)
    body = ft.Column(spacing=10, expand=True, scroll=ft.ScrollMode.AUTO)
    message = ft.Text("Durable jobs are local, resumable and audit-linked.", color=theme.MUTED, selectable=True)

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        try:
            recovered = scheduler.recover_expired_leases()
            workflows = scheduler.list_workflows()
            rows: list[ft.Control] = [
                ft.Row(
                    [
                        ft.Text(f"{len(workflows)} workflow(s) · recovered leases: {len(recovered)}", color=theme.MUTED),
                        ft.TextButton("Recover expired leases", key="jobs.recover", on_click=refresh),
                        ft.TextButton("Refresh", key="jobs.refresh", on_click=refresh),
                        ft.TextButton("Run durable self-check", key="jobs.self-check", on_click=run_self_check),
                    ],
                    wrap=True,
                )
            ]
            if not workflows:
                rows.append(ft.Text("No durable workflows have been submitted yet.", color=theme.MUTED))
            for workflow in workflows:
                jobs = scheduler.list_jobs(workflow.workflow_id)
                events = scheduler.list_events(workflow.workflow_id, limit=1000)
                controls: list[ft.Control] = [
                    ft.Text(
                        f"{workflow.label} · {workflow.status.value} · {workflow.workflow_id}",
                        color=theme.TEXT,
                        weight=ft.FontWeight.BOLD,
                        selectable=True,
                    ),
                    ft.Text(
                        f"Inputs {workflow.input_hash[:16]}… · created {workflow.created_at} · "
                        f"events {len(events)} · hash chain {'valid' if scheduler.verify_event_chain(workflow.workflow_id) else 'INVALID'} · "
                        f"finished {workflow.finished_at or 'running'}",
                        color=theme.MUTED,
                        size=11,
                        selectable=True,
                    ),
                ]
                if workflow.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    controls.append(
                        ft.TextButton(
                            "Cancel workflow",
                            key="jobs.cancel.workflow",
                            on_click=lambda _event, workflow_id=workflow.workflow_id: cancel_workflow(workflow_id),
                        )
                    )
                for job in jobs:
                    dependencies = ", ".join(job.dependencies) or "none"
                    controls.append(
                        ft.Text(
                            f"  ↳ {job.job_key}: {job.status.value} · deps={dependencies} · "
                            f"retry={job.retry_count}/{job.max_retries} · checkpoint={dict(job.checkpoint) or 'none'}",
                            color=theme.MUTED,
                            size=11,
                            selectable=True,
                        )
                    )
                rows.append(panel(ft.Column(controls, spacing=5)))
            body.controls = rows
            message.value = "Durable jobs are local, resumable and audit-linked."
        except Exception as exc:
            body.controls = [ft.Text(f"Unable to read durable jobs: {type(exc).__name__}: {exc}", color=theme.RED, selectable=True)]
            message.value = "The durable job store reported a readable failure. No output was published."
        page.update()

    def cancel_workflow(workflow_id: str) -> None:
        try:
            scheduler.cancel(workflow_id)
            message.value = f"Cancellation recorded for {workflow_id}."
        except Exception as exc:
            message.value = f"Cancellation failed: {type(exc).__name__}: {exc}"
        refresh()

    def run_self_check(_event: ft.ControlEvent) -> None:
        dedupe_key = f"durable-self-check:{datetime.now(timezone.utc).date().isoformat()}"
        try:
            workflow = scheduler.submit(
                "durable_self_check",
                "Durable scheduler self-check",
                (JobSpec("verify_event_chain", "Verify event hash chain", input_payload={"scope": "local"}),),
                input_payload={"requested_from": "jobs_page"},
                dedupe_key=dedupe_key,
            )
            message.value = f"Started {workflow.workflow_id}; acknowledgement recorded."
        except Exception as exc:
            message.value = f"Self-check could not start: {type(exc).__name__}: {exc}"
            refresh()
            return

        def worker() -> None:
            scheduler.run_once(lambda _context: {"event_chain_valid": scheduler.verify_event_chain()})
            refresh()

        threading.Thread(target=worker, name="durable-job-self-check", daemon=True).start()
        page.update()

    refresh()
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Jobs & Activity", "Durable local workflows, dependency order, recovery actions and hash-chained audit events."),
                        message,
                        body,
                    ],
                    spacing=10,
                    expand=True,
                )
            )
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
