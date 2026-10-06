from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, section_header
from etf_cockpit.app.components.kit import glass_panel, table_style
from etf_cockpit.app.components.states import state_panel
from etf_cockpit.app.formatting import format_currency, format_date, format_number, format_percent
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import export_table
from etf_cockpit.core.paths import EXPORTS_DIR
from etf_cockpit.app.workspaces import save_workspace
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.ui_facade import build_simple_instrument_scores


def comparison_page(page: ft.Page, state: AppState) -> ft.Control:
    reference_context = context_from_snapshot(
        state.snapshot,
        purpose="comparison",
        analysis_id=f"comparison:{getattr(state.snapshot, 'universe_revision', 'unknown')}",
    )
    scores = build_simple_instrument_scores(
        state.snapshot.config,
        state.snapshot.signals,
        state.snapshot.forecasts,
        state.snapshot.prices,
        universe_revision=str(getattr(state.snapshot, "universe_revision", "") or state.universe_cache_revision),
        benchmark_data_id=reference_context.benchmark_data_id,
        benchmark_reference=reference_context.projection,
        benchmark_registry=reference_context.registry,
        reference_identity=reference_context.identity,
        peer_member_ids=reference_context.peer_member_ids,
        cash_observation_time=state.snapshot.benchmark_reference_decision_time,
    )
    if not scores:
        return ft.Column(
            [
                state_panel("empty", "Comparison unavailable", "No canonical score rows are available for a comparison.", details="Import or refresh local evidence first; no values are inferred."),
            ],
            expand=True,
        )

    by_id = {score.instrument_key: score for score in scores}
    ids = list(by_id)
    left_id = state.selected_etf if state.selected_etf in by_id else ids[0]
    right_id = next((item for item in ids if item != left_id), left_id)
    options = [ft.dropdown.Option(item, f"{by_id[item].display_id} - {by_id[item].name}") for item in ids]
    left = ft.Dropdown(key="comparison.left", label="Instrument A", value=left_id, options=options, width=300, dense=True)
    right = ft.Dropdown(key="comparison.right", label="Instrument B", value=right_id, options=options, width=300, dense=True)
    result = ft.Column(spacing=8)
    export_status = ft.Text("CSV export writes a local file only; nothing is uploaded.", color=theme.MUTED, selectable=True)
    status = ft.Text("Comparison is local evidence only; no action or order authority is created.", color=theme.MUTED, selectable=True)

    def update_page() -> None:
        update = getattr(page, "update", None)
        if callable(update):
            update()

    def render(_event: ft.ControlEvent | None = None) -> None:
        first = by_id.get(left.value or "")
        second = by_id.get(right.value or "")
        if first is None or second is None:
            result.controls = [state_panel("warning", "Select two instruments", "Both comparison sides must be present in the canonical local score set.")]
            update_page()
            return
        result.controls = [_comparison_table(first, second)]
        update_page()

    def export_csv(_event: ft.ControlEvent) -> None:
        first = by_id.get(left.value or "")
        second = by_id.get(right.value or "")
        if first is None or second is None:
            export_status.value = "CSV export unavailable: select two instruments from the canonical score set."
            export_status.color = theme.AMBER
        else:
            result_ = export_table("comparison_aligned_evidence", comparison_frame(first, second), EXPORTS_DIR / "comparison_aligned_evidence.csv")
            if result_.ok:
                export_status.value = f"Exported {result_.rows} rows locally to {result_.destination}; nothing was uploaded."
                export_status.color = theme.GREEN
            else:
                export_status.value = f"CSV export failed: {result_.error or result_.status}. No file was uploaded."
                export_status.color = theme.AMBER
        update_page()

    def save(_event: ft.ControlEvent) -> None:
        path = save_workspace(
            "latest-comparison",
            {
                "workspace_type": "instrument_comparison",
                "instrument_ids": [left.value, right.value],
                "saved_at_data_date": state.snapshot.data_report.as_of_date,
                "evidence_mode": state.evidence_mode,
                "execution_allowed": False,
            },
        )
        status.value = f"Saved local comparison workspace: {path}"
        update_page()

    left.on_select = render
    right.on_select = render
    render()
    return ft.Column(
        [
            glass_panel(
                ft.Column(
                    [
                        section_header("Comparison workspace", "Compare aligned canonical score, price, return and evidence metadata for two local instruments."),
                        ft.Row(
                            [
                                evidence_chip("Coverage", "shown per row", theme.CYAN),
                                evidence_chip("Units", "EUR and percent", theme.BLUE_GREY),
                                evidence_chip("Authority", "disabled", theme.GREEN),
                            ],
                            wrap=True,
                        ),
                        ft.Row([left, right, ft.OutlinedButton("Save workspace", key="comparison.save-workspace", on_click=save), ft.OutlinedButton("Export CSV", key="comparison.export-csv", icon=ft.Icons.DOWNLOAD, on_click=export_csv)], wrap=True),
                        status,
                        export_status,
                    ],
                    spacing=8,
                ),
                key="comparison.header",
                label="Comparison workspace",
                padding=18,
            ),
            result,
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _comparison_fields() -> tuple[tuple[str, object], ...]:
    return (
        ("Instrument", lambda score: score.display_id),
        ("Name", lambda score: score.name),
        ("Latest price", lambda score: format_currency(score.latest_price)),
        ("Final score", lambda score: format_number(score.final_score_10, decimals=1, unavailable="Unavailable")),
        ("Evidence quality", lambda score: format_number(score.evidence_quality_10, decimals=1, unavailable="Unavailable")),
        ("Risk/friction", lambda score: format_number(score.risk_friction_10, decimals=1, unavailable="Unavailable")),
        ("Period return", lambda score: format_percent(score.instrument_period_return)),
        ("Cash return", lambda score: format_percent(getattr(score, "cash_return", None))),
        ("Excess over cash", lambda score: format_percent(getattr(score, "excess_over_cash", None))),
        ("Cash comparison", lambda score: str(getattr(score, "cash_comparison_status", "unavailable"))),
        ("Data date", lambda score: format_date(score.latest_date)),
        ("Coverage", lambda score: "available" if score.latest_price is not None else "partial/unavailable"),
        ("Execution authority", lambda _score: "disabled"),
    )


def comparison_frame(first: object, second: object) -> pd.DataFrame:
    """Return the displayed comparison rows as strings; missing values stay explicit."""
    records = [
        {"Measure": label, f"A: {first.display_id}": str(value(first)), f"B: {second.display_id}": str(value(second))}
        for label, value in _comparison_fields()
    ]
    return pd.DataFrame(records)


def _comparison_table(first: object, second: object) -> ft.Container:
    rows = []
    for label, value in _comparison_fields():
        rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(label, color=theme.MUTED, selectable=True)), ft.DataCell(ft.Text(str(value(first)), color=theme.TEXT, selectable=True)), ft.DataCell(ft.Text(str(value(second)), color=theme.TEXT, selectable=True))]))
    table = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(column, color=theme.TEXT)) for column in ("Measure", first.display_id, second.display_id)],
        rows=rows,
        data_row_min_height=34,
        data_row_max_height=58,
    )
    return glass_panel(
        ft.Column(
            [
                section_header("Aligned evidence", "Displayed values come from the canonical score objects. Missing values remain explicit and are never filled by UI logic."),
                table_style(table, key="comparison.table", label="Aligned evidence table"),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        key="comparison.evidence",
        label="Aligned evidence",
        padding=18,
    )


__all__ = ["comparison_page"]
