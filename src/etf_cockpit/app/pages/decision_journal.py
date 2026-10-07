from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.chartkit import Slice, donut_chart
from etf_cockpit.app.components.kit import (
    Button,
    Disclosure,
    EmptyState,
    GlassCard,
    ListRow,
    Note,
    Segmented,
    Well,
)
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.formatting import format_number, format_timestamp
from etf_cockpit.app.pages._l4a_common import input_of, page_body, text_field
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import DATA_DIR
from etf_cockpit.data.decision_journal import DecisionJournal, JournalEntry, JournalIntegrityError


_STATES = ("pending", "accepted", "rejected", "deferred")
_STATE_LABELS = {"pending": "Pending", "accepted": "Accepted", "rejected": "Rejected", "deferred": "Deferred"}
_STATE_DOTS = {"pending": "warn", "accepted": "ok", "rejected": "bad", "deferred": "info"}
_STATE_TAGS = {"pending": "warn", "accepted": "ok", "rejected": "bad", "deferred": "mute"}


def decision_journal_page(page: ft.Page | None, state: AppState) -> PageView:
    del state
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
    status_note = Note("")
    selected_state = {"value": "pending"}

    def set_state(value: str) -> None:
        selected_state["value"] = value.casefold()

    try:
        entries = journal.list_entries(root=DATA_DIR)
    except PermissionError:
        entries = []
        status_note.value = "Partial: local journal storage is locked; manual review is required."
    except JournalIntegrityError:
        entries = []
        status_note.value = "Unavailable: local journal storage requires manual review."
    except Exception:
        entries = []
        status_note.value = "Unavailable: local journal entries could not be read."

    recent_host = ft.Column(spacing=theme.SPACE_2)
    state_chart_host = Well(EmptyState("Unavailable", "Decision state counts are unavailable."))
    calendar_note = Note("Review dates are unavailable until local entries include review dates.")
    calendar_host = Well(EmptyState("Unavailable", "Review dates are unavailable until local entries include review dates."))

    def render_entries() -> None:
        recent = []
        for entry in entries[-12:]:
            state_key = str(getattr(entry, "decision_state", "pending")).casefold()
            recent.append(
                ListRow(
                    _STATE_DOTS.get(state_key, "info"),
                    getattr(entry, "decision", "Decision"),
                    f"{format_timestamp(getattr(entry, 'created_at', None), unavailable='—')} · confidence "
                    f"{format_number(getattr(entry, 'confidence', None), decimals=2, unavailable='—')}",
                    tag=(_STATE_LABELS.get(state_key, "Unavailable"), _STATE_TAGS.get(state_key, "mute")),
                )
            )
        if recent:
            recent_host.controls = recent
        else:
            recent_host.controls = [Well(EmptyState("No local journal entries yet", "Local entries will appear here after they are saved."))]

        counts = {name: sum(str(getattr(entry, "decision_state", "pending")).casefold() == name for entry in entries) for name in _STATES}
        donut = donut_chart(
            [Slice(_STATE_LABELS[name], counts[name], colour) for name, colour in zip(_STATES, theme.CATEGORICAL)],
            center_text="Decisions",
            show_legend=True,
            unavailable_reason="No local journal entries are available.",
            insight="Local decisions by state.",
        )
        state_chart_host.content = donut

        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=30)
        review_rows = []
        due_count = 0
        dated_entries = 0
        for entry in entries:
            raw_date = getattr(entry, "review_date", None)
            if not raw_date:
                continue
            try:
                review = date.fromisoformat(str(raw_date))
            except ValueError:
                continue
            dated_entries += 1
            if today <= review <= cutoff:
                due_count += 1
            state_key = str(getattr(entry, "decision_state", "pending")).casefold()
            review_rows.append(
                (
                    review,
                    ListRow(
                        _STATE_DOTS.get(state_key, "info"),
                        f"{review.isoformat()} · {getattr(entry, 'decision', 'Decision')}",
                        f"{_STATE_LABELS.get(state_key, 'Unavailable')} · confidence "
                        f"{format_number(getattr(entry, 'confidence', None), decimals=2, unavailable='—')}",
                        tag=(_STATE_LABELS.get(state_key, "Unavailable"), _STATE_TAGS.get(state_key, "mute")),
                    ),
                )
            )
        review_rows.sort(key=lambda item: item[0])
        if review_rows:
            calendar_host.content = ft.Column([row for _, row in review_rows], spacing=theme.SPACE_2)
            calendar_note.value = f"{format_number(due_count, decimals=0)} reviews are due in the next 30 days."
        elif dated_entries:
            calendar_host.content = EmptyState("No review dates", "No valid review dates are available.")
            calendar_note.value = "Review dates are unavailable."
        elif entries:
            calendar_host.content = EmptyState("No review dates", "Local entries do not contain valid review dates.")
            calendar_note.value = "Review dates are unavailable; no due count is inferred."
        else:
            calendar_host.content = EmptyState("No local reviews", "Review dates are unavailable without local entries.")
            calendar_note.value = "Reviews due in the next 30 days are unavailable without local entries."

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
            entries.append(entry)
            status_note.value = "Saved locally. No external action was created."
            render_entries()
        except PermissionError:
            status_note.value = "Unavailable: local storage is locked; no external action was created."
        except Exception:
            status_note.value = "Unavailable: the local note could not be saved. Check the entered values."
        if page is not None:
            page.update()

    render_entries()
    new_decision = GlassCard(
        "New decision",
        note="stored locally · no broker or execution authority",
        body=ft.Column(
            [
                title,
                note,
                Segmented([_STATE_LABELS[name] for name in _STATES], "Pending", on_change=set_state),
                confidence,
                review_date,
                evidence_refs,
                alternatives,
                invalidation_rules,
                instrument_ids,
                Disclosure(
                    "links and context",
                    ft.Column([portfolio_context, model_run_ids, proposal_ids, order_ids], spacing=theme.SPACE_2),
                ),
                Button.primary("Save note", key="decision-journal.save", on_click=save_note),
                status_note,
                Note("Partial: local storage can be unavailable or locked. No broker execution or external orders are supported."),
            ],
            spacing=theme.SPACE_2,
        ),
    )
    return PageView(
        chrome=PageChrome(
            "Decision Journal",
            "Your decisions, alternatives and rationale beside the evidence · user-owned notes",
        ),
        body=page_body(
            [
                new_decision,
                GlassCard("Recent local entries", body=recent_host),
                GlassCard("Decisions by state", body=state_chart_host),
                GlassCard("Review calendar", body=ft.Column([calendar_note, calendar_host], spacing=theme.SPACE_2)),
            ]
        ),
    )


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


__all__ = ["decision_journal_page"]
