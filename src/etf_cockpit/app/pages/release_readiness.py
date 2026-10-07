"""Read-only release readiness evidence surface."""

from __future__ import annotations

import json

import flet as ft

from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.state import AppState
from etf_cockpit.application.quality_programme import load_quality_programme_report
from etf_cockpit.application.ui_facade import legal_terms_report, release_certification_report
from etf_cockpit.core.paths import ROOT


def release_readiness_page(page: ft.Page | None, state: AppState) -> PageView:
    try:
        certification = release_certification_report(ROOT)
    except Exception as exc:
        certification = {
            "status": "blocked",
            "network_calls": False,
            "execution_allowed": False,
            "registry_sha256": None,
            "release_commit": None,
            "blockers": [f"Certification evidence unavailable: {type(exc).__name__}"],
            "accepted_limitations": [],
            "checks": [],
        }
    try:
        legal = legal_terms_report(ROOT)
    except Exception as exc:
        legal = {"status": "unavailable", "review_status": "unavailable", "registry_sha256": None, "unavailable_reason": f"Legal terms evidence unavailable: {type(exc).__name__}"}
    quality = load_quality_programme_report(ROOT)
    try:
        projection = json.loads((ROOT / "docs" / "product-completion" / "CURRENT_STATUS.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        projection = None

    status = str(certification.get("status") or "unavailable")
    headline = "Certification: " + status.replace("_", " ").title()
    quality_status = str(quality.get("status") or "unavailable")
    quality_display = quality_status.replace("_", " ").title()
    legal_status = str(legal.get("status") or "unavailable")
    legal_display = legal_status.replace("_", " ").title()
    legal_review = str(legal.get("review_status") or "").replace("_", " ").title()
    network_calls = certification.get("network_calls")
    certification_note = (
        "Certification remains blocked until the closure matrix, mandatory gates and signed release evidence pass."
        if status.casefold() == "blocked"
        else "Evidence-only certification status for the completion programme."
    )
    strip = kit.KpiStrip(
        "Certification",
        headline,
        certification_note,
        [
            ("Execution", "disabled" if certification.get("execution_allowed") is False else "Unavailable", "Execution remains disabled by policy.", "neg"),
            ("Quality programme", quality_display, str(quality.get("unavailable_reason") or ("Quality programme status is unavailable from local evidence." if quality_status == "unavailable" else "Local quality evidence.")), None),
            ("Legal terms", legal_display, legal_review or ("Legal terms status is unavailable from local evidence." if legal_status == "unavailable" else "Legal terms evidence."), None),
            ("Network calls", "No" if network_calls is False else "Yes" if network_calls is True else "Unavailable", "Unavailable: network-call status is not recorded." if network_calls is None else "Reported by local certification evidence.", None),
        ],
    )

    checks = []
    for check in certification.get("checks", []) or []:
        check_status = str(check.get("status") or "unavailable").casefold()
        passed = True if check_status in {"passed", "pass", "ok"} else False if check_status in {"failed", "blocked", "fail"} else None
        title = str(check.get("check_id") or "Check")
        checks.append(kit.GateCheck(passed, title.replace("_", " ").title(), "See local check evidence details."))
    checks_card = kit.GlassCard(
        "Mandatory checks",
        note="Local certification gates",
        body=ft.Column(
            [
                *(checks or [kit.EmptyState("Checks unavailable", "No mandatory check results are available from the local certification report.")]),
                kit.Disclosure(
                    "Mandatory check evidence",
                    "\n".join(
                        f"{check.get('check_id') or 'Unavailable'} · status={check.get('status') or 'Unavailable'} · evidence={check.get('evidence') or check.get('reason') or 'Unavailable'}"
                        for check in certification.get("checks", []) or []
                        if isinstance(check, dict)
                    ) or "No mandatory check details are available.",
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )

    readiness_rows = [
        kit.ListRow("info", "Release commit", "Available" if certification.get("release_commit") else "Unavailable", tag=("Reference" if certification.get("release_commit") else "Unavailable", "mute" if certification.get("release_commit") else "bad")),
        kit.ListRow("info", "Issue registry SHA-256", "Recorded" if certification.get("registry_sha256") else "Unavailable", tag=("Reference" if certification.get("registry_sha256") else "Unavailable", "mute" if certification.get("registry_sha256") else "bad")),
        kit.ListRow("info", "Readiness projection", "Available" if isinstance(projection, dict) else "Unavailable", tag=("Local" if isinstance(projection, dict) else "Unavailable", "mute" if isinstance(projection, dict) else "bad")),
    ]
    evidence_card = kit.GlassCard(
        "Release evidence",
        body=ft.Column(
            [
                *readiness_rows,
                kit.Disclosure(
                    "Evidence references",
                    f"release_commit={certification.get('release_commit') or 'Unavailable'}\nregistry_sha256={certification.get('registry_sha256') or 'Unavailable'}\nreadiness_projection={ROOT / 'docs' / 'product-completion' / 'CURRENT_STATUS.json'}\n"
                    + ("Readiness projection unavailable; activation remains blocked.\n" if not isinstance(projection, dict) else "")
                    + f"certification_issue={certification.get('issue_id') or 'Unavailable'}\nexecution_allowed=false",
                ),
            ],
            spacing=8,
        ),
        expand=True,
    )

    blockers = list(certification.get("blockers", []) or [])
    blocker_rows = [kit.ListRow("bad", "Certification blocker", "See blocker details in Disclosure.", tag=("Blocked", "bad")) for _item in blockers]
    blocker_card = kit.GlassCard(
        "Blockers",
        body=ft.Column(
            [
                *(blocker_rows or [kit.EmptyState("No blockers recorded", "No blocker details are available from the local report.")]),
                kit.Disclosure("Blocker details", "\n".join(str(item) for item in blockers) or "No blocker details are available from the local report."),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    limitation_copy = [
        "Execution remains disabled; this evidence surface cannot authorise order transmission.",
        "Certification reads local evidence only and makes no network calls.",
        "Optional providers and model weights are not mandatory for the local-first path.",
    ]
    limitation_rows = [kit.ListRow("info", item, tag=("Accepted", "mute")) for item in limitation_copy]
    limitation_rows.extend(kit.ListRow("info", str(item), tag=("Accepted", "mute")) for item in certification.get("accepted_limitations", []) or [])
    limitations_card = kit.GlassCard("Accepted limitations", body=ft.Column(limitation_rows, spacing=4, scroll=ft.ScrollMode.AUTO), expand=True)

    quality_card = kit.GlassCard(
        "Quality programme",
        body=ft.Column(
            [
                kit.Tag(quality_display, "ok" if quality_status == "passed" else "warn"),
                kit.Note("ISSUE-0143 bounded local evidence; this surface never starts tests or network calls."),
                kit.Disclosure(
                    "Quality evidence details",
                    "\n".join(
                        [
                            f"json_report={quality.get('report_path') or 'Unavailable'}",
                            f"Markdown: {quality.get('report_paths', {}).get('markdown') if isinstance(quality.get('report_paths'), dict) else 'Unavailable'}",
                            *(f"{suite.get('suite_id', 'Unavailable')}: {suite.get('status', 'Unavailable')}" for suite in quality.get("suites", []) or [] if isinstance(suite, dict)),
                            *(str(item) for item in quality.get("failures", []) or []),
                        ]
                    ),
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    legal_card = kit.GlassCard(
        "Legal terms",
        body=ft.Column(
            [
                kit.Tag(f"{legal_display} · {str(legal.get('review_status') or 'Unavailable').replace('_', ' ').title()}", "ok" if legal_status == "passed" else "warn"),
                kit.Note("Professional review remains required where recorded by the legal registry."),
                kit.Disclosure("Legal evidence details", f"registry_sha256={legal.get('registry_sha256') or 'Unavailable'}\n{legal.get('unavailable_reason') or ''}"),
            ],
            spacing=8,
        ),
        expand=True,
    )
    body = ft.Column(
        [
            strip,
            ft.ResponsiveRow([ft.Container(content=checks_card, col={"xs": 12, "md": 8}), ft.Container(content=evidence_card, col={"xs": 12, "md": 4})], spacing=12, run_spacing=12),
            ft.ResponsiveRow([ft.Container(content=blocker_card, col={"xs": 12, "md": 6}), ft.Container(content=limitations_card, col={"xs": 12, "md": 6})], spacing=12, run_spacing=12),
            ft.ResponsiveRow([ft.Container(content=quality_card, col={"xs": 12, "md": 6}), ft.Container(content=legal_card, col={"xs": 12, "md": 6})], spacing=12, run_spacing=12),
        ],
        spacing=12,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return PageView(PageChrome("Release Readiness", "Evidence-only certification status for the completion programme"), body)


__all__ = ["release_readiness_page"]
