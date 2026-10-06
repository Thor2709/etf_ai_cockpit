"""Render-only strategy template builder page."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import section_header
from etf_cockpit.app.components.kit import glass_panel, status_tag
from etf_cockpit.app.state import AppState
from etf_cockpit.application.strategy_templates import StrategyTemplateFacade


def strategy_builder_page(page: ft.Page, state: AppState) -> ft.Control:
    facade = StrategyTemplateFacade()
    snapshot = getattr(state.snapshot, "signals", ())
    matches = facade.matches(snapshot)
    match_ids = {template_id: sum(item.template_id == template_id for item in matches) for template_id in facade.enabled}
    status = ft.Text("Local preferences are stored atomically; execution_allowed=false.", color=theme.MUTED, selectable=True)

    rows: list[ft.Control] = []
    for template in facade.templates:
        enabled_now = facade.is_enabled(template.template_id)
        badge = status_tag("Enabled" if enabled_now else "Disabled", "g" if enabled_now else "w", key=f"strategy-builder.status.{template.template_id}")
        button = ft.Button(
            "Disable" if enabled_now else "Enable",
            data=(template.template_id, not enabled_now),
            key="strategy-builder.template.*",
        )

        def toggle_template(
            event: ft.ControlEvent,
            template_id: str = template.template_id,
            action_button: ft.Button = button,
            status_badge: ft.Container = badge,
        ) -> None:
            control = getattr(event, "control", action_button)
            data = getattr(control, "data", action_button.data)
            enabled = bool(data[1]) if isinstance(data, tuple) and len(data) > 1 else False
            try:
                facade.set_enabled(template_id, enabled)
                action_button.data = (template_id, not enabled)
                action_button.text = "Disable" if not enabled else "Enable"
                status_badge.content.value = "Enabled" if enabled else "Disabled"
                status_badge.content.color = theme.GREEN if enabled else theme.AMBER
                status_badge.bgcolor = "#296fcfa6" if enabled else "#29e6c27a"
                status.value = f"Saved {template_id} preference locally; no analysis or execution was started."
                status.color = theme.GREEN
            except (KeyError, OSError, ValueError) as exc:
                status.value = f"Template preference was not saved: {type(exc).__name__}."
                status.color = theme.AMBER
            if callable(getattr(page, "update", None)):
                page.update()

        button.on_click = toggle_template
        rows.append(
            glass_panel(
                ft.Column(
                    [
                        ft.Row(
                            [
                                badge,
                                button,
                                ft.Text(template.name, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                                ft.Text(f"matches: {match_ids.get(template.template_id, 0)}", color=theme.CYAN, size=theme.FONT_SM),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text(f"v{template.version} · hash {template.definition_hash[:16]} · benchmark {template.benchmark}", color=theme.MUTED, selectable=True),
                        ft.Text(f"stages: {dict(template.stages)}", color=theme.MUTED, selectable=True),
                        ft.Text("context-only; no trade actions" if template.context_only else "long-only research/review template; no execution authority", color=theme.AMBER, selectable=True),
                    ],
                    spacing=6,
                ),
                key=f"strategy-builder.card.{template.template_id}",
                label=f"Strategy template {template.name}",
                padding=18,
            )
        )
    return ft.Column(
        [
            section_header("Strategy builder", "Enable or disable reproducible, benchmarked long-only/context-only templates. Matches are descriptive review evidence."),
            status,
            *rows,
        ],
        spacing=12,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


__all__ = ["strategy_builder_page"]
