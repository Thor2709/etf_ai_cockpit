from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, metric_card, panel, section_header
from etf_cockpit.app.components.simple_scores import score_colour, simple_score_grouped_sections, simple_score_legend
from etf_cockpit.app.components.states import state_panel
from etf_cockpit.app.state import ActivityUnavailableError, AppState, activity_result_error
from etf_cockpit.core.paths import FORECASTS_DIR
from etf_cockpit.core.paths import ROOT
from etf_cockpit.application.alerts import (
    AlertReadback,
    AlertRecord,
    AlertRevisionConflict,
    AlertStatus,
    AlertType,
    dismiss_local_alert,
    read_local_alerts,
    snooze_local_alert,
)
from etf_cockpit.application.digest import (
    DashboardDigest,
    build_digest,
    filter_news_contradiction_inputs,
    score_run_pair_as_of,
)
from etf_cockpit.application.ui_facade import (
    EVENT_CLEAN_PATH,
    NEWS_CLEAN_PATH,
    MacroWarehouse,
    MacroWarehouseError,
    SimpleInstrumentScore,
    build_news_contradiction_rows,
    build_simple_instrument_scores,
    compare_runs,
    events_available_as_of,
    filter_forecasts_for_universe,
    load_calendar_events,
    load_latest_forecasts,
    load_news_items,
    normalise_event_decision_time,
    score_history_frame,
    sort_news_items,
)


def _rebuild(page: ft.Page, state: AppState) -> None:
    from etf_cockpit.app.router import render_shell

    render_shell(page, state, page.route or state.snapshot.config.ui.default_page)


def _go_to(page: ft.Page, state: AppState, route: str) -> None:
    from etf_cockpit.app.router import navigate_to

    navigate_to(page, state, route)


def _restore_cancelled_result(state: AppState, action_id: str, *controls: ft.Control) -> None:
    message = state.restore_cancelled_activity_message(action_id)
    if message is not None:
        for control in controls:
            control.value = message


def dashboard_page(page: ft.Page, state: AppState) -> ft.Control:
    narrow = float(getattr(page, "width", 0) or state.snapshot.config.ui.window_width) < 760
    scores = build_simple_instrument_scores(
        state.snapshot.config,
        state.snapshot.signals,
        state.snapshot.forecasts,
        state.snapshot.prices,
        universe_revision=str(
            getattr(state.snapshot, "universe_revision", "")
            or getattr(state, "universe_cache_revision", "")
        ),
    )
    best = scores[0] if scores else None
    configured_count = sum(1 for score in scores if score.source_group == "Primary tier")
    candidate_count = sum(1 for score in scores if score.source_group == "Secondary tier")
    sparebanken_count = sum(1 for score in scores if score.source_group == "Sparebanken")
    model_pairs = _valid_model_pairs(state)
    cards = _summary_cards(state, best, configured_count, candidate_count, sparebanken_count, model_pairs, narrow=narrow)

    return ft.Column(
        [
            _evidence_state_panel(state),
            _what_matters_today(state, scores=scores),
            cards,
            _alerts_digest(page, state),
            _run_changes_digest(page, state),
            _news_digest(page, state),
            _action_bar(page, state),
            simple_score_legend(),
            panel(
                ft.Column(
                    [
                        section_header(
                            "Simple yfinance scores",
                            "Primary tier, secondary tier and Sparebanken rows are separated by asset class. Expand a row for evidence quality, risk/friction, deterministic algorithms and low-authority AI forecast confirmation.",
                        ),
                        simple_score_grouped_sections(scores, page=page, state=state),
                    ],
                    spacing=12,
                ),
            ),
            _activity_panel(state, page=page),
            _secondary_actions(page, state),
        ],
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )


def _evidence_state_panel(state: AppState) -> ft.Container:
    status = str(state.snapshot.data_report.status or "").casefold()
    state_name = "success" if status == "clean" else "warning" if status == "warning" else "error" if status == "blocked" else "empty"
    return state_panel(
        state_name,
        "Evidence state",
        f"Data health is {state.snapshot.data_report.status}; scores and model outputs remain advisory evidence.",
        details=f"Evidence mode: {theme.EVIDENCE_MODE_LABELS.get(state.evidence_mode, state.evidence_mode)} | execution_allowed=false",
    )


def _what_matters_today(state: AppState, *, scores: list[SimpleInstrumentScore] | None = None) -> ft.Container:
    """Render the bounded local context digest without granting authority."""

    try:
        digest = _dashboard_digest(state, scores=scores)
        rows: list[ft.Control] = []
        for item in digest.items:
            as_of = item.as_of or "as-of unavailable"
            rows.append(
                ft.Text(
                    f"{item.severity.upper()} | {item.title}: {item.detail} "
                    f"(status={item.status}, source={item.provenance}, as_of={as_of}, execution_allowed=false)",
                    color=theme.TEXT if item.status == "available" else theme.AMBER,
                    selectable=True,
                    size=11,
                    max_lines=4,
                    overflow=ft.TextOverflow.ELLIPSIS,
                )
            )
        unavailable = [source for source, status in digest.source_status if status != "available"]
        if unavailable:
            rows.append(
                ft.Text(
                    "Unavailable/manual-review inputs: " + ", ".join(unavailable),
                    color=theme.MUTED,
                    selectable=True,
                    size=11,
                )
            )
        body: ft.Control = ft.Column(rows, spacing=4)
    except Exception as exc:
        body = ft.Text(
            f"Digest unavailable; manual review required ({type(exc).__name__}). execution_allowed=false",
            color=theme.AMBER,
            selectable=True,
        )
    control = panel(
        ft.Column(
            [
                section_header(
                    "What matters today",
                    "Deterministic local context across score changes, warnings, models, contradictions, events, freshness and audit status; informational only.",
                ),
                body,
            ],
            spacing=8,
        )
    )
    control.key = "dashboard.what-matters-today"
    return control


