from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import build_version_registry, compatibility_summary, extract_and_validate_audit_archive
from etf_cockpit.audit.thesis_diary import ThesisDiaryIntegrityError, ThesisDiaryStore
from etf_cockpit.audit.local_llm import (
    build_local_audit_context,
    check_local_llm_status,
    generate_local_audit_commentary,
    load_local_llm_settings,
    save_local_audit_commentary,
)
from etf_cockpit.services import ChatGPTBridge
from etf_cockpit.governance.product_scope import load_authority_matrix


def _thesis_diary_text() -> str:
    try:
        entries = ThesisDiaryStore().list_entries()
    except (ThesisDiaryIntegrityError, OSError, ValueError) as exc:
        return f"LLM thesis diary unavailable; manual review required ({type(exc).__name__})."
    if not entries:
        return "No persisted instrument-specific LLM thesis entries."
    lines = []
    for entry in entries:
        lines.append(
            " | ".join(
                (
                    f"{entry.instrument_id} @ {entry.decision_time}",
                    f"label={entry.final_advisory_label}",
                    f"evidence_score={entry.evidence_score if entry.evidence_score is not None else 'unknown'}",
                    f"evidence_quality={entry.evidence_quality if entry.evidence_quality is not None else 'unknown'}",
                    f"risk_friction={entry.risk_friction if entry.risk_friction is not None else 'unknown'}",
                    f"uncertainty={entry.uncertainty}",
                    f"sources={','.join(entry.input_sources) or 'unknown'}",
                    f"thesis={entry.thesis_summary}",
                    f"risk={entry.risk_summary}",
                    f"contradictions={entry.contradiction_summary}",
                    f"review={entry.human_review_status}",
                    f"outcomes={entry.outcomes}",
                    f"backtest={entry.backtest_validity}",
                    "execution_allowed=false",
                )
            )
        )
    return "\n".join(lines)


