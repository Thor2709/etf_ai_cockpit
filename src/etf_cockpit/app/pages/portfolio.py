"""Portfolio Sandbox page (FINAL_UI_SPEC 6.4): account snapshot, value vs. benchmark and the Holdings, Policy and
Candidates views, with the existing evidence blocks below the fold. Analysis only: ``execution_allowed=false``."""

from __future__ import annotations

import math
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.charts import allocation_donut, portfolio_performance_chart  # noqa: F401 - monkeypatched by tests
from etf_cockpit.app.components.fixed_income_views import portfolio_maturity_ladder_panel
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    Field,
    GlassCard,
    Headline,
    KpiTile,
    ListRow,
    Note,
    ScoreBar,
    Segmented,
    TableColumn,
    Tag,
    Well,
    pill_group,
)
from etf_cockpit.app.components.overlap import overlap_evidence_panel, report_weight
from etf_cockpit.app.components.shell.page_view import PageView, SegmentGroup
from etf_cockpit.app.formatting import format_currency, format_number, format_percent
from etf_cockpit.app.pages import _p4_common as common
from etf_cockpit.app.pages._p4_common import workflow_button as _workflow_button
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    PortfolioAnalysis,
    PortfolioCandidate,
    PortfolioSandboxPersistenceError,
    RebalanceConstraints,
    RebalanceReport,
    StorageRevisionConflict,
    analyse_portfolio_candidate,
    build_rebalance_report,
    build_portfolio_candidate,
    candidate_id,
    draft_portfolio_candidate,
    load_portfolio_candidate,
    load_portfolio_forecast_aggregation,
    load_portfolio_performance_series,
    load_portfolio_risk_profile_projection,
    load_portfolio_calendar_projection,
    load_portfolio_maturity_ladder_projection,
    load_portfolio_holdings_projection,
    load_portfolio_goals_projection,
    load_fixed_income_screener,
    portfolio_snapshot_binding,
    performance_series_frame,
    CANONICAL_DISTRIBUTION_HORIZONS_DAYS,
    PRIMARY_MODEL_HORIZON_DAYS,
    rebalance_inapplicable_instruments,
    save_portfolio_candidate,
    select_holdings_view,
    export_table,
)
from etf_cockpit.application.portfolio_sandbox import (
    draft_portfolio_proposal,
    export_portfolio_analysis,
)
from etf_cockpit.application.monthly_decision_template import (
    build_monthly_decision_template,
    monthly_decision_template_lines,
    unavailable_monthly_evidence,
)
from etf_cockpit.application.ui_views import portfolio as portfolio_view
from etf_cockpit.core.paths import EXPORTS_DIR, ROOT

_RANGES = ["1M", "3M", "1Y", "Custom"]
_VIEWS = ["Holdings", "Policy", "Candidates"]
_METRICS = (
    ("portfolio_value", "Portfolio value"),
    ("net_invested_capital", "Net invested capital"),
    ("investment_pnl", "Investment P&L"),
    ("twr_index", "TWR index"),
    ("twr_return", "TWR return"),
    ("mwr_return", "MWR return"),
    ("drawdown", "Drawdown"),
    ("cash_value", "Cash value"),
    ("net_contributions", "Net contributions"),
    ("income", "Income"),
    ("fees_tax", "Fees & tax"),
    ("fx", "FX"),
    ("benchmark", "Benchmark"),
)
_AGGREGATIONS = ("day", "week", "month", "quarter", "year")
_BAR_AGGREGATIONS = {"quarter", "year"}
_NO_HISTORY = ("No saved daily valuations", "Saved daily portfolio valuation history is unavailable or empty.")
_ASSET_FILTERS = ("all", "stock", "etf", "bond")
_SORTS = (
    ("instrument_id:asc", "Instrument A–Z"),
    ("instrument_id:desc", "Instrument Z–A"),
    ("value:desc", "Value high to low"),
    ("value:asc", "Value low to high"),
    ("weight:desc", "Weight high to low"),
    ("expected_return:desc", "Expected return high to low"),
)
_COLUMN_PRESETS = ("full", "values", "analysis")


# ---------------------------------------------------------------------------
# Small presentation helpers shared by the blocks below
# ---------------------------------------------------------------------------


def Dropdown(*, key: str, options: list[object], value: str | None, on_select: Callable[[object], object] | None = None, disabled: bool = False) -> ft.Dropdown:  # noqa: N802 - the acceptance scanner finds keyed inputs by this name
    return common.dropdown(key=key, options=options, value=value, on_select=on_select, disabled=disabled)  # type: ignore[arg-type]


def TextField(*, key: str, value: str = "", hint: str = "", on_change: Callable[[object], object] | None = None, on_submit: Callable[[object], object] | None = None) -> ft.TextField:  # noqa: N802
    built = common.text_input(key=key, value=value, hint=hint, on_change=on_change)
    built.on_submit = on_submit
    return built


def panel(content: ft.Control, *, expand: bool | int = False) -> ft.Container:
    """Plain spacing wrapper for evidence content (the cards around it are kit ``GlassCard``s)."""
    return ft.Container(content=content, expand=expand)


def section_header(title: str, subtitle: str = "") -> ft.Column:
    controls: list[ft.Control] = [common.text(title, 13.5, 600)]
    if subtitle:
        controls.append(common.text(subtitle, 12, 400, theme.INK2, max_lines=3))
    return ft.Column(controls, spacing=theme.SPACE_1, tight=True)


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> ft.Control:
    """Kit DataTable from plain text cells (legacy evidence sections)."""
    columns = [TableColumn(str(index), header, flex=1, sortable=False) for index, header in enumerate(headers)]
    return DataTable(columns, [{str(i): str(cell) for i, cell in enumerate(row)} for row in rows], max_visible_rows=30)


def _src_note(text: str) -> ft.Text:
    note = Note(text)
    note.selectable = True
    return note


def evidence_chip(label: str, value: str, colour: str) -> ft.Control:
    kind = "ok" if colour == theme.GREEN else "warn" if colour == theme.AMBER else "mute"
    return Tag(f"{label}: {value}", kind, dense=True)


def _card(title: str, note: str = "", body: ft.Control | list[ft.Control] | None = None, *, width: float | None = None, height: float | None = None, key: str | None = None, menu: ft.Control | None = None) -> ft.Control:
    return GlassCard(title, note, body=body, width=width, height=height, key=key, menu=menu)


def _text_lines(*lines: str, colour: str = theme.INK2) -> ft.Control:
    return ft.Column([common.text(line, 12.5, 400, colour, max_lines=3) for line in lines], spacing=4, tight=True)


def _money(value: float | None, *, decimals: int = 0) -> str | None:
    return None if value is None else f"€ {value:,.{decimals}f}"


def _signed(value: float | None, decimals: int = 1) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    text = f"{abs(value) * 100:.{decimals}f}%"
    return f"+{text}" if value > 0 else f"−{text}" if value < 0 else text


def _tone_colour(value: float | None) -> str:
    return theme.INK if value is None or value == 0 else theme.POS if value > 0 else theme.NEG


def _long_date(value: object) -> str:
    try:
        parsed = pd.Timestamp(str(value)[:10])
    except (TypeError, ValueError):
        return "unavailable"
    return f"{parsed.day:02d} {parsed.strftime('%b %Y')}" if not pd.isna(parsed) else "unavailable"


def _cell_value(cell: object) -> object | None:
    """Value of a projection cell, or None when its status is not available (never zero-filled)."""
    if isinstance(cell, Mapping):
        return cell.get("value") if cell.get("status") == "available" else None
    return cell


def _cell_number(cell: object) -> float | None:
    value = _cell_value(cell)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# ---------------------------------------------------------------------------
# Value vs. benchmark (hero card) — the old performance block, restyled
# ---------------------------------------------------------------------------


@dataclass
class _Performance:
    card: ft.Control
    set_range: Callable[[str], None]
    custom_start: ft.TextField
    custom_end: ft.TextField
    refresh: Callable[[], None]


def _performance_chart(series: object, benchmark: object | None, width: float, height: float, insight: str) -> ft.Control:
    points = [point for point in getattr(series, "points", ()) if point.value is not None]
    reason = series.reason or None  # type: ignore[attr-defined]
    metric_label = dict(_METRICS).get(series.metric, series.metric)  # type: ignore[attr-defined]
    y_name = "Index (start = 100)" if series.unit == "index" else f"{metric_label} ({series.currency if series.unit == 'currency' else series.unit})"  # type: ignore[attr-defined]
    if not points:
        return ck.empty_state(_NO_HISTORY[0], reason or _NO_HISTORY[1], width, height)
    if series.aggregation in _BAR_AGGREGATIONS:  # type: ignore[attr-defined]
        return ck.bar_chart(
            [point.period_end.isoformat() for point in points], [point.value for point in points],
            x_name="Period", y_name=y_name, width=width, height=height, insight=insight, margins=ck.Margins(68, 26, 40, 56),
            series_name=metric_label,
        )
    names = [point.period_end for point in points]
    lines = [ck.Series("Portfolio", [point.value for point in points], ck.palette.P, 3.2, glow=True, area=True, decimals=1)]
    if benchmark is not None and benchmark.status == "available":  # type: ignore[attr-defined]
        by_day = {point.period_end: point.value for point in getattr(benchmark, "points", ())}  # type: ignore[attr-defined]
        values = [by_day.get(day) for day in names]
        if any(value is not None for value in values):
            lines.append(ck.Series("Benchmark", values, ck.palette.BM, 2.0, dashed=True, decimals=1))
    return ck.line_chart(
        names, lines, x_name="Date", y_name=y_name, x_format="%Y-%m-%d", margins=ck.Margins(68, 26, 40, 56),
        legend_at="top-right", width=width, height=height, insight=insight,
    )


def _performance_controller(
    page: ft.Page | None,
    *,
    width: float = 760.0,
    height: float = 360.0,
    card_width: float | None = None,
    card_height: float | None = None,
    initial_range: str = "inception",
    on_series: Callable[[object, str], None] | None = None,
) -> _Performance:
    metric = common.dropdown(key="portfolio.performance.metric", options=_METRICS, value="twr_index")
    aggregation = common.dropdown(key="portfolio.performance.aggregation", options=[(item, item.title()) for item in _AGGREGATIONS], value="day")
    currency = common.text_input(key="portfolio.performance.currency", value="EUR")
    custom_start = common.text_input(key="portfolio.performance.custom-start", hint="2026-01-01")
    custom_end = common.text_input(key="portfolio.performance.custom-end", hint="2026-09-30")
    ui = {"range": initial_range}
    insight_text = common.text("Loading saved portfolio performance…", 12.5, 400, theme.INK, opacity=0.6, max_lines=1, key="portfolio.performance.status")
    export_status = common.text("CSV export writes the selected series to the local exports folder.", 12, 400, theme.INK2, max_lines=2, key="portfolio.performance.export-status")
    chart_host = ft.Column(key="portfolio.performance.chart", spacing=0)
    current_series: list[object] = []

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        series = load_portfolio_performance_series(
            metric=str(metric.value or "twr_index"),
            date_range="custom" if ui["range"] == "Custom" else ui["range"],
            aggregation=str(aggregation.value or "day"),
            currency=str(currency.value or "EUR"),
            custom_start=str(custom_start.value or "") or None,
            custom_end=str(custom_end.value or "") or None,
        )
        current_series[:] = [series]
        benchmark = None
        if series.metric == "twr_index":
            try:
                benchmark = load_portfolio_performance_series(
                    metric="benchmark", date_range="custom" if ui["range"] == "Custom" else ui["range"], aggregation=series.aggregation,
                    currency=series.currency, custom_start=str(custom_start.value or "") or None, custom_end=str(custom_end.value or "") or None,
                )
            except (OSError, TypeError, ValueError):
                benchmark = None
        stats = portfolio_view.series_stats([point.value for point in getattr(series, "points", ())], reason=series.reason)
        gap = None
        bench_reason = "benchmark return observations are not stored"
        if benchmark is not None and benchmark.status == "available":
            bench_stats = portfolio_view.series_stats([point.value for point in getattr(benchmark, "points", ())])
            if stats.range_return is not None and bench_stats.range_return is not None:
                gap = (stats.range_return - bench_stats.range_return) * 100.0
            bench_reason = benchmark.reason or bench_reason
        elif benchmark is not None and benchmark.reason:
            bench_reason = benchmark.reason
        if series.status == "unavailable" or stats.range_return is None:
            insight = series.reason or _NO_HISTORY[1]
        elif gap is None:
            insight = f"The portfolio is {_signed(stats.range_return)} over {ui['range']}; benchmark comparison unavailable ({str(bench_reason).rstrip('. ')})."
        else:
            insight = f"The portfolio is {_signed(stats.range_return)} over {ui['range']}, {abs(gap):.1f} pts {'ahead of' if gap >= 0 else 'behind'} the benchmark."
        insight_text.value = insight
        chart = _performance_chart(series, benchmark, width, height, insight)
        chart_host.controls = [Well(chart, width=width, height=height)]
        if _event is not None or page is not None:
            common.refresh(chart_host)
            common.refresh(insight_text)
        if on_series is not None:
            on_series(series, ui["range"])

    def export_selected(_event: ft.ControlEvent) -> None:
        if not current_series:
            refresh()
        series = current_series[0]
        result = export_table(
            "portfolio_performance_series",
            performance_series_frame(series),
            EXPORTS_DIR / "portfolio_performance_series.csv",
        )
        if result.ok:
            export_status.value = f"CSV ready: {result.destination} ({result.rows} rows)."
            export_status.color = theme.GREEN
        else:
            export_status.value = f"CSV export unavailable: {result.error}; previous output preserved."
            export_status.color = theme.RED
        common.refresh(export_status)
        _safe_update(page)

    def set_range(label: str) -> None:
        ui["range"] = label if label in _RANGES else "1Y"
        refresh(None)

    for control in (metric, aggregation):
        control.on_select = refresh
    for control in (currency, custom_start, custom_end):
        control.on_change = refresh
    options = common.Popover(
        "Chart options",
        ft.Column(
            [
                Field("Metric", control=metric),
                Field("Aggregation", control=aggregation),
                Field("Output currency", control=currency),
                _workflow_button("Download CSV", key_name="portfolio.performance.download", on_click=export_selected),
                export_status,
            ],
            spacing=12,
            tight=True,
        ),
        width=300,
    )
    refresh()
    body = ft.Column([insight_text, chart_host], spacing=8)
    card = _card(
        "Portfolio value vs. benchmark",
        "indexed to 100 at start",
        body,
        width=card_width,
        height=card_height,
        menu=common.menu_button("Options", options.toggle),
    )
    return _Performance(common.with_popovers(card, card_width or width, card_height, options), set_range, custom_start, custom_end, refresh)


def _portfolio_performance_block(page: ft.Page | None) -> ft.Control:
    """The value-vs-benchmark card on its own (used by tests and by the page)."""
    return _performance_controller(page).card


# ---------------------------------------------------------------------------
# Below-the-fold evidence cards (current content, kit styling)
# ---------------------------------------------------------------------------


def _status_line(text: str, colour: str = theme.INK2, **kwargs: object) -> ft.Text:
    return common.text(text, 12.5, 400, colour, max_lines=3, **kwargs)  # type: ignore[arg-type]


def _status_colour(status: object) -> str:
    return theme.GREEN if status == "available" else theme.AMBER if status == "partial" else theme.RED