def _dashboard_digest(state: AppState, *, scores: list[SimpleInstrumentScore] | None = None) -> DashboardDigest:
    as_of = str(getattr(getattr(state.snapshot, "data_report", None), "as_of_date", "") or "") or None
    cutoff = normalise_event_decision_time(as_of)
    report = _latest_run_change_report(cutoff)
    records: dict[str, list[dict[str, object]] | None] = {
        "score_changes": _score_change_record(report, as_of=as_of),
        "warning_changes": _warning_change_record(report, as_of=as_of),
    }

    alerts = (
        _read_alerts(as_of=cutoff.to_pydatetime(), limit=None)
        if cutoff is not None
        else AlertReadback("unavailable")
    )
    records["alerts"] = _alert_record(alerts, as_of=as_of)
    records["model_failures"] = _model_failure_record(alerts, as_of=as_of)
    records["manual_review"] = _manual_review_record(report, scores or (), as_of=as_of)
    records["stale_data"] = _stale_data_record(state, alerts, as_of=as_of)
    records["contradictions"] = _contradiction_record(state, as_of=as_of, cutoff=cutoff)
    records["upcoming_events"] = _event_record(as_of=as_of, cutoff=cutoff)
    records["audit_export"] = _audit_export_record(state, as_of=as_of)
    return build_digest(records, as_of=as_of)


def _latest_run_change_report(cutoff: object):
    history = score_history_frame()
    selected = score_run_pair_as_of(history, cutoff)
    if selected is None:
        return None
    eligible_history, current, previous = selected
    return compare_runs(eligible_history, current, previous)


def _score_change_record(report, *, as_of: str | None) -> list[dict[str, object]] | None:
    if report is None:
        return None
    score_comparable = [change for change in report.changes if change.score_delta is not None]
    rank_comparable = [change for change in report.changes if change.score_rank_delta is not None]
    score_changed = sorted(
        (change for change in score_comparable if change.score_delta != 0),
        key=lambda change: (-abs(change.score_delta), change.instrument_id),
    )
    rank_changed = sorted(
        (change for change in rank_comparable if change.score_rank_delta != 0),
        key=lambda change: (-abs(change.score_rank_delta), change.instrument_id),
    )
    score_detail = (
        "scores: " + ", ".join(f"{change.instrument_id} {change.score_delta:+.1f}" for change in score_changed[:3])
        if score_changed
        else "scores: no change"
        if score_comparable
        else "scores: unavailable"
    )
    rank_detail = (
        "ranks: " + ", ".join(f"{change.instrument_id} {change.score_rank_delta:+.0f}" for change in rank_changed[:3])
        if rank_changed
        else "ranks: no change"
        if rank_comparable
        else "ranks: unavailable"
    )
    if not score_comparable and not rank_comparable:
        status, severity = "unavailable", "warning"
    elif not score_comparable or not rank_comparable:
        status, severity = "manual_review", "warning"
    else:
        status = "available"
        severity = "warning" if score_changed or rank_changed else "info"
    return [{"title": "Biggest score/rank changes", "detail": f"{score_detail}; {rank_detail}.", "status": status, "severity": severity, "as_of": as_of, "provenance": "score_history"}]


