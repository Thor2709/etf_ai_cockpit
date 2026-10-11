from __future__ import annotations

from collections.abc import Mapping

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import (
    Button,
    DataTable,
    Disclosure,
    EmptyState,
    GlassCard,
    KpiStrip,
    KpiStripItem,
    KpiTile,
    Note,
    Tag,
    TableColumn,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.components.chartkit import Bubble, Segment, Series
from etf_cockpit.app.formatting import format_count, format_timestamp
from etf_cockpit.app.pages._lab_style import lab_page, panel, section_header
from etf_cockpit.application.runtime import DurableJobScheduler
from etf_cockpit.core.paths import ROOT
from etf_cockpit.core.values import finite_float_or_none
from etf_cockpit.application.validation import build_validation_preview, load_optimisation_evidence, load_training_evidence, record_validation_preview
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.application.validation import SyntheticScenarioGenerator, SyntheticScenarioSpec


@lab_page("training_centre")
def _step_key(value: object) -> tuple[int, float, str]:
    """Numbers in numeric order first, then everything else as text."""

    number = finite_float_or_none(value)
    return (0, number, "") if number is not None else (1, 0.0, str(value))


def _legacy_training_centre_page(page: ft.Page, state: object) -> ft.Control:
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
        ft.Row([_metrics_panel(metrics), _models_panel(models)], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            _reports_panel(runs),
        ],
        spacing=16,
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


def training_centre_page(page: ft.Page, state: object) -> PageView:
    """Present existing run and validation evidence without starting model work."""
    try:
        snapshot = load_training_evidence(ROOT)
        optimisation = load_optimisation_evidence(ROOT)
        workflows = DurableJobScheduler(ROOT).list_workflows(limit=100)
        runs = tuple(snapshot.get("training.run", ()))
        models = tuple(snapshot.get("training.model", ()))
        metrics = tuple(snapshot.get("training.metric", ()))
        reports = tuple(snapshot.get("validation.report", ()))
        trials = tuple(snapshot.get("validation.trial", ()))
        decisions = tuple(snapshot.get("validation.researcher_decision", ()))
        promotions = tuple(snapshot.get("validation.promotion_result", ()))
        load_reason = None
    except Exception:
        snapshot = {}
        optimisation = {"trials": (), "summaries": ()}
        workflows = ()
        runs = models = metrics = reports = trials = decisions = promotions = ()
        load_reason = "The local training registry is unavailable."

    def refresh(_event: object) -> None:
        if callable(getattr(page, "go", None)):
            page.go("/training-centre")

    def table_value(value: object) -> object:
        return "—" if value is None or str(value).strip().casefold() in {"", "none", "nan", "nat"} else value

    run_rows = []
    for run in runs:
        state_value = str(run.get("status") or "").replace("_", " ").title() or "Unavailable"
        state_kind = {"Completed": "ok", "Running": "warn", "Failed": "bad", "Cancelled": "mute", "Queued": "mute"}.get(state_value, "mute")
        run_rows.append(
            {
                "run": table_value(run.get("run_id")),
                "model": table_value(run.get("model_id") or run.get("model_name")),
                "state": Tag(state_value, state_kind),
                "started": format_timestamp(run.get("started_at"), unavailable="—"),
                "duration": table_value(run.get("duration")),
                "best_metric": table_value(run.get("best_metric")),
            }
        )
    run_table = DataTable(
        [TableColumn("run", "Run"), TableColumn("model", "Model"), TableColumn("state", "State"), TableColumn("started", "Started"), TableColumn("duration", "Duration"), TableColumn("best_metric", "Best metric")],
        run_rows,
        empty_title="No training runs have been registered.",
        empty_reason=load_reason or "The local registry contains no run rows.",
    )
    metric_names = sorted({str(item.get("name")) for item in metrics if item.get("name")})
    run_ids = sorted({str(item.get("run_id")) for item in metrics if item.get("run_id")})
    metric_charts: list[ft.Control] = []
    for metric_name in metric_names:
        metric_rows = [item for item in metrics if str(item.get("name")) == metric_name]
        steps = sorted({item.get("step") for item in metric_rows if item.get("step") is not None}, key=_step_key)
        metric_series = []
        for series_index, run_id in enumerate(run_ids):
            values = [
                next((row.get("value") for row in metric_rows if str(row.get("run_id")) == run_id and row.get("step") == step), None)
                for step in steps
            ]
            if any(value is not None for value in values):
                metric_series.append(Series(run_id, values, theme.CATEGORICAL[series_index % len(theme.CATEGORICAL)]))
        metric_insight = f"Recorded {metric_name} values across {len(metric_series)} training runs." if metric_series else f"Unavailable: no recorded {metric_name} values have a step."
        metric_charts.append(
            ck.line_chart(
                steps,
                metric_series,
                x_name="Step (count)",
                y_name=f"{metric_name} (reported unit)",
                unavailable_reason=load_reason or ("No metrics have been recorded." if not metrics else "No recorded metric values include a step.") if not metric_series else None,
                empty_title="No metrics have been recorded.",
                insight=metric_insight,
            )
        )
    if not metric_charts:
        metric_charts.append(
            ck.line_chart(
                [],
                [],
                x_name="Step (count)",
                y_name="Metric (reported unit)",
                unavailable_reason=load_reason or "No metrics have been recorded.",
                empty_title="No metrics have been recorded.",
                insight="Unavailable: no saved training metrics are available.",
            )
        )
    metrics_chart = ft.Column(metric_charts, spacing=8)
    metrics_insight = (
        f"Recorded {', '.join(metric_names)} metrics across {len(run_ids)} training runs."
        if metric_names and run_ids
        else "Unavailable: no saved training metric series are available."
    )
    report = max(reports, key=lambda item: str(item.get("run_id", "")), default=None)
    report_trials = [item for item in trials if report and item.get("report_id") == report.get("report_id")]
    report_decisions = [item for item in decisions if report and item.get("report_id") == report.get("report_id")]
    report_promotions = [item for item in promotions if report and item.get("report_id") == report.get("report_id")]
    validation_detail = _retained_validation_text(report, report_trials, report_decisions, report_promotions) if report else None
    prices = getattr(getattr(state, "snapshot", None), "prices", None)
    can_retain = prices is not None and hasattr(prices, "columns")
    validation_status = Note("No validation evidence change is pending.")

    def retain(_event: object) -> None:
        if not can_retain:
            return
        try:
            result = record_validation_preview(ROOT, prices)
        except Exception as exc:
            validation_status.value = f"Validation evidence could not be retained: {type(exc).__name__}: {exc}"
        else:
            if result is None:
                validation_status.value = "Unavailable: local adjusted-price history is insufficient to retain validation evidence."
            elif callable(getattr(page, "go", None)):
                page.go("/training-centre")
                return
            else:
                validation_status.value = "Retained validation evidence is available after refreshing this page."
        if callable(getattr(page, "update", None)):
            page.update()

    fold_records = report.get("folds", ()) if report else ()
    if not isinstance(fold_records, (list, tuple)):
        fold_records = ()
    fold_rows: list[str] = []
    fold_segments: list[list[Segment]] = []
    for fold_index, fold in enumerate(fold_records):
        if not isinstance(fold, Mapping):
            continue
        boundaries = [fold.get("train_indices"), fold.get("validation_indices"), fold.get("purged_indices"), fold.get("embargoed_indices")]
        if not all(isinstance(items, (list, tuple)) for items in boundaries):
            continue
        fold_rows.append(f"Fold {fold_index + 1}")
        fold_segments.append(
            [
                Segment(len(boundaries[0]), "pos", "Train"),
                Segment(len(boundaries[1]), "gold", "Validation"),
                Segment(len(boundaries[2]), "blue", "Purged"),
                Segment(len(boundaries[3]), "neg", "Embargoed"),
            ]
        )
    fold_chart_reason = "No retained validation fold boundaries are available."
    fold_chart_ready = bool(fold_records) and len(fold_rows) == len(fold_records)
    fold_chart = ck.horizontal_stacked_bar(
        fold_rows,
        fold_segments,
        x_name="Observations (count)",
        unit="observations",
        unavailable_reason=load_reason or (None if fold_chart_ready else fold_chart_reason),
        empty_title="Validation fold diagram unavailable",
        insight=f"Retained report contains {len(fold_rows)} walk-forward folds." if fold_chart_ready else "Unavailable: retained fold boundaries are incomplete.",
    )
    regime_results = report.get("regime_results") if report else None
    regime_names = ", ".join(str(name) for name in regime_results) if isinstance(regime_results, Mapping) and regime_results else None
    fold_tile_value = format_count(len(fold_records), unavailable="") if fold_records else ""
    trial_ids = report.get("trial_ids") if report else None
    retained_trial_count = len(trial_ids) if isinstance(trial_ids, (list, tuple)) else len(report_trials)
    validation_tiles = ft.Row(
        [
            KpiTile("Folds", fold_tile_value or None, "" if fold_tile_value else "No retained fold boundaries are available."),
            KpiTile("Trials retained", format_count(retained_trial_count, unavailable="") if report else None, "No retained validation report is available." if not report else ""),
            KpiTile("Selected", str(report.get("selected_trial_id")) if report and report.get("selected_trial_id") else None, "" if report and report.get("selected_trial_id") else "No selected trial is recorded."),
            KpiTile("Regimes", regime_names, "" if regime_names else "No regime results are recorded."),
        ],
        spacing=8,
        wrap=True,
    )
    validation_body = ft.Column(
        [
            fold_chart,
            validation_tiles,
            Disclosure("Retained validation evidence", validation_detail) if validation_detail else EmptyState("Validation preview unavailable", "No precomputed validation report is available for this snapshot."),
            Disclosure("Evidence action status", validation_status),
            ft.Row(
                [
                    Button.secondary("Retain trial evidence", on_click=retain, disabled=not can_retain, disabled_reason="Local price history is unavailable." if not can_retain else None, key="training-centre.record-evidence"),
                    ft.TextButton("Refresh validation report", on_click=refresh, key="training-centre.validation-refresh"),
                ],
                spacing=8,
            ),
        ],
        spacing=8,
    )
    opt_trials = tuple(optimisation.get("trials", ()))
    opt_summaries = tuple(optimisation.get("summaries", ()))
    trial_points = []
    for item in opt_trials:
        trial_index = item.get("trial_number", item.get("trial_index"))
        objective = item.get("objective", item.get("score"))
        if trial_index is None or objective is None:
            continue
        status = str(item.get("status", "")).casefold()
        if status not in {"completed", "pruned", "failed"}:
            continue
        group = status
        trial_points.append(Bubble(str(trial_index), float(trial_index), float(objective), group=group))
    optimisation_insight = f"Recorded objective values are available for {len(trial_points)} bounded trials." if trial_points else "Unavailable: no completed, pruned or failed trial objectives are available."
    optimisation_chart = ck.scatter_bubble(
        trial_points,
        groups=[("completed", theme.CHART_POS), ("pruned", theme.MUTED), ("failed", theme.CHART_NEG)],
        x_name="Trial (count)",
        y_name="Objective (reported unit)",
        x_unit="trials",
        y_unit="reported unit",
        unavailable_reason="No bounded optimisation rows with recorded trial and objective values are available." if not trial_points else None,
        insight=optimisation_insight,
    )
    workflow_count = sum(1 for item in workflows if getattr(item, "workflow_type", None) == "model_training")
    registry_ready = load_reason is None
    kpi = KpiStrip(
        "REGISTRY",
        "ready" if registry_ready else "Unavailable",
        "lightweight local registry · no external upload",
        [
            KpiStripItem("Runs", format_count(len(runs), unavailable="") if runs else None, "No training runs are registered." if not runs else ""),
            KpiStripItem("Models", format_count(len(models), unavailable="") if models else None, "No models are registered." if not models else ""),
            KpiStripItem("Metrics", format_count(len(metrics), unavailable="") if metrics else None, "No training metrics are recorded." if not metrics else ""),
            KpiStripItem("Training workflows", format_count(workflow_count, unavailable="") if workflow_count else None, "No training workflows are registered." if not workflow_count else ""),
        ],
    )
    latest_report_lines = [
        {"run": run.get("run_id"), "model": run.get("model_id") or run.get("model_name"), "state": str(run.get("status") or "Unavailable").replace("_", " ").title(), "started": format_timestamp(run.get("started_at"), unavailable="—"), "duration": run.get("duration") or "—", "best_metric": run.get("best_metric") or "—"}
        for run in runs
    ]
    scenario_details = Note("Generate a local scenario to view its seed and dataset hash.")
    scenario_tiles = ft.Row(
        [
            KpiTile(label, None, "Generate a seeded scenario to view fixture row counts.", expand=True)
            for label in ("Price rows", "Quality rows", "Execution fixtures")
        ],
        spacing=8,
    )

    def show_scenario_counts(rows: Mapping[str, object] | None, reason: str) -> None:
        labels = (("Price rows", "prices"), ("Quality rows", "data_quality"), ("Execution fixtures", "execution_events"))
        scenario_tiles.controls = [
            KpiTile(label, format_count(rows.get(key), unavailable="") or None if rows is not None else None, reason if rows is None or rows.get(key) is None else "", expand=True)
            for label, key in labels
        ]

    def generate_scenario(_event: object) -> None:
        try:
            dataset = SyntheticScenarioGenerator().generate(SyntheticScenarioSpec())
            evidence = SyntheticScenarioGenerator.validate(dataset)
            show_scenario_counts(evidence["rows"], "Fixture row count is unavailable.")
            scenario_details.value = f"Seed {dataset.metadata.get('seed', '—')} · hash {dataset.metadata.get('dataset_hash', '—')} · synthetic=true · promotion_eligible=false"
        except Exception:
            show_scenario_counts(None, "The local synthetic fixture could not be generated.")
            scenario_details.value = "The local synthetic fixture could not be generated."
        if callable(getattr(page, "update", None)):
            page.update()

    synthetic = GlassCard(
        "Synthetic Scenario Builder",
        body=ft.Column(
            [
                Note("Seeded local robustness fixtures; synthetic and not promotion-eligible."),
                scenario_tiles,
                Disclosure("Seed and dataset hash", scenario_details),
                ft.Row([Tag("synthetic", "mute"), Tag("not promotion-eligible", "mute")], spacing=8),
                Button.secondary("Generate seeded scenario", on_click=generate_scenario, key="training-centre.synthetic-scenario"),
            ],
            spacing=8,
        ),
        expand=True,
    )
    runs_row = ft.Row(
        [
            GlassCard("Run list", note="Queued, running, completed, failed, cancelled", body=ft.Column([ft.TextButton("Refresh", on_click=refresh, key="training-centre.refresh"), run_table], spacing=8), expand=True),
            GlassCard("Live metrics", insight=metrics_insight, body=metrics_chart, expand=True),
        ],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    validation_card = GlassCard("Validation Designer", insight=f"Retained report contains {len(fold_rows)} walk-forward folds." if fold_chart_ready else "Unavailable: retained validation fold data are incomplete.", body=validation_body, expand=True)
    optimisation_card = GlassCard("Bounded optimisation", insight=optimisation_insight, body=ft.Column([optimisation_chart, Disclosure("Trial and resource details", str(opt_summaries[-1]) if opt_summaries else "No bounded optimisation runs have been recorded.")], spacing=8), expand=True)
    detail_row = ft.Row(
        [validation_card, optimisation_card],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    body = ft.Column(
        [
            kpi,
            runs_row,
            detail_row,
            ft.Row(
                [
                    synthetic,
                    GlassCard("Model comparison and registry", body=Disclosure("Model registry details", str(models) if models else "No completed model has been registered."), expand=True),
                    GlassCard("Final reports and replay", body=Disclosure("Final report details", str(latest_report_lines) if latest_report_lines else "No completion reports are available."), expand=True),
                ],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            Note("execution_allowed=false · promotion requires recorded human approval"),
        ],
        spacing=16,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    def show_view(value: str) -> None:
        detail_row.controls = [optimisation_card, validation_card] if value == "Optimisation" else [validation_card, optimisation_card]
        body.controls[1:3] = [detail_row, runs_row] if value in {"Validation", "Optimisation"} else [runs_row, detail_row]
        if callable(getattr(page, "update", None)):
            page.update()

    return PageView(
        chrome=PageChrome("Training Centre", "Experiments, runs, metrics and model cards · promotion needs recorded human approval", (SegmentGroup("training-centre", ("Runs", "Validation", "Optimisation"), "Runs", on_change=show_view),)),
        body=body,
    )


__all__ = ["training_centre_page"]
