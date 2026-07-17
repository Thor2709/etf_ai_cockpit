from __future__ import annotations

from datetime import datetime, timezone
import threading

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    ApiStatus,
    CancelWorkflowCommand,
    PageRequest,
    SubmitWorkflowCommand,
)


def jobs_page(page: ft.Page, state: AppState) -> ft.Control:
    api = state.application_api
    body = ft.Column(spacing=10, expand=True, scroll=ft.ScrollMode.AUTO)
    message = ft.Text("Durable jobs are local, resumable and audit-linked.", color=theme.MUTED, selectable=True)

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        try:
            recovered = api.recover_expired_leases()
            workflows = api.get_jobs(PageRequest(limit=100))
            rows: list[ft.Control] = [
                ft.Row(
                    [
                        ft.Text(f"{workflows.total} workflow(s) · recovered leases: {len(recovered)}", color=theme.MUTED),
                        ft.TextButton("Recover expired leases", key="jobs.recover", on_click=refresh),
                        ft.TextButton("Refresh", key="jobs.refresh", on_click=refresh),
                        ft.TextButton("Run durable self-check", key="jobs.self-check", on_click=run_self_check),
                    ],
                    wrap=True,
                )
            ]
            if not workflows.items:
                rows.append(ft.Text("No durable workflows have been submitted yet.", color=theme.MUTED))
            for workflow in workflows.items:
                controls: list[ft.Control] = [
                    ft.Text(
                        f"{workflow.label} · {workflow.status} · {workflow.workflow_id}",
                        color=theme.TEXT,
                        weight=ft.FontWeight.BOLD,
                        selectable=True,
                    ),
                    ft.Text(
                        f"Created {workflow.created_at} · jobs {workflow.job_count} · "
                        f"hash chain {'valid' if workflow.hash_chain_valid else 'INVALID'} · finished {workflow.finished_at or 'running'}",
                        color=theme.MUTED,
                        size=11,
                        selectable=True,
                    ),
                ]
                if workflow.active:
                    controls.append(
                        ft.TextButton(
                            "Cancel workflow",
                            key="jobs.cancel.workflow",
                            on_click=lambda _event, workflow_id=workflow.workflow_id: cancel_workflow(workflow_id),
                        )
                    )
                controls.append(ft.Text(f"  ↳ {workflow.job_count} durable job(s) registered.", color=theme.MUTED, size=11, selectable=True))
                rows.append(panel(ft.Column(controls, spacing=5)))
            body.controls = rows
            message.value = "Durable jobs are local, resumable and audit-linked."
        except Exception as exc:
            body.controls = [ft.Text(f"Unable to read durable jobs: {type(exc).__name__}: {exc}", color=theme.RED, selectable=True)]
            message.value = "The durable job store reported a readable failure. No output was published."
        page.update()

    def cancel_workflow(workflow_id: str) -> None:
        try:
            result = api.execute(CancelWorkflowCommand(idempotency_key=f"cancel-{workflow_id}", workflow_id=workflow_id))
            message.value = f"Cancellation {'recorded' if result.status in {ApiStatus.ACCEPTED, ApiStatus.REPLAYED} else 'failed'} for {workflow_id}: {result.error_message or result.status.value}."
        except Exception as exc:
            message.value = f"Cancellation failed: {type(exc).__name__}: {exc}"
        refresh()

    def run_self_check(_event: ft.ControlEvent) -> None:
        dedupe_key = f"durable-self-check:{datetime.now(timezone.utc).date().isoformat()}"
        try:
            result = api.execute(
                SubmitWorkflowCommand(
                    idempotency_key=dedupe_key,
                    workflow_type="durable_self_check",
                    label="Durable scheduler self-check",
                    input_payload={"requested_from": "jobs_page"},
                    job_keys=("verify_event_chain",),
                    dedupe_key=dedupe_key,
                )
            )
            if result.status not in {ApiStatus.ACCEPTED, ApiStatus.REPLAYED}:
                raise RuntimeError(result.error_message or result.status.value)
            message.value = f"Started {result.resource_id or 'workflow'}; acknowledgement recorded."
        except Exception as exc:
            message.value = f"Self-check could not start: {type(exc).__name__}: {exc}"
            refresh()
            return

        def worker() -> None:
            api.run_next_job(lambda _context: {"event_chain_valid": api.verify_event_chain()})
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
