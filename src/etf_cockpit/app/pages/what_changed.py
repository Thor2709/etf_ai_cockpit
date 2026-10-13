from __future__ import annotations

import math

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    ListRow,
    Note,
    SectionHeader,
    TableColumn,
    Tag,
    Well,
    field_input_style,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_timestamp
from etf_cockpit.app.pages._p1_common import DOT_TOKENS, GridLayout, grid, make_layout, refresh, text
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
from etf_cockpit.application.ui_views.changes import (
    SEGMENT_ITEMS,
    ChangeRow,
    ChangesView,
    change_row,
    filter_rows,
    lineage_rows,
    score_bars,
    score_insight,
    signed,
    sorted_rows,
)

_RISING, _FALLING = theme.CHART_POS, theme.CHART_NEG


def _run_stamp(history: object, run_id: str | None) -> str | None:
    try:
        raw = history.loc[history["run_id"].astype(str).eq(str(run_id)), "run_completed_at"]
        return format_timestamp(raw.iloc[0]) if len(raw) else None
    except Exception:
        return None


def _changes_view(history: object, report: object, current: str | None, previous: str | None):
    context = upstream_run_context(history, current, previous) if report is not None else None
    version_summary = compatibility_summary(build_version_registry())
    rows = sorted_rows(change_row(change) for change in (report.changes if report is not None else ()))
    if current is None:
        subtitle = "No comparable runs yet"
    else:
        now = _run_stamp(history, current) or current
        before = (_run_stamp(history, previous) or previous) if previous else None
        subtitle = f"Run {now} vs. previous run {before}" if before else f"Run {now} · no previous run"
    view = ChangesView(
        subtitle=subtitle,
        rows=rows,
        lineage=lineage_rows(context, version_summary),
        lineage_detail=(
            f"Lineage registry {version_summary['registry_version']} · {version_summary['record_count']} records · "
            f"signature {str(version_summary['registry_signature'])[:16]}… · cache rebuilds are required when a "
            "dependency version or content hash changes."
        ),
        extras={"report_summary": str(getattr(report, "summary", "") or "")},
    )
    return view, context


