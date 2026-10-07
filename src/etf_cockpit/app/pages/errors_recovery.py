from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.formatting import format_timestamp
from etf_cockpit.app.state import AppState
from etf_cockpit.application.recovery_centre import (
    RECOVERY_POLICIES,
    build_recovery_read_model,
    developer_mode_enabled,
)

TextButton = kit.Button.secondary


def errors_recovery_page(page: ft.Page, state: AppState) -> PageView:
    records = state.error_store.recent(limit=30)
    model = build_recovery_read_model(state)
    errors = []
    for record in records:
        severity = "warn" if record.retryable else "bad"
        retry = TextButton(
            "Retry",
            key=f"errors.retry.{record.error_id}",
            on_click=lambda _event, error_id=record.error_id: _retry(page, state, error_id),
        ) if record.retryable else None
        details = f"error_id={record.error_id}\nfingerprint={record.fingerprint}\naction_id={record.action_id or '—'}\ncategory={record.category.value}"
        content = [
            kit.ListRow(
                "bad",
                record.user_message,
                format_timestamp(record.created_at, unavailable="Unavailable"),
                tag=(record.category.value, severity),
            )
        ]
        if retry is not None:
            content.append(retry)
        if developer_mode_enabled():
            content.append(kit.Disclosure("Developer detail", f"{details}\n{record.detail or 'No technical detail is available.'}"))
        errors.extend(content)
    recent_errors = kit.GlassCard(
        "Recent errors",
        note=f"{len(records)} controlled errors" if records else "Current session",
        body=ft.Column(
            errors or [kit.EmptyState("No controlled errors", "No controlled errors recorded in this session.")],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )

    jobs_unavailable = any("job" in reason.lower() for reason in model.unavailable_reasons)
    forecast_date = model.forecasts_last_known_good
    data_date = model.data_last_known_good
    if str(forecast_date or "").casefold() in {"unavailable", "n/a", "none"}:
        forecast_date = None
    if str(data_date or "").casefold() in {"unavailable", "n/a", "none"}:
        data_date = None
    recovery = kit.GlassCard(
        "Recovery status",
        note="Read-only local status",
        body=ft.Column(
            [
                kit.KpiTile("Latest published forecast date", forecast_date, "Unavailable: no published forecast date is available." if not forecast_date else ""),
                kit.KpiTile("Loaded data as-of date", data_date, "Unavailable: no loaded data date is available." if not data_date else ""),
                kit.KpiTile("Resumable/expired jobs", None if jobs_unavailable else "Available" if model.jobs else "None reported", "Unavailable: job status is not available from the local read API." if jobs_unavailable else "No resumable or expired jobs are reported." if not model.jobs else ""),
                kit.Note("Read-only status from trustworthy local read APIs; previous clean data remains unchanged after failed publication."),
                kit.Disclosure("Recovery read details", "\n".join(model.unavailable_reasons) or "No additional recovery details are available."),
                kit.Disclosure("Resumable and expired job details", "\n".join(model.jobs) or "No job details are available."),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )

    policy_rows = [
        kit.ListRow(
            "info",
            policy.title,
            f"Symptom: {policy.symptom} · Guarantee: {policy.guarantee} · Steps: {policy.steps}",
            tag=("Policy", "mute"),
        )
        for policy in RECOVERY_POLICIES
    ]
    policy = kit.GlassCard(
        "Recovery policy",
        note="Declarative guidance",
        body=ft.Column(policy_rows or [kit.EmptyState("Unavailable", "Recovery policy is not available.")], spacing=8, scroll=ft.ScrollMode.AUTO),
        expand=True,
    )

    current = getattr(state, "current_activity", None)
    activity_rows = []
    if current is not None:
        progress = f"{current.completed_units}/{current.total_units}" if current.total_units is not None else str(current.completed_units)
        activity_rows.append(kit.ListRow("info", current.label, f"{current.step} · {progress}"))
        activity_rows.append(kit.Disclosure("Activity details", f"status=running\nprogress={progress}\nmessage={current.message}"))
    for entry in list(getattr(state, "recent_activity", ()) or ()):
        message = getattr(entry, "message", "") or "No activity detail is available."
        activity_rows.append(
            kit.ListRow(
                "warn" if str(entry.status).lower() not in {"passed", "complete", "completed"} else "ok",
                getattr(entry, "label", "Activity"),
                getattr(entry, "step", "") or "Activity update",
            )
        )
        activity_rows.append(
            kit.Disclosure(
                "Activity details",
                f"message={message}\nstarted_at={format_timestamp(entry.started_at, unavailable='Unavailable')}\naction_id={getattr(entry, 'action_id', '') or '—'}\nstatus={entry.status}\nstep={entry.step}",
            )
        )
    activity = kit.GlassCard(
        "Activity log",
        note="Workflow progress and recent activity",
        body=ft.Column(activity_rows or [kit.EmptyState("No activity", "No activity is currently running.")], spacing=8, scroll=ft.ScrollMode.AUTO),
        expand=True,
    )
    if not developer_mode_enabled():
        recent_errors.content.controls.append(kit.Note("Technical detail is hidden outside developer mode."))
    body = ft.ResponsiveRow(
        [
            ft.Container(content=recent_errors, col={"xs": 12, "md": 7}),
            ft.Container(content=recovery, col={"xs": 12, "md": 5}),
            ft.Container(content=policy, col={"xs": 12, "md": 7}),
            ft.Container(content=activity, col={"xs": 12, "md": 5}),
        ],
        spacing=12,
        run_spacing=12,
        expand=True,
    )
    return PageView(PageChrome("Errors & Recovery", "Controlled failures and the safe recovery policy"), body)


def _retry(page: ft.Page, state: AppState, error_id: str) -> None:
    result = state.error_store.retry_request(error_id)
    state.last_message = "Retry requested." if result is not None else "This error is not retryable or its retry action is unavailable."
    from etf_cockpit.app.router import render_shell

    render_shell(page, state, "/errors")
