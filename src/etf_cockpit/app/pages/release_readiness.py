"""Read-only release readiness evidence surface."""

from __future__ import annotations

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.components.governance_badges import status_badge
from etf_cockpit.app.state import AppState
from etf_cockpit.application.quality_programme import load_quality_programme_report
from etf_cockpit.application.ui_facade import legal_terms_report, release_certification_report
from etf_cockpit.core.paths import ROOT


def release_readiness_page(_page: ft.Page | None, _state: AppState) -> ft.Control:
    try:
        certification = release_certification_report(ROOT)
    except Exception as exc:  # presentation remains fail-closed if local evidence is malformed
        certification = {
            "status": "blocked",
            "issue_id": "ISSUE-0152",
            "network_calls": False,
            "execution_allowed": False,
            "registry_sha256": "unavailable",
            "release_commit": "unavailable",
            "blockers": [f"certification evidence unavailable: {type(exc).__name__}: {exc}"],
            "accepted_limitations": [],
            "checks": [],
        }
    try:
        legal = legal_terms_report(ROOT)
        legal_status = f"{legal.get('status', 'failed')} ({legal.get('review_status', 'unavailable')})"
        legal_checksum = str(legal.get("registry_sha256", "unavailable"))
    except Exception as exc:
        legal_status = f"blocked ({type(exc).__name__})"
        legal_checksum = "unavailable"
    quality = load_quality_programme_report(ROOT)
    quality_status = str(quality.get("status", "not_run"))
    quality_colour = theme.GREEN if quality_status == "passed" else theme.AMBER
    quality_suites = quality.get("suites", []) or []
    quality_suite_lines = [
        ft.Text(
            f"{suite.get('suite_id', 'unknown')}: {suite.get('status', 'unknown')} ({suite.get('duration_ms', 0)} ms)",
            color=theme.TEXT if suite.get("status") == "passed" else theme.AMBER,
            size=11,
            selectable=True,
        )
        for suite in quality_suites
        if isinstance(suite, dict)
    ]
    quality_failures = [str(item) for item in quality.get("failures", [])]

    status = str(certification.get("status", "blocked"))
    status_colour = theme.GREEN if status == "passed" else theme.RED
    blockers = [str(item) for item in certification.get("blockers", [])]
    if len(blockers) > 10:
        blockers = blockers[:10] + [f"{len(certification.get('blockers', [])) - 10} additional blockers are recorded in the local JSON report."]
    limitations = [str(item) for item in certification.get("accepted_limitations", [])]
    checks = certification.get("checks", []) or []
    check_lines = [
        ft.Text(
            f"{check.get('check_id', 'unknown')}: {check.get('status', 'blocked')} - {check.get('evidence', '')}",
            color=theme.TEXT if check.get("status") == "passed" else theme.AMBER,
            size=11,
            selectable=True,
        )
        for check in checks
    ]
    blocker_lines = [ft.Text(f"- {item}", color=theme.AMBER, size=11, selectable=True) for item in blockers] or [ft.Text("- None", color=theme.GREEN)]
    limitation_lines = [ft.Text(f"- {item}", color=theme.MUTED, size=11, selectable=True) for item in limitations] or [ft.Text("- None recorded", color=theme.MUTED)]
    return ft.Column(
        [
            section_header("Release Readiness", "Evidence-only certification status for the finite completion programme."),
            panel(
                ft.Column(
                    [
                        ft.Row([status_badge("Certification", status, colour=status_colour), status_badge("Execution", "disabled", colour=theme.AMBER)], wrap=True),
                        ft.Text("ISSUE-0152 remains blocked until the closure matrix, mandatory gates and signed release evidence pass.", color=theme.AMBER, selectable=True),
                        ft.Text(f"Release commit: {certification.get('release_commit', 'unavailable')}", color=theme.MUTED, size=11, selectable=True),
                        ft.Text(f"Issue registry SHA-256: {certification.get('registry_sha256', 'unavailable')}", color=theme.MUTED, size=11, selectable=True),
                        ft.Text("Network calls: false · execution_allowed=false", color=theme.MUTED, size=11, selectable=True),
                    ],
                    spacing=8,
                )
            ),
            ft.ResponsiveRow(
                [
                    ft.Container(content=panel(ft.Column([ft.Text("Mandatory checks", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD), *check_lines], spacing=7)), col={"xs": 12, "md": 6}),
                    ft.Container(content=panel(ft.Column([ft.Text("Legal terms", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD), ft.Text(f"Status: {legal_status}", color=theme.AMBER, selectable=True), ft.Text(f"Registry checksum: {legal_checksum}", color=theme.MUTED, size=11, selectable=True), ft.Text("Professional review remains required where recorded by the legal registry.", color=theme.MUTED, size=11, selectable=True)], spacing=7)), col={"xs": 12, "md": 6}),
                ],
                spacing=12,
            ),
            panel(
                ft.Column(
                    [
                        ft.Row([status_badge("Quality programme", quality_status, colour=quality_colour)], wrap=True),
                        ft.Text("ISSUE-0143 bounded local evidence; this surface never starts tests or network calls.", color=theme.MUTED, size=11, selectable=True),
                        ft.Text(f"JSON: {quality.get('report_path', 'unavailable')}", color=theme.MUTED, size=11, selectable=True),
                        ft.Text(f"Markdown: {quality.get('report_paths', {}).get('markdown', 'unavailable') if isinstance(quality.get('report_paths'), dict) else 'unavailable'}", color=theme.MUTED, size=11, selectable=True),
                        *quality_suite_lines,
                        *(ft.Text(f"- {failure}", color=theme.AMBER, size=11, selectable=True) for failure in quality_failures),
                    ],
                    spacing=7,
                )
            ),
            panel(ft.Column([ft.Text("Blockers", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD), *blocker_lines], spacing=7)),
            panel(ft.Column([ft.Text("Accepted limitations", color=theme.TEXT, size=15, weight=ft.FontWeight.BOLD), *limitation_lines], spacing=7)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["release_readiness_page"]
