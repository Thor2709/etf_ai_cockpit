"""User-owned Decision Journal UI."""

from __future__ import annotations

from datetime import datetime, timezone
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
    status = ft.Text("", color=theme.MUTED, selectable=True)
    existing_column = ft.Column(spacing=8)
    try:
        entries = journal.list_entries(root=DATA_DIR)
        existing: list[ft.Control] = [
            ft.Text(f"{entry.created_at} | {entry.decision} | {entry.outcome}", color=theme.TEXT, size=12, selectable=True)
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
            entry = journal.create(
                JournalEntry(
                    journal_entry_id=f"note-{now:%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}",
                    created_at=now.isoformat(),
                    thesis=note.value or "",
                    decision=title.value or "review",
                    outcome="pending",
                    private_notes=note.value or None,
                ),
                root=DATA_DIR,
            )
            status.value = f"Saved locally at {entry.created_at}. No external action was created."
            status.color = theme.GREEN
            if existing_column.controls and isinstance(existing_column.controls[0], ft.Text) and str(getattr(existing_column.controls[0], "value", "")).startswith("Empty:"):
                existing_column.controls.clear()
            existing_column.controls.append(ft.Text(f"{entry.created_at} | {entry.decision} | {entry.outcome}", color=theme.TEXT, size=12, selectable=True))
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
            panel(ft.Column([title, note, save, status, ft.Text("Partial: local storage can be unavailable or locked. No broker execution or external orders are supported.", color=theme.AMBER, selectable=True)], spacing=10)),
            panel(ft.Column([ft.Text("Recent local entries", color=theme.TEXT, weight=ft.FontWeight.BOLD), existing_column], spacing=8), expand=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=14,
    )


__all__ = ["decision_journal_page"]
