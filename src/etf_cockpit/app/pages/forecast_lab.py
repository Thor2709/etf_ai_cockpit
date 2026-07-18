from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import metric_card, panel, section_header
from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.state import AppState
from etf_cockpit.features.forecast_lab import build_forecast_lab_report


def forecast_lab_page(page: ft.Page, state: AppState) -> ft.Control:
    """Render local forecast comparison and validation evidence."""

    report = build_forecast_lab_report(state.snapshot.forecasts, state.snapshot.prices)
    models = report["models"]
    runs = report["runs"]
    splits = report["walk_forward_splits"]
    status = str(report["status"])
    available_models = ", ".join(
        f"{name}={'available' if available else 'unavailable'}"
        for name, available in sorted(state.snapshot.model_status.items())
    ) or "none"
    configured_horizons = ", ".join(
        str(value) for value in getattr(state.snapshot.config.models, "forecast_horizons_trading_days", ())
    ) or "none"
    observed_horizons = ", ".join(
        str(int(value)) for value in sorted(pd.to_numeric(state.snapshot.forecasts.get("horizon_days"), errors="coerce").dropna().unique())
    ) if not state.snapshot.forecasts.empty and "horizon_days" in state.snapshot.forecasts.columns else "none"
    model_count = len(models)
    forecast_count = int(models["forecast_rows"].sum()) if not models.empty else 0
    matured_count = int(models["matured_rows"].sum()) if not models.empty else 0

    if status != "ok":
        unavailable = ft.Text("\n".join(report["notes"]), color=theme.MUTED, selectable=True)
    else:
        unavailable = ft.Text(
            "\n".join(report["notes"]), color=theme.MUTED, selectable=True
        )

    return ft.Column(
        [
            section_header(
                "Forecast Lab",
                "Local forecast runs, leakage-safe matured outcomes and model-card evidence. No training or promotion is performed here.",
            ),
            ft.Row(
                [
                    ft.ElevatedButton(
                        "Run forecasting models",
                        key="forecast-lab.run",
                        icon=ft.Icons.MODEL_TRAINING,
                        on_click=lambda _event: _run_action(
                            page,
                            state,
                            "Run forecasting models",
                            state.run_forecasting_models,
                        ),
                    ),
                    ft.Text(
                        "Uses the existing guarded local workflow; optional model failures remain visible.",
                        color=theme.MUTED,
                        size=12,
                    ),
                ],
                spacing=10,
            ),
            ft.Row(
                [
                    metric_card("Models", str(model_count), f"status={status}"),
                    metric_card("Forecast rows", str(forecast_count), f"as-of={report.get('as_of_date') or 'unavailable'}"),
                    metric_card("Matured outcomes", str(matured_count), "future adjusted-close observations"),
                    metric_card("Walk-forward splits", str(len(splits)), "evaluation-only date folds"),
                ],
                spacing=12,
            ),
            ft.Row(
                [
                    _run_panel(runs),
                    _model_panel(models),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            ft.Row(
                [
                    _split_panel(splits),
                    panel(
                        ft.Column(
                            [
                                section_header("Governance and availability", "Forecast evidence remains advisory and local-first."),
                                ft.Text(f"Cached model status: {available_models}", color=theme.MUTED, selectable=True),
                                ft.Text(f"Configured horizons (trading days): {configured_horizons}", color=theme.MUTED, selectable=True),
                                ft.Text(f"Observed forecast horizons: {observed_horizons}", color=theme.MUTED, selectable=True),
                                ft.Text("Promotion: shadow_only; execution_allowed=false", color=theme.MUTED, selectable=True),
                                ft.Text("Conformal intervals are diagnostic until minimum prior matured samples exist.", color=theme.MUTED, selectable=True),
                                ft.Text("Resource and latency metadata: not recorded", color=theme.MUTED, selectable=True),
                                unavailable,
                            ],
                            spacing=8,
                        ),
                        expand=True,
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _run_panel(frame: pd.DataFrame) -> ft.Container:
    rows = []
    for _, row in frame.head(20).iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row["run_id"]), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(row["as_of_date"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["models"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["promotion_state"]), color=theme.MUTED, size=12)),
                ]
            )
        )
    if not rows:
        body: ft.Control = ft.Text("No local forecast runs are available.", color=theme.MUTED)
    else:
        body = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Run")),
                ft.DataColumn(ft.Text("As-of")),
                ft.DataColumn(ft.Text("Models")),
                ft.DataColumn(ft.Text("Promotion")),
            ],
            rows=rows,
        )
    return panel(ft.Column([section_header("Experiment runs", "Run identity and model membership are read from local forecast rows."), body], scroll=ft.ScrollMode.AUTO), expand=True)


def _model_panel(frame: pd.DataFrame) -> ft.Container:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row["model_name"]), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(f"{int(row['forecast_rows'])}/{int(row['matured_rows'])}", color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["status_summary"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(_metric(row["mase"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(_metric(row["directional_accuracy"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["calibration_status"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["drift_status"]), color=theme.MUTED, size=12)),
                ]
            )
        )
    if not rows:
        body: ft.Control = ft.Text("No model rows are available for comparison.", color=theme.MUTED)
    else:
        body = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Model")),
                ft.DataColumn(ft.Text("Rows/matured")),
                ft.DataColumn(ft.Text("Statuses")),
                ft.DataColumn(ft.Text("MASE")),
                ft.DataColumn(ft.Text("Direction")),
                ft.DataColumn(ft.Text("Calibration")),
                ft.DataColumn(ft.Text("Drift")),
            ],
            rows=rows,
        )
    return panel(ft.Column([section_header("Model comparison", "Metrics are descriptive; no model is promoted or made executable."), body], scroll=ft.ScrollMode.AUTO), expand=True)


def _split_panel(frame: pd.DataFrame) -> ft.Container:
    if frame.empty:
        body: ft.Control = ft.Text("Not enough distinct forecast dates for a walk-forward split.", color=theme.MUTED)
    else:
        body = ft.Text("\n".join(f"{r.split_id}: train through {r.train_end}; test {r.test_start}–{r.test_end}" for r in frame.itertuples()), color=theme.MUTED, selectable=True)
    return panel(ft.Column([section_header("Walk-forward protocol", "Expanding date folds prevent future rows entering an earlier evaluation window."), body], spacing=8), expand=True)


def _metric(value: object) -> str:
    if value is None or pd.isna(value):
        return "pending"
    return f"{float(value):.3f}"
