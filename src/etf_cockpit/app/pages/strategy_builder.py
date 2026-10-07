"""Research-only strategy template page."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app.components.chartkit import bar_chart
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    GateCheck,
    GlassCard,
    ListRow,
    Note,
    TableColumn,
    Tag,
    Toggle,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.state import AppState
from etf_cockpit.application.strategy_templates import StrategyTemplateFacade


_STAGES = (
    ("analyse", "Analyse"),
    ("portfolio", "Portfolio"),
    ("backtest", "Backtest"),
    ("paper", "Paper"),
    ("draft_order", "Draft order"),
    ("canary", "Canary"),
    ("bounded_automatic", "Bounded automatic"),
)


def strategy_builder_page(page: ft.Page, state: AppState) -> PageView:
    facade = StrategyTemplateFacade()
    snapshot = getattr(getattr(state, "snapshot", None), "signals", ())
    matches = facade.matches(snapshot)
    by_template = {template.template_id: [] for template in facade.templates}
    for match in matches:
        by_template.setdefault(match.template_id, []).append(match)

    templates = list(facade.templates)
    template_rows_by_id: dict[str, ft.Control] = {}
    filter_state = {"selected": "All"}

    def select_template(template_id: str) -> None:
        template = templates_by_id[template_id]
        body.controls[0].controls[1] = GlassCard(
            f"Template detail · {template.name}",
            body=_template_detail(template, by_template[template_id]),
            expand=5,
        )
        if callable(getattr(page, "update", None)):
            page.update()

    templates_by_id = {template.template_id: template for template in templates}
    template_rows: list[ft.Control] = []
    for template in templates:
        enabled = facade.is_enabled(template.template_id)

        def set_enabled(value: bool, template_id: str = template.template_id) -> None:
            facade.set_enabled(template_id, value)
            filter_templates(filter_state["selected"])

        row = ft.Row(
            [
                Toggle(enabled, on_change=set_enabled, key=f"strategy-builder.status.{template.template_id}"),
                Button.secondary(
                    template.name,
                    on_click=lambda _e, template_id=template.template_id: select_template(template_id),
                    key="strategy-builder.template.*",
                ),
                Note(f"v{template.version} · benchmark {template.benchmark}"),
                Note(f"Matches {len(by_template[template.template_id])}"),
                Tag("context-only" if template.context_only else "long-only research", "warn" if template.context_only else "mute"),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        template_rows.append(row)
        template_rows_by_id[template.template_id] = row

    templates_card = GlassCard(
        "Strategy templates",
        note=f"{len(templates)} templates · {sum(facade.enabled.values())} enabled",
        body=[*template_rows, Note("Local preferences are stored atomically; execution_allowed=false.")],
        expand=7,
        key="strategy-builder.card.templates",
    )
    detail = GlassCard(
        f"Template detail · {templates[0].name}" if templates else "Template detail",
        body=_template_detail(templates[0], by_template[templates[0].template_id]) if templates else Note("Unavailable · no strategy templates are registered."),
        expand=5,
    )
    most_matches = max((len(by_template[template.template_id]) for template in templates), default=None)
    most_template = next(
        (template for template in templates if most_matches is not None and len(by_template[template.template_id]) == most_matches),
        None,
    )
    match_insight = (
        f"{most_template.name} has the most matches ({most_matches})."
        if most_template is not None
        else "Unavailable · no strategy match results are available."
    )
    matches_card = GlassCard(
        "Matches per template",
        insight=match_insight,
        body=bar_chart(
            [template.name for template in templates],
            [len(by_template[template.template_id]) for template in templates],
            x_name="Template",
            y_name="Matches (count)",
            unit="matches",
            show_labels=True,
            unavailable_reason="No strategy templates are registered." if not templates else None,
            insight=match_insight,
        ),
        expand=7,
    )
    coverage_rows = [
        {"template": template.name, **{key: _stage_label(template.stages.get(key)) for key, _ in _STAGES}}
        for template in templates
    ]
    coverage_card = GlassCard(
        "Stage coverage",
        body=DataTable(
            [TableColumn("template", "Template"), *[TableColumn(key, label) for key, label in _STAGES]],
            coverage_rows,
            max_visible_rows=8,
            empty_title="Unavailable",
            empty_reason="No strategy stage coverage is registered.",
        ),
        expand=5,
    )

    def filter_templates(option: str) -> None:
        filter_state["selected"] = option
        for template in templates:
            enabled = facade.is_enabled(template.template_id)
            template_rows_by_id[template.template_id].visible = (
                option == "All"
                or (option == "Enabled" and enabled)
                or (option == "Disabled" and not enabled)
            )
        if callable(getattr(page, "update", None)):
            page.update()

    body = ft.Column(
        [
            ft.Row([templates_card, detail], spacing=16, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ft.Row([matches_card, coverage_card], spacing=16, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(
        chrome=PageChrome(
            "Strategy Builder",
            "Reproducible long-only and context-only templates · matches are review evidence",
            [SegmentGroup("template-filter", ["All", "Enabled", "Disabled"], "All", filter_templates)],
        ),
        body=body,
    )


def _template_detail(template: object, matches: list[object]) -> ft.Control:
    stages = getattr(template, "stages", {})
    checks = []
    for key, label in _STAGES:
        stage_status = stages.get(key)
        if stage_status == "supported":
            reason = "Supported"
        elif stage_status == "supported_with_limitations":
            reason = "Supported with limitations"
        else:
            reason = "Unavailable"
        checks.append(
            GateCheck(stage_status in {"supported", "supported_with_limitations"}, label, reason)
        )
    matched = [
        ListRow("info", str(getattr(match, "instrument_id", "—")), str(getattr(match, "reason", "Unavailable")), last=index == len(matches) - 1)
        for index, match in enumerate(matches)
    ]
    return ft.Column(
        [
            Note(str(getattr(template, "description", "")) or "Description unavailable."),
            *checks,
            Disclosure("stage policy", str(dict(stages))),
            Disclosure("template definition", str(getattr(template, "definition", {}))),
            Disclosure("definition hash", str(getattr(template, "definition_hash", "")) or None),
            Note("Matched instruments"),
            *(matched or [Note("Unavailable · no instruments match this template.")]),
        ],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )


def _stage_label(value: object) -> ft.Control:
    if value == "supported":
        return Tag("✓", "ok", dense=True)
    if value == "supported_with_limitations":
        return Tag("~", "warn", dense=True)
    return Tag("–", "mute", dense=True)


__all__ = ["strategy_builder_page"]
