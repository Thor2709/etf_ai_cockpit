from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.core.job_scheduler import DurableJobScheduler
from etf_cockpit.core.paths import ROOT
from etf_cockpit.features.training_centre import LocalTrainingRegistry


def training_centre_page(page: ft.Page, _state: object) -> ft.Control:
    """Render durable local training evidence without granting model authority."""

    registry = LocalTrainingRegistry(ROOT)
    try:
        snapshot = registry.snapshot()
        workflows = DurableJobScheduler(ROOT).list_workflows(limit=100)
        runs = snapshot["training.run"]
        models = snapshot["training.model"]
        metrics = snapshot["training.metric"]
        message = "Lightweight local registry; no MLflow service, external upload or model execution is required."
    except Exception as exc:
        snapshot = {key: () for key in ("training.run", "training.model", "training.metric")}
        workflows = ()
        runs = models = metrics = ()
        message = f"Training evidence is unavailable: {type(exc).__name__}: {exc}"

    def refresh(_event: ft.ControlEvent) -> None:
        page.go("/training-centre")

    return ft.Column(
        [
            section_header(
                "Training Centre",
                "Experiments, runs, lineage, metrics and model-card evidence are local and replayable.",
            ),
            ft.Row(
                [
                    ft.TextButton("Refresh", key="training-centre.refresh", on_click=refresh),
                    ft.Text("execution_allowed=false · promotion requires recorded human approval", color=theme.MUTED, selectable=True),
                ],
                wrap=True,
            ),
            panel(ft.Column([section_header("Registry status", "The compatible lightweight adapter uses the existing transactional store."), ft.Text(message, color=theme.MUTED, selectable=True), ft.Text(f"Runs: {len(runs)} · models: {len(models)} · metrics: {len(metrics)} · training workflows: {len([item for item in workflows if item.workflow_type == 'model_training'])}", color=theme.TEXT, selectable=True)])),
            _runs_panel(runs),
            ft.Row([_metrics_panel(metrics), _models_panel(models)], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
            _reports_panel(runs),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _runs_panel(runs: tuple[dict[str, object], ...]) -> ft.Container:
    rows = [
        ft.DataRow(cells=[
            ft.DataCell(ft.Text(str(run.get("run_id", "")), color=theme.TEXT, size=12)),
            ft.DataCell(ft.Text(str(run.get("status", "")), color=theme.MUTED, size=12)),
            ft.DataCell(ft.Text(f"{float(run.get('progress', 0.0)):.0%}", color=theme.MUTED, size=12)),
            ft.DataCell(ft.Text(str(run.get("lineage_hash", ""))[:12], color=theme.MUTED, size=12)),
            ft.DataCell(ft.Text(str(run.get("promotion_state", "unpromoted")), color=theme.MUTED, size=12)),
        ])
        for run in runs[:50]
    ]
    body: ft.Control = ft.Text("No training runs have been registered.", color=theme.MUTED) if not rows else ft.DataTable(
        columns=[ft.DataColumn(ft.Text(label)) for label in ("Run", "Status", "Progress", "Lineage", "Promotion")],
        rows=rows,
    )
    return panel(ft.Column([section_header("Run list", "Queued, running, completed, failed and cancelled states remain durable."), body], scroll=ft.ScrollMode.AUTO))


def _metrics_panel(metrics: tuple[dict[str, object], ...]) -> ft.Container:
    lines = [f"{item.get('run_id')} · {item.get('name')}={item.get('value')} · step={item.get('step')}" for item in metrics[:30]]
    return panel(ft.Column([section_header("Live metrics", "Metrics are append-only evidence from local jobs."), ft.Text("\n".join(lines) or "No metrics have been recorded.", color=theme.MUTED, selectable=True)]), expand=True)


def _models_panel(models: tuple[dict[str, object], ...]) -> ft.Container:
    lines = [f"{item.get('name')} · approval={item.get('approval_state')} · promotion={item.get('promotion_state')} · aliases={','.join(item.get('aliases', [])) or 'none'}" for item in models[:30]]
    return panel(ft.Column([section_header("Model comparison and registry", "Only approved models may become challengers or champions; execution remains disabled."), ft.Text("\n".join(lines) or "No completed model has been registered.", color=theme.MUTED, selectable=True)]), expand=True)


def _reports_panel(runs: tuple[dict[str, object], ...]) -> ft.Container:
    lines = []
    for run in runs[:30]:
        report = run.get("completion_report") or {}
        lines.append(f"{run.get('run_id')} · {run.get('status')} · {report or 'completion report pending'}")
    return panel(ft.Column([section_header("Final reports and replay", "Completion reports retain the lineage needed for offline replay."), ft.Text("\n".join(lines) or "No completion reports are available.", color=theme.MUTED, selectable=True)]))


__all__ = ["training_centre_page"]
