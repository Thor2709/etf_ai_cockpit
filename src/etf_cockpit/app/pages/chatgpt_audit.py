from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading

import flet as ft

from etf_cockpit.app.components import kit
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView, SegmentGroup
from etf_cockpit.app.formatting import format_timestamp
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import (
    build_version_registry,
    compatibility_summary,
    extract_and_validate_audit_archive,
    load_manual_news,
    manual_news_markdown,
)
from etf_cockpit.application.chatgpt_review import (
    ThesisDiaryIntegrityError,
    ThesisDiaryStore,
    disclosure_safe_entry,
    disclosure_safe_outcome,
    disclosure_safe_review,
)
from etf_cockpit.application.chatgpt_review import (
    build_local_audit_context,
    check_local_llm_status,
    generate_local_audit_commentary,
    load_local_llm_settings,
    save_local_audit_commentary,
)
from etf_cockpit.application.chatgpt_review import ChatGPTBridge
from etf_cockpit.application.scope_facade import load_authority_matrix

Button = kit.Button.primary
TextButton = kit.Button.secondary


def _manual_note_credibility_text() -> str:
    """Render the same local-only credibility evidence included in audit exports."""

    try:
        notes = load_manual_news()
    except Exception as exc:
        return (
            "Manual note credibility evidence unavailable; manual review required "
            f"({type(exc).__name__}). executable_authority=false"
        )
    if notes.empty:
        return "No manual thesis/news notes imported; credibility flags are unavailable. executable_authority=false"
    return manual_news_markdown(notes)


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


def _thesis_diary_rows() -> list[dict[str, str]]:
    try:
        store = ThesisDiaryStore()
        entries = store.list_entries()
    except (ThesisDiaryIntegrityError, OSError, ValueError):
        return []
    rows = []
    for entry in entries:
        replay = store.replay(entry.thesis_id)
        redacted = replay.redaction_state == "redacted"
        display_entry = disclosure_safe_entry(entry) if redacted else entry
        review = disclosure_safe_review(replay.human_review) if redacted else replay.human_review
        outcomes = [disclosure_safe_outcome(value) for value in replay.outcomes] if redacted else list(replay.outcomes)
        rows.append(
            {
                "instrument": display_entry.instrument_id or "—",
                "date": format_timestamp(display_entry.decision_time, unavailable="—"),
                "thesis": display_entry.thesis_summary or "—",
                "review": str(review or "—"),
                "outcome": str(outcomes[-1]) if outcomes else "—",
            }
        )
    return rows