def _portfolio_fixed_income_returns_block(state: AppState, *, width: float | None = None) -> ft.Control:
    held_ids = tuple(sorted(_holding_ids(state.snapshot.holdings)))
    as_of_date = state.snapshot.data_report.as_of_date
    decision_time = f"{as_of_date}T23:59:59+00:00" if as_of_date is not None else ""
    result = load_fixed_income_screener(decision_time=decision_time, instrument_ids=held_ids)
    rows = result.get("rows") if isinstance(result, Mapping) else None
    rows = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    reasons = ", ".join(map(str, result.get("reason_codes", ())))
    table = DataTable(
        [
            TableColumn("instrument", "Instrument", flex=2, sortable=False),
            TableColumn("baseline", "Baseline", flex=2, numeric=True, sortable=False),
            TableColumn("net", "Net", flex=2, numeric=True, sortable=False),
            TableColumn("risk", "Risk-adjusted", flex=2, numeric=True, sortable=False),
            TableColumn("fit", "Portfolio fit", flex=2, sortable=False),
            TableColumn("blockers", "Blockers", flex=3, sortable=False),
        ],
        [
            {
                "instrument": str(row.get("instrument_id", "")),
                "baseline": format_percent(row.get("baseline_total_return")),
                "net": format_percent(row.get("net_total_return")),
                "risk": format_percent(row.get("risk_adjusted_score")),
                "fit": str(row.get("portfolio_fit", "unavailable")),
                "blockers": ", ".join(map(str, row.get("reason_codes", ()))) or "—",
            }
            for row in rows
        ],
        row_height=40,
        max_visible_rows=6,
        empty_title="No fixed-income holdings",
        empty_reason="No fixed-income holdings have saved terms and return inputs in this snapshot. " + reasons,
        key="portfolio.fixed-income.table",
    )
    status = f"Status: {result.get('status', 'unavailable')}; persistence={result.get('persistence_status', 'unavailable')}; execution_allowed=false."
    return _card("Fixed-income portfolio fit", "baseline, net and risk-adjusted", [table, Note(status)], width=width)


def _portfolio_maturity_ladder_block(state: AppState, analysis: PortfolioAnalysis, *, width: float | None = None) -> ft.Control:
    projection = load_portfolio_maturity_ladder_projection(state.snapshot, analysis)
    return _card("Fixed-income maturity and income ladder", "expected income and maturity proceeds", portfolio_maturity_ladder_panel(projection), width=width)


def _portfolio_risk_profiles_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
    *,
    width: float | None = None,
    height: float | None = None,
    body_size: tuple[float, float] | None = None,
) -> _RiskProfiles:
    selected_id = ["medium"]
    saved_versions: dict[str, Mapping[str, object]] = {}
    saved_history: dict[str, list[Mapping[str, object]]] = {}
    projection = [load_portfolio_risk_profile_projection(state.snapshot, current_analysis[0], profile_id=selected_id[0])]
    comparison_rows = projection[0].get("comparison", ())
    comparison_rows = comparison_rows if isinstance(comparison_rows, (list, tuple)) else ()
    options = [
        (str(item.get("profile_id")), str(item.get("label", item.get("profile_id", ""))))
        for item in comparison_rows
        if isinstance(item, Mapping)
    ]
    selector = Dropdown(key="portfolio.risk-profile.select", options=options, value=selected_id[0] if options else None, on_select=lambda event: select_profile(event), disabled=not options)
    segmented_host = ft.Container()
    description = common.text("", 12.5, 400, theme.INK2, max_lines=3)
    note_text = common.text("", 12, 400, theme.INK2, max_lines=2)
    status = common.text("", 12.5, 400, theme.INK2, max_lines=3)
    params_host = ft.Column(spacing=12)
    comparison_host = ft.Column(spacing=0)
    detail_text = common.text("", 12, 400, theme.INK2, mono=True, selectable=True)
    parameter_fields: dict[str, ft.TextField] = {}
    card_holder = ft.Container()

    def render_projection(value: Mapping[str, object]) -> None:
        profile = value.get("profile")
        profile = profile if isinstance(profile, Mapping) else {}
        parameters = profile.get("parameters")
        parameters = parameters if isinstance(parameters, Mapping) else {}
        guardrails = profile.get("guardrails")
        guardrails = guardrails if isinstance(guardrails, Mapping) else {}
        anchor_value = value.get("vwce_anchor")
        anchor_value = anchor_value if isinstance(anchor_value, Mapping) else {}
        eligibility = value.get("eligibility")
        eligibility = eligibility if isinstance(eligibility, Mapping) else {}
        status_value = str(value.get("status", "unavailable"))
        reason = value.get("reason")
        status.value = (
            f"Profile projection {status_value}; risk-relative rank/recommendation unavailable: {reason}."
            if reason
            else f"Profile projection {status_value}; execution remains disabled."
        )
        status.color = theme.GREEN if status_value == "partial" else theme.AMBER
        description.value = f"{profile.get('label', 'Risk profile')} · {profile.get('intent', '')}"
        note_text.value = f"policy version {profile.get('version', 'unavailable')} · {profile.get('origin', 'unavailable')}"
        parameter_fields.clear()
        for name, parameter in parameters.items():
            field = common.text_input(key=f"portfolio.risk-profile.param.{name}", value=str(parameter))
            parameter_fields[str(name)] = field
        cells = [
            ft.Column([Field(str(name).replace("_", " ").capitalize(), control=field), common.text(_helper(name, guardrails), 11.5, 400, theme.INK3)], spacing=theme.SPACE_1, tight=True, expand=True)
            for name, field in parameter_fields.items()
        ]
        params_host.controls = [ft.Row(cells[index : index + 2], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START) for index in range(0, len(cells), 2)]
        reasons = eligibility.get("binding_reasons", ())
        history_rows = value.get("version_history", ())
        anchor_text = (
            "VWCE anchor resolved: "
            f"share class={anchor_value.get('canonical_share_class_id')}; listing={anchor_value.get('listing_id')}; "
            f"date={anchor_value.get('effective_date')}; currency={anchor_value.get('output_currency')}; "
            f"horizon={anchor_value.get('horizon_years')} years; known={anchor_value.get('knowledge_cutoff')}; "
            f"source_digest={anchor_value.get('anchor_digest')}; resolution_digest={anchor_value.get('resolution_digest')}; "
            f"risk distribution={anchor_value.get('risk_envelope_status')}."
            if anchor_value.get("status") == "available"
            else f"VWCE anchor unavailable: {anchor_value.get('reason', 'saved anchor resolution unavailable')}."
        )
        detail_text.value = "\n".join(
            [
                f"Policy hash: {profile.get('policy_hash', 'unavailable')}",
                "Binding reasons: " + (", ".join(map(str, reasons)) if reasons else "none"),
                anchor_text,
                "Version history (this page session; persistent store unavailable): "
                + json.dumps(history_rows if isinstance(history_rows, (list, tuple)) else [], ensure_ascii=False, sort_keys=True, default=str),
                f"Raw portfolio analysis remains unchanged. Snapshot binding: {value.get('source_snapshot_hash') or 'unavailable'}.",
            ]
        )
        rows = value.get("comparison", ())
        rows = rows if isinstance(rows, (list, tuple)) else ()
        table_rows = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            result = item.get("eligibility")
            result = result if isinstance(result, Mapping) else {}
            elig = str(result.get("status", "unavailable"))
            table_rows.append({
                "profile": str(item.get("label", item.get("profile_id"))),
                "eligibility": Tag(elig, common.tag_kind(elig), dense=True),
                "rank": str(result.get("rank", "unavailable")),
                "recommendation": str(result.get("recommendation", "unavailable")),
            })
        comparison_host.controls = [
            DataTable(
                [TableColumn("profile", "Profile", flex=3, sortable=False), TableColumn("eligibility", "Eligibility", flex=2, sortable=False), TableColumn("rank", "Rank", flex=1, numeric=True, sortable=False), TableColumn("recommendation", "Recommendation", flex=3, sortable=False)],
                table_rows, row_height=36, max_visible_rows=5, empty_title="Profile comparison unavailable", empty_reason=str(reason or "No profile comparison rows."),
                key="portfolio.risk-profile.comparison",
            )
        ]
        if profile.get("profile_id"):
            saved_versions[str(profile["profile_id"])] = dict(profile)
            saved_history[str(profile["profile_id"])] = [dict(item) for item in history_rows if isinstance(item, Mapping)] if isinstance(history_rows, (list, tuple)) else []
        labels = [label for _, label in options]
        current_label = dict(options).get(selected_id[0])
        if labels and current_label in labels:
            segmented_host.content = Segmented(labels, current_label, on_change=select_label)

    def select_label(label: str) -> None:
        for profile_id, text in options:
            if text == label:
                selector.value = profile_id
                select_profile(None)
                return

    def refresh(
        _event: ft.ControlEvent | None = None,
        *,
        profile_edits: Mapping[str, object] | None = None,
        reset_to_preset: bool = False,
    ) -> Mapping[str, object]:
        profile_id = selected_id[0]
        result = load_portfolio_risk_profile_projection(
            state.snapshot,
            current_analysis[0],
            profile_id=profile_id,
            profile_version=saved_versions.get(profile_id),
            version_history=saved_history.get(profile_id, ()),
            profile_edits=profile_edits,
            reset_to_preset=reset_to_preset,
        )
        projection[0] = result
        render_projection(result)
        common.refresh(card_holder)
        _safe_update(page)
        return result

    def select_profile(_event: ft.ControlEvent | None) -> None:
        value = str(selector.value or "").strip()
        if value:
            selected_id[0] = value
            refresh()

    def save_profile(_event: ft.ControlEvent | None) -> None:
        try:
            values = {name: _parameter_value(field.value) for name, field in parameter_fields.items()}
            result = refresh(profile_edits=values)
            active = result.get("profile")
            version = active.get("version") if isinstance(active, Mapping) else "unavailable"
            status.value = f"Created risk-profile version {version}; the preset and earlier versions were retained."
            status.color = theme.GREEN
            common.refresh(status)
            _safe_update(page)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            status.value = f"Profile version was not saved: {exc}"
            status.color = theme.AMBER
            common.refresh(status)
            _safe_update(page)

    def reset_profile(_event: ft.ControlEvent | None) -> None:
        result = refresh(reset_to_preset=True)
        active = result.get("profile")
        version = active.get("version") if isinstance(active, Mapping) else "unavailable"
        status.value = f"Created reset version {version}; the preset and earlier versions were retained."
        status.color = theme.GREEN
        common.refresh(status)
        _safe_update(page)

    render_projection(projection[0])
    actions = ft.Row(
        [
            _workflow_button("Save as new version", key_name="portfolio.risk-profile.save", on_click=save_profile, primary=True, disabled=not options),
            _workflow_button("Reset to preset", key_name="portfolio.risk-profile.reset", on_click=reset_profile, disabled=not options),
        ],
        spacing=12,
    )
    inner = ft.Column(
        [segmented_host, description, params_host, actions, status, common.text("Profile comparison", 13.5, 600), comparison_host, Disclosure("policy hash and binding reasons", detail_text)],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )
    if body_size is not None:
        inner = ft.Container(content=inner, width=body_size[0], height=body_size[1])  # type: ignore[assignment]
    card = _card("Risk profile & guardrails", f"{note_text.value}", inner, width=width, height=height)
    card_holder.content = card
    return _RiskProfiles(card, selector, refresh)


@dataclass
class _RiskProfiles:
    card: ft.Control
    selector: ft.Dropdown
    refresh: Callable[..., object]


def _helper(name: object, guardrails: Mapping[str, object]) -> str:
    bounds = guardrails.get(str(name))
    return f"Allowed {bounds[0]} to {bounds[1]}" if isinstance(bounds, (list, tuple)) and len(bounds) == 2 else "Allowed range unavailable"


def _parameter_value(value: object) -> float:
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise ValueError("profile parameters must be finite numbers") from exc
    if not math.isfinite(number):
        raise ValueError("profile parameters must be finite numbers")
    return number


def _portfolio_forecast_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
    *,
    width: float | None = None,
) -> ft.Control:
    status = common.text("Loading saved portfolio forecast…", 12.5, 400, theme.INK2, max_lines=3, key="portfolio.forecast.status")
    result_host = ft.Column(key="portfolio.forecast.results", spacing=12)

    def cell_text(value: object, *, as_currency: bool = False, as_percent: bool = False) -> str:
        if not isinstance(value, Mapping) or value.get("status") not in {"available", "partial"}:
            reason = value.get("reason") if isinstance(value, Mapping) else None
            return f"Unavailable: {reason or 'saved input unavailable'}"
        raw = value.get("value")
        if as_currency:
            return format_currency(raw, currency=str(currency.value or "EUR").upper())
        if as_percent:
            return format_percent(raw)
        return str(raw) if raw is not None else "N/A"

    def selected_view(view: Mapping[str, object]) -> Mapping[str, object]:
        net, gross = view.get("net"), view.get("gross")
        chosen = net if isinstance(net, Mapping) and net.get("status") != "unavailable" else gross
        return chosen if isinstance(chosen, Mapping) else {}

    def quantile_rows(view: Mapping[str, object]) -> list[dict[str, object]]:
        selected = selected_view(view)
        quantiles = selected.get("quantiles")
        gain_quantiles = selected.get("gain_loss_quantiles")
        rows: list[dict[str, object]] = []
        if isinstance(quantiles, Mapping):
            for percentile in ("q05", "q25", "q50", "q75", "q95"):
                gain = gain_quantiles.get(percentile) if isinstance(gain_quantiles, Mapping) else None
                rows.append({
                    "percentile": percentile.upper(),
                    "return": format_percent(quantiles.get(percentile)),
                    "gain": format_currency(gain, currency=str(currency.value or "EUR").upper()),
                    "_value": quantiles.get(percentile),
                })
        return rows

    def render_view(label: str, view: Mapping[str, object]) -> ft.Control:
        selected = selected_view(view)
        probabilities = selected.get("probabilities")
        coverage = view.get("coverage")
        coverage = coverage if isinstance(coverage, Mapping) else {}
        components = view.get("components")
        components = components if isinstance(components, Mapping) else {}
        costs = view.get("cost_contributions")
        costs = costs if isinstance(costs, Mapping) else {}
        tail = selected.get("tail_dependence")
        tail = tail if isinstance(tail, Mapping) else {}
        rows = quantile_rows(view)
        status_value = str(view.get("status", "unavailable"))
        table: ft.Control = DataTable(
            [TableColumn("percentile", "Fan percentile", flex=2, sortable=False), TableColumn("return", "Return", flex=2, numeric=True, sortable=False), TableColumn("gain", "Gain / loss", flex=3, numeric=True, sortable=False)],
            rows, row_height=34, max_visible_rows=5, empty_title="Forecast quantiles unavailable", empty_reason=str(selected.get("reason") or "Forecast quantiles unavailable."),
        )
        probability_lines = []
        if isinstance(probabilities, Mapping):
            for key, title in (("loss", "Loss"), ("beat_cash", "Beat cash"), ("beat_benchmark", "Beat benchmark")):
                probability_lines.append(f"{title}: {cell_text(probabilities.get(key), as_percent=True)}")
        contribution_lines = [f"{title}: {cell_text(components.get(key), as_currency=True)}" for key, title in (("price", "Price"), ("income", "Income"), ("fx", "FX"))]
        contribution_lines.extend(f"Cost {key}: {cell_text(value, as_currency=True)}" for key, value in costs.items())
        return ft.Column(
            [
                section_header(label, f"Status: {status_value}; exposure confidence: {format_percent(coverage.get('confidence'))}; unsupported weight: {format_percent(coverage.get('unsupported_exposure_weight'))}."),
                _status_line(f"Expected gain / loss: {cell_text(selected.get('expected_gain_loss'), as_currency=True)}"),
                _status_line(f"Expected return: {cell_text(selected.get('expected_return'), as_percent=True)}"),
                table,
                Disclosure(
                    f"{label.lower()} contributions and probabilities",
                    "\n".join(
                        [
                            *probability_lines,
                            "Contributions and costs use saved holding records; missing inputs remain unavailable.",
                            *contribution_lines,
                            f"Scenario volatility: {cell_text(selected.get('volatility'), as_percent=True)} | Tail dependence: {tail.get('status', 'unavailable')} | Cost sensitivity: {cell_text(view.get('cost_sensitivity'), as_currency=True)}",
                            str(view.get("reason") or ""),
                        ]
                    ),
                ),
            ],
            spacing=8,
        )

    def distribution_chart(forecast: object) -> ft.Control:
        current_rows = quantile_rows(forecast.current)  # type: ignore[attr-defined]
        target_rows = quantile_rows(forecast.target)  # type: ignore[attr-defined]
        labels = [row["percentile"] for row in (current_rows or target_rows)]
        if not labels:
            return ck.empty_state("No forecast distribution", str(selected_view(forecast.target).get("reason") or "Forecast quantiles unavailable."), 480, 240)  # type: ignore[attr-defined]

        def percent_values(rows: list[dict[str, object]]) -> list[float | None]:
            by_label = {row["percentile"]: row["_value"] for row in rows}
            return [None if by_label.get(label) is None else float(by_label[label]) * 100.0 for label in labels]  # type: ignore[arg-type]

        return ck.grouped_bar_chart(
            [str(label) for label in labels],
            [ck.BarSeries("Current holdings", percent_values(current_rows), "blue"), ck.BarSeries("What-if target", percent_values(target_rows), "gold")],
            x_name="Forecast percentile", y_name="Return (%)", width=480, height=240, margins=ck.Margins(56, 16, 34, 44),
        )

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        forecast = load_portfolio_forecast_aggregation(
            state.snapshot,
            current_analysis[0],
            horizon_days=int(horizon.value or PRIMARY_MODEL_HORIZON_DAYS),
            output_currency=str(currency.value or "EUR").upper(),
        )
        status.value = f"Portfolio forecast status: {forecast.status}; horizon={forecast.horizon_days or 'unavailable'} days; execution_allowed=false."
        if forecast.reason:
            status.value = f"{status.value} {forecast.reason}"
        status.color = _status_colour(forecast.status)
        comparison = forecast.comparison if isinstance(forecast.comparison, Mapping) else {}
        if forecast.status == "unavailable":
            result_host.controls = [EmptyState("Forecast unavailable", str(forecast.reason or "Saved portfolio forecast inputs are unavailable."), height=160)]
            if _event is not None:
                common.refresh(result_host)
                common.refresh(status)
                _safe_update(page)
            return
        result_host.controls = [
            Well(distribution_chart(forecast), width=480, height=240),
            render_view("Current holdings", forecast.current),
            render_view("What-if target", forecast.target),
            _status_line(
                f"Target minus current expected return: {format_percent(comparison.get('expected_return_difference'))} | q05: {format_percent(comparison.get('q05_return_difference'))}"
            ),
            Disclosure(
                "forecast assumptions",
                "Assumptions: seeded saved-distribution scenarios; q05–q95 tails clamp to saved endpoints; perfect positive correlation is the stress case. "
                f"Seed={forecast.provenance.get('scenario_seed', 'unavailable')}; count={forecast.provenance.get('scenario_count', 'unavailable')}; "
                f"risk model={forecast.provenance.get('risk_model_version', 'unavailable')}; input hashes are retained in forecast evidence.",
            ),
        ]
        if _event is not None:
            common.refresh(result_host)
            common.refresh(status)
            _safe_update(page)

    horizon = Dropdown(key="portfolio.forecast.horizon", options=[str(value) for value in sorted(CANONICAL_DISTRIBUTION_HORIZONS_DAYS)], value=str(PRIMARY_MODEL_HORIZON_DAYS), on_select=refresh)
    currency = TextField(key="portfolio.forecast.currency", value="EUR", on_submit=refresh)
    refresh_button = _workflow_button("Refresh forecast", key_name="portfolio.forecast.refresh", on_click=refresh)
    refresh()
    controls = ft.Row(
        [Field("Forecast horizon (days)", control=horizon, expand=True), Field("Output currency", control=currency, expand=True), ft.Container(refresh_button, padding=ft.Padding(left=0, top=19, right=0, bottom=0))],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )
    return _card("Portfolio forecast", "exact-horizon seeded scenarios", [controls, status, result_host], width=width)