def _warning_change_record(report, *, as_of: str | None) -> list[dict[str, object]] | None:
    if report is None:
        return None
    warning_evidence_unavailable = not report.changes or any(
        change.current_warnings == "unavailable"
        or change.previous_warnings in {None, "unavailable"}
        for change in report.changes
    )
    if warning_evidence_unavailable:
        return [{
            "title": "Score warning changes unavailable",
            "detail": "Current or previous warning evidence is unavailable; warning changes require manual review.",
            "status": "unavailable",
            "severity": "warning",
            "as_of": as_of,
            "provenance": "score_history",
        }]
    added = sorted({warning for change in report.changes for warning in change.warnings_added})
    removed = sorted({warning for change in report.changes for warning in change.warnings_removed})
    if not added and not removed:
        return [{"title": "No new or removed score warnings", "detail": "The latest two local score runs have no warning-flag changes.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "score_history"}]
    parts = []
    if added:
        parts.append("added=" + ", ".join(added[:4]))
    if removed:
        parts.append("removed=" + ", ".join(removed[:4]))
    return [{"title": "New/removed score warnings", "detail": "; ".join(parts), "status": "available", "severity": "warning", "as_of": as_of, "provenance": "score_history"}]


def _alert_record(readback: AlertReadback, *, as_of: str | None) -> list[dict[str, object]]:
    if readback.status != "available":
        return [{"title": "Local alerts unavailable", "detail": "Alert storage could not be read; current warnings require manual review.", "status": "unavailable", "severity": "warning", "as_of": as_of, "provenance": "local_alerts"}]
    if not readback.records:
        return [{"title": "No active local warnings", "detail": "The local alert seam is available and contains no active records.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "local_alerts"}]
    critical = any(record.alert.severity.value == "critical" for record in readback.records)
    subjects = ", ".join(sorted({record.alert.subject_id for record in readback.records})[:5])
    return [{"title": f"{len(readback.records)} active local warning(s)", "detail": f"Review: {subjects}.", "status": "available", "severity": "critical" if critical else "warning", "as_of": as_of, "provenance": "local_alerts"}]


def _model_failure_record(readback: AlertReadback, *, as_of: str | None) -> list[dict[str, object]] | None:
    if readback.status != "available":
        return [{"title": "Model failure status unavailable", "detail": "Local alert storage could not be read, so model failures cannot be ruled out.", "status": "unavailable", "severity": "warning", "as_of": as_of, "provenance": "local_alerts"}]
    failures = [record for record in readback.records if record.alert.alert_type is AlertType.MODEL_FORECAST_FAILURE]
    if not failures:
        return [{"title": "No active model failures", "detail": "No model-forecast failure alert is registered in the local alert seam.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "local_alerts"}]
    subjects = ", ".join(sorted({record.alert.subject_id for record in failures})[:5])
    return [{"title": "Model failures require review", "detail": f"Forecast failure alerts: {subjects}.", "status": "available", "severity": "critical", "as_of": as_of, "provenance": "local_alerts"}]


def _manual_review_record(report, scores, *, as_of: str | None) -> list[dict[str, object]] | None:
    identifiers = {change.instrument_id for change in (report.changes if report is not None else ()) if "review" in change.current_action.casefold()}
    identifiers.update(
        str(getattr(score, "display_id", ""))
        for score in scores
        if any(
            "review" in str(getattr(score, field, "")).casefold()
            for field in ("decision", "final_action")
        )
    )
    identifiers.discard("")
    if report is None and not scores:
        return None
    if not identifiers:
        return [{"title": "No instrument is flagged for manual review", "detail": "Current local score and display evidence contains no manual-review decision.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "score_history/dashboard_scores"}]
    return [{"title": f"{len(identifiers)} instrument(s) need manual review", "detail": ", ".join(sorted(identifiers)[:6]), "status": "manual_review", "severity": "warning", "as_of": as_of, "provenance": "score_history/dashboard_scores"}]


def _stale_data_record(state: AppState, alerts: AlertReadback, *, as_of: str | None) -> list[dict[str, object]]:
    status = str(getattr(getattr(state.snapshot, "data_report", None), "status", "") or "").casefold()
    stale_subjects = sorted({record.alert.subject_id for record in alerts.records if record.alert.alert_type is AlertType.STALE_DATA}) if alerts.status == "available" else []
    if alerts.status != "available" or not status:
        return [{"title": "Stale-data status unavailable", "detail": "The data-health or alert input is unavailable; freshness requires manual review.", "status": "unavailable", "severity": "warning", "as_of": as_of, "provenance": "data_report/local_alerts"}]
    if status == "clean" and not stale_subjects:
        return [{"title": "No stale data warning is registered", "detail": "The current data-health report is Clean and no stale-data alert is active.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "data_report/local_alerts"}]
    detail = f"data health={status}"
    if stale_subjects:
        detail += "; stale alerts=" + ", ".join(stale_subjects[:5])
    return [{"title": "Stale or non-clean data needs review", "detail": detail, "status": "manual_review", "severity": "warning", "as_of": as_of, "provenance": "data_report/local_alerts"}]


def _contradiction_record(
    state: AppState,
    *,
    as_of: str | None,
    cutoff: object | None = None,
) -> list[dict[str, object]]:
    try:
        news = sort_news_items(load_news_items(NEWS_CLEAN_PATH))
        prices = getattr(state.snapshot, "prices", pd.DataFrame())
        filtered_inputs = filter_news_contradiction_inputs(
            news,
            prices,
            cutoff if cutoff is not None else normalise_event_decision_time(as_of),
        )
        macro = MacroWarehouse().summary(root=ROOT, decision_time=as_of)
    except (MacroWarehouseError, OSError, TypeError, ValueError):
        return [{"title": "News/macro contradiction status unavailable", "detail": "Local contradiction inputs could not be read; no contradiction is inferred.", "status": "unavailable", "severity": "warning", "as_of": as_of, "provenance": "news_context/macro_warehouse"}]
    if filtered_inputs is None:
        return [{"title": "News/macro contradictions unavailable", "detail": "Point-in-time news or adjusted-price evidence is missing, malformed, or unavailable at the snapshot cutoff; no contradiction is inferred.", "status": "unavailable", "severity": "warning", "as_of": as_of, "provenance": "news_context/adjusted_prices/macro_warehouse"}]
    filtered_news, filtered_prices = filtered_inputs
    contradictions = build_news_contradiction_rows(filtered_news, filtered_prices)
    macro_status = str(macro.get("status", "unavailable"))
    count = len(contradictions)
    detail = f"{count} deterministic news contradiction(s); macro contradiction comparison is unavailable (macro context={macro_status})."
    return [{"title": "News/macro contradiction status", "detail": detail, "status": "manual_review", "severity": "warning", "as_of": as_of, "provenance": "news_context/adjusted_prices/macro_warehouse"}]


def _event_record(*, as_of: str | None, cutoff: object | None = None) -> list[dict[str, object]] | None:
    decision_time = cutoff if isinstance(cutoff, pd.Timestamp) else normalise_event_decision_time(as_of)
    if decision_time is None:
        return None
    try:
        events = load_calendar_events(EVENT_CLEAN_PATH)
        events = events_available_as_of(events, decision_time) if not events.empty else events
    except (OSError, TypeError, ValueError):
        return [{"title": "Upcoming events unavailable", "detail": "The local event calendar could not be read at the snapshot decision time.", "status": "unavailable", "severity": "warning", "as_of": as_of, "provenance": "event_calendar"}]
    if events.empty:
        return [{"title": "Upcoming events unavailable", "detail": "No validated event records are available at the snapshot decision time.", "status": "unavailable", "severity": "warning", "as_of": as_of, "provenance": "event_calendar"}]
    upcoming = events[pd.to_datetime(events["event_date"], errors="coerce").dt.date >= decision_time.date()]
    if upcoming.empty:
        return [{"title": "No upcoming validated events", "detail": "The available local event calendar contains no event on or after the snapshot date.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "event_calendar"}]
    labels = ", ".join(f"{row.get('instrument_id', 'unavailable')} {row.get('event_date', 'unavailable')}" for _, row in upcoming.head(4).iterrows())
    return [{"title": f"{len(upcoming)} upcoming event(s)", "detail": labels, "status": "available", "severity": "warning", "as_of": as_of, "provenance": "event_calendar"}]


def _audit_export_record(state: AppState, *, as_of: str | None) -> list[dict[str, object]]:
    export_path = getattr(state, "last_export_path", None)
    activities = tuple(getattr(state, "recent_activity", ()) or ())
    failures = [entry for entry in activities if "export" in str(getattr(entry, "label", "")).casefold() and str(getattr(entry, "status", "")).casefold() in {"failed", "unavailable", "cancelled", "interrupted"}]
    if failures:
        return [{"title": "Recent audit/export failed", "detail": str(getattr(failures[-1], "message", "Manual review is required.")), "status": "manual_review", "severity": "warning", "as_of": as_of, "provenance": "session_activity"}]
    if export_path:
        return [{"title": "Audit/export available", "detail": f"Latest packet: {Path(str(export_path)).name}.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "session_activity"}]
    return [{"title": "No recent audit/export in this session", "detail": "No local audit packet export has been recorded; export status is informational and does not change authority.", "status": "available", "severity": "info", "as_of": as_of, "provenance": "session_activity"}]


def _run_changes_digest(_page: ft.Page, _state: AppState) -> ft.Control:
    """Show a deterministic, informational summary of the latest run delta."""

    history = score_history_frame()
    if history.empty or "run_id" not in history.columns:
        body: ft.Control = ft.Text("Run changes unavailable; complete two score runs to populate the digest.", color=theme.MUTED, selectable=True)
    else:
        if "run_completed_at" in history.columns:
            history = history.sort_values(["run_completed_at", "run_id"], kind="stable")
        runs = list(dict.fromkeys(history["run_id"].astype(str).tolist()))
        current = runs[-1]
        previous = runs[-2] if len(runs) > 1 else None
        report = compare_runs(history, current, previous)
        lines = [ft.Text(report.summary, color=theme.MUTED, selectable=True)]
        for change in report.changes[:5]:
            lines.append(ft.Text(f"{change.instrument_id}: {change.summary}", color=theme.MUTED, selectable=True, size=11))
        body = ft.Column(lines, spacing=4)
    return panel(
        ft.Column(
            [
                section_header("Run changes digest", "Latest score-run differences are deterministic, informational and cannot change current action authority."),
                body,
                ft.TextButton("Open What Changed", key="dashboard.open-what-changed", on_click=lambda _event: _go_to(_page, _state, "/what-changed")),
            ],
            spacing=8,
        )
    )


def _news_digest(page: ft.Page, state: AppState) -> ft.Control:
    """Show the latest canonical news context without granting authority."""

    frame = sort_news_items(load_news_items(NEWS_CLEAN_PATH))
    if frame.empty:
        body: ft.Control = ft.Text("News unavailable; no timestamp-validated local context is registered.", color=theme.MUTED, selectable=True)
    else:
        rows = []
        for _, row in frame.tail(4).iterrows():
            rows.append(ft.Text(
                f"{row.get('published_at', 'unavailable')} | {row.get('headline', 'Headline unavailable')} | {row.get('provider_name', 'provider unavailable')} | timestamp={row.get('timestamp_status', 'unavailable')} | context_only=true | executable_authority=false",
                color=theme.MUTED,
                selectable=True,
                size=11,
            ))
        body = ft.Column(rows, spacing=4)
    return panel(
        ft.Column(
            [
                section_header("News & context digest", "Recent local news is dated, source-linked context only and cannot change deterministic scores or actions."),
                body,
                ft.TextButton("Open News & Context", key="dashboard.open-news-context", on_click=lambda _event: _go_to(page, state, "/news-context")),
            ],
            spacing=8,
        )
    )


def _read_alerts(
    *,
    subject_id: str | None = None,
    as_of: datetime | str | None = None,
    include_inactive: bool = False,
    limit: int | None = 8,
) -> AlertReadback:
    try:
        return read_local_alerts(
            ROOT,
            subject_id=subject_id,
            as_of=as_of,
            include_inactive=include_inactive,
            limit=limit,
        )
    except Exception:
        return AlertReadback("unavailable")


def _alert_colour(record: AlertRecord) -> str:
    return {
        "critical": theme.RED,
        "warning": theme.AMBER,
        "info": theme.CYAN,
    }.get(record.alert.severity.value, theme.MUTED)


def _alert_row(page: ft.Page | None, state: AppState, record: AlertRecord, *, actions: bool) -> ft.Control:
    alert = record.alert
    status = f"status={alert.status.value}"
    text = ft.Text(
        f"{alert.title} | {alert.message} | type={alert.alert_type.value} | severity={alert.severity.value} | confidence={alert.confidence.value} | subject={alert.subject_id} | {status} | execution_allowed=false",
        color=theme.MUTED,
        selectable=True,
        size=11,
        max_lines=4,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    controls: list[ft.Control] = [evidence_chip(alert.severity.value, alert.alert_type.value, _alert_colour(record)), text]
    if actions and alert.status is AlertStatus.ACTIVE:
        controls.extend(
            [
                ft.TextButton(
                    "Dismiss",
                    key=f"alert.dismiss.{alert.alert_id}",
                    on_click=lambda _event: _dismiss_alert(page, state, record),
                ),
                ft.TextButton(
                    "Snooze 1 day",
                    key=f"alert.snooze.{alert.alert_id}",
                    on_click=lambda _event: _snooze_alert(page, state, record),
                ),
            ]
        )
    return ft.Column([ft.Row(controls, spacing=8, wrap=True)], spacing=4)


def _alerts_digest(page: ft.Page, state: AppState) -> ft.Control:
    readback = _read_alerts()
    if readback.status != "available":
        return state_panel(
            "error",
            "Alerts unavailable",
            "Local alert storage could not be read; manual review is required.",
            details="Alert state is unavailable; execution_allowed=false",
        )
    records = readback.records
    body: ft.Control = (
        ft.Column([_alert_row(page, state, record, actions=True) for record in records], spacing=6)
        if records
        else ft.Text("No active local alerts or review reminders.", color=theme.MUTED, selectable=True)
    )
    return panel(
        ft.Column(
            [
                section_header(
                    "Alerts & review reminders",
                    "Local informational alerts with typed severity/confidence; defaults never block scores, models, portfolios or orders.",
                ),
                body,
            ],
            spacing=8,
        )
    )


def _alert_history_panel(page: ft.Page, state: AppState) -> ft.Control:
    readback = _read_alerts(include_inactive=True)
    if readback.status != "available":
        return state_panel(
            "error",
            "Alert history unavailable",
            "Local alert history could not be read; manual review is required.",
            details="Alert history is unavailable; execution_allowed=false",
        )
    records = readback.records
    body: ft.Control = (
        ft.Column([_alert_row(page, state, record, actions=False) for record in records], spacing=6)
        if records
        else ft.Text("No local alert history.", color=theme.MUTED, selectable=True)
    )
    return ft.Column(
        [
            ft.Text("Alert history", color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12),
            body,
        ],
        spacing=6,
    )


def _dismiss_alert(page: ft.Page | None, state: AppState, record: AlertRecord) -> None:
    try:
        dismiss_local_alert(ROOT, record.alert_id, expected_revision=record.revision)
        state.last_message = "Alert dismissed locally."
    except Exception as exc:
        state.last_message = (
            "Alert changed elsewhere; refresh required."
            if isinstance(exc, AlertRevisionConflict)
            else "Alert dismissal unavailable; manual review required."
        )
    if page is not None:
        _rebuild(page, state)


def _snooze_alert(page: ft.Page | None, state: AppState, record: AlertRecord) -> None:
    try:
        until = datetime.now(timezone.utc) + timedelta(days=1)
        snooze_local_alert(ROOT, record.alert_id, until, expected_revision=record.revision)
        state.last_message = "Alert snoozed locally for one day."
    except Exception as exc:
        state.last_message = (
            "Alert changed elsewhere; refresh required."
            if isinstance(exc, AlertRevisionConflict)
            else "Alert snooze unavailable; manual review required."
        )
    if page is not None:
        _rebuild(page, state)


def _summary_cards(
    state: AppState,
    best: SimpleInstrumentScore | None,
    configured_count: int,
    candidate_count: int,
    sparebanken_count: int,
    model_pairs: int,
    *,
    narrow: bool,
) -> ft.Control:
    total_count = configured_count + candidate_count + sparebanken_count
    data_status = state.snapshot.data_report.status
    mode = "Manual review" if data_status == "Blocked" else "Caution" if data_status == "Warning" else "Normal"
    best_score = None if best is None else best.final_score_10
    top_score_value = "N/A" if best_score is None else f"{best_score:.1f}/10"
    top_score_subtitle = "No scores yet" if best is None or best_score is None else f"{best.display_id} - {best.decision}"
    card_controls = [
        metric_card("Instruments", str(total_count), f"{configured_count} primary, {candidate_count} secondary, {sparebanken_count} Sparebanken", theme.CYAN),
        metric_card(
            "Top score",
            top_score_value,
            top_score_subtitle,
            score_colour(best_score),
        ),
        metric_card("Data health", data_status, f"as of {state.snapshot.data_report.as_of_date}", theme.GREEN if data_status == "Clean" else theme.AMBER),
        metric_card("Model rows", str(model_pairs), "valid baseline/Toto/TimesFM pairs", theme.PURPLE),
        metric_card(
            "Regime",
            "N/A" if best is None else best.market_regime_label,
            "yfinance market context" if best is not None else "run scores",
            score_colour(None if best is None else best.market_regime_score_10),
        ),
        metric_card("Final mode", mode, "advisory scoring only", theme.RED if mode == "Manual review" else theme.AMBER if mode == "Caution" else theme.GREEN),
    ]
    return ft.Column(card_controls, spacing=8) if narrow else ft.Row(card_controls, spacing=12)


def _action_bar(page: ft.Page, state: AppState) -> ft.Control:
    return panel(
        ft.Column(
            [
                section_header("Workflow", "Refresh yfinance data, run algorithms, run forecasting models, then inspect the scores."),
                ft.Row(
                    [
                        _workflow_button(
                            "1. Refresh yfinance data",
                            key_name="dashboard.refresh-yfinance",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda _event: _run_action(page, state, "Refresh yfinance data", state.refresh_yfinance_data),
                            width=220,
                        ),
                        _workflow_button(
                            "2. Run algorithms",
                            key_name="dashboard.run-algorithms",
                            icon=ft.Icons.AUTO_GRAPH,
                            on_click=lambda _event: _run_action(page, state, "Run algorithms", state.run_algorithm_scores),
                            width=190,
                        ),
                        _workflow_button(
                            "3. Run forecasting models",
                            key_name="dashboard.run-forecasting-models",
                            icon=ft.Icons.MODEL_TRAINING,
                            on_click=lambda _event: _run_action(page, state, "Run forecasting models", state.run_forecasting_models),
                            width=245,
                        ),
                        _workflow_button(
                            "4. Show scores",
                            key_name="dashboard.show-scores",
                            icon=ft.Icons.SCORE,
                            on_click=lambda _event: _go_to(page, state, "/signals"),
                            width=170,
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Text(state.last_message, color=theme.MUTED, size=12),
            ],
            spacing=10,
        )
    )


def _activity_panel(state: AppState, *, page: ft.Page | None = None) -> ft.Control:
    current = state.current_activity
    rows: list[ft.Control] = []
    if current is not None:
        rows.extend(
            [
                ft.Row(
                    [
                        ft.ProgressRing(width=18, height=18, stroke_width=2, color=theme.CYAN),
                        ft.Text(current.label, color=theme.TEXT, weight=ft.FontWeight.BOLD),
                        evidence_chip("Status", "running", theme.CYAN),
                        ft.TextButton(
                            "Cancel",
                            key="activity.cancel",
                            on_click=lambda _event: _cancel_activity(page, state),
                        ),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.ProgressBar(
                    value=(current.completed_units / current.total_units if current.total_units else None),
                    color=theme.CYAN,
                    bgcolor=theme.SURFACE_2,
                ),
                ft.Text(f"Current step: {current.step}", color=theme.MUTED),
                ft.Text(f"Started: {current.started_at}", color=theme.MUTED, size=11),
            ]
        )
    else:
        rows.append(ft.Text(state.last_message, color=theme.MUTED))

    recent = list(reversed(state.recent_activity[-5:]))
    if recent:
        rows.append(ft.Text("Recent activity", color=theme.TEXT, weight=ft.FontWeight.BOLD, size=12))
        for entry in recent:
            colour = theme.GREEN if entry.status == "success" else theme.RED if entry.status == "failed" else theme.CYAN
            output = f" | output: {Path(entry.output_path).name}" if entry.output_path else ""
            error = f" | error: {entry.error}" if entry.error else ""
            rows.append(
                ft.Column(
                    [
                        evidence_chip(entry.status, entry.label, colour),
                        ft.Text(
                            f"{entry.finished_at or entry.started_at} | {entry.message}{output}{error}",
                            color=theme.MUTED,
                            size=11,
                            max_lines=3,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=8,
                )
            )
    rows.append(_alert_history_panel(page, state))
    return panel(
        ft.Column(
            [
                section_header("Activity log", "Long-running actions show progress here and are saved to the session trace at logs/session.jsonl."),
                *rows,
            ],
            spacing=8,
        )
    )


def _workflow_button(label: str, *, key_name: str, icon: str, on_click, width: int) -> ft.Control:
    button = ft.OutlinedButton(
        label,
        key=key_name,
        tooltip=label,
        icon=icon,
        on_click=on_click,
    )
    return ft.Container(
        content=button,
        width=width,
        height=42,
    )


def _secondary_actions(page: ft.Page, state: AppState) -> ft.Control:
    return ft.Row(
        [
            ft.OutlinedButton(
                "Renew/import local files",
                key="dashboard.renew-import",
                icon=ft.Icons.DOWNLOAD,
                on_click=lambda _event: _open_renew_dialog(page, state),
            ),
            ft.OutlinedButton(
                "Audit packet",
                key="dashboard.export-audit",
                icon=ft.Icons.CHECK_CIRCLE,
                on_click=lambda _event: _export_pack(page, state),
            ),
            ft.OutlinedButton(
                "Advanced data/model diagnostics",
                key="dashboard.open-data-models",
                icon=ft.Icons.INSIGHTS,
                on_click=lambda _event: _go_to(page, state, "/data-models"),
            ),
        ],
        spacing=10,
        wrap=True,
    )


def _run_action(page: ft.Page, state: AppState, label: str, action: Callable[[], str]) -> None:
    if state.current_activity is not None:
        state.last_message = f"{state.current_activity.label} is still running. Please wait for it to finish."
        _rebuild(page, state)
        return
    entry = state.begin_activity(label, "Starting")
    action_id = entry.action_id
    _rebuild(page, state)

    def worker() -> None:
        try:
            if state.workflow_controller.is_cancel_requested(action_id):
                return
            state.update_activity("Running local workflow", expected_action_id=action_id)
            try:
                page.update()
            except Exception:
                pass
            with state.share_activity(action_id):
                result = action()
            failure = activity_result_error(result)
            if failure:
                raise ActivityUnavailableError(failure)
            message = str(result).strip() if result is not None else str(state.last_message or "").strip()
            if not message:
                raise RuntimeError("Tracked action completed without a readable result message.")
            if state.workflow_controller.is_cancel_requested(action_id):
                return
            state.finish_activity(message, label=label, expected_action_id=action_id)
        except Exception as exc:
            if not state.workflow_controller.is_cancel_requested(action_id):
                state.fail_activity(
                    label,
                    exc,
                    retry_callback=lambda: (_run_action(page, state, label, action), "Retry started.")[1],
                    expected_action_id=action_id,
                )
        finally:
            _restore_cancelled_result(state, action_id)
            state.release_activity(action_id)
            _rebuild(page, state)

    threading.Thread(target=worker, daemon=True).start()


def _cancel_activity(page: ft.Page | None, state: AppState) -> None:
    action_id = state.current_activity.action_id if state.current_activity is not None else None
    state.cancel_activity(expected_action_id=action_id)
    if page is not None:
        _rebuild(page, state)


def _run_dialog_action(page: ft.Page, state: AppState, result_text: ft.Text, label: str, step: str, action: Callable[[], str]) -> None:
    if state.current_activity is not None:
        result_text.value = f"{state.current_activity.label} is still running. Please wait for it to finish."
        page.update()
        return
    entry = state.begin_activity(label, step)
    action_id = entry.action_id
    result_text.value = f"{step}..."
    _rebuild(page, state)

    def worker() -> None:
        try:
            with state.share_activity(action_id):
                raw_result = action()
            failure = activity_result_error(raw_result)
            if failure:
                raise ActivityUnavailableError(failure)
            message = str(raw_result).strip() if raw_result is not None else str(state.last_message or "").strip()
            result_text.value = message
            state.finish_activity(message, label=label, expected_action_id=action_id)
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity(
                label,
                exc,
                retry_callback=lambda: (
                    _run_dialog_action(page, state, result_text, label, step, action),
                    "Retry started.",
                )[1],
                expected_action_id=action_id,
            )
            result_text.value = state.last_message
        finally:
            _restore_cancelled_result(state, action_id, result_text)
            state.release_activity(action_id)
            _rebuild(page, state)

    threading.Thread(target=worker, daemon=True).start()


def _export_pack(page: ft.Page, state: AppState) -> None:
    if state.current_activity is not None:
        state.last_message = f"{state.current_activity.label} is still running. Please wait for it to finish."
        _rebuild(page, state)
        return
    entry = state.begin_activity("Export audit packet", "Writing audit packet")
    action_id = entry.action_id
    _rebuild(page, state)

    def worker() -> None:
        try:
            with state.share_activity(action_id):
                path = state.export_audit_packet()
            state.finish_activity(
                f"Audit packet exported: {path}",
                output_path=path,
                expected_action_id=action_id,
            )
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity(
                "Export audit packet",
                exc,
                retry_callback=lambda: (_export_pack(page, state), "Retry started.")[1],
                expected_action_id=action_id,
            )
        finally:
            _restore_cancelled_result(state, action_id)
            state.release_activity(action_id)
            _rebuild(page, state)

    threading.Thread(target=worker, daemon=True).start()


def _valid_model_pairs(state: AppState) -> int:
    universe_revision = str(
        getattr(state.snapshot, "universe_revision", "")
        or getattr(state, "universe_cache_revision", "")
    )
    candidate_forecasts = load_latest_forecasts(
        "yfinance_candidate_forecasts_*.csv",
        FORECASTS_DIR,
        universe_revision=universe_revision,
    )
    configured_forecasts = filter_forecasts_for_universe(state.snapshot.forecasts, universe_revision)
    forecasts = pd.concat([configured_forecasts, candidate_forecasts], ignore_index=True)
    if forecasts.empty or not {"status", "model_allowed_in_score", "model_name", "etf_id"}.issubset(forecasts.columns):
        return 0
    allowed = forecasts["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    valid = forecasts[(forecasts["status"].astype(str).str.lower() == "ok") & allowed]
    return int(valid[["model_name", "etf_id"]].drop_duplicates().shape[0])


def _open_renew_dialog(page: ft.Page, state: AppState) -> None:
    result_text = ft.Text(
        "Choose a local update action. Imported files are validated before they replace clean data.",
        color=theme.MUTED,
    )

    def close_dialog(_event: ft.ControlEvent | None = None) -> None:
        if hasattr(page, "pop_dialog"):
            page.pop_dialog()
            return
        dialog.open = False
        page.update()

    def dry_run(_event: ft.ControlEvent) -> None:
        _run_dialog_action(page, state, result_text, "Validate current data", "Running dry-run validation", state.renew_data_dry_run)

    def api_status(_event: ft.ControlEvent) -> None:
        _run_dialog_action(page, state, result_text, "Use API/yfinance provider", "Checking provider configuration", state.renew_data_api_status)

    def rollback_prices(_event: ft.ControlEvent) -> None:
        _run_dialog_action(page, state, result_text, "Rollback prices", "Searching previous clean price snapshot", state.rollback_latest_prices)

    file_picker = ft.FilePicker(key="dashboard.renew-import.file-picker")
    try:
        if file_picker not in page.services:
            page.services.append(file_picker)
    except Exception:
        try:
            if file_picker not in page.overlay:
                page.overlay.append(file_picker)
        except Exception:
            pass

    def start_import_worker(
        dataset_type: str,
        action_id: str,
        *,
        selected_path: str | None = None,
        selected_bytes: bytes | None = None,
        selected_name: str = "upload",
    ) -> threading.Thread:
        def worker() -> None:
            try:
                state.update_activity(
                    f"Validating selected {dataset_type} file",
                    expected_action_id=action_id,
                )
                with state.share_activity(action_id):
                    if selected_path:
                        message = state.validate_local_import(selected_path, dataset_type)
                    elif selected_bytes is not None:
                        message = state.import_local_upload(selected_name, selected_bytes, dataset_type)
                    else:
                        raise ActivityUnavailableError("Selected file did not expose a path or readable bytes.")
                state.finish_activity(message, expected_action_id=action_id)
            except Exception as exc:
                if not state.activity_was_cancelled(action_id):
                    state.fail_activity(
                        f"Import {dataset_type}",
                        exc,
                        retry_callback=lambda: start_import(
                            dataset_type,
                            selected_path=selected_path,
                            selected_bytes=selected_bytes,
                            selected_name=selected_name,
                        ),
                        expected_action_id=action_id,
                    )
            finally:
                _restore_cancelled_result(state, action_id, result_text)
                state.release_activity(action_id)
                _rebuild(page, state)

        background = threading.Thread(target=worker, daemon=True)
        background.start()
        return background

    def start_import(
        dataset_type: str,
        *,
        selected_path: str | None = None,
        selected_bytes: bytes | None = None,
        selected_name: str = "upload",
    ) -> threading.Thread:
        entry = state.begin_activity(f"Import {dataset_type}", "Validating selected file")
        action_id = entry.action_id
        result_text.value = f"Importing selected {dataset_type} file..."
        _rebuild(page, state)
        return start_import_worker(
            dataset_type,
            action_id,
            selected_path=selected_path,
            selected_bytes=selected_bytes,
            selected_name=selected_name,
        )

    async def import_file(dataset_type: str) -> None:
        entry = state.begin_activity(f"Import {dataset_type}", "Opening local file picker")
        action_id = entry.action_id
        worker_started = False
        result_text.value = f"Opening local file picker for {dataset_type}..."
        _rebuild(page, state)
        try:
            files = await file_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["csv", "xlsx", "xls", "json", "jsonl", "parquet", "pq"],
                allow_multiple=False,
                with_data=True,
            )
            if not files:
                result_text.value = "No local file selected."
                state.finish_activity("No local file selected.", expected_action_id=action_id)
                return
            selected = files[0]
            selected_path = str(selected.path) if getattr(selected, "path", None) else None
            selected_bytes = bytes(selected.bytes) if getattr(selected, "bytes", None) is not None else None
            selected_name = str(getattr(selected, "name", "upload"))
            if state.activity_was_cancelled(action_id):
                return
            start_import_worker(
                dataset_type,
                action_id,
                selected_path=selected_path,
                selected_bytes=selected_bytes,
                selected_name=selected_name,
            )
            worker_started = True
            return
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity(f"Import {dataset_type}", exc, expected_action_id=action_id)
            result_text.value = state.last_message
        finally:
            if not worker_started:
                _restore_cancelled_result(state, action_id, result_text)
                state.release_activity(action_id)
                _rebuild(page, state)

    async def import_prices(_event: ft.ControlEvent) -> None:
        await import_file("prices")

    async def import_manual_notes(_event: ft.ControlEvent) -> None:
        await import_file("manual_news")

    async def import_etf_factsheets(_event: ft.ControlEvent) -> None:
        await import_file("etf_metadata")

    async def import_etf_holdings(_event: ft.ControlEvent) -> None:
        await import_file("etf_holdings")

    async def import_fx_rates(_event: ft.ControlEvent) -> None:
        await import_file("fx")

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Renew local data", color=theme.TEXT),
        content=ft.Container(
            width=640,
            height=430,
            content=ft.Column(
                [
                    ft.Text("Local imports", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                    ft.Text("Prices, FX, ETF factsheets, holdings and notes are copied to raw storage, validated, then committed only if clean enough.", color=theme.MUTED),
                    ft.Row(
                        [
                            ft.TextButton("Import prices", key="dashboard.import-prices", on_click=import_prices),
                            ft.TextButton("Import manual notes", key="dashboard.import-manual-notes", on_click=import_manual_notes),
                            ft.TextButton("Import ETF factsheets", key="dashboard.import-etf-factsheets", on_click=import_etf_factsheets),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.TextButton("Import ETF holdings", key="dashboard.import-etf-holdings", on_click=import_etf_holdings),
                            ft.TextButton("Import FX rates", key="dashboard.import-fx-rates", on_click=import_fx_rates),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Text("API provider", color=theme.TEXT, weight=ft.FontWeight.BOLD),
                    ft.Text("With yfinance configured, this refreshes Yahoo data. Without provider details, it returns a safe message.", color=theme.MUTED),
                    result_text,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
        actions=[
            ft.TextButton("Use API/yfinance provider", key="dashboard.renew-api-status", on_click=api_status),
            ft.TextButton("Validate current data", key="dashboard.renew-dry-run", on_click=dry_run),
            ft.TextButton("Rollback prices", key="dashboard.renew-rollback", on_click=rollback_prices),
            ft.TextButton("Close", key="dashboard.renew-close", on_click=close_dialog),
        ],
    )
    if hasattr(page, "show_dialog"):
        page.show_dialog(dialog)
    else:
        page.dialog = dialog
        dialog.open = True
        page.update()
