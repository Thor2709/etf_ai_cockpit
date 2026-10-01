"""Read-only fundamentals evidence surface for the local screener."""

from __future__ import annotations

import math
import json

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, metric_card, panel, section_header
from etf_cockpit.app.formatting import format_number, format_percent
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    FUNDAMENTAL_CLEAN_PATH,
    ScreenFilter,
    ScreenSort,
    build_screen_rows,
    export_screen_csv,
    latest_fundamental_rows,
    load_fundamental_evidence,
    load_fixed_income_screener,
    load_screen,
    query_for_snapshot,
    run_screen,
    save_screen,
    export_table,
)
from etf_cockpit.core.paths import EXPORTS_DIR


_FUNDAMENTAL_FIELDS = (
    ("valuation", "Valuation"),
    ("profitability", "Profitability"),
    ("leverage", "Leverage"),
    ("growth", "Growth"),
    ("shareholder_return", "Shareholder return"),
)


def screener_page(_page: ft.Page, _state: AppState) -> ft.Control:
    """Render and query local evidence without changing score or authority."""

    frame = load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    frame = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if "instrument_id" not in frame.columns:
        frame = pd.DataFrame()
    if "instrument_id" in frame.columns:
        frame = latest_fundamental_rows(frame)

    screen_frame = build_screen_rows(_state.snapshot, frame)
    as_of_date = _state.snapshot.data_report.as_of_date
    decision_time = f"{as_of_date}T23:59:59+00:00" if as_of_date is not None else ""
    fixed_income_result = load_fixed_income_screener(decision_time=decision_time)
    filters: list[ScreenFilter] = []
    current_query = [query_for_snapshot(_state.snapshot, screen_frame)]
    current_result = [run_screen(screen_frame, current_query[0])]

    field_options = sorted(str(field) for field in screen_frame.columns)
    filter_field = ft.Dropdown(
        key="screener.filter.field",
        label="Filter field",
        value="region" if "region" in field_options else (field_options[0] if field_options else None),
        options=[ft.DropdownOption(field) for field in field_options],
        width=210,
        dense=True,
    )
    filter_operator = ft.Dropdown(
        key="screener.filter.operator",
        label="Operator",
        value="eq",
        options=[ft.DropdownOption("eq", "equals"), ft.DropdownOption("min", "minimum"), ft.DropdownOption("max", "maximum")],
        width=140,
        dense=True,
    )
    filter_value = ft.TextField(key="screener.filter.value", label="Value", width=190, dense=True)
    sort_field = ft.Dropdown(
        key="screener.sort.field",
        label="Sort field",
        value="score" if "score" in field_options else (field_options[0] if field_options else None),
        options=[ft.DropdownOption(field) for field in field_options],
        width=210,
        dense=True,
    )
    sort_direction = ft.Dropdown(
        key="screener.sort.direction",
        label="Direction",
        value="descending",
        options=[ft.DropdownOption("descending"), ft.DropdownOption("ascending")],
        width=150,
        dense=True,
    )
    saved_name = ft.TextField(key="screener.saved.name", label="Saved screen name", width=240, dense=True)
    filter_summary = ft.Text("No active filters.", key="screener.filter.summary", color=theme.MUTED, selectable=True)
    result_status = ft.Text(
        f"{current_result[0].total_matched} of {current_result[0].total_input} local instruments shown.",
        key="screener.result.status",
        color=theme.MUTED,
        selectable=True,
    )
    lineage_status = ft.Text(
        _lineage_text(current_query[0]),
        key="screener.lineage",
        color=theme.MUTED,
        size=11,
        selectable=True,
    )
    results_host = ft.Column([_screen_results(current_result[0])], key="screener.results", scroll=ft.ScrollMode.AUTO)

    def refresh() -> None:
        query = query_for_snapshot(
            _state.snapshot,
            screen_frame,
            filters=tuple(filters),
            sort=(
                ScreenSort(
                    str(sort_field.value),
                    descending=sort_direction.value == "descending",
                ),
            )
            if sort_field.value
            else (),
        )
        result = run_screen(screen_frame, query)
        current_query[0] = query
        current_result[0] = result
        results_host.controls = [_screen_results(result)]
        warning = f" Warnings: {', '.join(result.warnings)}." if result.warnings else ""
        result_status.value = f"{result.total_matched} of {result.total_input} local instruments shown.{warning}"
        result_status.color = theme.AMBER if result.warnings else theme.MUTED
        filter_summary.value = _filter_summary(filters)
        lineage_status.value = _lineage_text(query)
        _safe_update(_page)

    def add_filter(_event: ft.ControlEvent | None) -> None:
        try:
            filters.append(ScreenFilter(str(filter_field.value or ""), str(filter_operator.value or "eq"), filter_value.value or ""))  # type: ignore[arg-type]
            filter_value.value = ""
            refresh()
        except ValueError as exc:
            result_status.value = f"Filter not applied: {exc}"
            result_status.color = theme.AMBER
            _safe_update(_page)

    def clear_filters(_event: ft.ControlEvent | None) -> None:
        filters.clear()
        refresh()

    def run_query(_event: ft.ControlEvent | None) -> None:
        try:
            refresh()
        except ValueError as exc:
            result_status.value = f"Screen unavailable: {exc}"
            result_status.color = theme.AMBER
            _safe_update(_page)

    def save_query(_event: ft.ControlEvent | None) -> None:
        try:
            path = save_screen(str(saved_name.value or ""), current_query[0])
            result_status.value = f"Saved local screen revision: {path}"
            result_status.color = theme.GREEN
            _state.last_message = result_status.value
        except (OSError, ValueError) as exc:
            result_status.value = f"Screen not saved: {exc}"
            result_status.color = theme.AMBER
        _safe_update(_page)

    def load_query(_event: ft.ControlEvent | None) -> None:
        try:
            query = load_screen(str(saved_name.value or ""))
            filters[:] = list(query.filters)
            if query.sort:
                sort_field.value = query.sort[0].field
                sort_direction.value = "descending" if query.sort[0].descending else "ascending"
            current_query[0] = query_for_snapshot(
                _state.snapshot,
                screen_frame,
                filters=query.filters,
                sort=query.sort,
                requested_fields=query.requested_fields,
            )
            current_result[0] = run_screen(screen_frame, current_query[0])
            results_host.controls = [_screen_results(current_result[0])]
            filter_summary.value = _filter_summary(filters)
            lineage_status.value = _lineage_text(current_query[0])
            result_status.value = f"Loaded latest saved screen; {current_result[0].total_matched} instruments shown."
            result_status.color = theme.GREEN
        except (OSError, ValueError) as exc:
            result_status.value = f"Screen not loaded: {exc}"
            result_status.color = theme.AMBER
        _safe_update(_page)

    def export_results(_event: ft.ControlEvent | None) -> None:
        try:
            path = export_screen_csv(current_result[0], current_query[0], EXPORTS_DIR / "screener_results.csv")
            _state.last_export_path = path
            _state.last_message = f"Screener CSV exported: {path}"
            result_status.value = _state.last_message
            result_status.color = theme.GREEN
        except (OSError, ValueError) as exc:
            result_status.value = f"Screener export unavailable: {exc}"
            result_status.color = theme.AMBER
        _safe_update(_page)

    rows = _table_rows(frame)
    available_count = sum(_has_five_values(row) for _, row in frame.iterrows()) if not frame.empty else 0
    eligible_count = 0
    if "eligibility" in frame.columns:
        eligible_count = int(frame["eligibility"].astype(str).str.startswith("eligible").sum())
    status = "Canonical rows available" if not frame.empty else "No canonical rows"
    status_colour = theme.GREEN if not frame.empty else theme.AMBER

    controls: list[ft.Control] = [
        panel(
            ft.Column(
                [
                    section_header(
                        "Fundamentals Screener",
                        "Canonical five-section fundamental evidence from the local clean store. Values are context only; they do not alter score weights, actions or broker authority.",
                    ),
                    ft.Row(
                        [
                            evidence_chip("Authority", "advisory/context only", theme.CYAN),
                            evidence_chip("Missing data", "N/A, not invented", theme.AMBER),
                            evidence_chip("Broker execution", "disabled", theme.GREEN),
                            evidence_chip("Source", str(FUNDAMENTAL_CLEAN_PATH), theme.BLUE_GREY),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=10,
            )
        ),
        _summary(
            frame,
            available_count,
            eligible_count,
            status,
            status_colour,
        ),
        _fixed_income_returns_block(_page, fixed_income_result),
        panel(
            ft.Column(
                [
                    section_header(
                        "Reproducible local screen",
                        "Filter and sort the evidence already loaded in this snapshot. Missing dimensions remain explicit; screens never refresh providers, change scores or grant execution authority.",
                    ),
                    ft.Row(
                        [
                            filter_field,
                            filter_operator,
                            filter_value,
                            ft.Button("Add filter", key="screener.filter.add", on_click=add_filter),
                            ft.TextButton("Clear filters", key="screener.filter.clear", on_click=clear_filters),
                        ],
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            sort_field,
                            sort_direction,
                            ft.OutlinedButton("Run screen", key="screener.run", icon=ft.Icons.SEARCH, on_click=run_query),
                        ],
                        wrap=True,
                    ),
                    filter_summary,
                    ft.Row(
                        [
                            saved_name,
                            ft.OutlinedButton("Save revision", key="screener.saved.save", icon=ft.Icons.SAVE, on_click=save_query),
                            ft.OutlinedButton("Load latest", key="screener.saved.load", on_click=load_query),
                            ft.OutlinedButton("Export CSV", key="screener.export.csv", icon=ft.Icons.DOWNLOAD, on_click=export_results),
                        ],
                        wrap=True,
                    ),
                    result_status,
                    lineage_status,
                    results_host,
                ],
                spacing=8,
            )
        ),
        panel(
            ft.Column(
                [
                    section_header(
                        "Instrument fundamentals",
                        "Every canonical row shows valuation, profitability, leverage, growth and shareholder return plus eligibility, provenance, freshness and limitations.",
                    ),
                    ft.Text("executable_authority=false | fundamentals are not an action or broker authority", color=theme.MUTED, size=11, selectable=True),
                    _table_body(frame, rows),
                ],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
            )
        ),
    ]
    return ft.Column(controls, spacing=14, expand=True, scroll=ft.ScrollMode.AUTO)


def _screen_results(result: object) -> ft.Control:
    rows = getattr(result, "rows", ())
    if not rows:
        return ft.Text("No instruments match the current local evidence screen.", color=theme.MUTED, selectable=True)
    fields = ("instrument_id", "region", "sector", "score", "quality", "risk_friction", "momentum", "volatility", "coverage")
    return ft.Row(
        [
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text(field.replace("_", " ").title(), size=11)) for field in fields],
                rows=[
                    ft.DataRow(
                        cells=[ft.DataCell(ft.Text(_display(row.get(field)), size=11, selectable=True)) for field in fields]
                    )
                    for row in rows
                ],
            )
        ],
        scroll=ft.ScrollMode.AUTO,
    )


