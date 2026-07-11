from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, panel, section_header
from etf_cockpit.app.state import AppState


def errors_recovery_page(page: ft.Page, state: AppState) -> ft.Control:
    records = state.error_store.recent(limit=30)
    rows: list[ft.Control] = []
    if not records:
        rows.append(ft.Text("No controlled errors recorded in this session.", color=theme.MUTED))
    for record in records:
        colour = theme.AMBER if record.retryable else theme.RED
        controls: list[ft.Control] = [
            ft.Text(
                f"{record.created_at} | {record.category.value} | action={record.action_id or 'n/a'}",
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
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Errors and recovery", "Retry is available only for explicitly retryable failures. Parser, identity, permission and input errors require correction first."),
                        *rows,
                    ],
                    spacing=10,
                )
            )
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _retry(page: ft.Page, state: AppState, error_id: str) -> None:
    result = state.error_store.retry_request(error_id)
    state.last_message = "Retry requested." if result is not None else "This error is not retryable or its retry action is unavailable."
    from etf_cockpit.app.router import render_shell

    render_shell(page, state, "/errors")