def _portfolio_calendar_block(
    page: ft.Page | None,
    state: AppState,
    analysis: PortfolioAnalysis,
    *,
    width: float | None = None,
) -> ft.Control:
    projection = load_portfolio_calendar_projection(state.snapshot, analysis, output_currency="EUR")
    available = projection.get("available_output_currencies", ("EUR",))
    currencies = sorted({str(item).upper() for item in available if str(item).isalpha() and len(str(item)) == 3}) if isinstance(available, (list, tuple, set)) else ["EUR"]
    if "EUR" not in currencies:
        currencies.insert(0, "EUR")
    calendar_host = ft.Column(spacing=12)

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        nonlocal projection
        projection = load_portfolio_calendar_projection(state.snapshot, analysis, output_currency=str(currency.value or "EUR"))
        calendar_host.controls = render(projection)
        if page is not None:
            common.refresh(calendar_host)
            _safe_update(page)

    currency = Dropdown(key="portfolio.calendar.currency", options=currencies, value="EUR", on_select=refresh)

    def month_chart(current: Mapping[str, object]) -> ft.Control:
        sums: dict[str, float] = {}
        records = current.get("cash_flow_summaries", ())
        for item in records if isinstance(records, (list, tuple)) else ():
            if not isinstance(item, Mapping) or item.get("period_type") != "month":
                continue
            amount = _cell_number(item.get("amount"))
            if amount is not None:
                sums[str(item.get("period"))] = sums.get(str(item.get("period")), 0.0) + amount
        labels = sorted(sums)
        return ck.bar_chart(
            labels, [sums[label] for label in labels], x_name="Month", y_name=f"Projected amount ({str(currency.value or 'EUR')})", width=480, height=220,
            show_labels=False, margins=ck.Margins(64, 16, 24, 44), unavailable_reason=None if labels else "Monthly amounts are unavailable until saved event amounts, terms, quantities and FX are covered.",
            empty_title="No projected cash flows",
        )

    def render(current: Mapping[str, object]) -> list[ft.Control]:
        warnings = current.get("warnings", ())
        warning_text = "; ".join(str(item) for item in warnings[:4]) if isinstance(warnings, (list, tuple)) else ""
        status = _status_line(
            f"Calendar status: {current.get('status', 'unavailable')}; output currency: {current.get('currency') or 'unavailable'}; execution_allowed=false."
            + (f" Coverage: {warning_text}" if warning_text else ""),
            theme.AMBER if warning_text or current.get("status") != "available" else theme.GREEN,
        )
        event_records = current.get("events", ())
        event_rows: list[dict[str, object]] = []
        for item in event_records if isinstance(event_records, (list, tuple)) else ():
            if not isinstance(item, Mapping):
                continue
            exposure = item.get("affected_exposure", {})
            exposure = exposure if isinstance(exposure, Mapping) else {}
            market_value = exposure.get("market_value")
            exposure_text = (
                format_currency(market_value, currency=str(exposure.get("currency") or "EUR"))
                if market_value is not None
                else f"Qty {format_number(exposure.get('quantity'))}"
            )
            event_date = str(item.get("event_date") or "Unavailable")
            if item.get("timezone_name"):
                event_date = f"{event_date} {item.get('timezone_name')}"
            payment_date = item.get("payment_date")
            if payment_date and str(payment_date)[:10] != event_date[:10]:
                event_date = f"{event_date} / pay {payment_date}"
            event_rows.append({
                "date": event_date,
                "event": str(item.get("title") or item.get("event_type") or "Unavailable"),
                "holding": str(item.get("instrument_id") or "Unavailable"),
                "status": str(item.get("status") or "Unavailable"),
                "source": f"{item.get('source_rank', 'other')}: {item.get('source_authority') or 'Unavailable'}; {item.get('confidence') or 'Unavailable'}",
                "exposure": exposure_text,
                "blackout": "Candidate" if item.get("blackout_candidate") else "No",
            })
        events = DataTable(
            [TableColumn("date", "Event date / payable", flex=3, sortable=False), TableColumn("event", "Event", flex=3, sortable=False), TableColumn("holding", "Holding", flex=2, sortable=False),
             TableColumn("status", "Status", flex=2, sortable=False), TableColumn("source", "Source / confidence", flex=3, sortable=False), TableColumn("exposure", "Exposure", flex=2, numeric=True, sortable=False),
             TableColumn("blackout", "Blackout", flex=2, sortable=False)],
            event_rows, row_height=40, max_visible_rows=6, empty_title="No saved events", empty_reason=str(current.get("reason") or "No saved events are available."),
        )
        summary_records = current.get("cash_flow_summaries", ())
        summary_rows = [
            {"period": f"{item.get('period_type', '')}: {item.get('period', '')}", "flow": str(item.get("flow_type") or "Unavailable"),
             "amount": format_currency(item.get("amount"), currency=str(item.get("currency") or "EUR")), "status": str(item.get("status") or "unavailable")}
            for item in (summary_records if isinstance(summary_records, (list, tuple)) else ())
            if isinstance(item, Mapping)
        ]
        summaries = DataTable(
            [TableColumn("period", "Period", flex=3, sortable=False), TableColumn("flow", "Cash flow", flex=2, sortable=False), TableColumn("amount", "Projected amount", flex=3, numeric=True, sortable=False), TableColumn("status", "Status", flex=2, sortable=False)],
            summary_rows, row_height=40, max_visible_rows=6, empty_title="No projected amounts",
            empty_reason="Monthly and quarterly amounts are unavailable until saved event amounts, terms, quantities, and FX are covered.",
        )
        return [
            Well(month_chart(current), width=480, height=220),
            status,
            Disclosure("events and projected cash flows", ft.Column([events, common.text("Projected monthly and quarterly cash flows", 13.5, 600), summaries], spacing=12)),
        ]

    calendar_host.controls = render(projection)
    return _card("Projected cash flows", "income, events, maturity and liquidity", [Field("Output currency", control=currency), calendar_host], width=width)


# ---------------------------------------------------------------------------
# Holdings (row B, Holdings view)
# ---------------------------------------------------------------------------


def _holding_display(
    cell: object,
    *,
    currency: str | None = None,
    percent: bool = False,
) -> str:
    if isinstance(cell, Mapping):
        if cell.get("status") != "available" or cell.get("value") is None:
            reason = str(cell.get("reason") or "source_value_unavailable")
            return f"unavailable · {reason}"
        value = cell.get("value")
    else:
        value = cell
    if value is None:
        return "unavailable · source_value_unavailable"
    if percent:
        return format_percent(value)
    if currency:
        return _currency_text(value, currency)
    if isinstance(value, (tuple, list)):
        return ", ".join(str(item) for item in value) or "none"
    return format_number(value) if isinstance(value, (int, float)) else str(value)


def _currency_text(value: object, currency: str) -> str:
    number = _cell_number(value)
    if currency == "EUR" and number is not None:
        return f"€ {number:,.0f}"
    return format_currency(value, currency=currency)


def _short(cell: object, *, currency: str | None = None, percent: bool = False) -> str | None:
    """Table text of a projection cell; an unavailable cell is an em dash, never zero."""
    value = _cell_value(cell)
    if value is None:
        return None
    return _holding_display(value, currency=currency, percent=percent)