def chatgpt_audit_page(page: ft.Page, state: AppState) -> PageView:
    path_field = ft.TextField(label="External audit commentary JSON path", expand=True, **kit.field_input_style(placeholder="Select a local commentary file path"))
    output = kit.Note("No audit import or export has run in this session.")
    output_details = kit.Note(state.last_message or "No technical audit action details are available.")
    output_disclosure = kit.Disclosure("Audit action details", output_details)
    saved_llm_output = getattr(state, "local_audit_output", "")
    llm_output = kit.Note("Local LLM commentary is available." if saved_llm_output else "Local LLM audit has not been run in this session.")
    llm_details = kit.Note(saved_llm_output or "No local LLM status details are available.")
    llm_disclosure = kit.Disclosure("Local LLM status details", llm_details)
    diary_output = kit.Note(_thesis_diary_text())
    credibility_output = kit.Note(f"{_manual_note_credibility_text()}\nexecutable_authority=false")
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

    def start_export_pack() -> threading.Thread | None:
        action_id = start_activity("Export audit packet", "Writing audit packet", output_details)
        if action_id is None:
            return None
        output_details.value = "Exporting audit packet..."
        refresh_shell()

        def worker() -> None:
            try:
                with state.share_activity(action_id):
                    path = state.export_audit_packet()
                if state.activity_was_cancelled(action_id):
                    return
                state.update_activity("Validating exported audit packet", expected_action_id=action_id)
                with TemporaryDirectory(prefix="audit_verify_") as verification_dir:
                    report = extract_and_validate_audit_archive(path, Path(verification_dir))
                if not report.valid:
                    raise ValueError(f"Audit packet validation failed: missing={report.missing}, checksums={report.checksum_errors}, secrets={report.secret_findings}")
                if state.activity_was_cancelled(action_id):
                    return
                message = f"Exported: {path} ({len(report.included)} artefacts; checksums validated; execution_allowed=false)"
                state.finish_activity(message, output_path=path, expected_action_id=action_id)
                output_details.value = message
            except Exception as exc:
                if not state.activity_was_cancelled(action_id):
                    state.fail_activity(
                        "Export audit packet",
                        exc,
                        retry_callback=lambda: start_export_pack(),
                        expected_action_id=action_id,
                    )
                    output_details.value = state.last_message
            finally:
                cancelled_message = state.restore_cancelled_activity_message(action_id)
                if cancelled_message is not None:
                    output_details.value = cancelled_message
                state.release_activity(action_id)
                refresh_shell()

        background = threading.Thread(target=worker, daemon=True)
        background.start()
        return background

    def export_pack(_event: ft.ControlEvent) -> None:
        start_export_pack()

    def import_audit(_event: ft.ControlEvent) -> None:
        action_id = start_activity("Import external audit response", "Validating audit JSON", output_details)
        if action_id is None:
            return
        output_details.value = "Validating and importing audit commentary..."
        page.update()
        try:
            with state.activity_publication(action_id):
                audit = ChatGPTBridge(state.snapshot.config).import_audit_json(Path(path_field.value))
            output_details.value = f"Imported audit commentary {audit.review_date}: {audit.overall_view}. It remains non-executable evidence."
            output.value = "Audit commentary imported. It remains non-executable evidence."
            state.finish_activity(output_details.value, expected_action_id=action_id)
        except Exception as exc:
            if not state.activity_was_cancelled(action_id):
                state.fail_activity("Import external audit response", exc, expected_action_id=action_id)
            output_details.value = state.last_message
            output.value = "Audit commentary import is unavailable. See action details."
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
            llm_output.value = status.message
            llm_details.value = f"status={status.status}\nmodel={status.model or 'Unavailable'}"
            state.finish_activity(llm_output.value, expected_action_id=action_id)
        except Exception as exc:
            if not state.activity_was_cancelled(action_id):
                state.fail_activity("Check LM Studio", exc, expected_action_id=action_id)
            llm_output.value = "Local LLM status is unavailable. See status details."
            llm_details.value = state.last_message
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
                llm_output.value = status.message
                llm_details.value = f"status={status.status}"
                state.local_audit_output = llm_output.value
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
                llm_output.value = f"Local commentary saved. {commentary.summary}"
                state.local_audit_output = llm_output.value
                diary_output.value = _thesis_diary_text()
                state.finish_activity(f"Saved local LLM commentary: {saved_path}", output_path=saved_path, expected_action_id=action_id)
        except Exception as exc:
            if not state.activity_was_cancelled(action_id):
                state.fail_activity("Generate local LLM commentary", exc, expected_action_id=action_id)
            llm_output.value = "Local LLM commentary is unavailable. See status details."
            llm_details.value = state.last_message
            state.local_audit_output = llm_output.value
        finally:
            state.release_activity(action_id)
            refresh_shell()

    active_stage = next(
        (
            stage.label
            for stage in getattr(getattr(authority_matrix, "policy", None), "authority_stages", ())
            if stage.enabled_by_default
        ),
        "Unavailable",
    )
    lineage_records = version_summary.get("record_count")
    lineage_value = str(lineage_records) if lineage_records not in (None, "", 0, "0") else None
    authority_card = kit.GlassCard(
        "Active product authority",
        body=ft.Column(
            [
                kit.Headline(active_stage),
                kit.KpiTile("ADR", authority_matrix.policy.adr_id if authority_matrix.policy is not None else None, "Authority matrix is unavailable." if authority_matrix.policy is None else ""),
                kit.KpiTile("Execution", "disabled", "Execution remains disabled by policy.", tone="neg"),
                kit.KpiTile(
                    "Lineage records",
                    lineage_value,
                    "Immutable after run" if lineage_value is not None else "Unavailable: no lineage records are available.",
                ),
                kit.Disclosure(
                    "Authority and lineage details",
                    f"matrix_checksum={authority_matrix.checksum if authority_matrix.policy is not None else 'unavailable'}\nregistry_signature={version_summary['registry_signature']}\nexecution_allowed=false",
                ),
            ],
            spacing=8,
        ),
        expand=True,
    )
    diary_card = kit.GlassCard(
        "LLM thesis diary",
        note="Instrument-specific, dated context only",
        body=ft.Column(
            [
                kit.DataTable(
                    [kit.TableColumn("instrument", "Instrument"), kit.TableColumn("date", "Date"), kit.TableColumn("thesis", "Thesis"), kit.TableColumn("review", "Human review"), kit.TableColumn("outcome", "Forward outcome")],
                    _thesis_diary_rows(),
                    empty_title="No persisted instrument-specific LLM thesis entries",
                    empty_reason="No persisted instrument-specific LLM thesis entries.",
                    expand=True,
                ),
                kit.Disclosure("Diary record details", diary_output),
                kit.Note("Human review and forward outcomes are persisted; diary output cannot alter scores, actions, risk gates or trade proposals."),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    credibility_card = kit.GlassCard(
        "Manual note credibility",
        note="Structured local flags",
        body=ft.Column(
            [
                kit.Note("Promotional and missing-method evidence cannot alter scores, actions or execution authority."),
                kit.Disclosure("Credibility flags", credibility_output),
                kit.Note("Manual credibility flags remain commentary only."),
            ],
            spacing=8,
        ),
        expand=True,
    )
    timeline_rows = []
    for item in list(getattr(state, "recent_activity", ()) or ()):
        if not any(word in str(getattr(item, "label", "")).casefold() for word in ("export", "import")):
            continue
        timeline_rows.append(kit.ListRow("info", item.label, getattr(item, "step", "") or "Local audit activity"))
        timeline_rows.append(
            kit.Disclosure(
                "Audit timeline details",
                f"message={getattr(item, 'message', '') or 'Unavailable'}\nstarted_at={format_timestamp(getattr(item, 'started_at', None), unavailable='Unavailable')}\naction_id={getattr(item, 'action_id', '') or '—'}\nstatus={getattr(item, 'status', 'Unavailable')}",
            )
        )
    timeline_card = kit.GlassCard(
        "Audit timeline",
        note="Local exports and imports",
        body=ft.Column(
            timeline_rows or [kit.EmptyState("No audit activity", "No local audit exports or imports are recorded in this session.")],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
    )
    export_card = kit.GlassCard(
        "External audit packet",
        body=ft.Column(
            [
                Button("Export audit packet", key="chatgpt.export-audit", on_click=export_pack),
                kit.Note("Export local evidence for review; imported responses are commentary only."),
                kit.Disclosure("Last export", str(state.last_export_path) if state.last_export_path else "No audit packet has been exported in this session."),
                output_disclosure,
            ],
            spacing=8,
        ),
    )
    import_card = kit.GlassCard(
        "Import audit commentary",
        body=ft.Column(
            [
                kit.Field("External audit commentary JSON path", control=path_field),
                Button("Validate and import", key="chatgpt.import-audit", on_click=import_audit),
                kit.Note("Validation rejects invalid JSON, unknown instrument ids, invalid actions, missing fields, conviction outside 0-1 and automatic-trading recommendations."),
                output,
                output_disclosure,
            ],
            spacing=8,
        ),
    )
    llm_card = kit.GlassCard(
        "Local LLM commentary",
        body=ft.Column(
            [
                ft.Row(
                    [
                        TextButton("Check LM Studio", key="chatgpt.check-llm", on_click=check_llm),
                        Button("Generate commentary", key="chatgpt.generate-commentary", on_click=run_local_llm_audit),
                    ],
                    spacing=8,
                ),
                kit.Note("Optional LM Studio review. Output is schema-validated and cannot alter scores."),
                llm_output,
                llm_disclosure,
            ],
            spacing=8,
        ),
    )
    notes_view = ft.Column(
        [
            ft.ResponsiveRow([ft.Container(content=authority_card, col={"xs": 12, "md": 4}), ft.Container(content=diary_card, col={"xs": 12, "md": 8})], spacing=12, run_spacing=12),
            ft.ResponsiveRow([ft.Container(content=credibility_card, col={"xs": 12, "md": 6}), ft.Container(content=timeline_card, col={"xs": 12, "md": 6})], spacing=12, run_spacing=12),
        ],
        spacing=12,
        visible=True,
    )
    export_view = ft.ResponsiveRow(
        [ft.Container(content=export_card, col={"xs": 12, "md": 6}), ft.Container(content=import_card, col={"xs": 12, "md": 6})],
        spacing=12,
        run_spacing=12,
        visible=False,
    )
    llm_view = ft.Column([llm_card], visible=False)
    body = ft.Column([notes_view, export_view, llm_view], expand=True, spacing=12, scroll=ft.ScrollMode.AUTO)

    def show_segment(name: str) -> None:
        notes_view.visible = name == "Notes"
        export_view.visible = name == "Export & import"
        llm_view.visible = name == "Local LLM"
        if hasattr(page, "update"):
            page.update()

    return PageView(
        PageChrome(
            "Audit Notes",
            "Local audit commentary and linked evidence · advisory text cannot override gates",
            (SegmentGroup("audit_view", ("Notes", "Export & import", "Local LLM"), "Notes", show_segment),),
        ),
        body,
    )
