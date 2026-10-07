from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.chartkit import Slice, donut_chart
from etf_cockpit.app.components.kit import Button, Disclosure, GlassCard, ListRow, Note, Segmented
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.data.decision_journal import DecisionJournal, JournalEntry, JournalIntegrityError
from etf_cockpit.core.paths import DATA_DIR


def decision_journal_page(page: ft.Page | None, state: AppState) -> PageView:
    journal = DecisionJournal()
    title = text_field("Decision title", "decision-journal.title")
    note = text_field("Private thesis / note", "decision-journal.note", multiline=True)
    evidence_refs = text_field("Evidence references (comma-separated)", "decision-journal.evidence")
    alternatives = text_field("Alternatives considered (comma-separated)", "decision-journal.alternatives")
    confidence = text_field("Confidence (0–1)", "decision-journal.confidence")
    invalidation_rules = text_field("Invalidation rules (comma-separated)", "decision-journal.invalidation")
    review_date = text_field("Review date (YYYY-MM-DD)", "decision-journal.review-date")
    instrument_ids = text_field("Instrument IDs (comma-separated)", "decision-journal.instruments")
    portfolio_context = text_field("Portfolio context (JSON)", "decision-journal.portfolio-context", multiline=True)
    model_run_ids = text_field("Model run IDs", "decision-journal.models")
    proposal_ids = text_field("Proposal IDs", "decision-journal.proposals")
    order_ids = text_field("Order IDs", "decision-journal.orders")
    status = ft.Text()
    selected_state = {"value": "pending"}

    def set_state(value: str) -> None:
        selected_state["value"] = value.lower()
    entries = []
    try:
        entries = journal.list_entries(root=DATA_DIR)
    except PermissionError:
        status.value = "Partial: local journal storage is locked; manual review is required."
    except JournalIntegrityError:
        status.value = "Unavailable: local journal storage requires manual review."
    except Exception:
        status.value = "Unavailable: local journal entries could not be read."

    def save_note(_event: ft.ControlEvent | None) -> None:
        try:
            context_text = (input_of(portfolio_context).value or "").strip()
            context = json.loads(context_text) if context_text else {}
            if not isinstance(context, dict):
                raise ValueError
            confidence_text = (input_of(confidence).value or "").strip()
            entry = journal.create(
                JournalEntry(
                    journal_entry_id=f"note-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    thesis=input_of(note).value or "",
                    decision=input_of(title).value or "review",
                    outcome="pending",
                    private_notes=input_of(note).value or None,
                    decision_state=selected_state["value"],
                    evidence_refs=_split(input_of(evidence_refs).value),
                    alternatives=_split(input_of(alternatives).value),
                    confidence=float(confidence_text) if confidence_text else None,
                    invalidation_rules=_split(input_of(invalidation_rules).value),
                    review_date=(input_of(review_date).value or "").strip() or None,
                    portfolio_context=context,
                    instrument_ids=_split(input_of(instrument_ids).value),
                    model_run_ids=_split(input_of(model_run_ids).value),
                    proposal_ids=_split(input_of(proposal_ids).value),
                    order_ids=_split(input_of(order_ids).value),
                ),
                root=DATA_DIR,
            )
            status.value = f"Saved locally at {entry.created_at}. No external action was created."
            status.color = theme.GREEN
            entries.append(entry)
        except PermissionError:
            status.value = "Unavailable: local storage is locked; no external action was created."
            status.color = theme.AMBER
        except Exception:
            status.value = "Unavailable: the local note could not be saved. Check the entered values."
            status.color = theme.AMBER
        if page is not None:
            page.update()

    recent_rows = [
        ListRow(
            "info",
            getattr(entry, "decision", "Decision"),
            f"{getattr(entry, 'created_at', '—')} · confidence {getattr(entry, 'confidence', None) if getattr(entry, 'confidence', None) is not None else '—'}",
            tag=(str(getattr(entry, "decision_state", "pending")), "mute"),
        )
        for entry in entries[-12:]
    ]
    if not recent_rows:
        recent_rows = [ListRow("info", "No local journal entries yet.")]

    by_state = {name: sum(getattr(entry, "decision_state", "pending") == name for entry in entries) for name in ("pending", "accepted", "rejected", "deferred")}
    donut = donut_chart(
        [Slice(name.title(), count, colour) for (name, count), colour in zip(by_state.items(), theme.CATEGORICAL)],
        center_text="Decisions",
        show_legend=True,
        unavailable_reason="No local journal entries are available.",
        insight="Local decisions by state.",
    )
    calendar = ft.Column(
        [ft.Text("Review calendar"), ft.Text("Review dates are unavailable until local entries include review dates.")]
    )

    new_decision = GlassCard(
        "New decision",
        note="stored locally · no broker or execution authority",
        body=ft.Column(
            [
                title,
                note,
                Segmented(["Pending", "Accepted", "Rejected", "Deferred"], "Pending", on_change=set_state),
                confidence,
                review_date,
                evidence_refs,
                alternatives,
                invalidation_rules,
                instrument_ids,
                Disclosure(
                    "links and context",
                    ft.Column([portfolio_context, model_run_ids, proposal_ids, order_ids]),
                ),
                Button.primary("Save note", key="decision-journal.save", on_click=save_note),
                status,
                Note("User-owned local journal entries remain stored on this device."),
                Note("Partial: local storage can be unavailable or locked. No broker execution or external orders are supported."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    cards = [
        new_decision,
        GlassCard("Recent local entries", body=ft.Column(recent_rows, spacing=theme.SPACE_2)),
        GlassCard("Decisions by state", body=donut),
        GlassCard("Review calendar", body=calendar),
    ]
    return PageView(
        chrome=PageChrome(
            "Decision Journal",
            "Your decisions, alternatives and rationale beside the evidence · user-owned notes",
        ),
        body=page_body(cards),
    )


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


__all__ = ["decision_journal_page"]
