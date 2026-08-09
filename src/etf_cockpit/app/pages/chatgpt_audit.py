from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import build_version_registry, compatibility_summary, extract_and_validate_audit_archive
from etf_cockpit.audit.thesis_diary import (
    ThesisDiaryIntegrityError,
    ThesisDiaryStore,
    disclosure_safe_entry,
    disclosure_safe_outcome,
    disclosure_safe_review,
)
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
    store = ThesisDiaryStore()
    for entry in entries:
        state = store.replay(entry.thesis_id)
        currently_redacted = state.redaction_state == "redacted"
        display_entry = disclosure_safe_entry(entry) if currently_redacted else entry
        review = disclosure_safe_review(state.human_review) if currently_redacted else state.human_review
        outcomes = [disclosure_safe_outcome(value) for value in state.outcomes] if currently_redacted else list(state.outcomes)
        lines.append(
            " | ".join(
                (
                    f"{display_entry.instrument_id} @ {display_entry.decision_time}",
                    f"label={display_entry.final_advisory_label}",
                    f"evidence_score={display_entry.evidence_score if display_entry.evidence_score is not None else 'unknown'}",
                    f"evidence_quality={display_entry.evidence_quality if display_entry.evidence_quality is not None else 'unknown'}",
                    f"risk_friction={display_entry.risk_friction if display_entry.risk_friction is not None else 'unknown'}",
                    f"uncertainty={display_entry.uncertainty}",
                    f"sources={','.join(display_entry.input_sources) or 'unknown'}",
                    f"thesis={display_entry.thesis_summary}",
                    f"risk={display_entry.risk_summary}",
                    f"contradictions={display_entry.contradiction_summary}",
                    f"review={review}",
                    f"redaction={state.redaction_state}",
                    f"expires_at={state.expires_at or 'none'}",
                    f"expired={state.expired}",
                    f"outcomes={outcomes}",
                    f"replayed_at={state.replayed_at or 'current'}",
                    f"backtest={display_entry.backtest_validity}",
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

    def refresh_shell() -> None:
        if not hasattr(page, "views"):
            page.update()
            return
        from etf_cockpit.app.router import render_shell

        render_shell(page, state, getattr(page, "route", "") or state.snapshot.config.ui.default_page)

    def start_activity(label: str, step: str, target: ft.Text) -> str | None:
        if state.current_activity is not None:
            target.value = f"{label} blocked: {state.current_activity.label} is already running."
            page.update()
            return None
        return state.begin_activity(label, step).action_id

    def export_pack(_event: ft.ControlEvent) -> None:
        action_id = start_activity("Export audit packet", "Writing audit packet", output)
        if action_id is None:
            return
        output.value = "Exporting audit packet..."
        page.update()
        try:
            with state.share_activity(action_id):
                path = state.export_audit_packet()
            with TemporaryDirectory(prefix="audit_verify_") as verification_dir:
                report = extract_and_validate_audit_archive(path, Path(verification_dir))
            if not report.valid:
                raise ValueError(f"Audit packet validation failed: missing={report.missing}, checksums={report.checksum_errors}, secrets={report.secret_findings}")
            message = f"Exported: {path} ({len(report.included)} artefacts; checksums validated; execution_allowed=false)"
            state.finish_activity(message, output_path=path, expected_action_id=action_id)
            output.value = message
        except Exception as exc:
            if state.activity_was_cancelled(action_id):
                return
            state.fail_activity("Export audit packet", exc, retry_callback=state.export_audit_packet, expected_action_id=action_id)
            output.value = state.last_message
        finally:
            state.release_activity(action_id)
            refresh_shell()

    def import_audit(_event: ft.ControlEvent) -> None:
        action_id = start_activity("Import external audit response", "Validating audit JSON", output)
        if action_id is None:
            return
        output.value = "Validating and importing audit commentary..."
        page.update()
        try:
            with state.activity_publication(action_id):
                audit = ChatGPTBridge(state.snapshot.config).import_audit_json(Path(path_field.value))
            output.value = f"Imported audit commentary {audit.review_date}: {audit.overall_view}. It remains non-executable evidence."
            state.finish_activity(output.value, expected_action_id=action_id)
        except Exception as exc:
            if not state.activity_was_cancelled(action_id):
                state.fail_activity("Import external audit response", exc, expected_action_id=action_id)
            output.value = state.last_message
        finally:
            state.release_activity(action_id)
            refresh_shell()

    def check_llm(_event: ft.ControlEvent) -> None:
        action_id = start_activity("Check LM Studio", "Checking local LLM endpoint", llm_output)
        if action_id is None:
            return
        llm_output.value = "Checking LM Studio..."
        page.update()
        try:
            status = check_local_llm_status()
            llm_output.value = f"{status.status}: {status.message}" + (f" Model: {status.model}" if status.model else "")
            state.finish_activity(llm_output.value, expected_action_id=action_id)
        except Exception as exc:
            if not state.activity_was_cancelled(action_id):
                state.fail_activity("Check LM Studio", exc, expected_action_id=action_id)
            llm_output.value = state.last_message
        finally:
            state.release_activity(action_id)
            refresh_shell()

    def run_local_llm_audit(_event: ft.ControlEvent) -> None:
        action_id = start_activity("Generate local LLM commentary", "Preparing audit context", llm_output)
        if action_id is None:
            return
        llm_output.value = "Generating local LLM commentary..."
        page.update()
        try:
            settings = load_local_llm_settings()
            state.update_activity("Calling local LLM audit endpoint", expected_action_id=action_id)
            page.update()
            context = build_local_audit_context(state.snapshot)
            status, commentary = generate_local_audit_commentary(context, settings)
            if commentary is None:
                llm_output.value = f"{status.status}: {status.message}"
                state.finish_activity(llm_output.value, expected_action_id=action_id)
            else:
                if status.context_snapshot is None:
                    raise ValueError("Local LLM generation did not retain its immutable context snapshot")
                with state.activity_publication(action_id):
                    saved_path = save_local_audit_commentary(
                        commentary,
                        model=status.model,
                        context=status.context_snapshot,
                        request_envelope=status.request_envelope,
                        response_payload=status.response_payload,
                        generation_time=status.generation_time,
                    )
                llm_output.value = f"Saved local LLM thesis diary: {saved_path}\n{commentary.summary}"
                diary_output.value = _thesis_diary_text()
                state.finish_activity(f"Saved local LLM commentary: {saved_path}", output_path=saved_path, expected_action_id=action_id)
        except Exception as exc:
            if not state.activity_was_cancelled(action_id):
                state.fail_activity("Generate local LLM commentary", exc, expected_action_id=action_id)
            llm_output.value = state.last_message
        finally:
            state.release_activity(action_id)
            refresh_shell()

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
