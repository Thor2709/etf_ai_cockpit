from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    ApiStatus,
    CancelWorkflowCommand,
    PageRequest,
    ResourcePolicy,
    SubmitWorkflowCommand,
    estimate_workflow_resources,
    generated_cache_cleanup,
    resource_profile_report,
)


def jobs_page(page: ft.Page, state: AppState) -> ft.Control:
    api = state.application_api
    body = ft.Column(spacing=10, expand=True, scroll=ft.ScrollMode.AUTO)
    message = ft.Text("Durable jobs are local, resumable and audit-linked.", color=theme.MUTED, selectable=True)
    resource_policy = ResourcePolicy(Path.cwd())
    resource_report = resource_profile_report(
        Path.cwd(),
        requested_profile=resource_policy.requested_profile,
        snapshot=resource_policy.snapshot,
    )
    estimate = estimate_workflow_resources(
        "durable_self_check",
        requested_profile=resource_policy.requested_profile,
        snapshot=resource_policy.snapshot,
    )
    selected_profile = resource_report["selected_profile"]
    benchmark_status = resource_report["benchmarks"]["status"]
    cleanup_status = resource_report["generated_cache"]["status"]
    cleanup_message = ft.Text(
        f"Generated-cache cleanup: {cleanup_status}.", color=theme.MUTED
    )

    def clean_generated_cache(_event: ft.ControlEvent) -> None:
        label = "Rebuild generated cache"
        if state.current_activity is not None:
            cleanup_message.value = f"Generated-cache cleanup blocked: {state.current_activity.label} is running."
            cleanup_message.color = theme.RED
            page.update()
            return
        action_id = state.begin_activity(label, "Inspecting generated cache").action_id
        try:
            state.assert_activity_publishable(action_id)
            result = generated_cache_cleanup(
                Path.cwd(),
                maximum_bytes=int(selected_profile["job_disk_limit_mb"]) * 1024 * 1024,
                apply=True,
            )
            removed = len(result.get("removed", []))
            cleanup_message.value = (
                f"Generated-cache cleanup: {result['status']}; removed {removed} reproducible file(s)."
            )
            cleanup_message.color = theme.RED if result["status"] in {"failed", "unavailable"} else theme.GREEN
            if result["status"] in {"failed", "unavailable"}:
                state.fail_activity(
                    label,
                    RuntimeError(str(result.get("error") or result.get("message") or result["status"])),
                    expected_action_id=action_id,
                )
                cleanup_message.value = state.last_message
            else:
                state.update_activity(
                    "Cache cleanup complete",
                    completed_units=1,
                    total_units=1,
                    expected_action_id=action_id,
                )
                state.finish_activity(
                    cleanup_message.value,
                    output_path=result.get("cache_path"),
                    label=label,
                    expected_action_id=action_id,
                )
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity(label, exc, expected_action_id=action_id)
            cleanup_message.value = state.last_message
            cleanup_message.color = theme.RED
        page.update()

    resource_panel = panel(
        ft.Column(
            [
                section_header("Resource readiness", "Every durable job is checked against the local snapshot before work starts."),
                ft.SelectionArea(ft.Text(
                    f"Profile: {resource_report['selected_profile']['profile_id']} ({resource_report['selected_status']}) | "
                    f"CPU {resource_report['snapshot']['cpu_cores']} core(s) | "
                    f"free disk {resource_report['snapshot'].get('disk_free_mb') or 'n/a'} MB | "
                    f"memory {resource_report['snapshot'].get('memory_available_mb') or resource_report['snapshot'].get('memory_total_mb') or 'n/a'} MB",
                    color=theme.MUTED,
                )),
                ft.Row(
                    [
                        ft.TextButton(
                            "Clean generated cache",
                            key="jobs.resource-cache-cleanup",
                            on_click=clean_generated_cache,
                        ),
                        cleanup_message,
                    ],
                    wrap=True,
                ),
                ft.SelectionArea(ft.Text(
                    f"Self-check estimate: {estimate['memory_mb']} MB memory, {estimate['disk_mb']} MB disk, "
                    f"batch={estimate['batch_size']}, chunk={estimate['chunk_size']}, status={estimate['status']}; "
                    "limits are local and execution_allowed=false.",
                    color=theme.MUTED,
                )),
                ft.SelectionArea(ft.Text(
                    f"Per-job quota: {selected_profile['job_memory_limit_mb']} MB memory, "
                    f"{selected_profile['job_disk_limit_mb']} MB disk, {selected_profile['job_cpu_limit']} CPU; "
                    f"benchmark evidence={benchmark_status}; generated-cache cleanup={cleanup_status}.",
                    color=theme.MUTED,
                )),
            ],
            spacing=6,
        )
    )

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
            resource_panel,
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
