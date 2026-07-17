"""Governance glossary surface."""

from __future__ import annotations

from pathlib import Path

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import legal_terms_report
from etf_cockpit.governance.product_scope import load_glossary


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
    legal_report = legal_terms_report(Path.cwd())
    if loaded.policy is not None and not loaded.diagnostic_mode:
        rows: list[ft.Control] = [
            panel(
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
            for entry in loaded.policy.entries
        ]
    else:
        rows = [panel(ft.Text("Unavailable: glossary policy could not be loaded. Manual review is required.", color=theme.AMBER, selectable=True))]
    return ft.Column(
        [
            section_header("Help and glossary", "Definitions are explanatory and do not grant authority."),
            ft.Text("Authority is evidence-bounded. Manual review is required whenever evidence is incomplete or stale. Unavailable states are explicit and never imply a positive decision.", color=theme.MUTED, selectable=True),
            panel(ft.Column([section_header("Terms and use boundaries", "The registry records source and model permissions for local replay and audit export."), ft.Text("Research and education only. Not financial or tax advice. No broker execution or order transmission.", color=theme.AMBER, selectable=True), ft.Text(f"Legal terms status: {legal_report['status']} ({legal_report['review_status']}); restricted sources are not redistributed.", color=theme.MUTED, selectable=True)], spacing=6)),
            ft.ResponsiveRow([ft.Container(content=row, col={"xs": 12, "md": 6}) for row in rows], spacing=12),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["help_glossary_page"]