def _filter_summary(filters: list[ScreenFilter]) -> str:
    if not filters:
        return "No active filters."
    return "Active filters: " + "; ".join(f"{item.field} {item.operator} {item.value}" for item in filters)


def _lineage_text(query: object) -> str:
    return (
        f"as_of={getattr(query, 'as_of', 'unavailable')} | "
        f"universe_revision={getattr(query, 'universe_revision', 'unavailable')} | "
        f"query_checksum={getattr(query, 'checksum', 'unavailable')} | execution_allowed=false"
    )


def _safe_update(page: ft.Page | None) -> None:
    if page is not None:
        page.update()


def _summary(
    frame: pd.DataFrame,
    available_count: int,
    eligible_count: int,
    status: str,
    status_colour: str,
) -> ft.Control:
    total = len(frame)
    cards = [
        metric_card("Canonical instruments", str(total), status, status_colour),
        metric_card("Complete five-section", str(available_count), "all five values present", theme.GREEN if available_count else theme.AMBER),
        metric_card("Score eligible", str(eligible_count), "eligibility is evidence metadata", theme.CYAN if eligible_count else theme.AMBER),
    ]
    for card in cards:
        card.col = {"xs": 12, "sm": 6, "lg": 4}
    return ft.ResponsiveRow(cards, spacing=12, run_spacing=8)


