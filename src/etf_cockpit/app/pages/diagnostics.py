from __future__ import annotations

import importlib
import os
import platform
import sys

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.architecture import build_report as build_architecture_report
from etf_cockpit.core.paths import DATA_DIR, LOG_DIR, MODEL_DIR, ROOT
from etf_cockpit.core.session_log import read_session_events, session_log_status
from etf_cockpit.core.errors import ErrorStore
from etf_cockpit.core.timing import timing_summary
from etf_cockpit.operations.event_store import load_events_with_tail_recovery


def _module_status(name: str) -> str:
    try:
        module = importlib.import_module(name)
        return f"ok {getattr(module, '__version__', '')}"
    except Exception as exc:
        return f"missing: {exc}"


def _torch_cuda_status() -> str:
    try:
        import torch

        if not torch.cuda.is_available():
            return "CUDA unavailable"
        return f"CUDA available | {torch.cuda.get_device_name(0)} | torch {torch.__version__}"
    except Exception as exc:
        return f"CUDA check failed: {exc}"


def diagnostics_page(_page: ft.Page, state: AppState) -> ft.Control:
    architecture = build_architecture_report(ROOT)
    lines = [
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
    ]
    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Runtime diagnostics", "Local paths, Python packages and model-runtime readiness."),
                        ft.Text("\n".join(lines), color=theme.MUTED, selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                )
            ),
            _session_log_panel(),
            _performance_panel(state),
        ],
        spacing=14,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _performance_panel(state: AppState) -> ft.Control:
    timing_path = LOG_DIR / "timings.jsonl"
    summary = timing_summary(timing_path, limit=50)
    timing_records = list(summary["records"])
    durations = list(summary["durations_ms"])
    slow_steps = list(summary["slow_steps"])
    cache_counts = dict(summary["cache_counts"])
    errors = ErrorStore().recent(limit=8)
    rows: list[ft.Control] = [
        ft.Text(f"Timing trace: {timing_path} | {len(timing_records)} parsed records", color=theme.MUTED, selectable=True),
        ft.Text(
            f"Durations: {len(durations)} | slow steps: {len(slow_steps)} | "
            f"cache hits: {cache_counts.get('hit', 0)} | misses: {cache_counts.get('miss', 0)} | "
            f"invalidations: {cache_counts.get('invalidation', 0)}",
            color=theme.MUTED,
            selectable=True,
        ),
        ft.Text(f"Controlled errors: {len(errors)} recent records", color=theme.MUTED),
        ft.Text(f"Current workflow: {state.current_activity.label if state.current_activity else 'idle'}", color=theme.MUTED),
    ]
    for record in reversed(timing_records[-6:]):
        if record.get("event_type") == "cache":
            text = (
                f"cache {record.get('cache_name')} {record.get('cache_status')} "
                f"action={record.get('action_id') or 'n/a'}"
            )
        else:
            text = (
                f"{record.get('step', 'step')} | {record.get('duration_ms', 'n/a')} ms | "
                f"slow={record.get('slow', False)} | action={record.get('action_id') or 'n/a'}"
            )
        rows.append(ft.Text(text, color=theme.MUTED, size=11, selectable=True))
    return panel(ft.Column([section_header("Performance and recovery", "Workflow timing, slow-step visibility and controlled error counts."), *rows], spacing=6))


def _session_log_panel() -> ft.Control:
    status = session_log_status()
    events = list(reversed(read_session_events(limit=40)))
    try:
        _, recovery = load_events_with_tail_recovery(LOG_DIR / "session.jsonl")
        integrity_text = (
            f"Tail recovery: quarantined to {recovery.quarantine_path}"
            if recovery.quarantined_tail
            else "Tail recovery: complete JSONL trace"
        )
    except ValueError as exc:
        integrity_text = f"Tail recovery: integrity error - {exc}"
    rows: list[ft.Control] = [
        ft.Text(f"Session ID: {status.get('session_id')}", color=theme.TEXT, selectable=True),
        ft.Text(f"Path: {status.get('path')}", color=theme.MUTED, selectable=True),
        ft.Text(
            f"Exists: {status.get('exists')} | Size: {status.get('size_bytes')} bytes | Initialised: {status.get('initialised')}",
            color=theme.MUTED,
            selectable=True,
        ),
        ft.Text("Secrets are redacted before writing. Logging failures do not block the app.", color=theme.MUTED),
        ft.Text(integrity_text, color=theme.MUTED, selectable=True),
    ]
    if not events:
        rows.append(ft.Text("No session events recorded yet. Start the app server or press a workflow button.", color=theme.MUTED))
    else:
        rows.append(ft.Text("Recent events", color=theme.TEXT, weight=ft.FontWeight.BOLD))
        for event in events[:25]:
            severity = str(event.get("severity") or "info").lower()
            colour = theme.RED if severity == "error" else theme.AMBER if severity == "warning" else theme.CYAN
            title = (
                f"{event.get('sequence_number')} | {event.get('event_type')} | "
                f"{event.get('status') or 'n/a'} | {event.get('button_label') or event.get('operation') or ''}"
            )
            detail = (
                f"{event.get('timestamp_local')} | action={event.get('action_id') or 'n/a'} | "
                f"message={event.get('user_message') or ''}"
            )
            if event.get("exception_type") or event.get("traceback_fingerprint"):
                detail += (
                    f" | exception={event.get('exception_type') or 'n/a'}: "
                    f"{event.get('exception_message_redacted') or 'n/a'}"
                    f" | fingerprint={event.get('traceback_fingerprint') or 'n/a'}"
                )
            rows.append(
                ft.Container(
                    bgcolor=theme.SURFACE_2,
                    border_radius=6,
                    padding=8,
                    content=ft.Column(
                        [
                            ft.Text(title, color=colour, size=12, weight=ft.FontWeight.BOLD),
                            ft.Text(detail, color=theme.MUTED, size=11, selectable=True),
                        ],
                        spacing=3,
                    ),
                )
            )
    return panel(
        ft.Column(
            [
                section_header("Session log", "Current app-server action trace from logs/session.jsonl."),
                *rows,
            ],
            spacing=8,
        )
    )