def _portfolio_holdings_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
    proposal_callback: Callable[[ft.ControlEvent | None], None],
    refresh_callbacks: list[Callable[[ft.ControlEvent | None], None]],
    *,
    range_getter: Callable[[], str] = lambda: "1Y",
    shares_getter: Callable[[], Mapping[str, float]] = lambda: {},
    width: float | None = None,
    height: float | None = None,
    body_size: tuple[float, float] | None = None,
) -> ft.Control:
    initial = load_portfolio_holdings_projection(state.snapshot, current_analysis[0], horizon_days=PRIMARY_MODEL_HORIZON_DAYS)
    run_rows = initial.get("analysis_runs", ())
    run_ids = [str(item.get("run_id")) for item in run_rows if isinstance(item, Mapping) and str(item.get("run_id", "")).strip()]
    selected_run = str(initial.get("selected_analysis_run_id") or "unavailable")
    if selected_run != "unavailable" and selected_run not in run_ids:
        run_ids.insert(0, selected_run)

    analysis_run = Dropdown(key="portfolio.holdings.analysis-run", options=run_ids or ["unavailable"], value=selected_run, on_select=lambda event: refresh(event))
    horizon = Dropdown(key="portfolio.holdings.horizon", options=[str(value) for value in sorted(CANONICAL_DISTRIBUTION_HORIZONS_DAYS)], value=str(PRIMARY_MODEL_HORIZON_DAYS), on_select=lambda event: refresh(event))
    currency = TextField(key="portfolio.holdings.currency", value="EUR", on_change=lambda event: refresh(event))
    search = TextField(key="portfolio.holdings.search", hint="Filter by instrument", on_change=lambda event: refresh(event))
    export_path = common.text_input(key="portfolio.holdings.export-path", hint="Enter a local file path")
    asset_filter = Dropdown(key="portfolio.holdings.asset-filter", options=list(_ASSET_FILTERS), value="all", on_select=lambda event: refresh(event))
    sort = Dropdown(key="portfolio.holdings.sort", options=list(_SORTS), value="weight:desc", on_select=lambda event: refresh(event))
    preset = Dropdown(key="portfolio.holdings.column-preset", options=list(_COLUMN_PRESETS), value="full", on_select=lambda event: refresh(event))
    status = common.text("Loading holdings evidence…", 12, 400, theme.INK2, trunc=True, key="portfolio.holdings.status")
    detail_host = ft.Column([], spacing=0, tight=True)
    row_host = ft.Column(key="portfolio.holdings.rows", spacing=0)
    projection_state: list[dict[str, object]] = [initial]
    table_height = (body_size[1] - 72) if body_size else 320.0

    def refresh(_event: ft.ControlEvent | None = None) -> None:
        selected_sort, _, direction = str(sort.value or "weight:desc").partition(":")
        try:
            selected_horizon = int(str(horizon.value or PRIMARY_MODEL_HORIZON_DAYS))
        except (TypeError, ValueError):
            selected_horizon = 0
        projection = load_portfolio_holdings_projection(
            state.snapshot,
            current_analysis[0],
            horizon_days=selected_horizon,
            output_currency=str(currency.value or ""),
            analysis_run_id=None if str(analysis_run.value or "") == "unavailable" else str(analysis_run.value),
            search=str(search.value or ""),
            asset_type=None if str(asset_filter.value or "all").casefold() == "all" else str(asset_filter.value),
            sort_by=selected_sort,
            descending=direction == "desc",
            column_preset=str(preset.value or "full").casefold(),
        )
        projection_state[:] = [projection]
        render_projection(projection)
        if _event is not None:
            common.refresh(row_host)
            common.refresh(status)
            _safe_update(page)

    def open_detail(_event: ft.ControlEvent, instrument_id: str) -> None:
        state.selected_etf = instrument_id
        if page is not None:
            page.go("/stock-research")

    def prepare_proposal(event: ft.ControlEvent | None) -> None:
        if not bool(projection_state[0].get("proposal_handoff_allowed")):
            status.value = "Proposal hand-off blocked: " + str(projection_state[0].get("proposal_handoff_reason") or "analysis_is_not_current_for_selected_snapshot")
            status.color = theme.AMBER
            common.refresh(status)
            _safe_update(page)
            return
        proposal_callback(event)

    def export_selected(_event: ft.ControlEvent | None) -> None:
        destination_text = str(export_path.value or "").strip()
        if not destination_text:
            status.value = "CSV export unavailable: enter a local destination path."
            status.color = theme.AMBER
            common.refresh(status)
            _safe_update(page)
            return
        projection = projection_state[0]
        rows = projection.get("rows", ())
        rows = rows if isinstance(rows, list) else []
        if not rows:
            status.value = "CSV export unavailable: the selected projection has no holding rows."
            status.color = theme.AMBER
            common.refresh(status)
            _safe_update(page)
            return
        portfolio_meta = projection.get("portfolio_snapshot")
        portfolio_meta = portfolio_meta if isinstance(portfolio_meta, Mapping) else {}
        performance_meta = projection.get("performance_snapshot")
        performance_meta = performance_meta if isinstance(performance_meta, Mapping) else {}
        metadata = {
            "projection_status": projection.get("status"),
            "portfolio_id": portfolio_meta.get("portfolio_id"),
            "portfolio_snapshot_id": portfolio_meta.get("snapshot_id"),
            "portfolio_source_checksum": portfolio_meta.get("source_checksum"),
            "performance_snapshot_date": performance_meta.get("date"),
            "analysis_run_id": projection.get("analysis_run_id"),
            "analysis_date": projection.get("analysis_date"),
            "analysis_policy_id": projection.get("analysis_policy_id"),
            "horizon_days": projection.get("horizon_days"),
            "output_currency": projection.get("output_currency"),
            "projection_reasons": ";".join(str(item) for item in projection.get("reasons", ())),
            "projection_conflicts": ";".join(str(item) for item in projection.get("conflicts", ())),
        }
        records: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            record = dict(metadata)
            for field, value in row.items():
                if isinstance(value, Mapping) and "status" in value:
                    record[field] = value.get("value")
                    record[f"{field}_status"] = value.get("status")
                    record[f"{field}_reason"] = value.get("reason")
                elif isinstance(value, Mapping):
                    for subfield, cell in value.items():
                        name = f"{field}_{subfield}"
                        if isinstance(cell, Mapping) and "status" in cell:
                            record[name] = cell.get("value")
                            record[f"{name}_status"] = cell.get("status")
                            record[f"{name}_reason"] = cell.get("reason")
                        else:
                            record[name] = cell
                elif isinstance(value, (tuple, list)):
                    record[field] = ";".join(str(item) for item in value)
                else:
                    record[field] = value
            records.append(record)
        result = export_table("portfolio_holdings_analysis", pd.DataFrame.from_records(records), Path(destination_text))
        if result.ok:
            status.value = f"Holdings evidence CSV ready: {result.destination} ({result.rows} rows)."
            status.color = theme.GREEN
        else:
            status.value = f"Holdings evidence CSV unavailable: {result.error}; previous output preserved."
            status.color = theme.AMBER
        common.refresh(status)
        _safe_update(page)

    def instrument_cell(instrument_id: str, name: object) -> ft.Control:
        return ft.TextButton(
            content=common.text(instrument_id, 13.5, 700, trunc=True),
            key=f"portfolio.holdings.instrument-detail.{instrument_id}",
            tooltip=str(name or instrument_id),
            on_click=lambda event, selected_id=instrument_id: open_detail(event, selected_id),
            style=ft.ButtonStyle(padding=ft.Padding(left=0, top=0, right=0, bottom=0)),
        )

    def render_projection(projection: dict[str, object]) -> None:
        rows = projection.get("rows", ())
        rows = rows if isinstance(rows, list) else []
        output_currency = str(projection.get("output_currency") or "EUR")
        horizon_days = projection.get("horizon_days")
        portfolio_meta = projection.get("portfolio_snapshot")
        portfolio_meta = portfolio_meta if isinstance(portfolio_meta, Mapping) else {}
        performance_meta = projection.get("performance_snapshot")
        performance_meta = performance_meta if isinstance(performance_meta, Mapping) else {}
        reason = projection.get("reason") or projection.get("analysis_reason")
        analysis_day = _long_date(projection.get("analysis_date"))
        status.value = (
            f"{str(projection.get('status', 'unavailable')).capitalize()}: {projection.get('row_count', 0)} of {projection.get('total_rows', 0)} positions"
            + (f" · analysis as of {analysis_day}" if analysis_day else "")
        )
        detail = (
            f"run {projection.get('analysis_run_id') or 'unavailable'} · data/performance as-of {portfolio_meta.get('as_of') or 'unavailable'}/"
            f"{performance_meta.get('date') or 'unavailable'} · analysis as-of {projection.get('analysis_date') or 'unavailable'} · "
            f"policy {projection.get('analysis_policy_ids') or 'unavailable'} · horizon {horizon_days or 'unavailable'} days"
        )
        if projection.get("conflicts"):
            detail += " · conflicts: " + ", ".join(str(item) for item in projection["conflicts"])
        if reason:
            status.value += f" · {_REASON_LABELS.get(str(reason), str(reason).replace('_', ' '))}"
            detail += f" · reason id: {reason}"
        detail_host.controls = [Disclosure("Holdings source", detail)]
        status.color = theme.GREEN if projection.get("status") == "available" else theme.AMBER
        proposal_button.disabled = not bool(projection.get("proposal_handoff_allowed"))
        preset_value = str(projection.get("column_preset", "full"))
        range_key = range_getter()
        shares = shares_getter()
        as_of = _as_of_date(portfolio_meta.get("as_of"))
        table_rows: list[dict[str, object]] = []
        weights: list[float] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            instrument_id = str(item.get("instrument_id", ""))
            if not instrument_id:
                continue
            weight = _cell_number(item.get("weight"))
            row: dict[str, object] = {"instrument": instrument_cell(instrument_id, item.get("name")), "weight": ScoreBar(None if weight is None else weight * 100.0, maximum=100, decimals=0)}
            if preset_value == "values":
                row.update(
                    value=_short(item.get("value"), currency=output_currency), cost=_short(item.get("cost_basis"), currency=output_currency),
                    pnl=_short(item.get("unrealised_pnl"), currency=output_currency), income=_short(item.get("income"), currency=output_currency),
                )
            elif preset_value == "analysis":
                row.update(
                    action=_short(item.get("action")), expected=_short(item.get("expected_return"), percent=True),
                    blockers=_short(item.get("blockers")), coverage=_short(item.get("coverage"), percent=True),
                )
            else:
                realised = portfolio_view.window_return(state.snapshot.prices, instrument_id, range_key, as_of) if hasattr(state.snapshot, "prices") else None
                share = shares.get(instrument_id)
                row.update(
                    value=_short(item.get("value"), currency=output_currency),
                    ret=_return_cell(realised),
                    risk=None if share is None else f"{share * 100:.0f}%",
                )
            table_rows.append(row)
            weights.append(-1.0 if weight is None else weight)
        if str(sort.value or "weight:desc") == "weight:desc":
            order = sorted(range(len(table_rows)), key=lambda index: -weights[index])
            table_rows = [table_rows[index] for index in order]
        cash_weight = current_analysis[0].current_cash_weight
        if preset_value == "full" and table_rows and cash_weight is not None:
            total = _total_value(current_analysis[0])
            table_rows.append({
                "instrument": common.text("Cash", 13.5, 700), "weight": ScoreBar(cash_weight * 100.0, maximum=100, decimals=0),
                "value": _money(None if total is None else total * cash_weight), "ret": None, "risk": None,
            })
        columns = {
            "values": [("instrument", "Instrument", 2, False), ("weight", "Weight", 3, False), ("value", "Value", 2, True), ("cost", "Cost basis", 2, True), ("pnl", "Unrealised P&L", 2, True), ("income", "Income", 2, True)],
            "analysis": [("instrument", "Instrument", 2, False), ("weight", "Weight", 3, False), ("action", "Action", 2, False), ("expected", "Expected return", 2, True), ("blockers", "Blockers", 3, False), ("coverage", "Coverage", 2, True)],
        }.get(
            preset_value,
            [("instrument", "Instrument", 2, False), ("weight", "Weight", 4, False), ("value", "Value", 2, True), ("ret", f"{range_key} return", 2, True), ("risk", "Risk contrib.", 2, True)],
        )
        row_host.controls = [
            DataTable(
                [TableColumn(key, label, flex=flex, numeric=numeric, sortable=key == "weight") for key, label, flex, numeric in columns],
                table_rows, sort_key="weight" if str(sort.value or "weight:desc") == "weight:desc" else None, descending=True, row_height=46, max_visible_rows=8, height=table_height, empty_title="No holdings",
                empty_reason=str(reason or "No holdings match the selected snapshot and filters."), key="portfolio.holdings.table",
            )
        ]

    proposal_button = _workflow_button("Prepare ISSUE-0130 draft", key_name="portfolio.holdings.proposal", on_click=prepare_proposal, disabled=True, disabled_reason="Run an analysis for the selected snapshot first")
    refresh_callbacks[:] = [refresh]
    render_projection(initial)

    filters = common.Popover(
        "Holdings options",
        ft.Column(
            [
                Field("Analysis run", control=analysis_run),
                Field("Exact forecast horizon (days)", control=horizon),
                Field("Output currency", control=currency),
                Field("Filter holdings", control=search),
                Field("Asset type", control=asset_filter),
                Field("Sort", control=sort),
                Field("Columns", control=preset),
                Field("CSV destination", control=export_path),
                _workflow_button("Refresh holdings", key_name="portfolio.holdings.refresh", on_click=refresh),
                _workflow_button("Export holdings evidence", key_name="portfolio.holdings.export", on_click=export_selected),
                proposal_button,
            ],
            spacing=12,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=320,
    )
    body = ft.Column([row_host, ft.Container(status, padding=ft.Padding(0, theme.SPACE_3, 0, 0)), detail_host], spacing=theme.SPACE_3)
    if body_size is not None:
        body = ft.Container(content=body, width=body_size[0], height=body_size[1])  # type: ignore[assignment]
    card = _card("Holdings", "sorted by weight", body, width=width, height=height, menu=common.menu_button("Options", filters.toggle))
    return common.with_popovers(card, width or 640, height, filters)


_REASON_LABELS = {"performance_snapshot_unavailable": "performance history unavailable"}


def _return_cell(value: float | None) -> ft.Control | None:
    text = _signed(value, 1)
    return None if text is None else common.text(text, 13.5, 400, _tone_colour(value), text_align=ft.TextAlign.RIGHT)


def _as_of_date(value: object) -> date | None:
    try:
        parsed = pd.Timestamp(str(value)[:10])
    except (TypeError, ValueError):
        return None
    return None if pd.isna(parsed) else parsed.date()


def _total_value(analysis: PortfolioAnalysis) -> float | None:
    invested_share = 1.0 - float(analysis.current_cash_weight)
    if invested_share <= 0:
        return None
    return float(analysis.current_value_eur) / invested_share


# ---------------------------------------------------------------------------
# Goals, alerts and what-if (row B, Policy view)
# ---------------------------------------------------------------------------


def _portfolio_goals_block(
    page: ft.Page | None,
    state: AppState,
    current_analysis: list[PortfolioAnalysis],
    *,
    width: float | None = None,
    height: float | None = None,
    body_size: tuple[float, float] | None = None,
) -> ft.Control:
    projection = [load_portfolio_goals_projection(state.snapshot, current_analysis[0])]
    policy_editor = common.text_input(key="portfolio-goals.policy", value=json.dumps(projection[0].get("policy_editor", {}), ensure_ascii=False, indent=2), multiline=True, mono=True, max_lines=10,
    )
    snooze_until = common.text_input(key="portfolio-goals.snooze-until", hint="For example, 2026-10-02T12:00:00+02:00")
    status = common.text("Policy limits are optional; unavailable evidence stays unavailable.", 12.5, 400, theme.INK2, max_lines=3)
    results = common.text("", 12, 400, theme.INK2, mono=True, selectable=True, key="portfolio-goals.results")
    alerts_host = ft.Column(spacing=0)

    def render_result(value: Mapping[str, object]) -> None:
        summary = {
            "status": value.get("status"),
            "source_snapshot_hash": value.get("source_snapshot_hash"),
            "policy": value.get("policy"),
            "policy_as_of": value.get("policy_as_of"),
            "policy_history": value.get("policy_history"),
            "alerts": value.get("alerts"),
            "unavailable_alerts": value.get("unavailable_alerts"),
            "scenario": value.get("scenario"),
            "acknowledgement_history": value.get("acknowledgement_history"),
            "execution_allowed": value.get("execution_allowed", False),
        }
        results.value = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        editor_value = value.get("policy_editor")
        if isinstance(editor_value, Mapping) and value.get("policy") is not None:
            policy_editor.value = json.dumps(editor_value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        alerts = value.get("alerts", ())
        rows = [item for item in (alerts if isinstance(alerts, (list, tuple)) else ()) if isinstance(item, Mapping)]
        alerts_host.controls = [
            ListRow("warn", str(item.get("title") or item.get("alert_id") or "Alert"), str(item.get("message") or item.get("reason") or ""), ("active", "warn"), last=index == len(rows) - 1)
            for index, item in enumerate(rows)
        ] or [common.text("No active alert conditions.", 12.5, 400, theme.INK2)]

    render_result(projection[0])

    def apply_action(action: Mapping[str, object], message: str) -> None:
        result = load_portfolio_goals_projection(state.snapshot, current_analysis[0], action=action)
        if result.get("status") in {"available", "partial"}:
            projection[0] = result
            status.value = message
            status.color = theme.GREEN
        else:
            status.value = f"Portfolio goals unavailable: {result.get('reason', result.get('status', 'unknown'))}"
            status.color = theme.AMBER
        render_result(result)
        common.refresh(status)
        _safe_update(page)

    def say(message: str, colour: str) -> None:
        status.value = message
        status.color = colour
        common.refresh(status)
        _safe_update(page)

    def save_policy(_event: ft.ControlEvent | None) -> None:
        try:
            values = json.loads(str(policy_editor.value or "{}"))
            if not isinstance(values, Mapping):
                raise ValueError("policy must be a JSON object")
            apply_action({"type": "save_policy", "policy": values}, "Validated policy saved as a new version.")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            say(f"Policy was not saved: {exc}", theme.AMBER)

    def run_what_if(_event: ft.ControlEvent | None) -> None:
        apply_action({"type": "simulate"}, "What-if recorded from the selected snapshot; the portfolio ledger was not changed.")

    def active_alert_ids() -> tuple[str, ...]:
        alerts = projection[0].get("alerts", ())
        if not isinstance(alerts, (list, tuple)):
            return ()
        return tuple(str(item.get("alert_id")) for item in alerts if isinstance(item, Mapping) and item.get("alert_id"))

    def acknowledge_alerts(_event: ft.ControlEvent | None) -> None:
        identifiers = active_alert_ids()
        if not identifiers:
            say("There are no active alert conditions to acknowledge.", theme.MUTED)
            return
        apply_action({"type": "acknowledge", "alert_ids": identifiers}, "Acknowledgement saved; active conditions remain visible.")

    def snooze_alerts(_event: ft.ControlEvent | None) -> None:
        identifiers = active_alert_ids()
        if not identifiers:
            say("There are no active alert conditions to snooze.", theme.MUTED)
            return
        apply_action({"type": "snooze", "alert_ids": identifiers, "until": str(snooze_until.value or "")}, "Snooze saved; active conditions remain visible.")

    def draft_what_if(_event: ft.ControlEvent | None) -> None:
        scenario = projection[0].get("scenario")
        scenario_policy_binding = scenario.get("policy_binding") if isinstance(scenario, Mapping) else None
        effective_policy_binding = projection[0].get("effective_policy_binding")
        candidate = current_analysis[0].candidate
        if (
            not isinstance(scenario, Mapping)
            or scenario.get("status") != "ready"
            or scenario.get("source_snapshot_hash") != projection[0].get("source_snapshot_hash")
            or scenario.get("candidate_id") != candidate.candidate_id
            or not isinstance(scenario_policy_binding, Mapping)
            or not isinstance(effective_policy_binding, Mapping)
            or scenario_policy_binding != effective_policy_binding
        ):
            say("Draft proposal blocked: run a ready what-if for the current candidate, snapshot, and effective policy first.", theme.AMBER)
            return
        try:
            handoff = draft_portfolio_proposal(state.snapshot, current_analysis[0])
            say(f"Draft proposal hand-off prepared ({len(handoff.get('changes', ()))} changes); execution remains disabled.", theme.GREEN)
        except (TypeError, ValueError) as exc:
            say(f"Draft proposal unavailable: {exc}", theme.AMBER)

    def export_audit(_event: ft.ControlEvent | None) -> None:
        try:
            audit = projection[0].get("audit_export")
            source_hash = str(projection[0].get("source_snapshot_hash") or "").strip()
            if not isinstance(audit, Mapping) or not source_hash:
                raise ValueError("snapshot-bound portfolio goals audit is unavailable")
            path = EXPORTS_DIR / f"portfolio_goals_{current_analysis[0].candidate.candidate_id}_{source_hash[:12]}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
            state.last_export_path = path
            say(f"Portfolio goals audit exported to {path.name}; execution remains disabled.", theme.GREEN)
        except (OSError, TypeError, ValueError) as exc:
            say(f"Portfolio goals audit unavailable: {exc}", theme.AMBER)

    audit_link = ft.TextButton(content=common.text("Export goals audit", 13, 600, theme.ACC), key="portfolio-goals.audit-export", on_click=export_audit)
    inner = ft.Column(
        [
            Field("Versioned portfolio policy (JSON)", control=policy_editor, multiline=True),
            Field("Snooze until (ISO 8601 with timezone)", control=snooze_until),
            ft.Column(
                [
                    ft.Row(
                        [
                            _workflow_button("Save policy version", key_name="portfolio-goals.policy.save", on_click=save_policy, primary=True),
                            _workflow_button("Run what-if", key_name="portfolio-goals.what-if", on_click=run_what_if),
                            _workflow_button("Acknowledge active alerts", key_name="portfolio-goals.alert.acknowledge", on_click=acknowledge_alerts),
                        ],
                        spacing=12,
                    ),
                    ft.Row(
                        [
                            _workflow_button("Snooze active alerts", key_name="portfolio-goals.alert.snooze", on_click=snooze_alerts),
                            _workflow_button("Prepare draft proposal", key_name="portfolio-goals.draft-proposal", on_click=draft_what_if),
                        ],
                        spacing=12,
                    ),
                ],
                spacing=8,
            ),
            audit_link,
            status,
            alerts_host,
            Disclosure("raw goals state", results),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )
    if body_size is not None:
        inner = ft.Container(content=inner, width=body_size[0], height=body_size[1])  # type: ignore[assignment]
    return _card("Goals, alerts & what-if", "optional limits · non-advisory", inner, width=width, height=height)


# ---------------------------------------------------------------------------
# Cards that follow the candidate analysis
# ---------------------------------------------------------------------------


def _risk_evidence(analysis: PortfolioAnalysis) -> Mapping[str, object]:
    risk = analysis.service_evidence.get("risk")
    return risk if isinstance(risk, Mapping) else {}


def _candidate_volatility(analysis: PortfolioAnalysis) -> float | None:
    portfolio = _risk_evidence(analysis).get("portfolio")
    value = portfolio.get("annualised_volatility") if isinstance(portfolio, Mapping) else None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _candidate_tiles(analysis: PortfolioAnalysis) -> ft.Control:
    volatility = _candidate_volatility(analysis)
    cost = analysis.cost
    return common.tile_grid(
        (
            ("Expected return", None, "No portfolio-level expected return distribution is bound to this candidate", None),
            ("Volatility", None if volatility is None else f"{volatility * 100:.1f}%", "ann." if volatility is not None else "Robust risk evidence is unavailable for this candidate", None),
            ("Max drawdown", None, "Candidate drawdown is not part of the analysis contract", None),
            ("Cost", f"EUR {cost.total_cost_eur:,.2f}", f"{cost.weighted_cost_bps:.1f} bps estimated", None),
        )
    )


def _service_status_tags(analysis: PortfolioAnalysis) -> list[ft.Control]:
    names = ("optimiser", "optimiser_comparison", "factor_risk", "risk", "correlation", "rebalancing", "scenarios", "attribution", "cost")
    labels = {"optimiser_comparison": "optimiser comparison", "factor_risk": "factor risk"}
    tags: list[ft.Control] = []
    for name in names:
        value = analysis.service_evidence.get(name)
        status = str(value.get("status", "unavailable")) if isinstance(value, Mapping) else "unavailable"
        tags.append(Tag(f"{labels.get(name, name)}: {status}", common.tag_kind(status), dense=True))
    return tags


def _service_evidence_card(analysis: PortfolioAnalysis, *, width: float | None) -> ft.Control:
    return _card(
        "Existing service evidence",
        "canonical services · nothing is recalculated here",
        [
            ft.Row(_service_status_tags(analysis), wrap=True, spacing=8, run_spacing=8),
            Note(_portfolio_service_coverage(analysis)),
            Disclosure("service results", _portfolio_service_results(analysis)),
        ],
        width=width,
        key="portfolio.service-evidence",
    )


def _optimiser_card(analysis: PortfolioAnalysis, *, width: float | None) -> ft.Control:
    comparison = analysis.service_evidence.get("optimiser_comparison")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    methods = [item for item in comparison.get("methods", ()) if isinstance(item, Mapping)]
    rows = []
    for item in methods:
        weights = item.get("weights")
        top = (
            ", ".join(f"{name} {float(weight) * 100:.0f}%" for name, weight in sorted(weights.items(), key=lambda pair: -float(pair[1]))[:3])
            if isinstance(weights, Mapping) and weights
            else None
        )
        feasible = item.get("feasible")
        rows.append({
            "method": str(item.get("method", "unavailable")).replace("_", " "),
            "status": Tag("feasible" if feasible else "infeasible" if feasible is False else str(item.get("status", "unavailable")), "ok" if feasible else "bad" if feasible is False else "mute", dense=True),
            "weights": top,
        })
    table = DataTable(
        [TableColumn("method", "Method", flex=3, sortable=False), TableColumn("status", "Status", flex=2, sortable=False), TableColumn("weights", "Largest weights", flex=5, sortable=False)],
        rows, row_height=40, max_visible_rows=6, empty_title="No optimiser comparison",
        empty_reason=str(comparison.get("reason") or "Optimiser comparison evidence is unavailable for this candidate."), key="portfolio.optimiser-comparison",
    )
    return _card("Optimiser comparisons and baselines", "advisory methods and baselines", [table, Disclosure("baselines and constraints", json.dumps(comparison.get("baseline", {}), ensure_ascii=False, sort_keys=True, default=str, indent=2))], width=width)


def _monthly_template(analysis: PortfolioAnalysis, benchmark_registry: object | None) -> object:
    benchmark = analysis.service_evidence.get("benchmark_reference")
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    return build_monthly_decision_template(
        benchmark_reference=benchmark,
        benchmark_registry=benchmark_registry,
        alternatives={
            name: unavailable_monthly_evidence(f"portfolio_{name}_return_projection_unavailable")
            for name in ("basket", "benchmark", "cash", "no_action")
        },
        expected_returns=unavailable_monthly_evidence("portfolio_level_expected_return_distribution_unavailable"),
        optimiser=_monthly_portfolio_optimiser(analysis),
        costs=_monthly_portfolio_costs(analysis),
        events=unavailable_monthly_evidence("event_replay_projection_not_bound_to_portfolio_candidate"),
        forward_evidence=unavailable_monthly_evidence("forward_evidence_snapshot_not_bound_to_portfolio_candidate"),
        paper_outcomes=unavailable_monthly_evidence("paper_account_snapshot_not_bound_to_portfolio_candidate"),
        concentration={
            "status": "partial",
            "reason": "theme_exposure_not_present_in_portfolio_analysis_contract",
            "sector": {
                "status": "available" if analysis.sector_exposure else "unavailable",
                "source_id": "PortfolioAnalysis.sector_exposure",
                "exposures": [{"label": row.bucket, "weight": row.target_weight} for row in analysis.sector_exposure],
            },
            "theme": unavailable_monthly_evidence("theme_exposure_not_present_in_portfolio_analysis_contract"),
            "execution_allowed": False,
        },
        assumptions={
            "status": "available",
            "version": "monthly-decision-assumptions.v1",
            "source_id": analysis.candidate.candidate_id,
            "values": {
                "rebalance_cadence": "monthly",
                "execution_assumption": "next_session",
                "candidate_id": analysis.candidate.candidate_id,
                "candidate_source_revision": analysis.candidate.source_revision,
                "source_snapshot_bound": analysis.snapshot_binding is not None,
            },
            "execution_allowed": False,
        },
        evidence_maturity="unavailable",
        source=f"portfolio_candidate:{analysis.candidate.candidate_id}",
    )


def _monthly_card(analysis: PortfolioAnalysis, benchmark_registry: object | None, *, width: float | None) -> ft.Control:
    lines = monthly_decision_template_lines(_monthly_template(analysis, benchmark_registry))
    return _card(
        "Monthly decision template",
        "basket, benchmark, cash proxy and no action",
        [Note("Advisory comparison context for a monthly basket, canonical benchmark, canonical cash proxy and no-action alternative."), Disclosure("template lines", "\n".join(lines))],
        width=width,
    )


def _rebalance_summary(report: RebalanceReport, full: ft.Control) -> ft.Control:
    trades = [item for item in report.trades if abs(item.trade_value_eur) > 0 or item.status not in {"no_change"}]
    rows: list[ft.Control] = [
        ListRow(
            "info",
            f"{item.instrument_id}: {item.action.replace('buy', 'increase').replace('sell', 'reduce')} EUR {item.trade_value_eur:+,.2f}",
            item.status.replace("_", " "),
            ("draft-only", "mute"),
            last=index == len(trades) - 1,
        )
        for index, item in enumerate(trades)
    ] or [common.text("No rebalance changes are proposed.", 12.5, 400, theme.INK2)]
    return ft.Column([*rows, Disclosure("rebalance workspace", full)], spacing=8)


def _candidate_chips() -> ft.Control:
    return ft.Row(
        [
            evidence_chip("Authority", "portfolio research only", theme.CYAN),
            evidence_chip("Persistence", "local revisioned state", theme.BLUE_GREY),
            evidence_chip("ETF overlap", "direct evidence enabled", theme.AMBER),
            evidence_chip("Execution", "disabled", theme.GREEN),
        ],
        spacing=8,
        run_spacing=8,
        wrap=True,
    )


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def portfolio_page(page: ft.Page | None, state: AppState) -> PageView:
    """Render editable research candidates without creating executable intent."""

    layout = common.make_layout(page)
    ready = [False]
    initial = draft_portfolio_candidate(state.snapshot)
    saved_revision = [0]
    saved_candidate_id: list[str | None] = [None]
    universe = {str(item.id): item for item in state.snapshot.config.universe.etfs if bool(item.enabled)}
    held_ids = _holding_ids(state.snapshot.holdings)
    ui = {"view": "Holdings", "range": "1Y"}
    registry = getattr(state.snapshot, "benchmark_reference_registry", None)

    name = common.text_input(key="portfolio.workspace-name", value=initial.name)
    notional = common.text_input(key="portfolio.analysis-notional", value=f"{initial.analysis_notional_eur:.2f}")
    cash = common.text_input(key="portfolio.cash-weight", value=f"{initial.cash_weight * 100:g}")
    cash_account = common.text_input(key="portfolio.account-cash-target", value=f"{initial.cash_weight * 100:g}")
    target_inputs: dict[str, ft.TextField] = {}

    def target_field(instrument_id: str, value: float) -> ft.TextField:
        return common.text_input(key=f"portfolio.target-weight.{instrument_id}", value=f"{value * 100:.4f}",
            tooltip=_target_label(instrument_id, universe.get(instrument_id), state.snapshot.holdings),
        )

    for instrument_id in sorted(held_ids | {key for key, weight in initial.targets.items() if weight}):
        target_inputs[instrument_id] = target_field(instrument_id, float(initial.targets.get(instrument_id, 0.0)))

    account = common.dropdown(key="portfolio.account", options=_snapshot_values(state.snapshot, "account_id", "default"), value=str(getattr(state.snapshot, "account_id", "default") or "default"))
    portfolio = common.dropdown(key="portfolio.portfolio", options=_snapshot_values(state.snapshot, "portfolio_id", "default"), value=str(getattr(state.snapshot, "portfolio_id", "default") or "default"))
    snapshot = common.dropdown(key="portfolio.snapshot", options=_snapshot_values(state.snapshot, "snapshot_id", "current"), value=str(getattr(state.snapshot, "snapshot_id", "current") or "current"))
    holdings_view = common.dropdown(key="portfolio.holdings-view", options=("direct", "look_through", "combined"), value="combined")
    holdings_view.visible = False  # the Segmented toggle below is the visible control; this keeps the value for the handlers
    mode_host = ft.Container(key="portfolio.holdings-mode-host")
    mode_change: list[Callable[[str], None]] = []

    def build_mode_toggle() -> ft.Control:
        return holdings_mode_toggle(str(holdings_view.value or "combined"), on_change=lambda value: mode_change[0](value) if mode_change else None)

    mode_host.content = build_mode_toggle()
    initial_analysis = analyse_portfolio_candidate(
        state.snapshot, initial, account_id=str(account.value or "default"), portfolio_id=str(portfolio.value or "default"),
        snapshot_id=str(snapshot.value or "current"), holdings_view=str(holdings_view.value or "combined"),
    )
    current_analysis = [initial_analysis]
    holdings_refresh_callbacks: list[Callable[[ft.ControlEvent | None], None]] = []
    initial_status = "Unsaved candidate. Edit weights and select Analyse candidate."
    if state.snapshot.holdings.empty:
        initial_status = "No current holdings are available. Candidate targets can still be analysed from a zero-current baseline."
    status = common.text(initial_status, 12.5, 400, theme.INK2, max_lines=3, key="portfolio.status")
    result_host = ft.Column([_analysis_view(initial_analysis, benchmark_registry=registry)], key="portfolio.results", spacing=12)
    rebalance_host = ft.Column([Note("Select Validate rebalance preview to compare local alternatives.")], key="portfolio.rebalance-results", spacing=12)
    tiles_host = ft.Container(content=_candidate_tiles(initial_analysis))
    overlap_line = common.text(f"ETF overlap status: {initial_analysis.overlap_status}", 12.5, 400, theme.INK2)
    services_host = ft.Container()
    optimiser_host = ft.Container()
    monthly_host = ft.Container()
    targets_host = ft.Column(spacing=0)
    add_choice = common.dropdown(key="portfolio.add-instrument", options=[], value=None)
    below_width = layout.span_width(6)

    def current_weights() -> dict[str, float]:
        selected = select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined"))
        sums: dict[str, float] = {}
        for _, row in selected.iterrows():
            instrument_id = str(row.get("etf_id", row.get("instrument_id", "")))
            sums[instrument_id] = sums.get(instrument_id, 0.0) + float(row.get("current_weight", 0.0))
        return {key: math.fsum([value]) for key, value in sums.items()}

    def render_targets() -> None:
        current = current_weights()
        header = ft.Row(
            [common.text(label, 11, 600, theme.INK3, upper=True, expand=expand, text_align=align) for label, expand, align in (("Instrument", 3, ft.TextAlign.LEFT), ("Current %", 2, ft.TextAlign.RIGHT), ("Target %", 3, ft.TextAlign.RIGHT), ("Change", 2, ft.TextAlign.RIGHT))],
            spacing=12,
        )
        rows: list[ft.Control] = [header]
        for instrument_id in sorted(target_inputs):
            control = target_inputs[instrument_id]
            try:
                change = _percentage(control.value) - current.get(instrument_id, 0.0)
            except ValueError:
                change = None
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(common.text(instrument_id, 13.5, 700, trunc=True), expand=3),
                            ft.Container(common.text(f"{current.get(instrument_id, 0.0) * 100:.1f}", 13, 400, theme.INK2, text_align=ft.TextAlign.RIGHT), expand=2, alignment=ft.Alignment(1, 0)),
                            Well(control, expand=3, height=36, padding=ft.Padding(left=12, top=0, right=12, bottom=0), alignment=ft.Alignment(-1, 0)),
                            ft.Container(common.text("—" if change is None else f"{change * 100:+.1f}".replace("-", "−"), 13, 400, _tone_colour(change), text_align=ft.TextAlign.RIGHT), expand=2, alignment=ft.Alignment(1, 0)),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    height=44,
                )
            )
        targets_host.controls = rows
        remaining = sorted(set(universe) - set(target_inputs))
        add_choice.options = [ft.dropdown.Option(item) for item in remaining]
        add_choice.value = None

    def add_instrument(_event: object = None) -> None:
        chosen = str(add_choice.value or "")
        if chosen and chosen not in target_inputs:
            target_inputs[chosen] = target_field(chosen, 0.0)
            render_targets()
            common.refresh(targets_host)
            common.refresh(add_choice)
            _safe_update(page)

    def values() -> tuple[str, str, dict[str, object], object]:
        targets: dict[str, object] = {}
        selected_ids = _holding_ids(select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined")))
        actionable_ids = set(universe) | selected_ids
        for instrument_id, control in target_inputs.items():
            if instrument_id in actionable_ids:
                targets[instrument_id] = _percentage(control.value)
        return str(name.value or ""), str(notional.value or ""), targets, _percentage(cash.value)

    def sync_cash(source: ft.TextField, other: ft.TextField) -> Callable[[object], None]:
        def changed(_event: object) -> None:
            if other.value != source.value:
                other.value = source.value
                common.refresh(other)

        return changed

    for control, other in ((cash, cash_account), (cash_account, cash)):
        control.on_change = sync_cash(control, other)

    performance = _performance_controller(
        page,
        width=layout.card_body(8, 0, insight=False)[0],
        height=max(layout.card_body(8, 0, insight=False)[1] - 32, 160.0),
        card_width=layout.span_width(8),
        card_height=layout.row_heights[0],
        initial_range="1Y",
        on_series=lambda series, label: render_account() if ready[0] else None,
    )
    risk_body = layout.card_body(6, 1)
    risk_profiles = _portfolio_risk_profiles_block(
        page, state, current_analysis, width=layout.span_width(6), height=layout.row_heights[1], body_size=risk_body
    )

    share_cache: dict[tuple[object, ...], tuple[dict[str, float], str | None]] = {}

    def current_shares() -> tuple[dict[str, float], str | None]:
        selected = select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined"))
        ident = "etf_id" if "etf_id" in selected.columns else "instrument_id"
        key = (str(holdings_view.value), tuple(sorted(zip(selected[ident].astype(str), selected.get("current_weight", pd.Series(dtype=float)).astype(str))))) if not selected.empty else ("empty",)
        if key not in share_cache:
            share_cache[key] = portfolio_view.current_risk_shares(selected, getattr(state.snapshot, "prices", pd.DataFrame()))
        return share_cache[key]

    def lines() -> list[portfolio_view.HoldingLine]:
        selected = select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined"))
        as_of = _as_of_date(getattr(getattr(current_analysis[0], "snapshot_binding", None), "as_of", None))
        return portfolio_view.holding_lines(selected, getattr(state.snapshot, "prices", pd.DataFrame()), current_shares()[0], ui["range"], as_of)

    account_host = ft.Container()
    risk_chart_host = ft.Container()

    def render_account() -> None:
        analysis = current_analysis[0]
        total = _total_value(analysis)
        series = load_portfolio_performance_series(metric="twr_index", date_range="custom" if ui["range"] == "Custom" else ui["range"], aggregation="day", currency="EUR",
                                                    custom_start=str(performance.custom_start.value or "") or None, custom_end=str(performance.custom_end.value or "") or None)
        stats = portfolio_view.series_stats([point.value for point in getattr(series, "points", ())], reason=series.reason)
        invested = [line.weight for line in lines()]
        hhi = portfolio_view.herfindahl(invested)
        cash_weight = analysis.current_cash_weight
        try:
            target = f" · target {format_percent(_percentage(cash.value), decimals=0)}"
        except ValueError:
            target = ""
        change = _signed(stats.range_return)
        change_text = [
            common.text(change, 12.5, 400, _tone_colour(stats.range_return)) if change else common.text("Return unavailable", 12.5, 400, theme.INK2),
            common.text(f" over {ui['range']} · benchmark comparison unavailable" if change else f" ({stats.reason or 'saved valuations are unavailable'})", 12.5, 400, theme.INK2),
        ]
        binding = analysis.snapshot_binding
        as_of = _long_date(getattr(binding, "as_of", None) or state.snapshot.data_report.as_of_date)
        drawdown = _signed(stats.max_drawdown)
        account_host.content = ft.Column(
            [
                ft.Container(Headline(_money(total) or "Unavailable", 58) if total is not None else common.text("Unavailable", 40, 300, theme.INK2), height=72, alignment=ft.Alignment(-1, 0)),
                ft.Row(change_text, spacing=0, tight=True),
                common.tile_grid(
                    (
                        ("Cash", _money(None if total is None else total * cash_weight), f"{cash_weight * 100:.1f}%{target}", None),
                        ("Volatility", None if stats.volatility is None else f"{stats.volatility * 100:.1f}%", "ann." if stats.volatility is not None else stats.reason or "Saved valuations are unavailable", None),
                        ("Max drawdown", drawdown, f"over {ui['range']}" if drawdown else stats.reason or "Saved valuations are unavailable", "neg" if drawdown and stats.max_drawdown and stats.max_drawdown < 0 else None),
                        ("Concentration", None if hhi is None else f"HHI {hhi:.2f}", portfolio_view.hhi_band(hhi) or "No holdings weights are available", None),
                    )
                ),
                ft.Row([Field("Risk profile", control=risk_profiles.selector, expand=True), Field("Cash target (%)", control=cash_account, expand=True)], spacing=12),
                Note("Sandbox values are local estimates. Policy changes are versioned; nothing is sent to a broker."),
            ],
            spacing=theme.SPACE_4,
        )
        snapshot_button.content = common.text(f"as-of {as_of} · EUR ▾", 12, 600, theme.ACC, trunc=True)
        for control in (account_host, snapshot_button):
            common.refresh(control)

    def render_risk_chart() -> None:
        shown = lines()[: portfolio_view.MAX_BARS]
        reason = None
        if not shown:
            reason = "No holdings are available for the selected view."
        elif not any(line.risk_share is not None for line in shown):
            reason = current_shares()[1] or "Risk contributions are unavailable for the selected holdings."
        insight = portfolio_view.risk_insight(shown)
        width, height = layout.card_body(5, 1, insight=True)
        chart = ck.grouped_bar_chart(
            [line.instrument_id for line in shown],
            [
                ck.BarSeries("Weight", [None if line.weight is None else line.weight * 100.0 for line in shown], "blue"),
                ck.BarSeries("Risk contribution", [None if line.risk_share is None else line.risk_share * 100.0 for line in shown], "gold"),
            ],
            x_name="Holding", y_name="Share of total (%)", width=width, height=height, margins=ck.Margins(56, 16, 34, 58),
            unavailable_reason=reason, empty_title="No risk contribution", insight=insight or reason,
        )
        risk_chart_host.content = GlassCard("Risk contribution vs. weight", "% of portfolio · by holding", insight or reason, body=Well(chart, width=width, height=height), width=layout.span_width(5), height=layout.row_heights[1])
        common.refresh(risk_chart_host)

    def render_derived() -> None:
        analysis = current_analysis[0]
        tiles_host.content = _candidate_tiles(analysis)
        overlap_line.value = f"ETF overlap status: {analysis.overlap_status}"
        services_host.content = _service_evidence_card(analysis, width=below_width)
        optimiser_host.content = _optimiser_card(analysis, width=below_width)
        monthly_host.content = _monthly_card(analysis, registry, width=below_width)
        render_targets()
        render_account()
        render_risk_chart()
        for control in (tiles_host, overlap_line, services_host, optimiser_host, monthly_host, targets_host):
            common.refresh(control)

    def refresh(candidate: PortfolioCandidate, *, message: str, colour: str = theme.GREEN) -> None:
        analysis = analyse_portfolio_candidate(
            state.snapshot, candidate, account_id=str(account.value or "default"), portfolio_id=str(portfolio.value or "default"),
            snapshot_id=str(snapshot.value or "current"), holdings_view=str(holdings_view.value or "combined"),
        )
        current_analysis[:] = [analysis]
        result_host.controls = [_analysis_view(analysis, benchmark_registry=registry)]
        if holdings_refresh_callbacks:
            holdings_refresh_callbacks[0](None)
        render_derived()
        status.value = message
        status.color = colour
        state.last_message = message
        common.refresh(result_host)
        common.refresh(status)
        _safe_update(page)

    def analyse(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            candidate = build_portfolio_candidate(
                state.snapshot, name=candidate_name, analysis_notional_eur=candidate_notional, target_weights=targets,
                cash_weight=candidate_cash, holdings_view=str(holdings_view.value or "combined"),
            )
            message = "Candidate analysed from the current local snapshot; execution remains disabled."
            if saved_revision[0]:
                message += " Save to create the next local revision."
            refresh(candidate, message=message)
        except (TypeError, ValueError) as exc:
            status.value = f"Candidate not analysed: {exc}"
            status.color = theme.AMBER
            result_host.controls = [panel(common.text("Candidate results are unavailable until the validation error is corrected.", 12.5, 400, theme.AMBER, max_lines=3))]
            common.refresh(status)
            common.refresh(result_host)
            _safe_update(page)

    def change_mode(value: str) -> None:
        holdings_view.value = value
        mode_host.content = build_mode_toggle()
        common.refresh(mode_host)
        analyse(None)

    mode_change.append(change_mode)

    def rebalance_preview(_event: ft.ControlEvent | None) -> None:
        try:
            _, candidate_notional, targets, candidate_cash = values()
            selected_holdings = select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined"))
            binding = portfolio_snapshot_binding(
                state.snapshot, account_id=str(account.value or "default"), portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"), holdings_view=str(holdings_view.value or "combined"),
            )
            inapplicable = rebalance_inapplicable_instruments(
                state.snapshot, selected_holdings,
                _holding_ids(selected_holdings) | {instrument_id for instrument_id, target_weight in targets.items() if float(target_weight) > 0},
            )
            if inapplicable:
                rebalance_host.controls = [
                    ft.Column(
                        [
                            section_header("Rebalance workspace", "The existing discrete rebalance service is ETF-only; mixed-asset targets remain explicit and are not silently discarded."),
                            common.text("Inapplicable mixed-asset targets: " + ", ".join(inapplicable), 12.5, 400, theme.AMBER, max_lines=3),
                            common.text(
                                f"source=account={binding.account_id} | portfolio={binding.portfolio_id} | snapshot={binding.snapshot_id} | "
                                f"as_of={binding.as_of or 'unavailable'} | view={binding.holdings_view} | checksum={binding.source_checksum[:12]} | execution_allowed=false",
                                11.5, 400, theme.INK2, max_lines=3,
                            ),
                        ],
                        spacing=8,
                    )
                ]
                status.value = "Rebalance preview is inapplicable for mixed-asset targets; no target was dropped and no order was created."
                status.color = theme.AMBER
                state.last_message = status.value
                common.refresh(status)
                common.refresh(rebalance_host)
                _safe_update(page)
                return
            report = build_rebalance_report(
                state.snapshot.config, selected_holdings, targets, target_cash_weight=candidate_cash, portfolio_value_eur=candidate_notional,
                constraints=RebalanceConstraints(cash_buffer_weight=0.02, min_trade_eur=50.0, lot_size=1.0, allow_fractional_lots=False),
            )
            rebalance_host.controls = [_rebalance_summary(report, _rebalance_view(report, source_binding=binding))]
            status.value = "Rebalance preview validated from the current local snapshot; no order or broker action was created."
            status.color = theme.GREEN if report.feasible else theme.AMBER
            state.last_message = status.value
            common.refresh(status)
            common.refresh(rebalance_host)
            _safe_update(page)
        except (TypeError, ValueError) as exc:
            status.value = f"Rebalance preview unavailable: {exc}"
            status.color = theme.AMBER
            rebalance_host.controls = [common.text("Rebalance alternatives are unavailable until the validation error is corrected.", 12.5, 400, theme.AMBER, max_lines=3)]
            common.refresh(status)
            common.refresh(rebalance_host)
            _safe_update(page)

    def say(message: str, colour: str) -> None:
        status.value = message
        status.color = colour
        common.refresh(status)
        _safe_update(page)

    def save(_event: ft.ControlEvent | None) -> None:
        try:
            candidate_name, candidate_notional, targets, candidate_cash = values()
            identity = candidate_id(candidate_name)
            saved = save_portfolio_candidate(
                state.snapshot, name=candidate_name, analysis_notional_eur=candidate_notional, target_weights=targets, cash_weight=candidate_cash,
                expected_revision=saved_revision[0] if saved_candidate_id[0] == identity else 0, account_id=str(account.value or "default"),
                portfolio_id=str(portfolio.value or "default"), snapshot_id=str(snapshot.value or "current"), holdings_view=str(holdings_view.value or "combined"),
            )
            saved_revision[0] = saved.revision
            saved_candidate_id[0] = saved.candidate.candidate_id
            refresh(saved.candidate, message=f"Saved local candidate revision {saved.revision}; no order or proposal was created.")
        except StorageRevisionConflict as exc:
            say(f"Candidate not saved because a newer local revision exists: {exc}", theme.AMBER)
        except (OSError, PortfolioSandboxPersistenceError, TypeError, ValueError) as exc:
            say(f"Candidate not saved: {exc}", theme.AMBER)

    def load(_event: ft.ControlEvent | None) -> None:
        try:
            saved = load_portfolio_candidate(
                state.snapshot, str(name.value or ""), account_id=str(account.value or "default"), portfolio_id=str(portfolio.value or "default"),
                snapshot_id=str(snapshot.value or "current"), holdings_view=str(holdings_view.value or "combined"),
            )
            saved_revision[0] = saved.revision
            saved_candidate_id[0] = saved.candidate.candidate_id
            for instrument_id, weight in dict(saved.candidate.target_weights).items():
                if instrument_id not in target_inputs and float(weight):
                    target_inputs[instrument_id] = target_field(instrument_id, 0.0)
            _apply_candidate(saved.candidate, name, notional, target_inputs, cash)
            cash_account.value = cash.value
            message = f"Loaded local candidate revision {saved.revision}."
            colour = theme.GREEN
            if saved.source_stale:
                message += " Its source binding changed, so derived values were re-evaluated from the current snapshot."
                colour = theme.AMBER
            refresh(saved.candidate, message=message, colour=colour)
        except (OSError, PortfolioSandboxPersistenceError, TypeError, ValueError) as exc:
            say(f"Candidate not loaded: {exc}", theme.AMBER)

    def bound_analysis() -> tuple[PortfolioCandidate, PortfolioAnalysis]:
        candidate_name, candidate_notional, targets, candidate_cash = values()
        candidate = build_portfolio_candidate(
            state.snapshot, name=candidate_name, analysis_notional_eur=candidate_notional, target_weights=targets,
            cash_weight=candidate_cash, holdings_view=str(holdings_view.value or "combined"),
        )
        analysis = analyse_portfolio_candidate(
            state.snapshot, candidate, account_id=str(account.value or "default"), portfolio_id=str(portfolio.value or "default"),
            snapshot_id=str(snapshot.value or "current"), holdings_view=str(holdings_view.value or "combined"),
        )
        return candidate, analysis

    def export(_event: ft.ControlEvent | None) -> None:
        try:
            candidate, analysis = bound_analysis()
            path = export_portfolio_analysis(analysis, ROOT / "data" / "exports" / f"portfolio_sandbox_{candidate.candidate_id}.json")
            state.last_export_path = path
            say(f"Sandbox export written: {path.name}; execution remains disabled.", theme.GREEN)
        except (OSError, TypeError, ValueError) as exc:
            say(f"Sandbox export unavailable: {exc}", theme.AMBER)

    def draft_proposal(_event: ft.ControlEvent | None) -> None:
        try:
            _, analysis = bound_analysis()
            handoff = draft_portfolio_proposal(state.snapshot, analysis)
            say(f"Draft hand-off prepared for ISSUE-0130 ({len(handoff['changes'])} changes); no proposal or order was created.", theme.GREEN)
        except (TypeError, ValueError) as exc:
            say(f"Draft hand-off unavailable: {exc}", theme.AMBER)

    def draft_holdings_proposal(_event: ft.ControlEvent | None) -> None:
        binding = current_analysis[0].snapshot_binding
        if (
            binding is None
            or binding.account_id != str(account.value or "default")
            or binding.portfolio_id != str(portfolio.value or "default")
            or binding.snapshot_id != str(snapshot.value or "current")
            or binding.holdings_view != str(holdings_view.value or "combined")
        ):
            say("Proposal hand-off blocked: analyse the currently selected portfolio snapshot before using the holdings action.", theme.AMBER)
            return
        draft_proposal(_event)

    def reset_current(_event: ft.ControlEvent | None) -> None:
        selected_holdings = select_holdings_view(state.snapshot.holdings, str(holdings_view.value or "combined"))
        current_lines: dict[str, list[float]] = {instrument_id: [] for instrument_id in target_inputs}
        for _, row in selected_holdings.iterrows():
            instrument_id = str(row.get("etf_id", row.get("instrument_id", "")))
            if instrument_id in current_lines:
                current_lines[instrument_id].append(float(row.get("current_weight", 0.0)))
        current = {instrument_id: math.fsum(sorted(weights)) for instrument_id, weights in current_lines.items()}
        for instrument_id, control in target_inputs.items():
            control.value = f"{current[instrument_id] * 100:.4f}"
        cash.value = f"{max(0.0, 1.0 - sum(current.values())) * 100:.4f}"
        cash_account.value = cash.value
        render_targets()
        say("Controls reset to the current local allocation; select Analyse candidate to recompute.", theme.MUTED)
        common.refresh(targets_host)

    # --- first row -----------------------------------------------------------------------------------------------
    snapshot_button = common.menu_button("as-of", lambda _e: None)
    snapshot_popover = common.Popover(
        "Account snapshot",
        ft.Column(
            [
                common.text("Selected portfolio snapshot", 12.5, 600),
                Field("Account snapshot", control=account),
                Field("Portfolio snapshot", control=portfolio),
                Field("As-of snapshot", control=snapshot),
                common.text("Holdings view", 11, 600, theme.INK3, upper=True),
                mode_host,
                holdings_view,
                Note("Direct and look-through holdings remain separate; complete ETF look-through is unavailable until ISSUE-0022."),
            ],
            spacing=12,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=320,
    )
    snapshot_button.on_click = snapshot_popover.toggle
    render_account()
    account_body = ft.Container(account_host, width=layout.card_body(4, 0, insight=False)[0], height=layout.card_body(4, 0, insight=False)[1])
    account_card = common.with_popovers(
        _card("Account snapshot", "", ft.Column([account_body], scroll=ft.ScrollMode.AUTO), width=layout.span_width(4), height=layout.row_heights[0], menu=snapshot_button),
        layout.span_width(4), layout.row_heights[0], snapshot_popover,
    )

    # --- second row views -----------------------------------------------------------------------------------------
    holdings_size = layout.card_body(7, 1)
    holdings_card = _portfolio_holdings_block(
        page, state, current_analysis, draft_holdings_proposal, holdings_refresh_callbacks,
        range_getter=lambda: ui["range"], shares_getter=lambda: current_shares()[0],
        width=layout.span_width(7), height=layout.row_heights[1], body_size=holdings_size,
    )
    render_risk_chart()
    goals_card = _portfolio_goals_block(page, state, current_analysis, width=layout.span_width(6), height=layout.row_heights[1], body_size=layout.card_body(6, 1, insight=False))

    candidate_size = layout.card_body(7, 1, insight=False)
    render_targets()
    candidate_buttons = ft.Column(
        [
            ft.Row(
                [
                    _workflow_button("Analyse candidate", key_name="portfolio.analyse", on_click=analyse, primary=True),
                    _workflow_button("Validate rebalance preview", key_name="portfolio.rebalance-preview", on_click=rebalance_preview),
                    _workflow_button("Save revision", key_name="portfolio.save", on_click=save),
                ],
                spacing=12,
            ),
            ft.Row(
                [
                    _workflow_button("Load latest", key_name="portfolio.load", on_click=load),
                    _workflow_button("Export evidence", key_name="portfolio.export", on_click=export),
                    _workflow_button("Prepare ISSUE-0130 draft", key_name="portfolio.draft-proposal", on_click=draft_proposal),
                    ft.TextButton(content=common.text("Reset to current", 13, 600, theme.ACC), key="portfolio.reset-current", on_click=reset_current),
                ],
                spacing=12,
            ),
        ],
        spacing=8,
    )
    weights_body = ft.Container(
        ft.Column(
            [
                ft.Row([Field("Candidate name", control=name, expand=True), Field("Analysis notional (EUR)", control=notional, expand=True), Field("Cash target (%)", control=cash, expand=True)], spacing=12),
                targets_host,
                ft.Row([Field("Add instrument", control=add_choice, expand=True), ft.Container(Button.secondary("Add instrument", add_instrument), padding=ft.Padding(left=0, top=19, right=0, bottom=0))], spacing=12),
                candidate_buttons,
                status,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=candidate_size[0], height=candidate_size[1],
    )
    weights_card = _card("Candidate weights", f"{len(target_inputs)} instruments · weights in %", weights_body, width=layout.span_width(7), height=layout.row_heights[1])
    result_size = layout.card_body(5, 1, insight=False)
    result_body = ft.Container(
        ft.Column([_candidate_chips(), tiles_host, overlap_line, rebalance_host, Disclosure("full candidate analysis", result_host)], spacing=12, scroll=ft.ScrollMode.AUTO),
        width=result_size[0], height=result_size[1],
    )
    result_card = _card("Candidate result", "advisory context", result_body, width=layout.span_width(5), height=layout.row_heights[1])

    def view_row(cells: list[tuple[ft.Control, int]], visible: bool) -> ft.Control:
        if layout.narrow:
            column = ft.Column([ft.Container(card, height=layout.row_heights[1]) for card, _ in cells], spacing=common.GAP)
            column.visible = visible
            return column
        row = ft.Row([card for card, _ in cells], spacing=common.GAP, vertical_alignment=ft.CrossAxisAlignment.START)
        host = ft.Container(row, height=layout.row_heights[1], visible=visible)
        return host

    views = {
        "Holdings": view_row([(holdings_card, 7), (risk_chart_host, 5)], True),
        "Policy": view_row([(risk_profiles.card, 6), (goals_card, 6)], False),
        "Candidates": view_row([(weights_card, 7), (result_card, 5)], False),
    }

    def select_view(label: str) -> None:
        ui["view"] = label
        for key, control in views.items():
            control.visible = key == label
            common.refresh(control)

    # --- below the fold ---------------------------------------------------------------------------------------------
    render_derived_holders = (services_host, optimiser_host, monthly_host)
    services_host.content = _service_evidence_card(initial_analysis, width=below_width)
    optimiser_host.content = _optimiser_card(initial_analysis, width=below_width)
    monthly_host.content = _monthly_card(initial_analysis, registry, width=below_width)
    forecast_card = _portfolio_forecast_block(page, state, current_analysis, width=below_width)
    calendar_card = _portfolio_calendar_block(page, state, initial_analysis, width=below_width)
    fixed_card = _portfolio_fixed_income_returns_block(state, width=below_width)
    ladder_card = _portfolio_maturity_ladder_block(state, initial_analysis, width=below_width)

    def pair(left: ft.Control, right: ft.Control) -> ft.Control:
        if layout.narrow:
            return ft.Column([left, right], spacing=common.GAP)
        return ft.Row([left, right], spacing=common.GAP, vertical_alignment=ft.CrossAxisAlignment.START)

    below = [
        *views.values(),
        pair(forecast_card, calendar_card),
        pair(fixed_card, ladder_card),
        pair(services_host, optimiser_host),
        pair(monthly_host, ft.Container(width=below_width)),
    ]
    del render_derived_holders
    grid = common.grid(layout, [[(account_card, 4), (performance.card, 8)]], below=below)

    # --- range segments and the custom-range popover -----------------------------------------------------------------
    def apply_custom(_event: object = None) -> None:
        ui["range"] = "Custom"
        performance.set_range("Custom")
        custom_popover.toggle()
        render_account()
        holdings_refresh()

    def holdings_refresh() -> None:
        if holdings_refresh_callbacks:
            holdings_refresh_callbacks[0](None)
        render_risk_chart()

    custom_popover = common.Popover(
        "Custom range",
        ft.Column(
            [
                Field("Custom start (YYYY-MM-DD)", control=performance.custom_start),
                Field("Custom end (YYYY-MM-DD)", control=performance.custom_end),
                Button.primary("Apply", apply_custom),
            ],
            spacing=12,
            tight=True,
        ),
        width=300, top=0, right=0,
    )

    def select_range(label: str) -> None:
        if label == "Custom":
            if not custom_popover.control.visible:
                custom_popover.toggle()
            return
        ui["range"] = label
        performance.set_range(label)
        holdings_refresh()
        render_account()
        _safe_update(page)

    ready[0] = True
    render_derived()
    body = ft.Stack([grid, custom_popover.control], expand=True)
    groups = (SegmentGroup("view", _VIEWS, ui["view"], select_view), SegmentGroup("range", _RANGES, "1Y", select_range))
    return common.page_view("Portfolio Sandbox", "Account snapshot · analysis only, no orders", body, groups)


def _analysis_view(analysis: PortfolioAnalysis, *, benchmark_registry: object | None = None) -> ft.Control:
    cost = analysis.cost
    binding = analysis.snapshot_binding
    source_text = "snapshot binding unavailable"
    if binding is not None:
        source_text = (
            f"account={binding.account_id} | portfolio={binding.portfolio_id} | snapshot={binding.snapshot_id} | "
            f"as_of={binding.as_of or 'unavailable'} | view={binding.holdings_view} | source_checksum={binding.source_checksum[:12]}"
        )
    cards = ft.Row(
        [
            KpiTile("Current value", f"EUR {analysis.current_value_eur:,.0f}", expand=True),
            KpiTile("Current cash", f"{analysis.current_cash_weight:.1%}", expand=True),
            KpiTile("Estimated rebalance cost", f"EUR {cost.total_cost_eur:,.2f}", f"{cost.weighted_cost_bps:.1f} bps", expand=True),
        ],
        spacing=theme.SPACE_3,
    )

    allocation = _table(
        ("Instrument", "Current", "Target", "Target - current", "Signed notional", "Band", "Capability", "Why not"),
        [
            (
                f"{row.instrument_id} · {row.name}", f"{row.current_weight:.2%}", f"{row.target_weight:.2%}", f"{row.drift:+.2%}",
                f"EUR {row.signed_notional_eur:+,.2f}", row.drift_status.replace("_", " "),
                f"{row.asset_type}: {row.capability_status}", row.why_not or row.marginal_effect,
            )
            for row in analysis.allocations
        ],
    )
    benchmark = analysis.service_evidence.get("benchmark_reference")
    profile = analysis.service_evidence.get("profile_relative")
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    benchmark_blockers = ", ".join(str(item) for item in benchmark.get("blockers", ())) or "none"
    profile_blockers = ", ".join(str(item) for item in profile.get("blockers", ())) or "none"
    benchmark_provenance = benchmark.get("provenance", {})
    benchmark_registry_hash = benchmark.get("registry_hash")
    if isinstance(benchmark_provenance, dict):
        benchmark_registry_hash = benchmark_provenance.get("registry_hash", benchmark_registry_hash)
    selected_identity_parts: list[str] = []
    for label, key in (("benchmark", "benchmark"), ("cash", "cash"), ("peer", "peer_set")):
        selected = benchmark.get(key, {})
        if isinstance(selected, dict) and selected.get("status") == "available":
            selected_identity_parts.append(
                f"{label}={selected.get('id')}@{selected.get('version')} digest:{selected.get('content_hash')}"
            )
    reference_identity_parts = [
        f"{item.get('id')}@{item.get('version')} digest:{item.get('content_hash')}"
        for item in benchmark.get("references", ())
        if isinstance(item, dict)
    ]
    selected_identities = " | ".join(selected_identity_parts) or "unavailable"
    reference_identities = " | ".join(reference_identity_parts) or "unavailable"
    anchor_resolution = profile.get("anchor_resolution", {})
    anchor_resolution = anchor_resolution if isinstance(anchor_resolution, dict) else {}
    reference_evidence = panel(
        ft.Column(
            [
                section_header(
                    "Benchmark and profile reference evidence",
                    "Canonical status, blockers and provenance remain visible; unavailable evidence never becomes an implicit comparison.",
                ),
                Disclosure("benchmark_reference source", (
                    "benchmark_reference: "
                    f"status={benchmark.get('status', 'unavailable')} | blockers={benchmark_blockers} | "
                    f"selected={selected_identities} | references={reference_identities} | "
                    f"provenance=registry_hash:{benchmark_registry_hash or 'unavailable'}"
                )),
                Disclosure("profile_relative source", (
                    "profile_relative: "
                    f"status={profile.get('profile_relative_status', profile.get('status', 'unavailable'))} | blockers={profile_blockers} | "
                    f"canonical_share_class_id:{anchor_resolution.get('canonical_share_class_id') or 'unavailable'} "
                    f"listing_id:{anchor_resolution.get('listing_id') or 'unavailable'} "
                    f"effective_date:{anchor_resolution.get('effective_date') or 'unavailable'} "
                    f"knowledge_cutoff:{anchor_resolution.get('knowledge_cutoff') or 'unavailable'} | "
                    f"provenance=anchor_digest:{anchor_resolution.get('anchor_digest') or 'unavailable'} "
                    f"conversion_digest:{anchor_resolution.get('conversion_digest') or 'unavailable'} "
                    f"resolution_digest:{anchor_resolution.get('resolution_digest') or 'unavailable'}"
                )),
            ]
        )
    )
    monthly_template = _monthly_template(analysis, benchmark_registry)
    monthly_decision_evidence = panel(
        ft.Column(
            [
                section_header(
                    "Monthly decision template",
                    "Advisory comparison context for a monthly basket, canonical benchmark, canonical cash proxy and no-action alternative.",
                ),
                ft.Text("\n".join(monthly_decision_template_lines(monthly_template)), color=theme.MUTED, selectable=True),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Selected portfolio snapshot", "Every before/after result is bound to this local source identity; live ledger state is never mutated."),
                        Disclosure("Snapshot source identity", source_text),
                        _src_note("Direct and look-through holdings remain separate; complete ETF look-through is unavailable until ISSUE-0022."),
                    ]
                )
            ),
            cards,
            panel(
                ft.Column(
                    [
                        section_header("Current versus candidate", "Positive signed notional means an increase for analysis; it is not an instruction."),
                        allocation,
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            _allocation_donut_panel(analysis),
            ft.Row(
                [
                    _exposure_table("Sector exposure", analysis.sector_exposure),
                    _exposure_table("Region exposure", analysis.region_exposure),
                    _exposure_table("Currency exposure", analysis.currency_exposure),
                ],
                spacing=12,
                wrap=True,
            ),
            overlap_evidence_panel(analysis.overlap, key="portfolio.etf-overlap"),
            _holding_evidence_view(analysis),
            _constraint_evidence_view(analysis),
            reference_evidence,
            monthly_decision_evidence,
            panel(
                ft.Column(
                    [
                        section_header("Existing service evidence", "What-if targets are passed to canonical factor-risk, covariance, optimiser, rebalance, scenario and attribution services; no calculation is duplicated here."),
                        ft.Text(
                            " | ".join(
                                f"{name}={value.get('status', 'unavailable')}"
                                for name, value in analysis.service_evidence.items()
                                if isinstance(value, dict)
                                and name in {"optimiser", "optimiser_comparison", "factor_risk", "risk", "correlation", "rebalancing", "scenarios", "attribution", "cost"}
                            ) or "service evidence unavailable",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                        Disclosure("Method coverage", _portfolio_service_coverage(analysis)),
                        _portfolio_service_results(analysis),
                    ]
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Limitations and warnings", "Warnings remain visible and do not grant authority."),
                        ft.Text("\n".join(analysis.warnings or ("No candidate concentration warnings.",)), color=theme.MUTED, selectable=True),
                        Disclosure("Boundary flags", f"source_stale={str(analysis.source_stale).lower()} | overlap={analysis.overlap_status} | proposal_boundary=ISSUE-0130:draft-only | execution_allowed=false"),
                    ]
                )
            ),
        ],
        spacing=12,
    )


def _service_value(value: object) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "unavailable"
    return str(value)


def _service_result_controls(label: str, value: object) -> list[ft.Control]:
    """Display canonical projections, retaining table axes and every disclosed row."""
    if isinstance(value, Mapping):
        if {"columns", "index", "data"}.issubset(value):
            table = _table(
                (str(value.get("index_name") or "row"), *[str(column) for column in value["columns"]]),
                [(_service_value(index), *[_service_value(item) for item in row]) for index, row in zip(value["index"], value["data"], strict=True)],
            )
            return [ft.Text(label, color=theme.TEXT), table]
        controls = []
        for key, item in value.items():
            controls.extend(_service_result_controls(f"{label} / {key}", item))
        return controls or [ft.Text(f"{label}: unavailable", color=theme.MUTED)]
    if isinstance(value, (list, tuple)):
        return [control for index, item in enumerate(value, start=1)
                for control in _service_result_controls(f"{label} [{index}]", item)] or [ft.Text(f"{label}: none reported", color=theme.MUTED)]
    return [_src_note(f"{label}: {_service_value(value)}")]


def _portfolio_service_results(analysis: PortfolioAnalysis) -> ft.Control:
    titles = {"optimiser_comparison": "Optimiser comparisons and baselines", "optimiser": "Selected optimiser",
              "factor_risk": "Factor risk and contributions", "risk": "Covariance and risk contributions",
              "correlation": "Correlation matrix",
              "rebalancing": "Rebalance and tax evidence", "scenarios": "Scenario results", "attribution": "Performance attribution", "cost": "Cost evidence"}
    controls: list[ft.Control] = []
    for name, title in titles.items():
        result = analysis.service_evidence.get(name)
        if not isinstance(result, Mapping):
            result = {"status": "unavailable", "reason": "canonical service result missing"}
        for warning in result.get("warnings", ()):
            controls.append(_src_note(f"{title}: {warning}"))
        if result.get("reason"):
            controls.append(_src_note(f"{title}: {result['reason']}"))
        controls.append(ft.ExpansionTile(
            title=ft.Text(title), subtitle=ft.Text(str(result.get("status", "unavailable"))),
            maintain_state=True, expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[ft.Column(_service_result_controls(title, result), height=320, scroll=ft.ScrollMode.AUTO)],
        ))
    return ft.Column(controls, spacing=theme.SPACE_2)


def _portfolio_service_coverage(analysis: PortfolioAnalysis) -> str:
    """Summarise method/coverage evidence without hiding unavailable inputs."""

    comparison = analysis.service_evidence.get("optimiser_comparison")
    methods = comparison.get("methods", ()) if isinstance(comparison, dict) else ()
    factor = analysis.service_evidence.get("factor_risk")
    risk = analysis.service_evidence.get("risk")
    scenario = analysis.service_evidence.get("scenarios")
    attribution = analysis.service_evidence.get("attribution")
    factor_coverage = factor.get("coverage", {}) if isinstance(factor, dict) else {}
    risk_coverage = risk.get("coverage", {}) if isinstance(risk, dict) else {}
    scenario_count = len(scenario.get("results", ())) if isinstance(scenario, dict) else 0
    factor_status = (
        factor_coverage.get("status", factor.get("status", "unavailable"))
        if isinstance(factor_coverage, dict) and isinstance(factor, dict)
        else "unavailable"
    )
    risk_status = (
        risk_coverage.get("status", risk.get("status", "unavailable"))
        if isinstance(risk_coverage, dict) and isinstance(risk, dict)
        else "unavailable"
    )
    return (
        f"methods={len(methods) if isinstance(methods, (list, tuple)) else 0} | "
        f"factor_coverage={factor_status} | "
        f"covariance_coverage={risk_status} | "
        f"scenarios={scenario_count} | attribution={attribution.get('status', 'unavailable') if isinstance(attribution, dict) else 'unavailable'} | execution_allowed=false"
    )


def _monthly_portfolio_optimiser(analysis: PortfolioAnalysis) -> dict[str, object]:
    value = analysis.service_evidence.get("optimiser")
    if not isinstance(value, dict) or value.get("status") == "unavailable":
        return unavailable_monthly_evidence("canonical_optimiser_solution_unavailable")
    return {
        "status": "partial",
        "reason": "solver_binding_diagnostics_not_exposed_by_portfolio_service_projection",
        "model_version": value.get("model_version"),
        "method": value.get("method"),
        "source_id": "PortfolioAnalysis.service_evidence.optimiser",
        "constraints": {
            "status": "available",
            "source_id": "PortfolioAnalysis.constraints",
            "rows": [
                {
                    "name": row.name,
                    "current_value": row.current_value,
                    "target_value": row.target_value,
                    "limit": row.limit,
                    "status": row.status,
                    "reason": row.reason,
                }
                for row in analysis.constraints
            ],
            "execution_allowed": False,
        },
        "solution": {
            "status": value.get("status"),
            "feasible": value.get("feasible"),
            "weights": value.get("weights", {}),
            "warnings": value.get("warnings", []),
            "diagnostics": unavailable_monthly_evidence("solver_binding_diagnostics_unavailable"),
            "execution_allowed": False,
        },
        "execution_allowed": False,
    }


def _monthly_portfolio_costs(analysis: PortfolioAnalysis) -> dict[str, object]:
    cost = analysis.cost
    return {
        "status": "available" if cost.capacity_eur is not None else "partial",
        "reason": "capacity_unavailable" if cost.capacity_eur is None else "complete_portfolio_cost_estimate",
        "model_id": cost.model_id,
        "source_id": "PortfolioCostEstimate",
        "components": [
            {
                "estimate_id": item.estimate_id,
                "instrument_id": item.instrument_id,
                "order_value_eur": item.order_value_eur,
                "cost_eur": item.total_cost_eur,
                "cost_bps": item.total_cost_bps,
                "commission_eur": item.commission_eur,
                "spread_bps": item.spread_bps,
                "slippage_bps": item.slippage_bps,
                "market_impact_bps": item.market_impact_bps,
                "capacity_eur": item.capacity_eur,
                "capacity_status": item.capacity_status,
                "data_quality": item.data_quality,
                "execution_allowed": False,
            }
            for item in cost.estimates
        ],
        "total": {
            "order_value_eur": cost.total_order_value_eur,
            "cost_eur": cost.total_cost_eur,
            "cost_bps": cost.weighted_cost_bps,
        },
        "capacity": {
            "status": "available" if cost.capacity_eur is not None else "unavailable",
            "amount_eur": cost.capacity_eur,
        },
        "assumptions": [
            assumption
            for item in cost.estimates
            for assumption in item.assumptions
        ],
        "execution_allowed": False,
    }


HOLDINGS_MODE_LABELS = (("direct", "Direct"), ("look_through", "Look-through"), ("combined", "Combined"))


def holdings_mode_toggle(selected: str, *, on_change: Callable[[str], object] | None = None) -> ft.Control:
    """Direct / look-through / combined toggle over the existing holdings views."""

    labels = [label for _, label in HOLDINGS_MODE_LABELS]
    by_label = {label: value for value, label in HOLDINGS_MODE_LABELS}
    current = dict(HOLDINGS_MODE_LABELS).get(selected, "Combined")
    return pill_group(
        labels,
        current,
        key="portfolio.holdings-mode",
        label="Holdings mode",
        on_change=(lambda label: on_change(by_label[label])) if on_change else None,
    )


def _allocation_donut_panel(analysis: PortfolioAnalysis) -> ft.Control:
    view = analysis.snapshot_binding.holdings_view if analysis.snapshot_binding is not None else "combined"
    mapped = [row for row in analysis.holdings if row.capability_status == "supported"]
    unmapped_rows = [row for row in analysis.holdings if row.capability_status != "supported"]
    unmapped = sum(row.current_weight for row in unmapped_rows) if analysis.holdings else None
    donut = allocation_donut(
        [(row.instrument_id, row.current_weight) for row in mapped],
        key="portfolio.allocation-donut",
        title=f"Allocation ({view.replace('_', '-')})",
        unknown_weight=report_weight(analysis.overlap, "unknown_weight") if view != "direct" else None,
        unmapped_weight=unmapped,
        unavailable_reason="direct view has no look-through unknown weight" if view == "direct" else "no holdings evidence for this view",
    )
    return panel(ft.Column([section_header("Allocation donut", "Unknown and Unmapped shares are shown explicitly and never redistributed."), donut], spacing=theme.SPACE_2))


def _holding_evidence_view(analysis: PortfolioAnalysis) -> ft.Control:
    table = _table(
        ("Instrument", "View", "Asset", "Current", "Capability", "Reason"),
        [(row.instrument_id, row.holding_view, row.asset_type, f"{row.current_weight:.2%}", row.capability_status, row.capability_reason) for row in analysis.holdings],
    )
    return panel(
        ft.Column(
            [section_header("Direct and look-through holdings", "Lineage, capability and source identity remain explicit; unresolved ETF look-through is not redistributed."), table],
            scroll=ft.ScrollMode.AUTO,
        )
    )


def _constraint_evidence_view(analysis: PortfolioAnalysis) -> ft.Control:
    constraint_lines = [
        f"{item.name}: {item.status} ({item.reason})"
        for item in analysis.constraints
    ]
    why_not_lines = [f"{instrument_id}: {reason}" for instrument_id, reason in analysis.why_not]
    before_after = [f"{instrument_id}: {before:.2%} → {after:.2%}" for instrument_id, before, after in analysis.before_after]
    text = "\n".join(
        [
            "Applicable constraints:",
            *(constraint_lines or ["none available"]),
            "Marginal before/after weight effect:",
            *(before_after or ["none"]),
            "Explicit why-not outcomes:",
            *(why_not_lines or ["none"]),
        ]
    )
    return panel(
        ft.Column(
            [
                section_header("Constraints, marginal effect and why not", "A blocked, inapplicable or no-trade outcome is visible rather than silently omitted."),
                Disclosure("Constraint detail", text),
            ]
        )
    )


def _rebalance_view(report: RebalanceReport, *, source_binding: object | None = None) -> ft.Control:
    alternatives = _table(
        ("Alternative", "Changes", "Drift proxy", "Cost", "Cash"),
        [
            (item.name.replace("_", " ").title(), item.trade_count, f"{item.tracking_error_proxy:.2%}", f"EUR {item.estimated_cost_eur:,.2f}", f"{item.cash_weight:.2%}")
            for item in report.alternatives.values()
        ],
    )
    trades = _table(
        ("Instrument", "Change", "Value", "Status", "Cost"),
        [
            (item.instrument_id, item.action.replace("buy", "increase").replace("sell", "reduce"), f"EUR {item.trade_value_eur:+,.2f}", item.status.replace("_", " "), f"EUR {item.estimated_cost_eur:,.2f}")
            for item in report.trades
            if abs(item.trade_value_eur) > 0 or item.status not in {"no_change"}
        ],
    )
    warning_text = "\n".join(report.warnings or ("No rebalance warnings.",))
    return panel(
        ft.Column(
            [
                section_header("Rebalance workspace", "Compare cost-, cash-, lot- and restriction-aware alternatives. This is advisory evidence only."),
                Disclosure(
                    "Source identity",
                    "source="
                    + (
                        f"account={getattr(source_binding, 'account_id')} | portfolio={getattr(source_binding, 'portfolio_id')} | "
                        f"snapshot={getattr(source_binding, 'snapshot_id')} | as_of={getattr(source_binding, 'as_of') or 'unavailable'} | "
                        f"view={getattr(source_binding, 'holdings_view')} | checksum={getattr(source_binding, 'source_checksum')[:12]}"
                        if source_binding is not None
                        else "unavailable"
                    ),
                ),
                ft.Row(
                    [
                        evidence_chip("Feasibility", "available" if report.feasible else "manual review", theme.GREEN if report.feasible else theme.AMBER),
                        evidence_chip("Cash after change", f"{report.cash_weight:.1%}", theme.BLUE_GREY),
                        evidence_chip("Tax", report.tax_status.replace("_", " "), theme.AMBER),
                        evidence_chip("Execution", "disabled", theme.GREEN),
                    ],
                    wrap=True,
                    spacing=theme.SPACE_2,
                ),
                ft.Text("Alternatives", weight=ft.FontWeight.BOLD, color=theme.TEXT),
                alternatives,
                ft.Text("Proposed changes", weight=ft.FontWeight.BOLD, color=theme.TEXT),
                trades,
                ft.Text(warning_text, color=theme.MUTED, selectable=True),
                Disclosure(
                    "Model assumptions",
                    f"model_version={report.model_version} | lot_policy={report.assumptions['lot_policy']} | min_trade_eur={report.assumptions['min_trade_eur']:.2f} | tax_jurisdiction={report.tax_jurisdiction} | execution_allowed=false",
                ),
            ],
            spacing=theme.SPACE_3,
            scroll=ft.ScrollMode.AUTO,
        )
    )
def _exposure_table(title: str, rows: object) -> ft.Control:
    return panel(
        ft.Column(
            [
                ft.Text(title, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                _table(("Bucket", "Current", "Target"), [(row.bucket, f"{row.current_weight:.1%}", f"{row.target_weight:.1%}") for row in rows]),  # type: ignore[union-attr]
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _percentage(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("weights must be finite percentages")
    try:
        return float(str(value or "").strip()) / 100.0
    except ValueError as exc:
        raise ValueError("weights must be finite percentages") from exc


def _holding_ids(holdings: object) -> set[str]:
    if not hasattr(holdings, "iterrows"):
        return set()
    return {
        instrument_id
        for _, row in holdings.iterrows()  # type: ignore[union-attr]
        if (instrument_id := str(row.get("etf_id", row.get("instrument_id", ""))).strip())
    }


def _target_label(instrument_id: str, configured: object | None, holdings: object) -> str:
    if configured is not None:
        return f"{instrument_id} target (%)"
    asset_types = sorted(
        {
            str(row.get("asset_type", row.get("instrument_type", row.get("asset_class", "unknown"))) or "unknown")
            for _, row in holdings.iterrows()  # type: ignore[union-attr]
            if str(row.get("etf_id", row.get("instrument_id", ""))).strip() == instrument_id
        }
    )
    return f"{instrument_id} target (%) [current {'/'.join(asset_types) or 'unknown'}]"


def _apply_candidate(candidate: object, name: ft.TextField, notional: ft.TextField, targets: dict[str, ft.TextField], cash: ft.TextField) -> None:
    name.value = str(getattr(candidate, "name"))
    notional.value = f"{float(getattr(candidate, 'analysis_notional_eur')):.2f}"
    values = dict(getattr(candidate, "target_weights"))
    for instrument_id, control in targets.items():
        control.value = f"{float(values.get(instrument_id, 0.0)) * 100:.4f}"
    cash.value = f"{float(getattr(candidate, 'cash_weight')) * 100:.4f}"


def _safe_update(page: ft.Page | None) -> None:
    if page is None:
        return
    try:
        page.update()
    except (AssertionError, RuntimeError):
        return


def _snapshot_values(snapshot: object, field: str, fallback: str) -> tuple[str, ...]:
    raw = getattr(snapshot, field, None)
    return (str(raw or fallback),)


__all__ = ["portfolio_page"]
