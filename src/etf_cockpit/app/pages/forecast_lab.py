"""Forecast Lab page (FINAL_UI_SPEC 6.6): run card, model comparison, walk-forward protocol, error vs. baseline."""

from __future__ import annotations

import math
import re

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    EmptyState,
    GlassCard,
    ListRow,
    Note,
    ScoreBar,
    TableColumn,
    Tag,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count
from etf_cockpit.app.pages import _p4_common as common
from etf_cockpit.app.pages._p4_common import workflow_button as _workflow_button
from etf_cockpit.app.pages.dashboard import _run_action
from etf_cockpit.app.state import AppState
from etf_cockpit.application.forecast_service import build_forecast_lab_workspace
from etf_cockpit.application.ui_views import forecast_lab as lab_view

_HORIZONS = list(lab_view.HORIZON_LIMITS)
_UNAVAILABLE_MODEL = "Unavailable: optional package or weights not installed"
_MODEL_LINES = (ck.palette.P, *ck.palette.CATEGORICAL[1:])  # accent first; the baseline is neutral grey and dashed
_BASELINE_LINE = ck.palette.BM
_GAP = 16
_COMPARISON_ROW = 78
_CALIBRATION_NOTE = "Calibration compares the stored conformal coverage interval with its 90% target."


def _pct(value: object, decimals: int = 0) -> str | None:
    if value is None or pd.isna(value):
        return None
    return f"{float(value) * 100:.{decimals}f}%"


def _display_name(model_id: str, catalogue: pd.DataFrame) -> str:
    match = catalogue.loc[catalogue["model_id"] == model_id] if not catalogue.empty else catalogue
    if not match.empty:
        return str(match.iloc[0]["display_name"])
    spaced = re.sub(r"(?<=\d)_(?=\d)", ".", model_id).replace("_", " ").strip()
    return spaced.title() or model_id


def _metric(value: object) -> str:
    return "pending" if value is None or pd.isna(value) else f"{float(value):.3f}"


def _net_value(row: pd.Series) -> str:
    status = str(row["net_value_status"])
    value = row["net_forward_value"]
    return status if value is None or pd.isna(value) else f"{float(value):+.4f} ({status})"


def _drift(row: pd.Series) -> str:
    score = row["drift_score"]
    return str(row["drift_status"]) if score is None or pd.isna(score) else f"{row['drift_status']} ({float(score):.2f})"


def _runtime(row: pd.Series) -> str:
    runtime = row["runtime_ms"]
    run_id = row.get("resource_run_id")
    label = "" if run_id is None or pd.isna(run_id) else f" ({run_id})"
    return f"{row['resource_status']}{label}" if runtime is None or pd.isna(runtime) else f"{float(runtime):.0f} ms{label}"


def _calibration_tag(row: pd.Series) -> ft.Control:
    coverage, low, high = (row.get(name) for name in ("conformal_coverage", "conformal_coverage_ci_lower", "conformal_coverage_ci_upper"))
    if coverage is None or pd.isna(coverage) or low is None or pd.isna(low) or high is None or pd.isna(high):
        tag = Tag("n/a", "mute", dense=True)
        tag.tooltip = f"Pending: not enough matured samples. {_CALIBRATION_NOTE}"
        return tag
    inside = float(low) <= lab_view.CONFORMAL_TARGET <= float(high)
    tag = Tag("Good" if inside else "Poor", "ok" if inside else "bad", dense=True)
    tag.tooltip = _CALIBRATION_NOTE
    return tag


def _status_tag(model_id: str, row: pd.Series | None, card: pd.Series | None) -> ft.Control:
    if row is None:
        reason = str(card["state_reason"]) if card is not None else _UNAVAILABLE_MODEL
        tag = Tag("Unavailable", "bad", dense=True)
        tag.tooltip = reason
        return tag
    if lab_view.is_baseline(model_id):
        return Tag("Reference", "mute", dense=True)
    return Tag("Shadow" if str(row["promotion_state"]) == "shadow_only" else "Available", "warn" if str(row["promotion_state"]) == "shadow_only" else "ok", dense=True)


def _net_cell(value: str, sub: str | None) -> ft.Control:
    """Right-aligned value with its status sub-label, like the other numeric columns."""
    parts = [common.text(value, 13.5, 400, text_align=ft.TextAlign.RIGHT, no_wrap=True)]
    if sub:
        parts.append(common.text(sub, 11.5, 400, theme.INK3, text_align=ft.TextAlign.RIGHT, no_wrap=True))
    return ft.Column(parts, spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.END)


