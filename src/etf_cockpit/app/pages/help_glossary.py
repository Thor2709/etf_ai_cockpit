"""Governance glossary surface."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import LegalTermsError, legal_terms_report
from etf_cockpit.core.paths import project_root
from etf_cockpit.governance.product_scope import load_glossary
from etf_cockpit.app.content.user_guidance import get_guidance_topics


def help_glossary_page(page: ft.Page | None, state: AppState) -> ft.Control:
    route = str(getattr(page, "route", "") or "") if page is not None else ""
    target = route.split("#", 1)[1].casefold() if "#" in route else ""

    def _slug(term: str) -> str:
        return term.casefold().replace(" ", "-").replace("/", "-")

    def open_help(term: str) -> None:
        if page is None:
            return
        suffix = f"#{_slug(term)}" if term else ""
        go = getattr(page, "go", None)
        if callable(go):
            go(f"/help{suffix}")
        else:
            page.route = f"/help{suffix}"
    loaded = load_glossary()
    try:
        legal_report = legal_terms_report(project_root())
        legal_status_text = f"Legal terms status: {legal_report['status']} ({legal_report['review_status']}); restricted sources are not redistributed."
        legal_status_color = theme.MUTED
    except LegalTermsError:
        legal_status_text = "Legal terms status: unavailable (manual review required); restricted sources are not redistributed."
        legal_status_color = theme.AMBER

    guidance_topics = get_guidance_topics()
    guidance_items: list[tuple[object, ft.Control]] = []
    for topic in guidance_topics:
        is_selected = target in {topic.slug, topic.slug.replace("-", "_")} or any(
            target == route.lstrip("/") or target == route.lstrip("/").replace("-", "_")
            for route in topic.routes
        )
        sections = [
            ft.Column(
                [
                    ft.Text(section.heading, weight=ft.FontWeight.BOLD, size=12, color=theme.TEXT, selectable=True),
                    ft.Text(section.body, color=theme.MUTED, size=11, selectable=True),
                ],
                spacing=2,
            )
            for section in topic.sections
        ]
        card = panel(
            ft.Column(
                [
                    ft.Text(topic.title, weight=ft.FontWeight.W_600, size=14, selectable=True),
                    ft.Text("Selected guide", color=theme.CYAN, size=10) if is_selected else ft.Container(height=0),
                    ft.Text(topic.summary, color=theme.MUTED, size=12, selectable=True),
                    ft.Text(f"Pages: {', '.join(topic.routes)}", color=theme.CYAN, size=11, selectable=True),
                    *sections,
                    ft.Text(topic.authority_notice, color=theme.AMBER, size=11, selectable=True),
                ],
                spacing=4,
            ),
            expand=True,
        )
        card.key = f"help.guidance-topic.{topic.slug}"
        guidance_items.append((topic, ft.Container(content=card, col={"xs": 12, "md": 6})))

    guidance_grid = ft.ResponsiveRow([container for _, container in guidance_items], spacing=10)
    guidance_no_match = ft.Text(
        "No user guidance topics matched the filter.",
        color=theme.MUTED,
        key="help.guidance-no-match",
        visible=False,
        selectable=True,
    )

    glossary_items: list[tuple[object | None, ft.Control]] = []
    if loaded.policy is not None and not loaded.diagnostic_mode:
        for entry in loaded.policy.entries:
            row_card = panel(
                ft.Column(
                    [
                        ft.TextButton(
                            entry.term,
                            key=f"help.glossary-term.{_slug(entry.term)}",
                            tooltip=f"Open glossary definition for {entry.term}",
                            on_click=lambda _event, term=entry.term: open_help(term),
                        ),
                        ft.Text("Selected definition", color=theme.CYAN, size=10) if target == _slug(entry.term) else ft.Container(height=0),
                        ft.Text(entry.definition, color=theme.MUTED, selectable=True),
                        ft.Text(entry.authority_note or "Authority remains bounded by evidence and policy.", color=theme.AMBER, size=11, selectable=True),
                    ],
                    spacing=6,
                ),
                expand=True,
            )
            glossary_items.append((entry, ft.Container(content=row_card, col={"xs": 12, "md": 6})))
    else:
        glossary_items.append(
            (
                None,
                ft.Container(
                    content=panel(ft.Text("Unavailable: glossary policy could not be loaded. Manual review is required.", color=theme.AMBER, selectable=True)),
                    col={"xs": 12, "md": 6},
                ),
            )
        )

    glossary_grid = ft.ResponsiveRow([container for _, container in glossary_items], spacing=12)
    glossary_no_match = ft.Text(
        "No glossary terms matched the filter.",
        color=theme.MUTED,
        key="help.glossary-no-match",
        visible=False,
        selectable=True,
    )

    def on_search_change(event: ft.ControlEvent | str | None = None) -> None:
        value = ""
        if isinstance(event, str):
            value = event
        elif event is not None:
            control = getattr(event, "control", None)
            value = str(getattr(control, "value", "") or getattr(event, "data", "") or "")
        if not value:
            value = str(search_box.value or "")
        value = value.strip().casefold()

        if value:
            guidance_grid.controls = [
                container
                for topic, container in guidance_items
                if value in topic.slug.casefold()
                or value in topic.title.casefold()
                or value in topic.summary.casefold()
                or any(
                    value in route.casefold()
                    or value in section.heading.casefold()
                    or value in section.body.casefold()
                    for route in topic.routes
                    for section in topic.sections
                )
            ]
            glossary_grid.controls = [
                container
                for entry, container in glossary_items
                if entry is not None
                and (
                    value in str(entry.term).casefold()
                    or value in str(entry.definition).casefold()
                    or value in str(entry.authority_note or "").casefold()
                )
            ]
        else:
            guidance_grid.controls = [container for _, container in guidance_items]
            glossary_grid.controls = [container for _, container in glossary_items]
        guidance_no_match.visible = bool(value) and not guidance_grid.controls
        glossary_no_match.visible = bool(value) and not glossary_grid.controls
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    search_box = ft.TextField(
        key="help.glossary-search",
        hint_text="Filter glossary and page guidance...",
        dense=True,
    )
    setattr(search_box, "on_change", on_search_change)
    guidance_panel = panel(
        ft.Column(
            [
                section_header("Page-level help and user manual", "Every registered workspace has explanatory guidance and an explicit authority boundary."),
                search_box,
                guidance_grid,
                guidance_no_match,
            ],
            spacing=8,
        )
    )
    guidance_panel.key = "help.user-guidance-panel"
    return ft.Column(
        [
            section_header("Help and glossary", "Definitions are explanatory and do not grant authority."),
            ft.Text("Authority is evidence-bounded. Manual review is required whenever evidence is incomplete or stale. Unavailable states are explicit and never imply a positive decision.", color=theme.MUTED, selectable=True),
            panel(ft.Column([section_header("Terms and use boundaries", "The registry records source and model permissions for local replay and audit export."), ft.Text("Research and education only. Not financial or tax advice. No broker execution or order transmission.", color=theme.AMBER, selectable=True), ft.Text(legal_status_text, color=legal_status_color, selectable=True)], spacing=6)),
            guidance_panel,
            section_header("Financial and governance glossary", "Explanatory definitions across portfolio, valuation, model, and governance concepts."),
            glossary_grid,
            glossary_no_match,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["help_glossary_page"]
