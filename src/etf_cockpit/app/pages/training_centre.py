from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.core.job_scheduler import DurableJobScheduler
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.validation import build_validation_preview, load_training_evidence, record_validation_preview
from etf_cockpit.features.synthetic_scenarios import SyntheticScenarioGenerator, SyntheticScenarioSpec


def training_centre_page(page: ft.Page, state: object) -> ft.Control:
    """Render durable local training evidence without granting model authority."""

    try:
        snapshot = load_training_evidence(ROOT)
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
            _synthetic_panel(),
            _validation_panel(
                page,
                getattr(getattr(state, "snapshot", None), "prices", None),
                snapshot.get("validation.report", ()),
                snapshot.get("validation.trial", ()),
                snapshot.get("validation.researcher_decision", ()),
                snapshot.get("validation.promotion_result", ()),
            ),
            _runs_panel(runs),
            ft.Row([_metrics_panel(metrics), _models_panel(models)], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
            _reports_panel(runs),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _validation_panel(
    page: ft.Page | None,
    prices: object,
    retained_reports: tuple[dict[str, object], ...] = (),
    retained_trials: tuple[dict[str, object], ...] = (),
    retained_decisions: tuple[dict[str, object], ...] = (),
    retained_promotions: tuple[dict[str, object], ...] = (),
) -> ft.Container:
    """Show split and promotion evidence without executing a model."""

    report = build_validation_preview(prices)
    if report is None:
        controls: list[ft.Control] = [
            section_header("Validation Designer", "Purged/embargoed walk-forward reports remain unavailable until sufficient adjusted-price history exists."),
            ft.Text("Validation preview unavailable: at least one local adjusted-price return history is required.", color=theme.AMBER, selectable=True),
        ]
    else:
        detail = [
            f"Folds: {len(report.folds)} · trials retained: {len(report.trials)} · selected: {report.selected_trial_id}",
            f"final_test_used_for_selection={str(report.final_test_used_for_selection).lower()} · promotion_eligible={str(report.promotion_eligible).lower()}",
            f"Uncertainty: {report.uncertainty.get('status')} · CI {report.uncertainty.get('lower_5')} to {report.uncertainty.get('upper_95')}",
            f"Regimes: {', '.join(report.regime_results) or 'unavailable'} · subgroups: {', '.join(report.subgroup_results) or 'unavailable'}",
            f"protocol={report.protocol_version} · fingerprint={report.to_dict()['report_fingerprint'][:12]}",
        ]
        controls = [
            section_header("Validation Designer", "The protocol separates development folds from an untouched final test; discarded trials and promotion limitations remain visible."),
            ft.Text("\n".join(detail), color=theme.MUTED, selectable=True),
        ]

    def refresh(_event: ft.ControlEvent) -> None:
        if page is not None and callable(getattr(page, "go", None)):
            page.go("/training-centre")

    latest_report = max(retained_reports, key=lambda item: str(item.get("run_id", "")), default=None)
    latest_trials = [item for item in retained_trials if latest_report and item.get("report_id") == latest_report.get("report_id")]
    latest_decisions = [item for item in retained_decisions if latest_report and item.get("report_id") == latest_report.get("report_id")]
    latest_promotions = [item for item in retained_promotions if latest_report and item.get("report_id") == latest_report.get("report_id")]
    if latest_report:
        latest_decision = max(latest_decisions, key=lambda item: str(item.get("decided_at", "")), default=None)
        latest_promotion = max(latest_promotions, key=lambda item: str(item.get("evaluated_at", "")), default=None)
        diagnostic = (
            f"Retained report {latest_report.get('report_id')} · trials={len(latest_trials)} · "
            f"DSR={latest_report.get('deflated_sharpe')} · PBO={latest_report.get('probability_of_backtest_overfitting')} · "
            f"FDR={latest_report.get('false_discovery_rate')} · decision={latest_decision.get('decision') if latest_decision else 'pending'}"
        )
        trial_detail = " · ".join(
            f"{item.get('trial_id')}={'selected' if item.get('selected') else 'discarded'} "
            f"series={len(item.get('return_series', []))} parameters={item.get('parameters')} "
            f"scores={item.get('validation_scores')} discarded_reason={item.get('discarded_reason') or 'none'}"
            for item in latest_trials
        ) or "no trial rows"
        fold_detail = "; ".join(
            f"fold {fold.get('fold')}: train={fold.get('train_indices')} validation={fold.get('validation_indices')} "
            f"purged={fold.get('purged_indices')} embargoed={fold.get('embargoed_indices')}"
            for fold in latest_report.get("folds", [])
        ) or "no fold boundaries"
        promotion_detail = (
            f"eligible={latest_promotion.get('eligible')} reasons={latest_promotion.get('reasons')}"
            if latest_promotion
            else "no persisted promotion result"
        )
        retained_text = ft.Text(
            f"{diagnostic}\n{trial_detail}\nfeatures={latest_report.get('features')} · thresholds={latest_report.get('thresholds')} · variants={latest_report.get('variants')}\n"
            f"folds={len(latest_report.get('folds', []))} · {fold_detail}\nselection={latest_report.get('selection_method')} · "
            f"data_hash={latest_report.get('data_hash')} · code_hash={latest_report.get('code_hash')}\n"
            f"researcher_decision={latest_decision} · promotion={promotion_detail} · execution_allowed=false",
            color=theme.MUTED,
            selectable=True,
        )
        evidence_status = ft.Text("Retained evidence is loaded from the local transactional store.", color=theme.MUTED, selectable=True)
    else:
        retained_text = ft.Text("No retained trial evidence is available yet.", color=theme.MUTED, selectable=True)
        evidence_status = ft.Text("Trial evidence is not yet retained.", color=theme.MUTED, selectable=True)

    def record_evidence(_event: ft.ControlEvent) -> None:
        try:
            result = record_validation_preview(ROOT, prices if hasattr(prices, "columns") else None)
            if result is None:
                evidence_status.value = "Trial evidence unavailable: local adjusted-price history is insufficient."
            else:
                report = result["report"]
                promotion = result["promotion"]
                evidence_status.value = (
                    f"Retained report {report.get('report_id')} with {len(report.get('trial_ids', []))} trials; "
                    f"promotion_eligible={str(promotion.get('eligible', False)).lower()} · execution_allowed=false"
                )
        except Exception as exc:
            evidence_status.value = f"Trial evidence failed safely: {type(exc).__name__}: {exc}"
        if page is not None and callable(getattr(page, "update", None)):
            page.update()

    controls.extend([
        retained_text,
        ft.Row(
            [
                ft.OutlinedButton("Retain trial evidence", key="training-centre.record-evidence", on_click=record_evidence),
                ft.TextButton("Refresh validation report", key="training-centre.validation-refresh", on_click=refresh),
                evidence_status,
            ],
            wrap=True,
        )
    ])
    return panel(ft.Column(controls, spacing=8))


def _synthetic_panel() -> ft.Container:
    """Show a deterministic robustness fixture without granting promotion authority."""

    spec = SyntheticScenarioSpec(periods=60, seed=42, missing_rate=0.04, jump_probability=0.03)
    try:
        dataset = SyntheticScenarioGenerator().generate(spec)
        evidence = SyntheticScenarioGenerator.validate(dataset)
        summary = f"{evidence['rows']['prices']} price rows · {evidence['rows']['data_quality']} quality rows · {evidence['rows']['execution_events']} execution fixtures"
        detail = f"Seed {spec.seed} · hash {str(dataset.metadata['dataset_hash'])[:12]} · labels {evidence['status']}"
    except Exception as exc:
        summary = "Synthetic scenario unavailable"
        detail = f"Controlled failure: {type(exc).__name__}: {exc}"
    return panel(
        ft.Column(
            [
                section_header("Synthetic Scenario Builder", "Seeded market, data-quality and execution fixtures for invariants and robustness only."),
                ft.Row([ft.TextButton("Generate seeded scenario", key="training-centre.synthetic-scenario", on_click=lambda _event: None), ft.Text("synthetic=true · promotion_eligible=false", color=theme.MUTED, selectable=True)], wrap=True),
                ft.Text(summary, color=theme.TEXT, selectable=True),
                ft.Text(detail, color=theme.MUTED, selectable=True),
            ]
        )
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
