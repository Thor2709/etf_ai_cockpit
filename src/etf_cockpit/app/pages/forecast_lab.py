from __future__ import annotations

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.pages._lab_style import lab_page, metric_card, model_status_row, panel, section_header
from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.state import AppState
from etf_cockpit.application.forecast_service import build_forecast_lab_workspace


@lab_page("forecast_lab")
def forecast_lab_page(page: ft.Page, state: AppState) -> ft.Control:
    """Render local forecast comparison and validation evidence."""

    report = build_forecast_lab_workspace(state.snapshot.config, state.snapshot.forecasts, state.snapshot.prices)
    models = report["models"]
    model_catalogue = report["model_catalogue"]
    runs = report["runs"]
    splits = report["walk_forward_splits"]
    fold_evaluation = report["walk_forward_evaluation"]
    status = str(report["status"])
    available_models = ", ".join(
        f"{name}={'available' if available else 'unavailable'}"
        for name, available in sorted(state.snapshot.model_status.items())
    ) or "none"
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
            _forecast_run_status(state),
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
            _horizon_panel(models),
            ft.Row(
                [
                    _split_panel(splits, fold_evaluation),
                    panel(
                        ft.Column(
                            [
                                section_header("Governance and availability", "Forecast evidence remains advisory and local-first."),
                                ft.Text(
                                    "Forecasts are low-authority and cannot rescue or upgrade weak deterministic evidence.",
                                    color=theme.MUTED,
                                    selectable=True,
                                ),
                                ft.Text(f"Cached model status: {available_models}", color=theme.MUTED, selectable=True),
                                model_status_row(state.snapshot.model_status, key_prefix="forecast-lab.model-status"),
                                ft.Text("Promotion: shadow_only; execution_allowed=false", color=theme.MUTED, selectable=True),
                                ft.Text("Conformal intervals are diagnostic until minimum prior matured samples exist.", color=theme.MUTED, selectable=True),
                                ft.Text(
                                    "Net value: forecast direction x matured adjusted return less the canonical round-trip cost; "
                                    "unavailable when a cost is unavailable.",
                                    color=theme.MUTED,
                                    selectable=True,
                                ),
                                ft.Text(
                                    "Resource use: duration measured for the displayed forecast run; not_recorded when no matching run measurement exists.",
                                    color=theme.MUTED,
                                    selectable=True,
                                ),
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
            _catalogue_panel(model_catalogue),
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


def _forecast_run_status(state: AppState) -> ft.Control:
    current = getattr(state, "current_activity", None)
    if current is not None and getattr(current, "action_id", None) == "forecasts":
        progress = (
            current.completed_units / current.total_units
            if current.total_units
            else None
        )
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.ProgressRing(width=18, height=18, stroke_width=2, color=theme.CYAN),
                        ft.Text(f"Forecast run in progress: {current.label}", color=theme.TEXT),
                        ft.Text(f"Current step: {current.step}", color=theme.MUTED),
                    ],
                    wrap=True,
                    spacing=10,
                ),
                ft.ProgressBar(value=progress, color=theme.CYAN, bgcolor=theme.SURFACE_2),
            ],
            spacing=6,
        )
    recent = getattr(state, "recent_activity", ()) or ()
    last_forecast = next(
        (entry for entry in reversed(recent) if getattr(entry, "action_id", None) == "forecasts"),
        None,
    )
    if last_forecast is None:
        text = "Forecast run status: not run in this session."
    else:
        text = f"Forecast run status: {last_forecast.status} — {last_forecast.message}"
    return ft.Text(text, color=theme.MUTED, selectable=True)


def _horizon_panel(frame: pd.DataFrame) -> ft.Container:
    rows = []
    for _, row in frame.iterrows():
        value = row["latest_forecast_value"]
        latest_value = "unavailable" if value is None or pd.isna(value) else f"{float(value):+.2%}"
        latest = (
            f"{latest_value} on {row['latest_forecast_date']} "
            f"({row['latest_forecast_etf_id']}, {int(row['latest_forecast_horizon_days'])} trading days; "
            f"{row['latest_forecast_status']})"
        )
        configured = ", ".join(str(value) for value in row["configured_horizons"]) or "none"
        observed = ", ".join(str(value) for value in row["observed_horizons"]) or "none"
        skipped = "; ".join(
            f"{item['horizon_days']} ({item['reason']})" for item in row["skipped_horizons"]
        ) or "none"
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row["model_name"]), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(latest, color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(configured, color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(observed, color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(skipped, color=theme.MUTED, size=12)),
                ]
            )
        )
    body: ft.Control = (
        ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Model")),
                ft.DataColumn(ft.Text("Latest forecast value/date")),
                ft.DataColumn(ft.Text("Configured horizons")),
                ft.DataColumn(ft.Text("Observed horizons")),
                ft.DataColumn(ft.Text("Skipped horizons/reason")),
            ],
            rows=rows,
        )
        if rows
        else ft.Text("No per-model forecast or horizon rows are available.", color=theme.MUTED)
    )
    return panel(
        ft.Column(
            [
                section_header("Latest forecasts and horizon coverage", "Forecast values and skipped horizons are read from the domain report."),
                body,
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


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
                    ft.DataCell(ft.Text(_net_value(row), color=theme.MUTED, size=12)),
                    ft.DataCell(
                        ft.Text(
                            f"{_metric(row['interval_coverage'])} / {_metric(row['conformal_coverage'])}",
                            color=theme.MUTED,
                            size=12,
                        )
                    ),
                    ft.DataCell(ft.Text(str(row["calibration_status"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(_drift(row), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(_runtime(row), color=theme.MUTED, size=12)),
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
                ft.DataColumn(ft.Text("Net value")),
                ft.DataColumn(ft.Text("Coverage int/conf")),
                ft.DataColumn(ft.Text("Calibration")),
                ft.DataColumn(ft.Text("Drift")),
                ft.DataColumn(ft.Text("Runtime")),
            ],
            rows=rows,
        )
    return panel(ft.Column([section_header("Model comparison", "Metrics are descriptive; no model is promoted or made executable."), body], scroll=ft.ScrollMode.AUTO), expand=True)


def _split_panel(frame: pd.DataFrame, evaluation: pd.DataFrame) -> ft.Container:
    if frame.empty:
        return panel(
            ft.Column(
                [
                    section_header("Walk-forward protocol", "Expanding date folds prevent future rows entering an earlier evaluation window."),
                    ft.Text("Not enough distinct forecast dates for a walk-forward split.", color=theme.MUTED),
                ],
                spacing=8,
            ),
            expand=True,
        )
    body = ft.Text("\n".join(f"{r.split_id}: train through {r.train_end}; test {r.test_start}–{r.test_end}" for r in frame.itertuples()), color=theme.MUTED, selectable=True)
    rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(row["split_id"]), color=theme.TEXT, size=12)),
                ft.DataCell(ft.Text(str(row["model_name"]), color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(str(int(row["matured_rows"])), color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(_metric(row["mae"]), color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(_metric(row["directional_accuracy"]), color=theme.MUTED, size=12)),
                ft.DataCell(ft.Text(_net_value(row), color=theme.MUTED, size=12)),
            ]
        )
        for _, row in evaluation.head(40).iterrows()
    ]
    fold_body: ft.Control = (
        ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Fold")),
                ft.DataColumn(ft.Text("Model")),
                ft.DataColumn(ft.Text("Matured")),
                ft.DataColumn(ft.Text("MAE")),
                ft.DataColumn(ft.Text("Direction")),
                ft.DataColumn(ft.Text("Net value")),
            ],
            rows=rows,
        )
        if rows
        else ft.Text("No matured forecasts fall inside a walk-forward test window yet.", color=theme.MUTED)
    )
    return panel(
        ft.Column(
            [
                section_header("Walk-forward protocol", "Expanding date folds prevent future rows entering an earlier evaluation window."),
                body,
                fold_body,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _catalogue_panel(frame: pd.DataFrame) -> ft.Container:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row["display_name"]), color=theme.TEXT, size=12)),
                    ft.DataCell(ft.Text(str(row["family"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(", ".join(row["tasks"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["state"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["licence"]), color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(f"{row['latency_class']}/{row['resource_class']}", color=theme.MUTED, size=12)),
                    ft.DataCell(ft.Text(str(row["promotion_state"]), color=theme.MUTED, size=12)),
                ]
            )
        )
    body: ft.Control = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Model card")),
            ft.DataColumn(ft.Text("Family")),
            ft.DataColumn(ft.Text("Tasks")),
            ft.DataColumn(ft.Text("Availability")),
            ft.DataColumn(ft.Text("Licence")),
            ft.DataColumn(ft.Text("Latency/resources")),
            ft.DataColumn(ft.Text("Promotion")),
        ],
        rows=rows,
    ) if rows else ft.Text("No model cards are registered.", color=theme.MUTED)
    return panel(
        ft.Column(
            [
                section_header("Model cards", "Capabilities, data needs, licence and resource classes are descriptive evidence only."),
                body,
                ft.Text("Unavailable optional packages or weights are shown as N/A; no model is selected on in-sample accuracy.", color=theme.MUTED, selectable=True),
            ],
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )


def _metric(value: object) -> str:
    if value is None or pd.isna(value):
        return "pending"
    return f"{float(value):.3f}"


def _net_value(row: pd.Series) -> str:
    status = str(row["net_value_status"])
    value = row["net_forward_value"]
    if value is None or pd.isna(value):
        return status
    return f"{float(value):+.4f} ({status})"


def _drift(row: pd.Series) -> str:
    score = row["drift_score"]
    if score is None or pd.isna(score):
        return str(row["drift_status"])
    return f"{row['drift_status']} ({float(score):.2f})"


def _runtime(row: pd.Series) -> str:
    runtime = row["runtime_ms"]
    run_id = row.get("resource_run_id")
    run_label = "" if run_id is None or pd.isna(run_id) else f" ({run_id})"
    if runtime is None or pd.isna(runtime):
        return f"{row['resource_status']}{run_label}"
    return f"{float(runtime):.0f} ms{run_label}"
