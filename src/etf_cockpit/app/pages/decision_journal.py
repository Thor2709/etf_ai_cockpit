"""User-owned Decision Journal UI."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.core.paths import DATA_DIR
from etf_cockpit.application.ui_facade import DecisionJournal, JournalEntry, JournalIntegrityError


def decision_journal_page(page: ft.Page | None, state: AppState) -> ft.Control:
    journal = DecisionJournal()
    title = ft.TextField(label="Decision title", key="decision-journal.title", autofocus=False)
    note = ft.TextField(label="Private thesis / note", key="decision-journal.note", multiline=True, min_lines=3, max_lines=8)
    decision_state = ft.Dropdown(
        label="Decision state",
        key="decision-journal.state",
        value="pending",
        options=[ft.dropdown.Option(value) for value in ("pending", "accepted", "rejected", "deferred")],
        width=220,
    )
    evidence_refs = ft.TextField(label="Evidence references (comma-separated)", key="decision-journal.evidence")
    alternatives = ft.TextField(label="Alternatives considered (comma-separated)", key="decision-journal.alternatives")
    confidence = ft.TextField(label="Confidence (0-1)", key="decision-journal.confidence", width=180)
    invalidation_rules = ft.TextField(label="Invalidation rules (comma-separated)", key="decision-journal.invalidation")
    review_date = ft.TextField(label="Review date (YYYY-MM-DD)", key="decision-journal.review-date", width=220)
    portfolio_context = ft.TextField(label="Portfolio context (JSON)", key="decision-journal.portfolio-context", multiline=True, min_lines=2, max_lines=4)
    instrument_ids = ft.TextField(label="Instrument IDs (comma-separated)", key="decision-journal.instruments")
    model_run_ids = ft.TextField(label="Model run IDs (comma-separated)", key="decision-journal.models")
    proposal_ids = ft.TextField(label="Proposal IDs (comma-separated)", key="decision-journal.proposals")
    order_ids = ft.TextField(label="Order IDs (comma-separated)", key="decision-journal.orders")
    status = ft.Text("", color=theme.MUTED, selectable=True)
    existing_column = ft.Column(spacing=8)

    def _split_values(value: str | None) -> list[str]:
        return [item.strip() for item in (value or "").split(",") if item.strip()]

    def _entry_label(entry: JournalEntry) -> str:
        links = ", ".join(
            value
            for values in (entry.model_run_ids, entry.proposal_ids, entry.order_ids)
            for value in values
        ) or "none"
        return (
            f"{entry.created_at} | {entry.decision_state} | {entry.decision} | "
            f"review={entry.review_date or 'none'} | evidence={len(entry.evidence_refs)} | links={links}"
        )

    try:
        entries = journal.list_entries(root=DATA_DIR)
        existing: list[ft.Control] = [
            ft.Text(_entry_label(entry), color=theme.TEXT, size=12, selectable=True)
            for entry in entries[-12:]
        ]
        if not existing:
            existing = [ft.Text("Empty: no local journal entries yet.", color=theme.MUTED)]
        existing_column.controls = existing
    except JournalIntegrityError as exc:
        existing_column.controls = [ft.Text(f"Unavailable: journal integrity requires manual review ({exc}).", color=theme.AMBER, selectable=True)]
    except PermissionError as exc:
        existing_column.controls = [ft.Text(f"Partial: local journal storage is locked ({exc}); manual review is required.", color=theme.AMBER, selectable=True)]
    except Exception as exc:
        existing_column.controls = [ft.Text(f"Error: local journal entries could not be read ({type(exc).__name__}); manual review is required.", color=theme.RED, selectable=True)]

    def save_note(_event: ft.ControlEvent) -> None:
        try:
            now = datetime.now(timezone.utc)
            confidence_value = float(confidence.value) if (confidence.value or "").strip() else None
            context_text = (portfolio_context.value or "").strip()
            context = json.loads(context_text) if context_text else {}
            if not isinstance(context, dict):
                raise ValueError("portfolio context must be a JSON object")
            entry = journal.create(
                JournalEntry(
                    journal_entry_id=f"note-{now:%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}",
                    created_at=now.isoformat(),
                    thesis=note.value or "",
                    decision=title.value or "review",
                    outcome="pending",
                    private_notes=note.value or None,
                    decision_state=decision_state.value or "pending",
                    evidence_refs=_split_values(evidence_refs.value),
                    alternatives=_split_values(alternatives.value),
                    confidence=confidence_value,
                    invalidation_rules=_split_values(invalidation_rules.value),
                    review_date=(review_date.value or "").strip() or None,
                    portfolio_context=context,
                    instrument_ids=_split_values(instrument_ids.value),
                    model_run_ids=_split_values(model_run_ids.value),
                    proposal_ids=_split_values(proposal_ids.value),
                    order_ids=_split_values(order_ids.value),
                ),
                root=DATA_DIR,
            )
            status.value = f"Saved locally at {entry.created_at}. No external action was created."
            status.color = theme.GREEN
            if existing_column.controls and isinstance(existing_column.controls[0], ft.Text) and str(getattr(existing_column.controls[0], "value", "")).startswith("Empty:"):
                existing_column.controls.clear()
            existing_column.controls.append(ft.Text(_entry_label(entry), color=theme.TEXT, size=12, selectable=True))
            if page is not None:
                page.update()
        except JournalIntegrityError as exc:
            status.value = f"Unavailable: journal integrity requires manual review ({exc})."
            status.color = theme.AMBER
            if page is not None:
                page.update()
        except PermissionError as exc:
            status.value = f"Partial: local journal storage is unavailable ({exc}); no external action was created."
            status.color = theme.AMBER
            if page is not None:
                page.update()
        except Exception as exc:
            status.value = f"Error: local journal save unavailable ({exc})."
            status.color = theme.RED
            if page is not None:
                page.update()

    save = ft.FilledButton("Save note", key="decision-journal.save", tooltip="Save user-owned local note", on_click=save_note)
    return ft.Column(
        [
            section_header("User-owned local journal", "User-owned local notes and outcomes; no broker or execution authority is provided."),
            panel(
                ft.Column(
                    [
                        title,
                        note,
                        ft.Row([decision_state, confidence], wrap=True),
                        evidence_refs,
                        alternatives,
                        invalidation_rules,
                        review_date,
                        portfolio_context,
                        instrument_ids,
                        model_run_ids,
                        proposal_ids,
                        order_ids,
                        save,
                        status,
                        ft.Text("Partial: local storage can be unavailable or locked. No broker execution or external orders are supported.", color=theme.AMBER, selectable=True),
                    ],
                    spacing=10,
                )
            ),
            panel(ft.Column([ft.Text("Recent local entries", color=theme.TEXT, weight=ft.FontWeight.BOLD), existing_column], spacing=8), expand=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["decision_journal_page"]
