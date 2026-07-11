from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.app.state import AppState


def instrument_detail_page(_page: ft.Page, state: AppState) -> ft.Control:
    selected = state.selected_etf
    model = build_instrument_detail(state.snapshot, selected)
    rows = [ft.Row([ft.Text(name, color=theme.TEXT, width=160), ft.Text(str(value), color=theme.MUTED, selectable=True)], spacing=8) for name, value in model.sections.items()]
    return ft.Column([panel(ft.Column([section_header(f"Instrument Detail: {model.display_name}", "Canonical identity, score evidence, data freshness and unavailable states are shown without recalculating authority in the UI."), ft.Text(str(model.identity), color=theme.MUTED, selectable=True), *rows], spacing=8))], expand=True, scroll=ft.ScrollMode.AUTO)