def _table_body(frame: pd.DataFrame, rows: list[ft.DataRow]) -> ft.Control:
    if frame.empty:
        return ft.Text(
            "Fundamentals unavailable: no canonical rows are present at the clean path. This is an explicit no-data state; missing metrics are not inferred or scored.",
            color=theme.MUTED,
            selectable=True,
        )
    return ft.Row(
        [
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT, size=11)) for label in _column_labels()],
                rows=rows,
                data_row_min_height=42,
                data_row_max_height=120,
            )
        ],
        scroll=ft.ScrollMode.AUTO,
    )


def _table_rows(frame: pd.DataFrame) -> list[ft.DataRow]:
    if frame.empty:
        return []
    rows: list[ft.DataRow] = []
    for _, record in frame.iterrows():
        cells = [
            ft.DataCell(ft.Text(_display(record.get("instrument_id")), color=theme.TEXT, size=11, selectable=True)),
            *[
                ft.DataCell(ft.Text(_display(record.get(field)), color=theme.TEXT if _is_value(record.get(field)) else theme.AMBER, size=11, selectable=True))
                for field, _label in _FUNDAMENTAL_FIELDS
            ],
            ft.DataCell(ft.Text(_display(record.get("eligibility"), fallback="unavailable"), color=theme.CYAN, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("source", record.get("source_authority")), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("as_of_date", record.get("as_of")), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("missing_fields"), fallback="none recorded"), color=theme.AMBER if _is_value(record.get("missing_fields")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("warnings"), fallback="none recorded"), color=theme.AMBER if _is_value(record.get("warnings")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("limitations"), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_status"), fallback="unavailable"), color=theme.CYAN if _is_value(record.get("sector_relative_status")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_value"), fallback="unavailable"), color=theme.CYAN if _is_value(record.get("sector_relative_value")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_peer"), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_benchmark"), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_delta"), fallback="unavailable"), color=theme.CYAN if _is_value(record.get("sector_relative_delta")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_limitation"), fallback="No sector-relative comparison evidence supplied."), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text("false", color=theme.GREEN, size=11, selectable=True)),
        ]
        rows.append(ft.DataRow(cells=cells))
    return rows