def chatgpt_audit_page(page: ft.Page, state: AppState) -> ft.Control:
    path_field = ft.TextField(label="External audit commentary JSON path", expand=True)
    output = ft.Text(state.last_message, color=theme.MUTED, selectable=True)
    llm_output = ft.Text("Local LLM audit has not been run in this session.", color=theme.MUTED, selectable=True)
    diary_output = ft.Text(_thesis_diary_text(), color=theme.MUTED, selectable=True, size=11)
    authority_matrix = load_authority_matrix()
    version_summary = compatibility_summary(build_version_registry())

    def export_pack(_event: ft.ControlEvent) -> None:
        state.begin_activity("Export audit packet", "Writing audit packet")
        output.value = "Exporting audit packet..."
        page.update()
        try:
            path = state.export_audit_packet()
            with TemporaryDirectory(prefix="audit_verify_") as verification_dir:
                report = extract_and_validate_audit_archive(path, Path(verification_dir))
            if not report.valid:
                raise ValueError(f"Audit packet validation failed: missing={report.missing}, checksums={report.checksum_errors}, secrets={report.secret_findings}")
            message = f"Exported: {path} ({len(report.included)} artefacts; checksums validated; execution_allowed=false)"
            state.finish_activity(message, output_path=path)
            output.value = message
        except Exception as exc:
            state.fail_activity("Export audit packet", exc, retry_callback=state.export_audit_packet)
            output.value = state.last_message
        page.update()

    def import_audit(_event: ft.ControlEvent) -> None:
        state.begin_activity("Import external audit response", "Validating audit JSON")
        output.value = "Validating and importing audit commentary..."
        page.update()
        try:
            audit = ChatGPTBridge(state.snapshot.config).import_audit_json(Path(path_field.value))
            output.value = f"Imported audit commentary {audit.review_date}: {audit.overall_view}. It remains non-executable evidence."
            state.finish_activity(output.value)
        except Exception as exc:
            state.fail_activity("Import external audit response", exc)
            output.value = f"Import rejected: {exc}"
        page.update()

    def check_llm(_event: ft.ControlEvent) -> None:
        state.begin_activity("Check LM Studio", "Checking local LLM endpoint")
        llm_output.value = "Checking LM Studio..."
        page.update()
        try:
            status = check_local_llm_status()
            llm_output.value = f"{status.status}: {status.message}" + (f" Model: {status.model}" if status.model else "")
            state.finish_activity(llm_output.value)
        except Exception as exc:
            state.fail_activity("Check LM Studio", exc)
            llm_output.value = state.last_message
        page.update()

    def run_local_llm_audit(_event: ft.ControlEvent) -> None:
        state.begin_activity("Generate local LLM commentary", "Preparing audit context")
        llm_output.value = "Generating local LLM commentary..."
        page.update()
        try:
            settings = load_local_llm_settings()
            state.update_activity("Calling local LLM audit endpoint")
            page.update()
            context = build_local_audit_context(state.snapshot)
            status, commentary = generate_local_audit_commentary(context, settings)
            if commentary is None:
                llm_output.value = f"{status.status}: {status.message}"
                state.finish_activity(llm_output.value)
            else:
                saved_path = save_local_audit_commentary(commentary, model=status.model, context=context)
                llm_output.value = f"Saved local LLM thesis diary: {saved_path}\n{commentary.summary}"
                diary_output.value = _thesis_diary_text()
                state.finish_activity(f"Saved local LLM commentary: {saved_path}", output_path=saved_path)
        except Exception as exc:
            state.fail_activity("Generate local LLM commentary", exc)
            llm_output.value = f"Local LLM audit ignored: {exc}"
        page.update()

    return ft.Column(
        [
            panel(
                ft.Column(
                    [
                        section_header("Active product authority", "Audit exports include the immutable scope and capability matrix checksum."),
                        ft.Text(
                            f"ADR {authority_matrix.policy.adr_id} · active stage: Research · execution_allowed=false · checksum: {authority_matrix.checksum}"
                            if authority_matrix.policy is not None
                            else "Authority matrix unavailable; audit remains fail-closed and requires manual review.",
                            key="chatgpt.authority-matrix",
                            color=theme.AMBER,
                            selectable=True,
                        ),
                        ft.Text(
                            f"Lineage registry: {version_summary['record_count']} records · signature {str(version_summary['registry_signature'])[:16]}… · immutable after run",
                            color=theme.MUTED,
                            selectable=True,
                        ),
                    ],
                    spacing=8,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("LLM thesis diary", "Instrument-specific, dated context only. Human review and forward outcomes are persisted; diary output cannot alter scores, actions, risk gates or trade proposals."),
                        diary_output,
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("External audit packet", "Export local evidence for review; imported responses are commentary only."),
                        ft.Row([ft.Button("Export audit packet", key="chatgpt.export-audit", on_click=export_pack), ft.Text(str(state.last_export_path or ""), color=theme.MUTED, selectable=True)]),
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Local LLM commentary", "Optional LM Studio review. Output is schema-validated and cannot alter scores."),
                        ft.Row([ft.Button("Check LM Studio", key="chatgpt.check-llm", on_click=check_llm), ft.Button("Generate commentary", key="chatgpt.generate-commentary", on_click=run_local_llm_audit)], spacing=10),
                        llm_output,
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Column(
                    [
                        section_header("Import audit commentary", "Strict JSON only; it is saved as a dated non-executable note."),
                        ft.Row([path_field, ft.Button("Validate and import", key="chatgpt.import-audit", on_click=import_audit)]),
                        output,
                    ],
                    spacing=10,
                )
            ),
            panel(
                ft.Text(
                    "Validation rejects invalid JSON, unknown instrument ids, invalid actions, missing fields, conviction outside 0-1 and automatic-trading recommendations.",
                    color=theme.MUTED,
                    selectable=True,
                )
            ),
        ],
        spacing=14,
        expand=True,
    )
