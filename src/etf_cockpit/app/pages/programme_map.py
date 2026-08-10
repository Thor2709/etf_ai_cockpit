"""Canonical programme map and authority view."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.components.governance_badges import status_badge
from etf_cockpit.app.state import AppState
from etf_cockpit.application.programme_map import ProgrammeMap, ProgrammeMapEntry, load_programme_map
from etf_cockpit.core.paths import ROOT


def _entry_card(entry: ProgrammeMapEntry) -> ft.Container:
    dependencies = ", ".join(entry.blocking_dependencies) or "none"
    inputs = ", ".join(entry.required_inputs) or "none"
    activation = ", ".join(entry.activation_dependencies) or "none"
    readiness_reasons = ", ".join(entry.readiness_reason_codes)
    edge_reasons = ", ".join(entry.edge_reason_codes) or "none"
    downstream = ", ".join(entry.downstream_issues) or "none"
    related = ", ".join(entry.related_issues) or "none"
    badges = [
        status_badge("Implementation", entry.implementation, colour=theme.CYAN),
        status_badge("Release", entry.release, colour=theme.AMBER),
        status_badge("Data", entry.data, colour=theme.MUTED),
        status_badge("Model", entry.model, colour=theme.MUTED),
        status_badge("Paper", entry.paper, colour=theme.AMBER),
        status_badge("Live", entry.live, colour=theme.RED),
        status_badge("Implementation readiness", "ready" if entry.ready else "blocked", colour=theme.GREEN if entry.ready else theme.AMBER),
        status_badge("Activation readiness", "ready" if entry.activation_ready else "blocked", colour=theme.GREEN if entry.activation_ready else theme.RED),
    ]
    return panel(
        ft.Column(
            [
                ft.Text(f"{entry.canonical_id} · {entry.title}", color=theme.TEXT, size=14, weight=ft.FontWeight.BOLD, selectable=True),
                ft.Text(f"{entry.phase} · priority {entry.priority}", color=theme.MUTED, size=11, selectable=True),
                ft.Row(badges, wrap=True, spacing=6, run_spacing=6),
                ft.Text(f"Blocking dependencies: {dependencies}", color=theme.MUTED, size=11, selectable=True),
                ft.Text(f"Required inputs: {inputs}", color=theme.MUTED, size=11, selectable=True),
                ft.Text(f"Readiness reasons: {readiness_reasons} · Edges: {edge_reasons}", color=theme.MUTED, size=11, selectable=True),
                ft.Text(f"Activation dependencies: {activation} · Activation reasons: {', '.join(entry.activation_reason_codes)}", color=theme.AMBER, size=11, selectable=True),
                ft.Text(f"Downstream issues: {downstream} · Related: {related}", color=theme.MUTED, size=11, selectable=True),
            ],
            spacing=7,
        ),
        expand=True,
    )


def _summary(map_data: ProgrammeMap) -> ft.Control:
    if map_data.status != "loaded":
        return panel(
            ft.Column(
                [
                    status_badge("Registry", "blocked", colour=theme.RED),
                    ft.Text(map_data.error or "Canonical issue registry unavailable; no readiness is inferred.", color=theme.AMBER, selectable=True),
                ],
                spacing=8,
            )
        )
    status_counts = " · ".join(f"{status}: {count}" for status, count in map_data.counts) or "none"
    return panel(
        ft.Column(
            [
                ft.Row([status_badge("Registry", "loaded", colour=theme.GREEN), status_badge("Paper authority", "disabled", colour=theme.AMBER), status_badge("Live authority", "disabled", colour=theme.RED)], wrap=True, spacing=6),
                ft.Text(f"Canonical issue records: {len(map_data.entries)} · implementation statuses: {status_counts}", color=theme.TEXT, selectable=True),
                ft.Text(f"Registry SHA-256: {map_data.registry_sha256}", color=theme.MUTED, size=11, selectable=True),
                ft.Text("Release is the registry package status, not release certification. Implementation readiness is derived only from the canonical closure evidence; programme status cannot resolve a blocker. Activation is separate and never grants execution. Missing data/model evidence remains explicit, paper/live authority is disabled by policy, and execution_allowed=false.", color=theme.AMBER, size=11, selectable=True),
            ],
            spacing=8,
        )
    )


def programme_map_page(_page: ft.Page | None, _state: AppState) -> ft.Control:
    """Render the canonical map as a read-only, text-first governance surface."""

    map_data = load_programme_map(ROOT)
    cards = [ft.Container(content=_entry_card(entry), col={"xs": 12, "md": 6, "lg": 4}) for entry in map_data.entries]
    if not cards and map_data.status == "blocked":
        cards.append(ft.Container(content=panel(ft.Text("No issue records are displayed while the registry is blocked.", color=theme.AMBER, selectable=True)), col={"xs": 12}))
    return ft.Column(
        [
            section_header("Programme Map", "Canonical implementation, release, data and authority status for every registered issue."),
            _summary(map_data),
            ft.ResponsiveRow(cards, spacing=12, run_spacing=12),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["programme_map_page"]