def _model_ids(models: pd.DataFrame, catalogue: pd.DataFrame) -> list[str]:
    """Models with stored rows first, then registered optional models that have none (shown as unavailable)."""
    stored = [str(name) for name in models["model_name"]] if not models.empty else []
    optional = (
        [str(row.model_id) for row in catalogue.itertuples() if bool(row.optional) and str(row.model_id) not in stored]
        if not catalogue.empty
        else []
    )
    return [*stored, *[name for name in optional if name in ("timesfm", "toto")]]


def _comparison_rows(ids: list[str], models: pd.DataFrame, catalogue: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model_id in ids:
        stored = models.loc[models["model_name"] == model_id]
        row = stored.iloc[0] if not stored.empty else None
        card_rows = catalogue.loc[catalogue["model_id"] == model_id] if not catalogue.empty else catalogue
        card = card_rows.iloc[0] if not card_rows.empty else None
        kind = "experimental" if card is not None and bool(card["optional"]) else "deterministic baseline"
        if card is None:
            kind = "deterministic baseline" if lab_view.is_baseline(model_id) else "not in the model zoo"
        if row is not None and str(row["resource_status"]) == "measured":
            kind = f"{kind} · Runtime {_runtime(row)}"
        name = (_display_name(model_id, catalogue), kind)
        if row is None:
            rows.append({"model": name, "rows": None, "direction": None, "net": None, "coverage": None, "gap": "", "calibration": Tag("n/a", "mute", dense=True), "status": _status_tag(model_id, None, card)})
            continue
        net = row["net_forward_value"]
        interval, conformal = _pct(row["interval_coverage"]), _pct(row["conformal_coverage"])
        rows.append({
            "model": name,
            "rows": f"{int(row['forecast_rows'])} / {int(row['matured_rows'])}",
            "direction": _pct(row["directional_accuracy"]),
            "net": _net_cell(str(row["net_value_status"]) if net is None or pd.isna(net) else f"{float(net) * 100:+.1f}%".replace("-", "−"), None if net is None or pd.isna(net) else str(row["net_value_status"])),
            "coverage": None if interval is None and conformal is None else f"{interval or '—'} / {conformal or '—'}",
            "gap": "",
            "calibration": _calibration_tag(row),
            "status": _status_tag(model_id, row, card),
        })
    return rows


def _run_status(state: AppState) -> ft.Control:
    current = getattr(state, "current_activity", None)
    if current is not None and getattr(current, "action_id", None) == "forecasts":
        progress = current.completed_units / current.total_units if current.total_units else None
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.ProgressRing(width=18, height=18, stroke_width=2, color=theme.ACC),
                        common.text(f"Forecast run in progress: {current.label}", 13, 400, trunc=True),
                    ],
                    spacing=8,
                ),
                common.text(f"Current step: {current.step}", 12, 400, theme.INK2, trunc=True),
                ScoreBar(progress * 100, maximum=100, decimals=0),
            ],
            spacing=4,
            tight=True,
        )
    recent = getattr(state, "recent_activity", ()) or ()
    last = next((entry for entry in reversed(recent) if getattr(entry, "action_id", None) == "forecasts"), None)
    text = "Forecast run status: not run in this session" if last is None else f"Forecast run status: {last.status} — {last.message}"
    return common.text(text, 13, 400, theme.INK2, max_lines=2)