def what_changed_page(_page: ft.Page, _state: AppState) -> PageView:
    history = score_history_frame()
    report = None
    current = previous = None
    if not history.empty and "run_id" in history.columns:
        current, previous = select_comparison_runs(history)
    if current is not None:
        report = compare_runs(history, current, previous)
    view, context = _changes_view(history, report, current, previous)
    layout = make_layout(_page)
    stacked = layout.narrow or layout.medium  # under 1300px: the table gets a full-width row, lineage moves below
    top_span = 12 if stacked else 8
    if stacked:
        layout = layout.with_row(460)
    state = {"segment": "All dimensions", "selected": view.rows[0].instrument_id if view.rows else None}

    search_field = ft.TextField(key="what-changed.filter.instrument", **field_input_style(placeholder="ID or name"))
    # The chrome segment group drives the dimension; this dropdown stays as the acceptance-contract target for
    # the dimension filter and is hidden because the segments are the visible control.
    dimension_filter = ft.Dropdown(
        key="what-changed.filter.dimension",
        value="all",
        options=[ft.dropdown.Option("all", "All dimensions")]
        + [
            ft.dropdown.Option(dimension, dimension.replace("_", " ").title())
            for dimension in (*REQUIRED_CHANGE_DIMENSIONS, *UPSTREAM_CHANGE_DIMENSIONS)
        ],
        visible=False,
    )
    changed_only = ft.Switch(
        key="what-changed.filter.changed-only",
        value=True,
        active_color=theme.SELECTED_BG[0],
        inactive_track_color=theme.FIELD_FILL,
        thumb_color=theme.INK,
    )
    table_holder = ft.Container(expand=True)
    path_holder = ft.Container(key="what-changed.path", expand=True)

    def visible_rows() -> list[ChangeRow]:
        return filter_rows(
            view.rows,
            query=search_field.value or "",
            changed_only=bool(changed_only.value),
            segment=state["segment"],
        )

    def choose(index: int) -> None:
        state["selected"] = visible_rows()[index].instrument_id
        _render_rows()

    def _render_rows(_event: object | None = None) -> None:
        rows = visible_rows()
        selected_index = next((i for i, row in enumerate(rows) if row.instrument_id == state["selected"]), None)
        table_holder.content = _changes_table(rows, view, selected_index, choose)
        chosen = next((row for row in rows if row.instrument_id == state["selected"]), None)
        if chosen is None:
            state["selected"] = None
        path_holder.content = _path_card(layout, chosen)
        refresh(table_holder)
        refresh(path_holder)

    search_field.on_change = _render_rows
    dimension_filter.on_select = _render_rows
    changed_only.on_change = _render_rows

    def choose_segment(value: str) -> None:
        state["segment"] = value
        _render_rows()

    table_holder.content = _changes_table(visible_rows(), view, 0 if view.rows else None, choose)
    path_holder.content = _path_card(layout, view.rows[0] if view.rows else None)
    changes_card = GlassCard(
        "Changes by instrument",
        layout.card_note(top_span, "informational only · cannot override current evidence gates"),
        body=ft.Column(
            [
                ft.Row(
                    [
                        Field("Search instrument", search_field, expand=2),
                        ft.Column(
                            [
                                text("Changed only", 11, 600, theme.INK3, tracking=0.08, upper=True),
                                ft.Container(content=changed_only, height=40, alignment=ft.Alignment(-1, 0)),
                            ],
                            spacing=4,
                            tight=True,
                        ),
                        dimension_filter,
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                table_holder,
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )
    bars = score_bars(view.rows)
    width, height = layout.card_body(6, 1, insight=True)
    score_chart = ck.bar_chart(
        [bar.instrument_id for bar in bars],
        [bar.score_delta for bar in bars],
        labels=[signed(bar.score_delta, 1) for bar in bars],
        x_name="Instrument",
        y_name="Score change (points)",
        decimals=1,
        y_min=math.floor(min([0.0, *(bar.score_delta for bar in bars)]) * 2) / 2 - 0.5,
        y_max=math.ceil(max([0.0, *(bar.score_delta for bar in bars)]) * 2) / 2 + 0.5,
        margins=ck.Margins(62, 20, 20, 48),
        width=width,
        height=height,
        unavailable_reason=None if bars else "No previous run to compare",
        empty_title="No score changes",
        insight=score_insight(bars),
    )
    lineage = (_lineage_card(view, layout, 12 if stacked else 4), 12 if stacked else 4)
    body = grid(
        layout,
        [
            [(changes_card, 12)] if stacked else [(changes_card, 8), lineage],
            [
                (
                    GlassCard(
                        "Score change by instrument",
                        layout.card_note(6, "points vs. previous run"),
                        insight=score_insight(bars),
                        body=Well(score_chart, width=width, height=height),
                        expand=True,
                    ),
                    6,
                ),
                (path_holder, 6),
            ],
            *([[lineage]] if stacked else []),
        ],
        below=_below_the_fold(view, report, context),
    )
    return PageView(
        chrome=PageChrome(
            "What Changed",
            view.subtitle,
            (SegmentGroup("dimension", SEGMENT_ITEMS, "All dimensions", choose_segment),),
        ),
        body=body,
    )


def _changes_table(rows: list[ChangeRow], view: ChangesView, selected: int | None, on_select) -> ft.Control:
    columns = [
        TableColumn("instrument", "Instrument", flex=2, sortable=False),
        TableColumn("score", "Score Δ", flex=2, numeric=True, sortable=False),
        TableColumn("rank", "Rank Δ", flex=2, numeric=True, sortable=False),
        TableColumn("freshness", "Freshness", flex=2, sortable=False),
        TableColumn("model", "Model", flex=2, sortable=False),
        TableColumn("forecasts", "Forecasts", flex=2, sortable=False),
        TableColumn("news", "News", flex=2, sortable=False),
        TableColumn("backtest", "Backtest trust", flex=3, sortable=False),
        TableColumn("risk", "Portfolio risk", flex=3, sortable=False),
    ]

    def delta(value: float | int | None, decimals: int) -> ft.Control:
        colour = theme.INK2 if not value else theme.POS if value > 0 else theme.NEG
        return text(signed(value, decimals), 13.5, 400, colour, text_align=ft.TextAlign.RIGHT)

    table_rows = [
        {
            "instrument": text(row.instrument_id, 13.5, 700, trunc=True),
            "score": delta(row.score_delta, 1),
            "rank": delta(row.rank_delta, 0),
            "freshness": Tag(*row.freshness, dense=True),
            "model": Tag(*row.model, dense=True),
            "forecasts": row.forecasts,
            "news": row.news,
            "backtest": row.backtest_trust,
            "risk": row.portfolio_risk,
        }
        for row in rows
    ]
    return DataTable(
        columns,
        table_rows,
        row_height=64,
        expand=True,
        selected_index=selected,
        on_select=on_select,
        empty_title="No changes to show" if view.rows else "No comparable runs",
        empty_reason="No instruments match the selected filters." if view.rows else view.empty_reason,
    )


def _lineage_card(view: ChangesView, layout: GridLayout, span: int) -> ft.Control:
    rows = [
        ListRow(DOT_TOKENS.get(item.dot, item.dot), item.title, item.sub, last=index == len(view.lineage) - 1)
        for index, item in enumerate(view.lineage)
    ]
    return GlassCard(
        "Run lineage",
        layout.card_note(span, "what the two runs depend on"),
        body=ft.Column(
            [
                ft.ListView(rows, spacing=0, expand=True),
                Disclosure("lineage signature and rebuild rule", view.lineage_detail),
            ],
            spacing=12,
            expand=True,
        ),
        expand=True,
    )


def _path_card(layout: GridLayout, row: ChangeRow | None) -> ft.Control:
    width, height = layout.card_body(6, 1, insight=True)
    if row is None:
        return GlassCard(
            "Causal path",
            "select an instrument",
            body=ck.empty_state("No instrument selected", "No instrument has a recorded change.", width, height),
            expand=True,
        )
    delta = row.score_delta
    direction = "rose" if (delta or 0) > 0 else "fell"
    note = "why the score changed" if not delta else f"why the score {direction} {abs(delta):.1f} points"
    sink = f"Score {signed(delta, 1)}"
    sink_colour = _RISING if (delta or 0) >= 0 else _FALLING
    nodes: list[ck.SankeyNode] = []
    links: list[ck.SankeyLink] = []
    sources: list[str] = []
    reason = None
    if row.causal_status == "available" and row.causal_paths:
        seen: dict[str, str] = {}
        for path in row.causal_paths:
            steps = [part.strip() for part in path.split("->") if part.strip()]
            for position, step in enumerate(steps):
                seen.setdefault(step, sink_colour if position == len(steps) - 1 else theme.CHART_PRIMARY)
            links.extend(ck.SankeyLink(source, target, 1.0) for source, target in zip(steps, steps[1:]))
            if steps and steps[0] not in sources:
                sources.append(steps[0])
        nodes = [ck.SankeyNode(name, colour) for name, colour in seen.items()]
    elif row.changed_inputs:
        nodes = [ck.SankeyNode(label, theme.CHART_MODEL) for label, _key in row.changed_inputs]
        nodes.append(ck.SankeyNode(sink, sink_colour))
        links = [ck.SankeyLink(label, sink, 1.0) for label, _key in row.changed_inputs]
        sources = [label for label, _key in row.changed_inputs]
    else:
        reason = f"No changed input is recorded for {row.instrument_id}."
        if row.causal_reason:
            reason += f" ({row.causal_reason})"
    insight = None
    if sources and delta:  # only from recorded inputs; never invented when links are missing
        insight = f"Score {direction} {abs(delta):.1f} through {', '.join(sources[:3])}" + (" and more." if len(sources) > 3 else ".")
    chart = ck.sankey(
        nodes,
        links,
        width=width,
        height=height - 24,
        unavailable_reason=reason,
        empty_title="No causal path",
        insight=f"{row.instrument_id}: {note}.",
    )
    return GlassCard(
        f"Causal path: {row.instrument_id}",
        layout.card_note(6, note),
        insight=insight,
        body=ft.Column(
            [Well(chart, width=width, height=height - 24), Note("Links show which inputs changed, not how much")],
            spacing=8,
            expand=True,
        ),
        expand=True,
    )


def _below_the_fold(view: ChangesView, report: object, context: dict | None) -> list[ft.Control]:
    """Every per-instrument dimension, the upstream context and the run summary the earlier page listed."""
    labels = (
        ("warnings", "Warnings"),
        ("freshness", "Freshness"),
        ("model_availability", "Model availability"),
        ("forecasts", "Forecasts"),
        ("news_inventory", "News inventory"),
        ("backtest_trust", "Backtest trust"),
        ("portfolio_risk", "Portfolio risk"),
        ("lineage", "Lineage"),
    )
    upstream = (
        ("source_revisions", "Source revisions"),
        ("classification", "Classification"),
        ("policy_versions", "Formula/policy versions"),
        ("portfolio_targets", "Portfolio targets"),
    )
    changes = list(getattr(report, "changes", ()) or ())
    columns = [
        TableColumn("instrument", "Instrument", flex=2, sortable=False),
        TableColumn("score", "Score delta", flex=2, numeric=True, sortable=False),
        TableColumn("rank", "Rank delta", flex=2, numeric=True, sortable=False),
    ]
    columns += [TableColumn(key, label, flex=2, sortable=False) for key, label in (*labels, *upstream)]
    columns.append(TableColumn("action", "Current action", flex=3, sortable=False))
    rows = []
    for change in changes:
        entry: dict[str, object] = {
            "instrument": text(change.instrument_id, 13.5, 700, trunc=True),
            "score": None if change.score_delta is None else f"{change.score_delta:+.1f}",
            "rank": None if change.score_rank_delta is None else f"{-change.score_rank_delta:+.0f}",
            "action": change.current_action or None,
        }
        for key, _label in labels:
            entry[key] = _status_cell(change.dimension_statuses.get(key, "unavailable"))
        for key, _label in upstream:
            entry[key] = _upstream_cell(change.upstream_changes.get(key))[0]
        rows.append(entry)
    out: list[ft.Control] = [
        SectionHeader(
            "All dimensions",
            "Every compared dimension per instrument (yes = changed, no = unchanged, N/A = not recorded).",
        ),
        GlassCard(
            "Dimension detail",
            f"{len(rows)} instruments",
            body=DataTable(
                columns, rows, row_height=44, max_visible_rows=10,
                empty_title="No comparison", empty_reason=view.empty_reason,
            ),
        ),
    ]
    if context is not None:
        out += [
            SectionHeader("Upstream context", "Corrections, dependencies and paper state between the two runs."),
            _context_panel(context, _upstream_line(changes, upstream)),
        ]
    if view.extras.get("report_summary"):
        out.append(Disclosure("run comparison summary", view.extras["report_summary"]))
    return out


def _status_cell(status: str) -> str:
    return {"changed": "yes", "unchanged": "no"}.get(status, "N/A")


def _upstream_cell(value: tuple[str, str | None, bool | None] | None) -> tuple[str, str]:
    if value is None:
        return "N/A", theme.INK2
    current, previous, changed = value
    if changed is None or current == "unavailable" or previous in (None, "unavailable"):
        return "N/A", theme.INK2
    return ("yes", theme.AMBER) if changed else ("no", theme.POS)


def _upstream_line(changes: list, upstream: tuple[tuple[str, str], ...]) -> str:
    """One sentence naming the upstream inputs (classification, policy versions, ...) that changed between the runs."""
    states = {
        label: {_upstream_cell(change.upstream_changes.get(key))[0] for change in changes} for key, label in upstream
    }
    changed = [label for label, seen in states.items() if "yes" in seen]
    if changed:
        return "Changed upstream inputs: " + ", ".join(changed) + "."
    if any("no" in seen for seen in states.values()):
        return "Upstream inputs recorded: unchanged between the two runs."
    return "Upstream inputs: not recorded for these runs."


def _context_panel(context: dict[str, object] | None, upstream_line: str = "") -> ft.Control:
    if context is None:
        return EmptyState("Upstream context unavailable", "Two comparable runs are needed.", expand=False, height=96)
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
    return GlassCard(
        "Upstream context",
        "",
        body=ft.Column(
            [
                text(upstream_line, 12.5, 400, theme.INK2, selectable=True),
                text(corrections_text, 12.5, 400, theme.INK2, selectable=True),
                text(dependency_text, 12.5, 400, theme.INK2, selectable=True),
                text(paper_text, 12.5, 400, theme.INK2, selectable=True),
                text(str(paper.get("note", "")), 12, 400, theme.INK3, selectable=True),
            ],
            spacing=8,
        ),
    )
