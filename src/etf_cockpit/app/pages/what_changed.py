from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.glass_pages import page_panel
from etf_cockpit.app.components.cards import section_header
from etf_cockpit.app.formatting import format_count
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    REQUIRED_CHANGE_DIMENSIONS,
    UPSTREAM_CHANGE_DIMENSIONS,
    build_version_registry,
    compatibility_summary,
    compare_runs,
    score_history_frame,
    select_comparison_runs,
    upstream_run_context,
)


panel = page_panel("what-changed")


def what_changed_page(_page: ft.Page, _state: AppState) -> ft.Control:
    history = score_history_frame()
    report = None
    changes = []
    current = previous = None
    if not history.empty and "run_id" in history.columns:
        current, previous = select_comparison_runs(history)

    if current is not None:
        report = compare_runs(history, current, previous)
        changes = list(report.changes)
    context = upstream_run_context(history, current, previous) if report is not None else None
    version_summary = compatibility_summary(build_version_registry())

    search_field = ft.TextField(
        label="Search instrument",
        key="what-changed.filter.instrument",
        hint_text="ID or name",
        dense=True,
        width=220,
    )
    dimension_filter = ft.Dropdown(
        label="Filter dimension",
        key="what-changed.filter.dimension",
        value="all",
        options=[ft.dropdown.Option("all", "All dimensions")]
        + [
            ft.dropdown.Option(dimension, dimension.replace("_", " ").title())
            for dimension in (*REQUIRED_CHANGE_DIMENSIONS, *UPSTREAM_CHANGE_DIMENSIONS)
        ],
        dense=True,
        width=210,
    )
    changed_only = ft.Checkbox(label="Changed only", key="what-changed.filter.changed-only", value=False)
    # Keep the comparison vertically scrollable with the page.  Per-instrument
    # cards below use responsive rows so narrow windows never need a wide
    # twelve-column table or horizontal scrolling.
    table_container = ft.Column()

    def _changed(change, dimension: str) -> bool:
        if dimension == "all":
            return any(status == "changed" for status in change.dimension_statuses.values())
        return change.dimension_statuses.get(dimension) == "changed"

    def _dimension_cell(change, key: str, yes_label: str = "yes") -> tuple[str, str]:
        status = change.dimension_statuses.get(key, "unavailable")
        if status == "unavailable":
            return "N/A", theme.MUTED
        return (yes_label, theme.AMBER) if status == "changed" else ("no", theme.GREEN)

    def _render_rows(_event: ft.ControlEvent | None = None) -> None:
        query = (search_field.value or "").strip().casefold()
        dimension = dimension_filter.value or "all"
        visible = []
        for change in changes:
            if query and query not in change.instrument_id.casefold():
                continue
            if changed_only.value and not _changed(change, "all"):
                continue
            if dimension != "all" and not _changed(change, dimension):
                continue
            visible.append(change)
        cards = []
        for change in visible:
            dimensions = (
                ("Score delta", "N/A" if change.score_delta is None else f"{change.score_delta:+.1f}", theme.CYAN),
                ("Rank delta", "N/A" if change.score_rank_delta is None else f"{change.score_rank_delta:+.0f}", theme.CYAN),
                ("Warnings", *_dimension_cell(change, "warnings")),
                ("Freshness", *_dimension_cell(change, "freshness")),
                ("Model availability", *_dimension_cell(change, "model_availability")),
                ("Forecasts", *_dimension_cell(change, "forecasts")),
                ("News inventory", *_dimension_cell(change, "news_inventory")),
                ("Backtest trust", *_dimension_cell(change, "backtest_trust")),
                ("Portfolio risk", *_dimension_cell(change, "portfolio_risk")),
                ("Lineage", *_dimension_cell(change, "lineage")),
                *(
                    (label, *_upstream_cell(change.upstream_changes.get(key)))
                    for key, label in (
                        ("source_revisions", "Source revisions"),
                        ("classification", "Classification"),
                        ("policy_versions", "Formula/policy versions"),
                        ("portfolio_targets", "Portfolio targets"),
                    )
                ),
                ("Current action", change.current_action or "unavailable", theme.MUTED),
            )
            metric_controls = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(label, color=theme.MUTED, size=10),
                            ft.Text(value, color=colour, size=12, weight=ft.FontWeight.BOLD),
                        ],
                        spacing=2,
                    ),
                    col={"xs": 6, "sm": 4, "md": 3},
                    padding=4,
                )
                for label, value, colour in dimensions
            ]
            cards.append(
                panel(
                    ft.Column(
                        [
                            ft.Text(change.instrument_id, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                            ft.ResponsiveRow(metric_controls, spacing=4, run_spacing=2),
                            ft.Text(change.summary, color=theme.MUTED, size=11),
                            ft.Text(
                                "Causal paths: "
                                + (
                                    "; ".join(change.causal_paths)
                                    if change.causal_paths_status == "available" and change.causal_paths
                                    else "no recorded dependency path to the result"
                                    if change.causal_paths_status == "available"
                                    else f"unavailable ({change.causal_paths_reason or 'not recorded'})"
                                ),
                                color=theme.MUTED,
                                size=11,
                                selectable=True,
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=10,
                )
            )
        table_container.controls = [
            ft.Text(f"{format_count(len(visible))} instrument(s) shown", color=theme.MUTED, size=11),
            *cards,
        ] if visible else [ft.Text("No instruments match the selected filters.", color=theme.MUTED)]
        try:
            if _page is not None:
                _page.update()
        except Exception:
            pass

    search_field.on_change = _render_rows
    dimension_filter.on_select = _render_rows
    changed_only.on_change = _render_rows
    if report is None:
        digest = ft.Text("No score runs with valid timezone-aware completion times are available to compare.", color=theme.MUTED)
    else:
        digest = ft.Column(
            [
                ft.Text(f"Current run: {current} | Previous: {previous or 'none'}", color=theme.MUTED),
                ft.Text(report.summary, color=theme.MUTED),
            ],
            spacing=4,
        )
    lineage = ft.Text(
        f"Lineage registry {version_summary['registry_version']} · {format_count(version_summary['record_count'])} records · "
        f"signature {str(version_summary['registry_signature'])[:16]}… · cache rebuilds are required when a dependency version or content hash changes.",
        color=theme.MUTED,
        selectable=True,
    )
    _render_rows()
    body = ft.Column(
        [digest, lineage, _context_panel(context), ft.Row([search_field, dimension_filter, changed_only], wrap=True), table_container],
        spacing=10,
    )
    return ft.Column([panel(ft.Column([section_header("What Changed", "Historical score and warning differences are informational only and cannot override current evidence gates."), body], spacing=10))], expand=True, scroll=ft.ScrollMode.AUTO)


def _upstream_cell(value: tuple[str, str | None, bool | None] | None) -> tuple[str, str]:
    if value is None:
        return "N/A", theme.MUTED
    current, previous, changed = value
    if changed is None or current == "unavailable" or previous in (None, "unavailable"):
        return "N/A", theme.MUTED
    return ("yes", theme.AMBER) if changed else ("no", theme.GREEN)


def _context_panel(context: dict[str, object] | None) -> ft.Control:
    if context is None:
        return ft.Container()
    corrections, dependencies, paper = (
        value if isinstance(value, dict) else {}
        for value in (context.get("corrections"), context.get("dependencies"), context.get("paper_state"))
    )
    if corrections.get("status") == "available":
        corrections_text = (
            f"Data corrections (point-in-time at each run): {'changed' if corrections.get('changed') else 'unchanged'}; "
            f"corrections {corrections.get('previous_corrections')} -> {corrections.get('current_corrections')}, "
            f"unresolved findings {corrections.get('previous_unresolved')} -> {corrections.get('current_unresolved')}."
        )
    else:
        corrections_text = f"Data corrections: unavailable ({corrections.get('reason', 'not recorded')})."
    if dependencies.get("status") == "available":
        changed = tuple(dependencies.get("changed_artifacts") or ())
        dependency_text = (
            "Changed run dependencies: " + "; ".join(changed) + "." if changed else "Run dependencies: unchanged between the two run manifests."
        )
    else:
        dependency_text = f"Run dependencies: unavailable ({dependencies.get('reason', 'not recorded')})."
    if paper.get("status") == "available":
        paper_text = (
            f"Paper/order state ({paper.get('comparison', 'unavailable')} through run completion): "
            f"orders {paper.get('previous_order_count', 'N/A')} -> {paper.get('current_order_count', 'N/A')}."
        )
    else:
        paper_text = f"Paper/order state: unavailable ({paper.get('reason', 'not recorded')})."
    return panel(
        ft.Column(
            [
                ft.Text("Upstream context", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.Text(corrections_text, color=theme.MUTED, size=11, selectable=True),
                ft.Text(dependency_text, color=theme.MUTED, size=11, selectable=True),
                ft.Text(paper_text, color=theme.MUTED, size=11, selectable=True),
                ft.Text(str(paper.get("note", "")), color=theme.MUTED, size=10, selectable=True),
            ],
            spacing=4,
        ),
        padding=10,
    )
