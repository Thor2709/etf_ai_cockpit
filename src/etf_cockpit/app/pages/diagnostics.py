from __future__ import annotations

import importlib
import os
import platform
import sys

import flet as ft

from etf_cockpit.app.components.chartkit import Segment, horizontal_stacked_bar
from etf_cockpit.app.components.kit import (
    DataTable,
    Disclosure,
    GlassCard,
    KpiTile,
    Note,
    TableColumn,
    Tag,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_count, format_number, format_timestamp
from etf_cockpit.app.state import AppState
from etf_cockpit.application.architecture import build_report as build_architecture_report
from etf_cockpit.application.diagnostics_views import (
    PerformanceBudgetError,
    build_performance_report,
    build_security_report,
    load_events_with_tail_recovery,
)
from etf_cockpit.application.ui_facade import (
    TransactionalStore,
    build_version_registry,
    compatibility_summary,
    load_analysis_parity_report,
)
from etf_cockpit.core.errors import ErrorStore
from etf_cockpit.core.paths import DATA_DIR, LOG_DIR, MODEL_DIR, ROOT
from etf_cockpit.core.session_log import read_session_events, session_log_status
from etf_cockpit.core.timing import timing_summary


def _module_status(name: str) -> str:
    try:
        module = importlib.import_module(name)
        return f"ok {getattr(module, '__version__', '')}"
    except Exception as exc:
        return f"missing: {type(exc).__name__}: {exc}"


def _torch_cuda_status() -> str:
    try:
        import torch

        if not torch.cuda.is_available():
            return "CUDA unavailable"
        return f"CUDA available | {torch.cuda.get_device_name(0)} | torch {torch.__version__}"
    except Exception as exc:
        return f"CUDA check failed: {type(exc).__name__}: {exc}"


def _storage_status() -> str:
    try:
        with TransactionalStore(ROOT) as store:
            report = store.integrity()
        return (
            f"{report.sqlite_integrity}; schema v{report.schema_version}; "
            f"foreign-key violations={len(report.foreign_key_violations)}"
        )
    except Exception as exc:
        return f"unavailable: {type(exc).__name__}: {exc}"


def _availability(value: object) -> str:
    return "Unavailable" if value is None else str(value)


def diagnostics_page(page: ft.Page, state: AppState | None) -> PageView:
    architecture = build_architecture_report(ROOT)
    storage = _storage_status()
    versions = compatibility_summary(build_version_registry(ROOT))
    parity = load_analysis_parity_report()
    parity_status = str(parity.get("status", "unavailable"))
    mismatch = parity.get("first_mismatch")
    parity_tag = (
        Tag("Passed", "ok")
        if parity_status == "passed"
        else Tag("Review required", "bad")
        if parity_status == "failed"
        else Tag("Unavailable", "warn")
    )
    mismatch_note = Note(
        "First mismatch: details available below."
        if isinstance(mismatch, dict)
        else "First mismatch: none recorded."
    )
    parity_details = Disclosure(
        "Analysis parity report details",
        ft.Text(f"Status: {parity_status}; first mismatch: {mismatch!r}"),
    )

    runtime_lines = [
        f"Python: {sys.version}",
        f"Executable: {sys.executable}",
        f"OS: {platform.platform()}",
        f"Working directory: {os.getcwd()}",
        f"Data folder access: {DATA_DIR.exists()} {DATA_DIR}",
        f"Log folder access: {LOG_DIR.exists()} {LOG_DIR}",
        f"Model folder access: {MODEL_DIR.exists()} {MODEL_DIR}",
        f"duckdb: {_module_status('duckdb')}",
        f"flet: {_module_status('flet')}",
        f"pandas: {_module_status('pandas')}",
        f"pyarrow: {_module_status('pyarrow')}",
        f"torch: {_module_status('torch')}",
        f"torch CUDA: {_torch_cuda_status()}",
        f"timesfm: {_module_status('timesfm')}",
        f"toto2: {_module_status('toto2')}",
        f"Presentation boundary: {architecture['status']} ({architecture['violation_count']} violations)",
        f"Local transactional storage: {storage}",
        f"Version registry: {versions['record_count']} records | {versions['available_count']} available | "
        f"signature {str(versions['registry_signature'])[:16]}",
        f"Compatibility: forward-only migrations={versions['forward_only_migrations']} | "
        f"immutable-after-run={versions['immutable_after_run']} | "
        f"rebuild-sensitive={versions['rebuild_sensitive_count']}",
    ]
    runtime_card = GlassCard(
        "Runtime diagnostics",
        note="local machine and model runtime",
        body=ft.Column(
            [
                KpiTile("Python", platform.python_version(), sub="Current runtime version"),
                KpiTile("OS", platform.system(), sub="Current operating system"),
                KpiTile(
                    "Model runtime",
                    None,
                    sub="Unavailable: no consolidated model-runtime readiness result is provided.",
                ),
                Disclosure("Full runtime diagnostics", ft.Column([ft.Text("\n".join(runtime_lines))], spacing=8)),
            ],
            spacing=12,
            expand=True,
        ),
        expand=4,
    )

    timing = timing_summary(LOG_DIR / "timings.jsonl", limit=50)
    timing_records = [
        record
        for record in timing["records"]
        if record.get("event_type") != "cache" and record.get("duration_ms") is not None
    ]
    slow_steps = list(timing["slow_steps"])
    cache_events = list(timing["cache_events"])
    duration_values = [record.get("duration_ms") for record in timing_records]
    if timing_records:
        slowest = max(timing_records, key=lambda record: float(record["duration_ms"]))
        slowest_name = str(slowest.get("step") or "—")
        insight = (
            f"{slowest_name} is slowest ({format_number(slowest.get('duration_ms'), decimals=1)} ms); "
            f"{format_count(len(slow_steps))} steps over budget."
        )
        timing_note = f"{format_count(len(timing_records))} recorded steps · local trace"
        timing_unavailable = None
    else:
        insight = "Unavailable: no recorded steps are available in the local trace."
        timing_note = insight
        timing_unavailable = "No timing records are available in the local trace."
    plotted_records = timing_records[-8:]
    timing_kinds = {"gold" if bool(record.get("slow")) else "blue" for record in plotted_records}
    timing_legend = (
        Note("Legend: within budget (blue) · over budget (gold)")
        if len(timing_kinds) > 1
        else None
    )
    timing_chart = horizontal_stacked_bar(
        [str(record.get("step") or "—") for record in plotted_records],
        [
            [
                Segment(
                    float(record["duration_ms"]),
                    kind="gold" if bool(record.get("slow")) else "blue",
                )
            ]
            for record in plotted_records
        ],
        x_name="Duration (ms)",
        unit=" ms",
        unavailable_reason=timing_unavailable,
        empty_title="Unavailable",
        insight=insight,
    )
    step_card = GlassCard(
        "Step timings",
        note=timing_note,
        body=ft.Column(
            [
                Note(insight),
                Note("Step (name) · Duration (ms)"),
                *([timing_legend] if timing_legend is not None else []),
                Well(timing_chart, expand=True),
                Disclosure(
                    "Timing trace details",
                    ft.Column(
                        [
                            ft.Text(f"Trace path: {LOG_DIR / 'timings.jsonl'}"),
                            ft.Text(f"Recent timing records: {timing_records!r}"),
                        ],
                        spacing=8,
                    ),
                ),
            ],
            spacing=12,
            expand=True,
        ),
        expand=8,
    )

    try:
        budget_report = build_performance_report(ROOT)
    except PerformanceBudgetError as exc:
        budget_report = {"status": "failed", "failures": [str(exc)], "storage_bytes": None}
    duration_count = len(duration_values) if duration_values else None
    slow_count = len(slow_steps) if duration_values else None
    cache_counts = timing["cache_counts"]
    cache_hits = cache_counts.get("hit") if cache_events else None
    cache_misses = cache_counts.get("miss") if cache_events else None
    cache_invalidations = cache_counts.get("invalidation") if cache_events else None
    budget_status = str(budget_report.get("status", "unavailable"))
    budget_tag = (
        Tag("Passed", "ok")
        if budget_status == "passed"
        else Tag("Review required", "bad")
        if budget_status == "failed"
        else Tag("Unavailable", "warn")
    )
    errors = ErrorStore().recent(limit=8)
    active_activity = getattr(state, "current_activity", None)
    performance_card = GlassCard(
        "Performance and recovery",
        note="versioned local budgets and recovery status",
        body=ft.Column(
            [
                ft.Row(
                    [
                        KpiTile("Durations", duration_count, sub="Measured local step durations" if duration_count is not None else "Unavailable: no duration samples."),
                        KpiTile("Slow steps", slow_count, sub="Recorded over-budget steps" if slow_count is not None else "Unavailable: no duration samples."),
                        KpiTile("Cache hits", cache_hits, sub="Local cache events" if cache_hits is not None else "Unavailable: no cache events."),
                        KpiTile("Misses", cache_misses, sub="Local cache events" if cache_misses is not None else "Unavailable: no cache events."),
                        KpiTile("Invalidations", cache_invalidations, sub="Local cache events" if cache_invalidations is not None else "Unavailable: no cache events."),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                ft.Row([Note("Versioned budgets:"), budget_tag], spacing=8, wrap=True),
                Note(f"Controlled errors: {format_count(len(errors))} recent records."),
                Note("A local workflow is active." if active_activity is not None else "No local workflow is active."),
                Disclosure(
                    "Performance and recovery details",
                    ft.Column(
                        [
                            ft.Text(f"Budget report: {budget_report!r}"),
                            ft.Text(
                                f"local storage={format_count(budget_report.get('storage_bytes'), unavailable='Unavailable')} bytes"
                            ),
                            ft.Text(f"Controlled error details: {errors!r}"),
                            ft.Text(f"Current workflow: {getattr(active_activity, 'label', None)}"),
                            ft.Text("Cache counts are unavailable until a cache event is recorded." if not cache_events else f"Cache counts: {cache_counts!r}"),
                        ],
                        spacing=8,
                    ),
                ),
            ],
            spacing=12,
            expand=True,
        ),
        expand=4,
    )

    security_report = build_security_report(ROOT)
    security_status = str(security_report.get("status", "unavailable"))
    security_tag = Tag(
        "Passed" if security_status == "passed" else "Review required" if security_status == "failed" else "Unavailable",
        "ok" if security_status == "passed" else "bad" if security_status == "failed" else "warn",
    )
    security_card = GlassCard(
        "Security policy",
        note="fail-closed local controls",
        body=ft.Column(
            [
                security_tag,
                Note(f"network_calls: {_availability(security_report.get('network_calls'))}"),
                Note(f"default_deny: {_availability(security_report.get('default_deny'))}"),
                Note(
                    "Blocking severities: "
                    + (", ".join(map(str, security_report["blocking_severities"])) if security_report.get("blocking_severities") is not None else "Unavailable")
                ),
                Disclosure(
                    "Security policy details",
                    ft.Column(
                        [
                            ft.Text(f"Policy report: {security_report!r}"),
                            ft.Text(
                                f"network_calls={str(security_report.get('network_calls')).lower()}"
                                if isinstance(security_report.get("network_calls"), bool)
                                else "network_calls=unavailable"
                            ),
                        ],
                        spacing=8,
                    ),
                ),
            ],
            spacing=12,
            expand=True,
        ),
        expand=4,
    )
    parity_card = GlassCard(
        "Analysis parity",
        note="saved replay report",
        body=ft.Column([parity_tag, mismatch_note, parity_details], spacing=12, expand=True),
        expand=4,
    )

    session_status = session_log_status()
    events = list(reversed(read_session_events(limit=40)))
    try:
        _, recovery = load_events_with_tail_recovery(LOG_DIR / "session.jsonl")
        recovery_text = (
            f"Tail recovery: quarantined to {recovery.quarantine_path}"
            if recovery.quarantined_tail
            else "Tail recovery: complete JSONL trace"
        )
    except ValueError as exc:
        recovery_text = f"Tail recovery: integrity error - {exc}"
    session_details = Disclosure(
        "Session details",
        ft.Column(
            [
                ft.Text(f"Session ID: {_availability(session_status.get('session_id'))}"),
                ft.Text(f"Path: {_availability(session_status.get('path'))}"),
                ft.Text(f"Exists: {_availability(session_status.get('exists'))}"),
                ft.Text(f"Size: {_availability(session_status.get('size_bytes'))} bytes"),
                ft.Text(f"Initialised: {_availability(session_status.get('initialised'))}"),
                ft.Text(recovery_text),
            ],
            spacing=8,
        ),
    )
    event_rows = []
    for event in events[:25]:
        severity = str(event.get("severity") or "info").casefold()
        level = Tag("Error", "bad") if severity == "error" else Tag("Warning", "warn") if severity == "warning" else Tag("Info", "ok")
        timestamp = event.get("timestamp_local")
        detail_parts = [
            f"status: {event.get('status')}",
            f"action: {event.get('action_id')}",
            f"operation: {event.get('operation')}",
            f"message: {event.get('user_message')}",
            f"exception: {event.get('exception_type')}: {event.get('exception_message_redacted')}",
            f"fingerprint: {event.get('traceback_fingerprint')}",
        ]
        event_rows.append(
            {
                "time": format_timestamp(timestamp) if timestamp else None,
                "level": level,
                "event": event.get("event_type"),
                "detail": Disclosure("Details", ft.Text("\n".join(part for part in detail_parts if not part.endswith(": None")))),
            }
        )
    events_table = DataTable(
        [
            TableColumn("time", "Time"),
            TableColumn("level", "Level"),
            TableColumn("event", "Event", flex=1),
            TableColumn("detail", "Detail", flex=2),
        ],
        event_rows,
        empty_title="Unavailable",
        empty_reason="No session events are recorded in the local trace.",
        expand=True,
    )
    session_card = GlassCard(
        "Session log",
        note="redacted local app-server trace",
        body=ft.Column(
            [
                Note("Secrets are redacted before writing. Logging failures do not block the app."),
                session_details,
                Note("Recent events"),
                Well(events_table, expand=True),
            ],
            spacing=12,
            expand=True,
        ),
    )

    runtime_view = ft.Column(
        [
            ft.Row([runtime_card, step_card], spacing=24),
            ft.Row([performance_card, security_card, parity_card], spacing=24),
            session_card,
        ],
        spacing=24,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    performance_view = ft.Column(
        [ft.Row([step_card, performance_card], spacing=24)],
        spacing=24,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    session_view = ft.Column([session_card], spacing=24, expand=True, scroll=ft.ScrollMode.AUTO)
    body_slot = ft.Column([runtime_view], spacing=24, expand=True)
    views = {"Runtime": runtime_view, "Performance": performance_view, "Session log": session_view}

    def select_segment(value: str) -> None:
        body_slot.controls = [views[value]]
        if page is not None:
            page.update()

    return PageView(
        chrome=PageChrome(
            title="Diagnostics",
            subtitle="Configuration, local service state and performance budgets · no external telemetry",
            segment_groups=(
                SegmentGroup("diagnostics", ("Runtime", "Performance", "Session log"), "Runtime", on_change=select_segment),
            ),
        ),
        body=body_slot,
    )
