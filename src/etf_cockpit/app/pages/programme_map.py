"""Canonical programme map and authority view."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app.components import kit
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.state import AppState
from etf_cockpit.application.programme_map import ProgrammeMapEntry, load_programme_map
from etf_cockpit.core.paths import ROOT


def _status_kind(status: str) -> str:
    value = status.casefold()
    if value in {"ready", "implemented", "integrated", "closed", "passed"}:
        return "ok"
    if value in {"blocked", "rejected"}:
        return "bad"
    if value in {"in_progress", "hardening_required"}:
        return "warn"
    return "mute"


def _issue_row(entry: ProgrammeMapEntry) -> dict[str, object]:
    return {
        "id": entry.canonical_id,
        "title": entry.title,
        "status": kit.Tag(entry.implementation.replace("_", " "), _status_kind(entry.implementation)),
        "release": entry.release.replace("_", " "),
        "data": entry.data.replace("_", " "),
        "authority": entry.live.replace("_", " "),
        "depends": ", ".join(entry.blocking_dependencies) or "—",
    }


def _bar_data(entries: tuple[ProgrammeMapEntry, ...]) -> tuple[list[str], list[list[ck.Segment]]]:
    phases = sorted({entry.phase for entry in entries})
    rows: list[list[ck.Segment]] = []
    for phase in phases:
        phase_entries = [entry for entry in entries if entry.phase == phase]
        done = sum(entry.implementation in {"closed", "implemented", "implemented_initially", "integrated", "ready"} for entry in phase_entries)
        in_progress = sum(entry.implementation in {"in_progress", "hardening_required"} for entry in phase_entries)
        blocked = sum(entry.implementation == "blocked" for entry in phase_entries)
        planned = sum(entry.implementation in {"planned", "deferred", "research_only"} for entry in phase_entries)
        rows.append(
            [
                ck.Segment(done, "pos", "Done"),
                ck.Segment(in_progress, "gold", "In progress"),
                ck.Segment(blocked, "gold", "Blocked"),
                ck.Segment(planned, "gold", "Planned"),
            ]
        )
    return phases, rows


def programme_map_page(page: ft.Page | None, state: AppState) -> PageView:
    map_data = load_programme_map(ROOT)
    entries = tuple(map_data.entries)
    registry_status = "Loaded" if map_data.status == "loaded" else "Blocked"
    registry_body = ft.Column(
        [
            kit.Tag(registry_status, "ok" if map_data.status == "loaded" else "bad"),
            kit.Disclosure(
                "Registry path and hash",
                f"path={ROOT / 'issues' / 'issue_registry.json'}\nsha256={map_data.registry_sha256}\nCanonical issue records: {len(entries)}\nimplementation statuses: {' · '.join(f'{status}: {count}' for status, count in map_data.counts)}\nRelease is the registry package status, not release certification.\nexecution_allowed=false",
            ),
            kit.Note("Implementation, release, data and authority status are read from the canonical issue registry."),
            *(
                [kit.ListRow("bad", "Registry blocked", map_data.error or "Canonical issue registry unavailable; no readiness is inferred.", tag=("Blocked", "bad"))]
                if map_data.status != "loaded"
                else []
            ),
        ],
        spacing=8,
    )
    registry_card = kit.GlassCard("Registry", body=registry_body, expand=True)

    table = kit.DataTable(
        [
            kit.TableColumn("id", "ID"),
            kit.TableColumn("title", "Title"),
            kit.TableColumn("status", "Status"),
            kit.TableColumn("release", "Release"),
            kit.TableColumn("data", "Data"),
            kit.TableColumn("authority", "Authority"),
            kit.TableColumn("depends", "Depends on"),
        ],
        [_issue_row(entry) for entry in entries] if map_data.status == "loaded" else [],
        expand=True,
        empty_title="Registry blocked",
        empty_reason="No issue records are displayed while the registry is blocked.",
    )
    issue_details = "\n\n".join(
        f"{entry.canonical_id} · {entry.title}\n{entry.phase} · priority {entry.priority}\nImplementation: {entry.implementation} · Release: {entry.release} · Data: {entry.data} · Model: {entry.model} · Paper: {entry.paper} · Live: {entry.live}\nImplementation readiness: {'ready' if entry.ready else 'blocked'} · Activation readiness: {'ready' if entry.activation_ready else 'blocked'}\nBlocking dependencies: {', '.join(entry.blocking_dependencies) or 'none'} · Required inputs: {', '.join(entry.required_inputs) or 'none'}\nReadiness reasons: {', '.join(entry.readiness_reason_codes)} · Edges: {', '.join(entry.edge_reason_codes) or 'none'}\nActivation dependencies: {', '.join(entry.activation_dependencies) or 'none'} · Activation reasons: {', '.join(entry.activation_reason_codes)}\nDownstream issues: {', '.join(entry.downstream_issues) or 'none'} · Related: {', '.join(entry.related_issues) or 'none'}\nexecution_allowed=false"
        for entry in entries
    )
    issue_details_text = kit.Note(issue_details or map_data.error or "No issue records are available.")
    issue_details_disclosure = kit.Disclosure("Issue record details", issue_details_text)
    issues_card = kit.GlassCard(
        "Issues",
        note=f"{len(entries)} registered issues" if map_data.status == "loaded" else "Unavailable",
        body=ft.Column([table, issue_details_disclosure], spacing=8, expand=True, scroll=ft.ScrollMode.AUTO),
        expand=True,
    )

    phases, segments = _bar_data(entries)
    status_chart = ck.horizontal_stacked_bar(
        phases,
        segments,
        x_name="Issues (count)",
        x_max=max((sum(segment.value for segment in row) for row in segments), default=0) or None,
        unavailable_reason="Issue status counts are unavailable while the registry is blocked." if map_data.status != "loaded" else "No issue records are available.",
        insight="Issue implementation states grouped by registered programme area.",
    )
    status_card = kit.GlassCard("Issues by status", note="Area · issue count", body=kit.Well(status_chart), expand=True)

    def show_segment(name: str) -> None:
        if name == "All":
            selected = entries
        elif name == "Open":
            selected = tuple(entry for entry in entries if entry.implementation not in {"closed", "implemented", "implemented_initially", "integrated", "ready"})
        elif name == "Done":
            selected = tuple(entry for entry in entries if entry.implementation in {"closed", "implemented", "implemented_initially", "integrated", "ready"})
        else:
            selected = tuple(entry for entry in entries if entry.implementation == "blocked")
        table.rows = [_issue_row(entry) for entry in selected] if map_data.status == "loaded" else []
        issue_details_text.value = "\n\n".join(
            f"{entry.canonical_id} · {entry.title}\n{entry.phase} · priority {entry.priority}\nImplementation: {entry.implementation} · Release: {entry.release} · Data: {entry.data} · Model: {entry.model} · Paper: {entry.paper} · Live: {entry.live}\nImplementation readiness: {'ready' if entry.ready else 'blocked'} · Activation readiness: {'ready' if entry.activation_ready else 'blocked'}\nBlocking dependencies: {', '.join(entry.blocking_dependencies) or 'none'} · Required inputs: {', '.join(entry.required_inputs) or 'none'}\nReadiness reasons: {', '.join(entry.readiness_reason_codes)} · Edges: {', '.join(entry.edge_reason_codes) or 'none'}\nActivation dependencies: {', '.join(entry.activation_dependencies) or 'none'} · Activation reasons: {', '.join(entry.activation_reason_codes)}\nDownstream issues: {', '.join(entry.downstream_issues) or 'none'} · Related: {', '.join(entry.related_issues) or 'none'}\nexecution_allowed=false"
            for entry in selected
        ) or map_data.error or "No issue records are available."
        issues_card.note_control.value = f"{len(selected)} registered issues" if map_data.status == "loaded" else "Unavailable"
        if page is not None and hasattr(page, "update"):
            page.update()

    body = ft.ResponsiveRow(
        [
            ft.Container(content=registry_card, col={"xs": 12, "md": 4}),
            ft.Container(content=status_card, col={"xs": 12, "md": 8}),
            ft.Container(content=issues_card, col={"xs": 12}),
        ],
        spacing=12,
        run_spacing=12,
        expand=True,
    )
    return PageView(
        PageChrome(
            "Programme Map",
            "Implementation, release, data and authority status for every registered issue",
            (SegmentGroup("programme_status", ("All", "Open", "Done", "Blocked"), "All", show_segment),),
        ),
        ft.Column([body], spacing=12, expand=True, scroll=ft.ScrollMode.AUTO),
    )


__all__ = ["programme_map_page"]
