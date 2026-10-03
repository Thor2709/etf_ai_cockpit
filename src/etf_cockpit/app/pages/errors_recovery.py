from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.glass_pages import page_panel
from etf_cockpit.app.components.cards import evidence_chip, section_header
from etf_cockpit.app.formatting import format_timestamp
from etf_cockpit.app.state import AppState
from etf_cockpit.application.recovery_centre import RECOVERY_POLICIES, build_recovery_read_model, developer_mode_enabled


panel = page_panel("errors-recovery")


def errors_recovery_page(page: ft.Page, state: AppState) -> ft.Control:
    records = state.error_store.recent(limit=30)
    rows: list[ft.Control] = []
    if not records:
        rows.append(ft.Text("No controlled errors recorded in this session.", color=theme.MUTED))
    for record in records:
        colour = theme.AMBER if record.retryable else theme.RED
        controls: list[ft.Control] = [
            ft.Text(
                f"{format_timestamp(record.created_at)} | {record.category.value} | action={record.action_id or 'n/a'}",
                color=colour,
                size=12,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(record.user_message, color=theme.TEXT, selectable=True),
            ft.Text(f"Error ID: {record.error_id} | fingerprint: {record.fingerprint}", color=theme.MUTED, size=11),
            evidence_chip("Retry", "enabled" if record.retryable else "manual review", theme.GREEN if record.retryable else theme.AMBER),
        ]
        if record.retryable:
            controls.append(
                ft.OutlinedButton(
                    "Retry",
                    key=f"errors.retry.{record.error_id}",
                    icon=ft.Icons.REFRESH,
                    on_click=lambda _event, error_id=record.error_id: _retry(page, state, error_id),
                )
            )
        rows.append(ft.Container(bgcolor=theme.SURFACE_2, border_radius=6, padding=10, content=ft.Column(controls, spacing=5)))
    model = build_recovery_read_model(state)
    return ft.Column([
        panel(ft.Column([section_header("Errors and recovery", "Review controlled failures and the safe recovery policy."), section_header("Recent errors"), *rows], spacing=10)),
        panel(_developer_detail(records)),
        panel(_activity_log(state)),
        panel(_recovery_status(model)),
        panel(_recovery_policy()),
    ], expand=True, scroll=ft.ScrollMode.AUTO)


def _developer_detail(records: list[object]) -> ft.Control:
    controls: list[ft.Control] = [section_header("Developer detail")]
    if not developer_mode_enabled():
        controls.append(ft.Text("Technical detail is hidden outside developer mode.", color=theme.MUTED))
        return ft.Column(controls, spacing=8)
    details = [record for record in records if getattr(record, "detail", "")]
    if not details:
        controls.append(ft.Text("No technical detail is available.", color=theme.MUTED))
    for record in details:
        controls.append(ft.ExpansionTile(title=ft.Text(f"{getattr(record, 'error_id', 'error')} detail"), controls=[ft.Text(getattr(record, "detail", ""), selectable=True, font_family="monospace")]))
    return ft.Column(controls, spacing=8)


def _activity_log(state: AppState) -> ft.Control:
    controls: list[ft.Control] = [section_header("Activity Log", "Current workflow progress and recent activity.")]
    current = getattr(state, "current_activity", None)
    if current is not None:
        progress = f"{current.completed_units}/{current.total_units}" if current.total_units is not None else str(current.completed_units)
        controls.append(ft.Text(f"Current: {current.label} | {current.step} | progress {progress} | {current.message}", color=theme.TEXT))
    else:
        controls.append(ft.Text("No activity is currently running.", color=theme.MUTED))
    entries = list(getattr(state, "recent_activity", ()) or ())
    if not entries:
        controls.append(ft.Text("No recent activity recorded.", color=theme.MUTED))
    for entry in entries:
        controls.append(ft.Text(f"{format_timestamp(entry.started_at)} | action={getattr(entry, 'action_id', '') or entry.label} | {entry.status} | {entry.message or entry.step}", color=theme.TEXT, selectable=True))
    return ft.Column(controls, spacing=8)


def _recovery_status(model) -> ft.Control:
    controls: list[ft.Control] = [section_header("Recovery status", "Read-only status from trustworthy local read APIs; previous clean data remains unchanged after failed publication.")]
    jobs_unavailable = any("job" in reason.lower() for reason in model.unavailable_reasons)
    job_text = "unavailable" if jobs_unavailable else "; ".join(model.jobs) if model.jobs else "none reported"
    controls.extend([ft.Text(f"Latest published forecast date in the loaded snapshot: {model.forecasts_last_known_good}"), ft.Text(f"Loaded data as-of date: {model.data_last_known_good}"), ft.Text(f"Resumable/expired jobs: {job_text}")])
    controls.extend(ft.Text(reason, color=theme.MUTED, size=11) for reason in model.unavailable_reasons)
    return ft.Column(controls, spacing=8)


def _recovery_policy() -> ft.Control:
    cards = [
        ft.Container(
            bgcolor=theme.SURFACE_2,
            border_radius=6,
            padding=10,
            content=ft.Column(
                [
                    ft.Text(card.title, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Symptom: {card.symptom}"),
                    ft.Text(f"Guarantee: {card.guarantee}"),
                    ft.Text(f"Steps: {card.steps}"),
                ],
                spacing=4,
            ),
        )
        for card in RECOVERY_POLICIES
    ]
    return ft.Column([section_header("Recovery policy", "Declarative guidance only; no automatic recovery actions."), *cards], spacing=8)


def _retry(page: ft.Page, state: AppState, error_id: str) -> None:
    result = state.error_store.retry_request(error_id)
    state.last_message = "Retry requested." if result is not None else "This error is not retryable or its retry action is unavailable."
    from etf_cockpit.app.router import render_shell

    render_shell(page, state, "/errors")