def _run_card(layout: common.GridLayout, page: object, state: AppState, report: dict, on_governance: object) -> ft.Control:
    models = report["models"]
    forecast_rows = int(models["forecast_rows"].sum()) if not models.empty else None
    matured = int(models["matured_rows"].sum()) if not models.empty else None
    share = f"{matured / forecast_rows * 100:.0f}% of rows" if forecast_rows and matured is not None else "no stored forecast rows"
    splits = report["walk_forward_splits"]
    status = {name: bool(value) for name, value in dict(getattr(state.snapshot, "model_status", {}) or {}).items()}
    available = ", ".join(sorted(_display_name(name, report["model_catalogue"]) for name, ok in status.items() if ok)) or "none"
    tiles = common.tile_grid(
        (
            ("Forecast rows", None if forecast_rows is None else format_count(forecast_rows), f"{len(models)} models" if forecast_rows is not None else "No local forecast rows are stored", None),
            ("Matured outcomes", None if matured is None else format_count(matured), share, None),
            ("Walk-forward splits", format_count(len(splits)) if report["status"] == "ok" else None, "expanding folds" if report["status"] == "ok" else "Not enough forecast dates", None),
            ("Promotion", "Shadow only", "execution off", None),
        )
    )
    run = _workflow_button(
        "Run forecasts",
        key_name="forecast-lab.run",
        on_click=lambda _event: _run_action(page, state, "Run forecasting models", state.run_forecasting_models),
        primary=True,
    )
    inner_w, _inner_h = layout.card_body(4, 0)
    body = ft.Column(
        [
            Note("Optional model failures remain visible. Forecasts are low-authority and cannot rescue or upgrade weak deterministic evidence."),
            ft.Row([run, Button.secondary("Open governance", on_governance, key="forecast-lab.open-governance")], spacing=12),
            _run_status(state),
            tiles,
            Note(f"Conformal intervals are diagnostic until enough matured samples exist. Cached model status: {available}."),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        width=inner_w,
    )
    return GlassCard("Run forecasting models", "guarded local workflow", body=body, width=layout.span_width(4), height=layout.row_heights[0])


def _comparison_card(layout: common.GridLayout, ids: list[str], models: pd.DataFrame, catalogue: pd.DataFrame, reason: str | None) -> ft.Control:
    width, height = layout.card_body(8, 0)
    columns = [
        TableColumn("model", "Model", flex=3, sortable=False),
        TableColumn("rows", "Rows / matured", flex=2, numeric=True, sortable=False),
        TableColumn("direction", "Direction", flex=2, numeric=True, sortable=False),
        TableColumn("net", "Net value", flex=2, numeric=True, sortable=False),
        *([] if layout.narrow else [TableColumn("coverage", "Coverage int/conf", flex=3, numeric=True, sortable=False)]),
        TableColumn("gap", "", width=_GAP, sortable=False),
        TableColumn("calibration", "Calibration", flex=2, sortable=False),
        TableColumn("status", "Status", flex=2, sortable=False),
    ]
    note_height = 24
    if reason or not ids:
        body: ft.Control = EmptyState("No model rows", reason or "No model rows are available for comparison.", height=height)
    else:
        table = DataTable(
            columns,
            _comparison_rows(ids, models, catalogue),
            row_height=_COMPARISON_ROW,
            height=max(height - note_height - 12, 160),
            key="forecast-lab.model-comparison",
        )
        body = ft.Column(
            [table, Note("Net value = forecast direction × matured adjusted return less the canonical round-trip cost.")],
            spacing=12,
            width=width,
        )
    return GlassCard("Model comparison", "descriptive metrics · no model is promoted", body=body, width=layout.span_width(8), height=layout.row_heights[0])


def _fold_legend(width: float, height: float, *, show: bool = True) -> ft.Control:
    """Legend for the two segment colours (chartkit's stacked bar has no legend option; see handoff OPEN)."""
    swatches = [] if not show else [Tag("Train window", "ok", dense=True), Tag("Test fold", "warn", dense=True)]
    return ft.Container(ft.Row(swatches, spacing=8, alignment=ft.MainAxisAlignment.END), width=width, height=height)


def _folds_card(layout: common.GridLayout, folds: lab_view.FoldBars) -> ft.Control:
    width, height = layout.card_body(6, 1, insight=True)
    insight = folds.reason or f"{folds.total} folds; the final test window stays untouched for selection."
    segments = [[ck.Segment(train, "pos"), ck.Segment(test, "gold")] for train, test in zip(folds.train_months, folds.test_months, strict=True)]
    axis_w = theme.SPACE_5
    legend_h = theme.SPACE_5
    chart = ck.horizontal_stacked_bar(
        list(folds.labels), segments, x_name="Months of history", margins=ck.Margins(78, 20, 20, 48), width=width - axis_w, height=height - legend_h - 8,
        unavailable_reason=folds.reason, empty_title="No walk-forward folds", insight=insight,
    )
    return GlassCard("Walk-forward protocol", "expanding train window · test fold", insight, body=ft.Column([_fold_legend(width, legend_h, show=folds.reason is None), ft.Row([ft.Container(common.text("Fold", theme.FONT_XS, 500, theme.INK2), rotate=ft.Rotate(-math.pi / 2), width=axis_w, alignment=ft.Alignment(0, 0)), Well(chart, width=width - axis_w, height=height - legend_h - 8)], spacing=0)], spacing=8), width=layout.span_width(6), height=layout.row_heights[1])


def _error_card(layout: common.GridLayout, series: lab_view.ErrorSeries, names: dict[str, str]) -> ft.Control:
    width, height = layout.card_body(6, 1, insight=True)
    if series.reason:
        insight = series.reason
    else:
        challengers = [name for name in series.lines if name != series.baseline]
        best = [(name, max((h for h, v in zip(series.horizons, series.lines[name], strict=True) if v is not None and v < 0), default=None)) for name in challengers]
        best = [(name, horizon) for name, horizon in best if horizon is not None]
        if best:
            name, horizon = max(best, key=lambda item: item[1])
            insight = f"{names.get(name, name)} beats the baseline up to {horizon} days; beyond that it is not better."
        else:
            insight = "No model beats the baseline at an evaluated horizon."
    lines = [ck.Series(names.get(series.baseline or "", "Baseline"), series.lines.get(series.baseline or "", []), _BASELINE_LINE, 3.0, markers=8, decimals=2, dashed=True)] if series.baseline in series.lines else []
    for index, name in enumerate(name for name in series.lines if name != series.baseline):
        lines.append(ck.Series(names.get(name, name), series.lines[name], _MODEL_LINES[index % len(_MODEL_LINES)], 3.0, markers=8, decimals=2))
    chart = ck.line_chart(
        [str(h) for h in series.horizons], lines, x_name="Horizon (days)", y_name="MAE minus baseline (pp)",
        margins=ck.Margins(56, 16, 34, 48), legend_at="top-right", width=width, height=height,
        unavailable_reason=series.reason, empty_title="No error comparison", insight=insight,
    )
    return GlassCard("Forecast error vs. baseline", "by horizon · below zero = better than baseline", insight, body=Well(chart, width=width, height=height), width=layout.span_width(6), height=layout.row_heights[1])


def _table_or_empty(columns: list[TableColumn], rows: list[dict[str, object]], empty: str, *, key: str, max_rows: int = 10) -> ft.Control:
    return DataTable(columns, rows, row_height=44, max_visible_rows=max_rows, empty_title="Unavailable", empty_reason=empty, key=key)


def _runs_card(layout: common.GridLayout, runs: pd.DataFrame, evaluation: pd.DataFrame) -> ft.Control:
    run_rows = [
        {"run": str(row["run_id"]), "asof": str(row["as_of_date"]), "models": str(row["models"]), "promotion": str(row["promotion_state"])}
        for _, row in runs.head(20).iterrows()
    ]
    fold_rows = [
        {"fold": str(r["split_id"]), "model": str(r["model_name"]), "matured": str(int(r["matured_rows"])), "mae": _metric(r["mae"]), "direction": _metric(r["directional_accuracy"]), "net": _net_value(r)}
        for _, r in evaluation.head(40).iterrows()
    ]
    runs_table = _table_or_empty(
        [TableColumn("run", "Run", flex=3), TableColumn("asof", "As-of", flex=2), TableColumn("models", "Models", flex=4), TableColumn("promotion", "Promotion", flex=2)],
        run_rows, "No local forecast runs are available.", key="forecast-lab.runs",
    )
    fold_table = _table_or_empty(
        [TableColumn("fold", "Fold", flex=2), TableColumn("model", "Model", flex=3), TableColumn("matured", "Matured", flex=2, numeric=True), TableColumn("mae", "MAE", flex=2, numeric=True), TableColumn("direction", "Direction", flex=2, numeric=True), TableColumn("net", "Net value", flex=3, numeric=True)],
        fold_rows, "No matured forecasts fall inside a walk-forward test window yet.", key="forecast-lab.fold-evaluation",
    )
    return GlassCard("Experiment runs", "run identity and model membership from local forecast rows", body=ft.Column([runs_table, Note("Walk-forward fold evaluation"), fold_table], spacing=12), width=layout.span_width(12))


def _horizon_card(layout: common.GridLayout, models: pd.DataFrame) -> ft.Control:
    rows, coverage = [], []
    for _, row in models.iterrows():
        value = row["latest_forecast_value"]
        latest_value = "unavailable" if value is None or pd.isna(value) else f"{float(value):+.2%}"
        latest = (
            f"{latest_value} on {row['latest_forecast_date']} "
            f"({row['latest_forecast_etf_id']}, {int(row['latest_forecast_horizon_days'])} trading days; {row['latest_forecast_status']})"
        )
        configured = ", ".join(str(v) for v in row["configured_horizons"]) or "none"
        observed = ", ".join(str(v) for v in row["observed_horizons"]) or "none"
        skipped = "; ".join(f"{item['horizon_days']} ({item['reason']})" for item in row["skipped_horizons"]) or "none"
        rows.append({"model": str(row["model_name"]), "latest": latest, "configured": configured, "observed": observed, "skipped": skipped})
        total = len(row["configured_horizons"])
        seen = len([h for h in row["observed_horizons"] if h in row["configured_horizons"]])
        coverage.append(
            ft.Row(
                [
                    ft.Container(common.text(str(row["model_name"]), 13, 600, trunc=True), width=180),
                    ScoreBar(None if not total else seen / total * 100.0, maximum=100, decimals=0),
                    common.text(f"{seen} of {total} horizons", 12, 400, theme.INK2, trunc=True),
                ],
                spacing=12,
            )
        )
    table = _table_or_empty(
        [TableColumn("model", "Model", flex=2), TableColumn("latest", "Latest forecast value/date", flex=5), TableColumn("configured", "Configured horizons", flex=2), TableColumn("observed", "Observed horizons", flex=2), TableColumn("skipped", "Skipped horizons/reason", flex=4)],
        rows, "No per-model forecast or horizon rows are available.", key="forecast-lab.horizons",
    )
    body: list[ft.Control] = [table, *coverage]
    return GlassCard("Latest forecasts and horizon coverage", "forecast values and skipped horizons from the domain report", body=body, width=layout.span_width(12))


def _governance_card(layout: common.GridLayout, state: AppState, report: dict, ids: list[str], catalogue: pd.DataFrame, models: pd.DataFrame) -> ft.Control:
    status = dict(getattr(state.snapshot, "model_status", {}) or {})
    stored = set(models["model_name"].astype(str)) if not models.empty else set()
    rows: list[ft.Control] = []
    for index, model_id in enumerate(ids):
        card_rows = catalogue.loc[catalogue["model_id"] == model_id] if not catalogue.empty else catalogue
        available = bool(status.get(model_id, model_id in stored)) if not lab_view.is_baseline(model_id) else True
        reason = (str(card_rows.iloc[0]["state_reason"]) if not card_rows.empty else "Not in the model zoo.") if not available else "Local rows are stored for this model."
        rows.append(
            ListRow("ok" if available else "bad", f"{_display_name(model_id, catalogue)}: {'Available' if available else 'Unavailable'}", reason, ("Available" if available else "Unavailable", "ok" if available else "bad"), last=index == len(ids) - 1, key=f"forecast-lab.model-status.{model_id}")
        )
    notes = [
        Note("Promotion: shadow_only; execution_allowed=false"),
        Note("Conformal intervals are diagnostic until minimum prior matured samples exist."),
        Note("Net value: forecast direction x matured adjusted return less the canonical round-trip cost; unavailable when a cost is unavailable."),
        Note("Resource use: duration measured for the displayed forecast run; not_recorded when no matching run measurement exists."),
        Note("Forecasts are low-authority and cannot rescue or upgrade weak deterministic evidence."),
    ]
    if report["status"] != "ok":
        notes.append(Note("\n".join(report["notes"])))
    return GlassCard("Governance and availability", "forecast evidence remains advisory and local-first", body=[*rows, *notes], width=layout.span_width(12), key="forecast-lab.governance")


def _cards_card(layout: common.GridLayout, catalogue: pd.DataFrame, models: pd.DataFrame) -> ft.Control:
    rows = []
    for _, row in catalogue.iterrows():
        stored = models.loc[models["model_name"] == row["model_id"]]
        resources = f"{row['latency_class']}/{row['resource_class']}"
        if not stored.empty:
            resources += f" · Runtime {_runtime(stored.iloc[0])}"
        rows.append({
            "card": str(row["display_name"]), "family": str(row["family"]), "tasks": ", ".join(row["tasks"]),
            "state": Tag("Available" if str(row["state"]) == "available" else "Unavailable", "ok" if str(row["state"]) == "available" else "bad", dense=True),
            "licence": str(row["licence"]), "resources": resources,
        })
    table = _table_or_empty(
        [TableColumn("card", "Model card", flex=3), TableColumn("family", "Family", flex=2), TableColumn("tasks", "Tasks", flex=3), TableColumn("state", "Availability", flex=2), TableColumn("licence", "Licence", flex=3), TableColumn("resources", "Latency/resources", flex=4)],
        rows, "No model cards are registered.", key="forecast-lab.model-cards", max_rows=12,
    )
    note = Note("Unavailable optional packages or weights are shown as N/A; no model is selected on in-sample accuracy.")
    return GlassCard("Model cards", "capabilities, data needs, licence and resource classes are descriptive evidence only", body=[table, note], width=layout.span_width(12))


def forecast_lab_page(page: ft.Page, state: AppState) -> PageView:
    """Render local forecast comparison and validation evidence (read-only; the run button uses the guarded workflow)."""
    report = build_forecast_lab_workspace(state.snapshot.config, state.snapshot.forecasts, state.snapshot.prices)
    models, catalogue = report["models"], report["model_catalogue"]
    layout = common.make_layout(page)
    ids = _model_ids(models, catalogue)
    names = {model_id: _display_name(model_id, catalogue) for model_id in ids}
    stored_ids = [str(name) for name in models["model_name"]] if not models.empty else []
    forecasts = getattr(state.snapshot, "forecasts", pd.DataFrame())
    first_date = forecasts["forecast_date"].min() if hasattr(forecasts, "columns") and "forecast_date" in forecasts.columns and not forecasts.empty else None
    folds = lab_view.fold_bars(report["walk_forward_splits"], first_date)
    ui = {"model": "All models", "horizon": "1Y"}
    holder = ft.Container()
    current: dict[str, ft.Column] = {}

    def on_governance(_event: object) -> None:
        async def go() -> None:
            await current["body"].scroll_to(scroll_key="forecast-lab.governance", duration=300)

        runner = getattr(page, "run_task", None)
        if callable(runner):
            runner(go)

    def selected_ids() -> list[str]:
        if ui["model"] == "All models":
            return ids
        if ui["model"] == "Baseline":
            return [name for name in ids if lab_view.is_baseline(name)]
        return [name for name in ids if names[name] == ui["model"]]

    def build() -> ft.Control:
        shown = selected_ids()
        reason = None if report["status"] == "ok" else "\n".join(report["notes"])
        error = lab_view.error_vs_baseline(forecasts, report["forecast_outcomes"], stored_ids, max_horizon=lab_view.HORIZON_LIMITS[ui["horizon"]])
        if ui["model"] != "All models" and error.baseline is not None:
            error = lab_view.ErrorSeries(error.horizons, error.baseline, {k: v for k, v in error.lines.items() if k == error.baseline or k in shown}, error.reason)
        body = common.grid(
            layout,
            [
                [(_run_card(layout, page, state, report, on_governance), 4), (_comparison_card(layout, shown, models, catalogue, reason), 8)],
                [(_folds_card(layout, folds), 6), (_error_card(layout, error, names), 6)],
            ],
            below=[
                _runs_card(layout, report["runs"], report["walk_forward_evaluation"]),
                _horizon_card(layout, models),
                _governance_card(layout, state, report, ids, catalogue, models),
                _cards_card(layout, catalogue, models),
            ],
        )
        current["body"] = body
        return body

    def rebuild() -> None:
        holder.content = build()
        common.refresh(holder)

    def select_model(label: str) -> None:
        ui["model"] = label
        rebuild()

    def select_horizon(label: str) -> None:
        ui["horizon"] = label
        rebuild()

    holder.content = build()
    model_items = ["All models", "Baseline", *[names[name] for name in stored_ids if not lab_view.is_baseline(name)]]
    groups = (
        SegmentGroup("model", model_items, ui["model"], select_model),
        SegmentGroup("horizon", _HORIZONS, ui["horizon"], select_horizon),
    )
    return common.page_view("Forecast Lab", "Forecast comparison and validation evidence · shadow only", holder, groups)


__all__ = ["forecast_lab_page"]
