"""Render-only strategy template builder page."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.strategy_templates import StrategyTemplateFacade


def strategy_builder_page(page: ft.Page, state: AppState) -> ft.Control:
    facade = StrategyTemplateFacade()
    snapshot = getattr(state.snapshot, "signals", ())
    matches = facade.matches(snapshot)
    match_ids = {template_id: sum(item.template_id == template_id for item in matches) for template_id in facade.enabled}
    status = ft.Text("Local preferences are stored atomically; execution_allowed=false.", color=theme.MUTED, selectable=True)

    def toggle_template(event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        data = getattr(control, "data", "")
        template_id = str(data[0] if isinstance(data, tuple) else data or "").strip()
        enabled = bool(data[1]) if isinstance(data, tuple) and len(data) > 1 else False
        if not template_id:
            status.value = "Template preference was not changed: missing template identity."
            status.color = theme.AMBER
        else:
            try:
                facade.set_enabled(template_id, enabled)
                status.value = f"Saved {template_id} preference locally; no analysis or execution was started."
                status.color = theme.GREEN
            except (KeyError, OSError, ValueError) as exc:
                status.value = f"Template preference was not saved: {type(exc).__name__}."
                status.color = theme.AMBER
        if callable(getattr(page, "update", None)):
            page.update()

    rows: list[ft.Control] = []
    for template in facade.templates:
        rows.append(
            panel(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Button(
                                    "Disable" if facade.is_enabled(template.template_id) else "Enable",
                                    data=(template.template_id, not facade.is_enabled(template.template_id)),
                                    key="strategy-builder.template.*",
                                    on_click=toggle_template,
                                ),
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
                )
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
