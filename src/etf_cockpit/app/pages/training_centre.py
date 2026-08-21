from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.core.job_scheduler import DurableJobScheduler
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.validation import build_validation_preview, load_optimisation_evidence, load_training_evidence, record_validation_preview
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.features.synthetic_scenarios import SyntheticScenarioGenerator, SyntheticScenarioSpec


def training_centre_page(page: ft.Page, state: object) -> ft.Control:
    """Render durable local training evidence without granting model authority."""

    try:
        snapshot = load_training_evidence(ROOT)
        optimisation = load_optimisation_evidence(ROOT)
        workflows = DurableJobScheduler(ROOT).list_workflows(limit=100)
        runs = snapshot["training.run"]
        models = snapshot["training.model"]
        metrics = snapshot["training.metric"]
        message = "Lightweight local registry; no MLflow service, external upload or model execution is required."
    except Exception as exc:
        snapshot = {key: () for key in ("training.run", "training.model", "training.metric")}
        optimisation = {"trials": (), "summaries": ()}
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
            _synthetic_panel(page),
            render_optimisation_history(optimisation["trials"], optimisation["summaries"]),
            _validation_panel(
                page,
                getattr(getattr(state, "snapshot", None), "prices", None),
                snapshot.get("validation.report", ()),
                snapshot.get("validation.trial", ()),
                snapshot.get("validation.researcher_decision", ()),
                snapshot.get("validation.promotion_result", ()),
                reference_context=(
                    context_from_snapshot(
                        state.snapshot,
                        purpose="validation",
                        analysis_id=f"training-validation:{getattr(state.snapshot, 'universe_revision', 'unknown')}",
                    )
                    if getattr(state, "snapshot", None) is not None
                    else None
                ),
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
    *,
    reference_context: object | None = None,
) -> ft.Container:
    """Show split and promotion evidence without executing a model."""

    report = build_validation_preview(prices, reference_context=reference_context)
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
        retained_text = ft.Text(
            _retained_validation_text(latest_report, latest_trials, latest_decisions, latest_promotions),
            color=theme.MUTED,
            selectable=True,
        )
        evidence_status = ft.Text("Retained evidence is loaded from the local transactional store.", color=theme.MUTED, selectable=True)
    else:
        retained_text = ft.Text("No retained trial evidence is available yet.", color=theme.MUTED, selectable=True)
        evidence_status = ft.Text("Trial evidence is not yet retained.", color=theme.MUTED, selectable=True)

    def record_evidence(_event: ft.ControlEvent) -> None:
        try:
            result = record_validation_preview(
                ROOT,
                prices if hasattr(prices, "columns") else None,
                reference_context=reference_context,
            )
            if result is None:
                evidence_status.value = "Trial evidence unavailable: local adjusted-price history is insufficient."
            else:
                report = result["report"]
                promotion = result["promotion"]
                evidence_status.value = (
                    f"Retained report {report.get('report_id')} with {len(report.get('trial_ids', []))} trials; "
                    f"promotion_eligible={str(promotion.get('eligible', False)).lower()} · execution_allowed=false"
                )
                updated_snapshot = load_training_evidence(ROOT)
                updated_report = next((item for item in updated_snapshot.get("validation.report", ()) if item.get("report_id") == report.get("report_id")), report)
                updated_trials = [item for item in updated_snapshot.get("validation.trial", ()) if item.get("report_id") == report.get("report_id")]
                updated_decisions = [item for item in updated_snapshot.get("validation.researcher_decision", ()) if item.get("report_id") == report.get("report_id")]
                updated_promotions = [item for item in updated_snapshot.get("validation.promotion_result", ()) if item.get("report_id") == report.get("report_id")]
                retained_text.value = _retained_validation_text(updated_report, updated_trials, updated_decisions, updated_promotions)
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