def _column_labels() -> tuple[str, ...]:
    return (
        "Instrument",
        *(label for _field, label in _FUNDAMENTAL_FIELDS),
        "Eligibility",
        "Source",
        "As of",
        "Missing",
        "Warnings",
        "Limitations",
        "Sector-relative",
        "Sector value",
        "Sector peer",
        "Sector benchmark",
        "Sector delta",
        "Sector limitation",
        "Executable authority",
    )


def _has_five_values(record: pd.Series) -> bool:
    return all(_is_value(record.get(field)) for field, _label in _FUNDAMENTAL_FIELDS)


def _is_value(value: object) -> bool:
    if value is None:
        return False
    if value is pd.NA or value is pd.NaT:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        # Array-like metadata (for example a list of limitations) is valid
        # evidence and is rendered as joined text below.
        return True
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return True


def _display(value: object, *, fallback: str = "N/A") -> str:
    if not _is_value(value):
        return fallback
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value) or fallback
    return str(value)


def _fixed_income_returns_block(
    page: ft.Page | None, result: object
) -> ft.Control:
    projection = result if isinstance(result, dict) else {}
    rows = projection.get("rows")
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    status = ft.Text(
        f"Status: {projection.get('status', 'unavailable')}; "
        f"as of {projection.get('decision_time', 'unavailable')}; "
        f"horizon={projection.get('horizon_days', 'unavailable')} days; "
        f"persistence={projection.get('persistence_status', 'unavailable')}; execution_allowed=false.",
        key="screener.fixed-income.status",
        color=theme.MUTED,
        selectable=True,
    )
    if projection.get("reason_codes"):
        status.value = f"{status.value} Reasons: {', '.join(map(str, projection['reason_codes']))}."
    table_rows = []
    for row in rows:
        q05, q95 = row.get("q05"), row.get("q95")
        distribution = (
            f"q05 {format_percent(q05)}–q95 {format_percent(q95)}"
            if q05 is not None and q95 is not None
            else f"{row.get('forecast_status', 'unavailable')}; q05–q95 unavailable"
        )
        peer_ci = (
            f"peer score {format_percent(row.get('peer_score_ci_q05'))}–"
            f"{format_percent(row.get('peer_score_ci_q95'))}"
            if row.get("peer_score_ci_q05") is not None
            and row.get("peer_score_ci_q95") is not None
            else "unavailable"
        )
        peer_support = (
            f"{row.get('peer_support', 0)}/{row.get('peer_minimum_support', 0)}"
            f" ({row.get('peer_level') or 'no cohort'})"
        )
        table_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row.get("instrument_id", "")), selectable=True)),
                    ft.DataCell(ft.Text(format_percent(row.get("yield_to_worst")))),
                    ft.DataCell(ft.Text(format_number(row.get("duration_years"), decimals=2))),
                    ft.DataCell(ft.Text(format_percent(row.get("baseline_total_return")))),
                    ft.DataCell(ft.Text(format_percent(row.get("risk_adjusted_score")))),
                    ft.DataCell(ft.Text(distribution)),
                    ft.DataCell(ft.Text(str(row.get("liquidity_status", "unavailable")))),
                    ft.DataCell(ft.Text(peer_support)),
                    ft.DataCell(ft.Text(peer_ci)),
                    ft.DataCell(ft.Text(str(row.get("rank") or "N/A"))),
                    ft.DataCell(
                        ft.Text(
                            ", ".join(map(str, row.get("reason_codes", ()))) or "—",
                            selectable=True,
                        )
                    ),
                ]
            )
        )

    export_status = ft.Text(
        "Export includes decomposition, peer, distribution and gate evidence.",
        key="screener.fixed-income.export-status",
        color=theme.MUTED,
        selectable=True,
    )

    def export_fixed_income(_event: ft.ControlEvent) -> None:
        if not rows:
            export_status.value = "Fixed-income audit export unavailable: no rows are available."
            export_status.color = theme.AMBER
            _safe_update(page)
            return
        audit_rows = []
        for row in rows:
            audit = {
                key: row.get(key)
                for key in (
                    "instrument_id",
                    "status",
                    "recommendation",
                    "yield_to_worst",
                    "duration_years",
                    "baseline_total_return",
                    "net_total_return",
                    "risk_penalty",
                    "risk_adjusted_score",
                    "forecast_status",
                    "q05",
                    "q50",
                    "q95",
                    "loss_probability",
                    "beat_cash_probability",
                    "beat_benchmark_probability",
                    "liquidity_status",
                    "peer_support",
                    "peer_minimum_support",
                    "peer_level",
                    "peer_status",
                    "robust_percentile",
                    "peer_score_ci_q05",
                    "peer_score_ci_q95",
                    "rank_stability",
                    "rank_stability_seed",
                    "rank",
                    "top_n",
                    "portfolio_fit",
                    "persisted",
                )
            }
            audit["reason_codes"] = ";".join(map(str, row.get("reason_codes", ())))
            audit["decomposition_json"] = json.dumps(row.get("decomposition"), sort_keys=True)
            audit["peer_cohort_json"] = json.dumps(row.get("peer_cohort"), sort_keys=True)
            audit["distribution_json"] = json.dumps(row.get("distribution"), sort_keys=True)
            audit["source_lineage"] = ";".join(map(str, row.get("source_lineage", ())))
            audit["analysis_snapshot_id"] = projection.get("analysis_snapshot_id")
            audit["decision_time"] = projection.get("decision_time")
            audit["horizon_days"] = projection.get("horizon_days")
            audit["execution_allowed"] = False
            audit_rows.append(audit)
        exported = export_table(
            "fixed_income_screener",
            pd.DataFrame(audit_rows),
            EXPORTS_DIR / "fixed_income_screener.csv",
        )
        if exported.ok:
            export_status.value = f"Fixed-income audit CSV ready: {exported.destination} ({exported.rows} rows)."
            export_status.color = theme.GREEN
        else:
            export_status.value = f"Fixed-income audit export unavailable: {exported.error}; previous output preserved."
            export_status.color = theme.RED
        _safe_update(page)

    columns = (
        "Instrument",
        "YTW",
        "Duration",
        "Baseline",
        "Risk-adjusted",
        "Distribution",
        "Liquidity",
        "Peer support",
        "CI",
        "Rank",
        "Blockers",
    )
    table: ft.Control = (
        ft.DataTable(
            columns=[ft.DataColumn(ft.Text(label)) for label in columns],
            rows=table_rows,
            column_spacing=14,
            data_row_min_height=42,
        )
        if table_rows
        else ft.Text(
            "No saved fixed-income terms are available at this decision time. "
            f"{', '.join(map(str, projection.get('reason_codes', ())))}",
            color=theme.MUTED,
            selectable=True,
        )
    )
    return panel(
        ft.Column(
            [
                section_header(
                    "Fixed-income expected returns",
                    "Deterministic carry, roll and risk scenarios use saved bond evidence. Forecast distributions remain research-only until horizon outcomes are calibrated.",
                ),
                ft.Text(
                    "Advisory only | missing data stays unavailable | no trading authority",
                    color=theme.MUTED,
                    size=11,
                    selectable=True,
                ),
                status,
                ft.Row([table], scroll=ft.ScrollMode.AUTO),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            "Export debt audit",
                            key="screener.fixed-income.export",
                            icon=ft.Icons.DOWNLOAD,
                            on_click=export_fixed_income,
                        ),
                        export_status,
                    ],
                    wrap=True,
                ),
            ],
            spacing=8,
        )
    )


__all__ = ["screener_page"]
