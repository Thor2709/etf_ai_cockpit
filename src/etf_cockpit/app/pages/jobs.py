from __future__ import annotations

from datetime import datetime, timezone
import threading

import flet as ft

from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    GlassCard,
    KpiTile,
    ListRow,
    Note,
    ScoreBar,
    TableColumn,
    Tag,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_timestamp
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
from etf_cockpit.core.paths import ROOT
from etf_cockpit.core.session_log import redact_text


_EMPTY_WORKFLOWS = "No durable workflows have been submitted yet."


def _status(value: str) -> tuple[str, str]:
    labels = {
        "queued": ("Queued", "mute"),
        "running": ("Running", "warn"),
        "succeeded": ("Completed", "ok"),
        "completed": ("Completed", "ok"),
        "failed": ("Failed", "bad"),
        "cancelled": ("Cancelled", "mute"),
    }
    return labels.get(value.casefold(), ("Unavailable", "bad"))


def _available_value(value: object, unit: str = "") -> str | None:
    if value is None or value == "":
        return None
    return f"{format_count(value, unavailable='—')} {unit}".strip()


def jobs_page(page: ft.Page | None, state: AppState | None) -> PageView:
    api = getattr(state, "application_api", None) if state is not None else None
    requested_profile = "auto"
    try:
        from etf_cockpit.application.onboarding_profile import load_onboarding

        requested_profile = load_onboarding(ROOT).hardware_profile
    except ValueError:
        pass

    try:
        if state is None:
            raise ValueError("No application state is available.")
        resource_policy = ResourcePolicy(ROOT, requested_profile=requested_profile)
        resource_report = resource_profile_report(
            ROOT,
            requested_profile=resource_policy.requested_profile,
            snapshot=resource_policy.snapshot,
        )
        estimate = estimate_workflow_resources(
            "durable_self_check",
            requested_profile=resource_policy.requested_profile,
            snapshot=resource_policy.snapshot,
        )
        selected_profile = resource_report.get("selected_profile") or {}
        resource_snapshot = resource_report.get("snapshot") or {}
        resource_reason = "Local resource readiness is unavailable."
        profile_value = str(selected_profile.get("profile_id") or "") or None
        cpu_value = _available_value(resource_snapshot.get("cpu_cores"), "cores")
        memory_value = _available_value(
            resource_snapshot.get("memory_available_mb") or resource_snapshot.get("memory_total_mb"),
            "MB",
        )
        disk_value = _available_value(resource_snapshot.get("disk_free_mb"), "MB")
        quota_note = (
            f"Per-job quota: {format_count(selected_profile.get('job_cpu_limit'), unavailable='—')} CPU cores; "
            f"{format_count(selected_profile.get('job_memory_limit_mb'), unavailable='—')} MB memory; "
            f"{format_count(selected_profile.get('job_disk_limit_mb'), unavailable='—')} MB disk."
        )
        resource_detail_text = (
            f"Self-check estimate: {estimate.get('memory_mb')} MB memory; {estimate.get('disk_mb')} MB disk; "
            f"batch={estimate.get('batch_size')}; chunk={estimate.get('chunk_size')}; status={estimate.get('status')}.\n"
            f"Selected profile: {selected_profile}; resource report: {resource_report}."
        )
        cache_status = str(resource_report.get("generated_cache", {}).get("status") or "unavailable")
        cleanup_status_text = f"Generated cache: {cache_status.replace('_', ' ').title()}"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        resource_report = {}
        estimate = {}
        selected_profile = {}
        resource_snapshot = {}
        resource_reason = "Local resource readiness is unavailable because no runtime profile data is available."
        profile_value = cpu_value = memory_value = disk_value = None
        quota_note = "Per-job quota is unavailable because no runtime profile data is available."
        resource_detail_text = "Self-check estimate and full resource profile are unavailable."
        cache_status = "unavailable"
        cleanup_status_text = "Generated cache: Unavailable"

    status_message = ft.Text("Durable jobs are local, resumable and audit-linked.")
    action_details = ft.Text("")
    cleanup_details = ft.Text("")
    cleanup_message = ft.Text(cleanup_status_text)
    workflow_note = ft.Text("Workflows are unavailable until the local job store is read.")
    workflow_rows: tuple[object, ...] = ()
    current_filter = {"value": "All"}
    recovered_count = 0
    table_slot = ft.Container(expand=True)
    timeline_slot = ft.Container(expand=True)
    workflow_details = ft.Column([], spacing=8)

    def update_page() -> None:
        if page is not None:
            page.update()

    def build_workflow_table(items: tuple[object, ...]) -> ft.Control:
        columns = [
            TableColumn("workflow", "Workflow", flex=2),
            TableColumn("state", "State"),
            TableColumn("progress", "Progress"),
            TableColumn("started", "Started"),
            TableColumn("duration", "Duration"),
            TableColumn("lease", "Lease"),
            TableColumn("action", "Action"),
        ]
        rows = []
        for workflow in items:
            label, kind = _status(str(getattr(workflow, "status", "")))
            rows.append(
                {
                    "workflow": getattr(workflow, "label", None) or "—",
                    "state": Tag(label, kind),
                    "progress": ScoreBar(None),
                    "started": format_timestamp(getattr(workflow, "created_at", None), unavailable="—"),
                    "duration": None,
                    "lease": None,
                    "action": None,
                }
            )
        return DataTable(
            columns,
            rows,
            empty_title=_EMPTY_WORKFLOWS,
            empty_reason="No durable workflows have been submitted yet.",
            expand=True,
        )

    def build_timeline(items: tuple[object, ...]) -> ft.Control:
        if not items:
            return EmptyState(
                _EMPTY_WORKFLOWS,
                "A workflow timeline is unavailable until workflow records exist.",
            )
        return ft.Column(
            [
                ListRow(
                    "warn" if str(getattr(item, "status", "")).casefold() == "running" else "info",
                    getattr(item, "label", None) or "—",
                    sub=format_timestamp(getattr(item, "created_at", None), unavailable="—"),
                    tag=Tag(_status(str(getattr(item, "status", "")))[0], _status(str(getattr(item, "status", "")))[1]),
                    last=index == len(items) - 1,
                )
                for index, item in enumerate(items)
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def filtered_workflows() -> tuple[object, ...]:
        if current_filter["value"] == "All":
            return workflow_rows
        if current_filter["value"] == "Running":
            return tuple(item for item in workflow_rows if str(getattr(item, "status", "")).casefold() in {"queued", "running"})
        if current_filter["value"] == "Failed":
            return tuple(item for item in workflow_rows if str(getattr(item, "status", "")).casefold() == "failed")
        return tuple(item for item in workflow_rows if str(getattr(item, "status", "")).casefold() in {"completed", "succeeded"})

    def update_workflow_views() -> None:
        selected = filtered_workflows()
        table_slot.content = build_workflow_table(selected)
        timeline_slot.content = Well(build_timeline(selected), expand=True)
        workflow_note.value = f"{format_count(len(workflow_rows))} workflows · recovered leases {format_count(recovered_count)}"
        workflow_details.controls = [
            Disclosure(
                "Workflow record",
                ft.Column(
                    [
                        Note(f"Workflow ID: {getattr(item, 'workflow_id', '—')}"),
                        Note(f"Raw status: {getattr(item, 'status', '—')}"),
                        Note(f"Hash chain valid: {getattr(item, 'hash_chain_valid', '—')}"),
                        Note(f"Error detail: {redact_text(str(getattr(item, 'error_message', '') or '—'))}"),
                    ],
                    spacing=8,
                ),
            )
            for item in workflow_rows
        ] or [Note("Workflow identifiers and raw statuses are unavailable until a workflow is returned.")]

    def select_filter(value: str) -> None:
        current_filter["value"] = value
        update_workflow_views()
        update_page()

    def refresh(_event: object | None = None) -> None:
        nonlocal workflow_rows, recovered_count
        if api is None:
            workflow_rows = ()
            recovered_count = 0
            update_workflow_views()
            return
        try:
            recovered = api.recover_expired_leases()
            workflow_page = api.get_jobs(PageRequest(limit=100))
            workflow_rows = tuple(workflow_page.items)
            recovered_count = len(recovered)
            status_message.value = "Durable workflow state refreshed from the local job store."
            action_details.value = ""
        except Exception as exc:
            workflow_rows = ()
            recovered_count = 0
            status_message.value = "Unable to read durable workflows from the local job store."
            action_details.value = f"{type(exc).__name__}: {redact_text(str(exc))}"
        update_workflow_views()
        update_page()

    def run_cache_cleanup(action_id: str) -> None:
        label = "Rebuild generated cache"
        try:
            with state.share_activity(action_id):
                result = generated_cache_cleanup(
                    ROOT,
                    maximum_bytes=int(selected_profile.get("job_disk_limit_mb") or 0) * 1024 * 1024,
                    apply=True,
                    publish_guard=lambda: state.activity_publication(action_id),
                )
            if state.activity_was_cancelled(action_id):
                return
            if result.get("status") in {"failed", "unavailable"}:
                cleanup_message.value = "Generated-cache cleanup failed."
                safe_error = redact_text(str(result.get("error") or result.get("message") or result.get("status")))
                cleanup_details.value = f"{safe_error}; result={result}"
                state.fail_activity(
                    label,
                    TimeoutError(safe_error),
                    retry_callback=start_cache_cleanup,
                    expected_action_id=action_id,
                )
            else:
                removed_count = len(result.get("removed", ()))
                cleanup_message.value = f"Generated-cache cleanup completed; {format_count(removed_count)} files removed."
                cleanup_details.value = str(result)
                state.update_activity("Cache cleanup complete", completed_units=1, total_units=1, expected_action_id=action_id)
                state.finish_activity(cleanup_message.value, output_path=result.get("cache_path"), label=label, expected_action_id=action_id)
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            safe_error = redact_text(str(exc))
            cleanup_message.value = "Generated-cache cleanup failed."
            cleanup_details.value = f"{type(exc).__name__}: {safe_error}"
            state.fail_activity(label, TimeoutError(safe_error), retry_callback=start_cache_cleanup, expected_action_id=action_id)
        finally:
            cancelled_message = state.restore_cancelled_activity_message(action_id)
            if cancelled_message is not None:
                cleanup_message.value = "Generated-cache cleanup was cancelled."
                cleanup_details.value = cancelled_message
            state.release_activity(action_id)
            update_page()

    def start_cache_cleanup() -> threading.Thread | None:
        if state is None:
            cleanup_message.value = "Generated-cache cleanup is unavailable."
            cleanup_details.value = "No application state is available."
            update_page()
            return None
        if state.current_activity is not None:
            cleanup_message.value = "Generated-cache cleanup is blocked while another local job is running."
            cleanup_details.value = str(state.current_activity)
            update_page()
            return None
        try:
            action_id = state.begin_activity("Rebuild generated cache", "Inspecting generated cache").action_id
        except Exception as exc:
            cleanup_message.value = "Generated-cache cleanup is unavailable."
            cleanup_details.value = f"{type(exc).__name__}: {redact_text(str(exc))}"
            update_page()
            return None
        cleanup_message.value = "Generated-cache cleanup is in progress."
        update_page()
        worker = threading.Thread(target=run_cache_cleanup, args=(action_id,), daemon=True)
        worker.start()
        return worker

    def clean_generated_cache(_event: object) -> None:
        start_cache_cleanup()

    def cancel_workflow(workflow_id: str) -> None:
        if api is None:
            return
        try:
            result = api.execute(CancelWorkflowCommand(idempotency_key=f"cancel-{workflow_id}", workflow_id=workflow_id))
            action_details.value = f"Workflow: {workflow_id}; response: {result.error_message or result.status.value}"
            status_message.value = "Workflow cancellation was recorded." if result.status in {ApiStatus.ACCEPTED, ApiStatus.REPLAYED} else "Workflow cancellation did not complete."
        except Exception as exc:
            status_message.value = "Workflow cancellation failed."
            action_details.value = f"{type(exc).__name__}: {redact_text(str(exc))}"
        refresh()

    def run_self_check(_event: object) -> None:
        if api is None:
            status_message.value = "The durable self-check is unavailable."
            update_page()
            return
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
            status_message.value = "Durable self-check submitted to the local scheduler."
            action_details.value = f"Response: {result}; workflow ID: {result.resource_id}"
        except Exception as exc:
            status_message.value = "The durable self-check could not start."
            action_details.value = f"{type(exc).__name__}: {redact_text(str(exc))}"
            refresh()
            return

        def worker() -> None:
            api.run_next_job(
                lambda _context: {"event_chain_valid": api.verify_event_chain(workflow_id=result.resource_id)},
                workflow_id=result.resource_id,
            )
            refresh()

        threading.Thread(target=worker, name="durable-job-self-check", daemon=True).start()
        update_page()

    table_slot.content = build_workflow_table(())
    timeline_slot.content = Well(build_timeline(()), expand=True)
    refresh()

    workflow_card = GlassCard(
        "Workflows",
        note="",
        body=ft.Column(
            [
                ft.Row(
                    [
                        workflow_note,
                        Button.secondary("Refresh", on_click=refresh, key="jobs.refresh"),
                        Button.secondary("Recover expired leases", on_click=refresh, key="jobs.recover"),
                        Button.primary("Run durable self-check", on_click=run_self_check, key="jobs.self-check"),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                table_slot,
                workflow_details,
                Disclosure("Action details", ft.Column([action_details], spacing=8)),
                status_message,
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )

    resource_card = GlassCard(
        "Resource readiness",
        note="local limits · no telemetry",
        body=ft.Column(
            [
                KpiTile("Profile", profile_value, sub=resource_reason if profile_value is None else "Selected local profile"),
                KpiTile("CPU", cpu_value, sub=resource_reason if cpu_value is None else "Available on this computer"),
                KpiTile("Memory", memory_value, sub=resource_reason if memory_value is None else "Available local memory"),
                KpiTile("Disk", disk_value, sub=resource_reason if disk_value is None else "Free local storage"),
                Note(quota_note),
                ft.Row(
                    [
                        Button.secondary("Clean generated cache", on_click=clean_generated_cache, key="jobs.resource-cache-cleanup"),
                        cleanup_message,
                    ],
                    spacing=12,
                    wrap=True,
                ),
                Disclosure("Self-check estimate and resource details", ft.Column([Note(resource_detail_text), cleanup_details], spacing=8)),
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )

    timeline_card = GlassCard(
        "Timeline",
        note="local workflow activity",
        body=timeline_slot,
        expand=True,
    )
    audit_card = GlassCard(
        "Audit events",
        note="hash-chained local events",
        body=Well(
            EmptyState("Unavailable", "The available job view does not provide audit event rows."),
            expand=True,
        ),
        expand=True,
    )

    row_a = ft.Row([workflow_card, resource_card], spacing=24, expand=6)
    row_b = ft.Row([timeline_card, audit_card], spacing=24, expand=4)
    body = ft.Column(
        [row_a, row_b, Note("Local job activity only. No broker or execution authority is enabled."), Disclosure("Raw authority flag", "execution_allowed=false")],
        spacing=24,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        chrome=PageChrome(
            title="Jobs & Activity",
            subtitle="Durable local workflows, dependency order and audit events",
            segment_groups=(
                SegmentGroup("jobs", ("All", "Running", "Failed", "Completed"), "All", on_change=select_filter),
            ),
        ),
        body=body,
    )