def render_optimisation_history(
    trials: tuple[dict[str, object], ...], summaries: tuple[dict[str, object], ...]
) -> ft.Container:
    """Show bounded search history and resource evidence without promotion."""

    latest = summaries[-1] if summaries else None
    summary_text = (
        "No bounded optimisation runs have been recorded."
        if latest is None
        else (
            f"run={latest.get('run_id')} · status={latest.get('status')} · trials={latest.get('trial_count')} · "
            f"best={latest.get('best_trial_id')} · importance={latest.get('parameter_importance')} · "
            f"peak_memory_mb={latest.get('peak_memory_mb')} · elapsed_seconds={latest.get('elapsed_seconds')} · "
            f"quota_stop={latest.get('stop_reason')} · promotion_eligible=false · execution_allowed=false"
        )
    )
    lines = [
        f"{item.get('run_id')} · {item.get('trial_id')} · {item.get('status')} · score={item.get('score')} · "
        f"duration_ms={item.get('duration_ms')} · peak_memory_mb={item.get('peak_memory_mb')} · parameters={item.get('parameters')}"
        for item in trials[-40:]
    ]
    return panel(
        ft.Column(
            [
                section_header("Bounded optimisation", "Serial local search retains completed, pruned, failed and cancelled trials; final-test metrics are unavailable during search."),
                ft.Text(summary_text, color=theme.MUTED, selectable=True),
                ft.Text("\n".join(lines) or "No optimisation trial rows are available.", color=theme.MUTED, selectable=True),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
    )


def _retained_validation_text(
    report: dict[str, object],
    trials: list[dict[str, object]],
    decisions: list[dict[str, object]],
    promotions: list[dict[str, object]],
) -> str:
    """Format all retained search and promotion evidence for the workspace."""

    latest_decision = max(decisions, key=lambda item: str(item.get("decided_at", "")), default=None)
    latest_promotion = max(promotions, key=lambda item: str(item.get("evaluated_at", "")), default=None)
    diagnostic = (
        f"Retained report {report.get('report_id')} · trials={len(trials)} · "
        f"DSR={report.get('deflated_sharpe')} · PBO={report.get('probability_of_backtest_overfitting')} · "
        f"FDR={report.get('false_discovery_rate')} · decision={latest_decision.get('decision') if latest_decision else 'pending'}"
    )
    trial_detail = " · ".join(
        f"{item.get('trial_id')}={'selected' if item.get('selected') else 'discarded'} "
        f"series={len(item.get('return_series', []))} parameters={item.get('parameters')} "
        f"scores={item.get('validation_scores')} discarded_reason={item.get('discarded_reason') or 'none'}"
        for item in trials
    ) or "no trial rows"
    fold_detail = "; ".join(
        f"fold {fold.get('fold')}: train={fold.get('train_indices')} validation={fold.get('validation_indices')} "
        f"purged={fold.get('purged_indices')} embargoed={fold.get('embargoed_indices')}"
        for fold in report.get("folds", [])
    ) or "no fold boundaries"
    promotion_detail = (
        f"eligible={latest_promotion.get('eligible')} reasons={latest_promotion.get('reasons')}"
        if latest_promotion
        else "no persisted promotion result"
    )
    return (
        f"{diagnostic}\n{trial_detail}\nfeatures={report.get('features')} · thresholds={report.get('thresholds')} · variants={report.get('variants')}\n"
        f"folds={len(report.get('folds', []))} · {fold_detail}\nselection={report.get('selection_method')} · "
        f"data_hash={report.get('data_hash')} · code_hash={report.get('code_hash')}\n"
        f"researcher_decision={latest_decision} · promotion={promotion_detail} · execution_allowed=false"
    )


def _synthetic_panel(page: ft.Page | None = None) -> ft.Container:
    """Show a deterministic robustness fixture without granting promotion authority."""

    spec = SyntheticScenarioSpec(periods=60, seed=42, missing_rate=0.04, jump_probability=0.03)
    summary_text = ft.Text(color=theme.TEXT, selectable=True)
    detail_text = ft.Text(color=theme.MUTED, selectable=True)

    def generate_synthetic_scenario(_event: ft.ControlEvent | None = None) -> None:
        try:
            dataset = SyntheticScenarioGenerator().generate(spec)
            evidence = SyntheticScenarioGenerator.validate(dataset)
            summary_text.value = (
                f"{evidence['rows']['prices']} price rows · "
                f"{evidence['rows']['data_quality']} quality rows · "
                f"{evidence['rows']['execution_events']} execution fixtures"
            )
            detail_text.value = (
                f"Seed {spec.seed} · hash {str(dataset.metadata['dataset_hash'])[:12]} · "
                f"labels {evidence['status']}"
            )
        except Exception as exc:
            summary_text.value = "Synthetic scenario unavailable"
            detail_text.value = f"Controlled failure: {type(exc).__name__}: {exc}"
        if _event is not None and callable(getattr(page, "update", None)):
            page.update()

    generate_synthetic_scenario()
    return panel(
        ft.Column(
            [
                section_header("Synthetic Scenario Builder", "Seeded market, data-quality and execution fixtures for invariants and robustness only."),
                ft.Row([ft.TextButton("Generate seeded scenario", key="training-centre.synthetic-scenario", on_click=generate_synthetic_scenario), ft.Text("synthetic=true · promotion_eligible=false", color=theme.MUTED, selectable=True)], wrap=True),
                summary_text,
                detail_text,
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
