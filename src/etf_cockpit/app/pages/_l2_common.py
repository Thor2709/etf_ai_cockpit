"""Small UI helpers shared by the L2 evidence pages."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import flet as ft
import pandas as pd

from etf_cockpit.app.components import kit

ACTION_LABELS = {
    "filings.fetch-sec": "Fetch SEC companyfacts",
    "filings.import-sec": "Import SEC companyfacts",
    "filings.import-sec-bulk": "Import local SEC ZIP",
    "filings.fetch-sec-bulk": "Fetch official SEC bulk",
    "filings.cache-sec-bulk": "Use session cache",
    "filings.discover-esef": "Discover ESEF filings",
    "filings.download-esef": "Download ESEF package",
    "filings.import-esef": "Import ESEF package",
    "filings.discover-oam": "Discover official filings",
    "filings.import-local-oam": "Import local OAM export",
    "filings.import-manual-official": "Archive manual official filing",
    "etf-disclosures.import-document": "Register ETF document",
    "etf-disclosures.import-report": "Import bounded report",
    "etf-disclosures.verify-report": "Verify report",
    "etf-disclosures.reject-report": "Reject report",
    "etf-disclosures.import-holdings": "Import ETF holdings",
    "etf-disclosures.import-kid": "Import PRIIPs KID",
    "etf-disclosures.import-methodology": "Import index methodology",
    "etf-disclosures.import-sfdr": "Import SFDR disclosure",
}


def read_frame(path: Path) -> pd.DataFrame:
    from etf_cockpit.app.pages import trust_evidence

    return trust_evidence._read_frame(path)


def table_columns(fields: Iterable[str], labels: dict[str, str] | None = None) -> list[kit.TableColumn]:
    return [
        kit.TableColumn(field, (labels or {}).get(field, field.replace("_", " ").title()))
        for field in fields
    ]


def display_value(value: object) -> str:
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    return str(value)


def evidence_table(
    name: str,
    path: Path,
    fields: Iterable[str],
    *,
    labels: dict[str, str] | None = None,
    technical: Iterable[str] = (),
) -> kit.EvidenceTable:
    frame = read_frame(path)
    selected = list(fields)
    hidden = set(technical)
    rows: list[dict[str, object]] = []
    for record in frame.to_dict(orient="records"):
        values: dict[str, object] = {}
        for field in selected:
            value = record.get(field)
            missing = display_value(value) == "—"
            if missing:
                values[field] = "—"
            elif field in hidden:
                values[field] = kit.Disclosure("Technical detail", str(value))
            elif field in {"status", "coverage_status", "resolution_status", "identity_status"}:
                values[field] = kit.Tag(str(value).replace("_", " ").title(), "warn")
            else:
                values[field] = str(value)
        rows.append(values)
    return kit.EvidenceTable(
        name=name,
        columns=table_columns(selected, labels),
        rows=rows,
        file_name=path.name,
        source_path=str(path),
    )


def legacy_action_panel(page: ft.Page, legacy_control: ft.Control, title: str, note: str) -> ft.Control:
    """Rebuild existing action callbacks with kit inputs and buttons."""
    fields: list[tuple[ft.Control, ft.Control]] = []
    buttons: list[ft.Control] = []
    details: list[ft.Control] = []
    field_map: dict[int, ft.Control] = {}

    def collect(control: ft.Control) -> None:
        name = control.__class__.__name__
        if name == "TextField":
            key = id(control)
            if key not in field_map:
                replacement = ft.TextField(
                    label=getattr(control, "label", None),
                    value=getattr(control, "value", None),
                    key=getattr(control, "key", None),
                    password=bool(getattr(control, "password", False)),
                    can_reveal_password=bool(getattr(control, "can_reveal_password", False)),
                    **kit.field_input_style(placeholder=str(getattr(control, "hint_text", "") or "")),
                )

                def copy_value(_event: ft.ControlEvent, old=control, new=replacement) -> None:
                    old.value = new.value

                replacement.on_change = copy_value
                field_map[key] = replacement
                fields.append((control, replacement))
            return
        if name == "Dropdown":
            if id(control) in field_map:
                return
            options = [
                str(getattr(option, "key", None) or getattr(option, "text", ""))
                for option in (getattr(control, "options", None) or [])
            ]

            def copy_dropdown(value: str, old=control) -> None:
                old.value = value

            replacement = kit.Field(
                str(getattr(control, "label", None) or "Option"),
                value=str(getattr(control, "value", "") or ""),
                options=options,
                on_change=copy_dropdown,
            )
            field_map[id(control)] = replacement
            fields.append((control, replacement))
            return
        if name in {"OutlinedButton", "ElevatedButton", "TextButton", "FilledButton"}:
            key = getattr(control, "key", None)
            text = ACTION_LABELS.get(str(key))
            if text is None and str(key).startswith("manual-note.confirm."):
                text = "Confirm flags"
            elif text is None and str(key).startswith("manual-note.clear."):
                text = "Clear flags"
            if text is None:
                text = getattr(control, "text", None)
            if not isinstance(text, str) or not text:
                text = getattr(text, "value", None) or _first_text(control)
            text = text or "Action"
            callback = getattr(control, "on_click", None)

            def invoke(event: ft.ControlEvent, action=callback) -> None:
                for old, new in fields:
                    if old.__class__.__name__ == "TextField":
                        old.value = new.value
                if action is not None:
                    action(event)

            button_builder = kit.Button.secondary
            buttons.append(
                button_builder(
                    str(text),
                    on_click=invoke,
                    key=getattr(control, "key", None),
                )
            )
            return
        if name == "Text":
            value = str(getattr(control, "value", "") or "")
            if value:
                details.append(kit.Disclosure("Import status detail", control))
            return
        if name == "DataTable":
            old_columns = getattr(control, "columns", [])
            columns: list[kit.TableColumn] = []
            for index, column in enumerate(old_columns):
                label = getattr(getattr(column, "label", None), "value", None) or f"Column {index + 1}"
                columns.append(kit.TableColumn(f"column_{index}", str(label)))
            rows: list[dict[str, object]] = []
            for row in getattr(control, "rows", []):
                values = {}
                for index, cell in enumerate(getattr(row, "cells", [])):
                    value = getattr(getattr(cell, "content", None), "value", None)
                    label = str(getattr(getattr(old_columns[index], "label", None), "value", ""))
                    technical = any(
                        token in label.lower()
                        for token in ("checksum", "sha", "path", "status", "authority", "source id", "json")
                    )
                    display = display_value(value)
                    values[f"column_{index}"] = (
                        kit.Disclosure("Technical detail", display)
                        if technical and display != "—"
                        else display
                    )
                rows.append(values)
            if columns:
                details.append(kit.DataTable(columns, rows))
            return
        children = getattr(control, "controls", None)
        if children is not None:
            for child in children:
                collect(child)
        content = getattr(control, "content", None)
        if content is not None and content is not control:
            collect(content)

    collect(legacy_control)

    field_controls = [new for old, new in fields]
    rendered: list[ft.Control] = [
        ft.Row(field_controls, spacing=8, wrap=True),
        ft.Row(buttons, spacing=8, wrap=True),
        *details,
    ]
    if not field_controls and not buttons and not details:
        rendered = [kit.EmptyState("Unavailable", "Import controls are unavailable.")]
    return kit.GlassCard(
        title,
        note,
        body=ft.Column(rendered, spacing=8),
    )


def unavailable_reason(frame: pd.DataFrame, reason: str) -> str | None:
    return None if not frame.empty else reason


def _first_text(control: ft.Control) -> str | None:
    pending = [control]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in visited:
            continue
        visited.add(id(current))
        if current.__class__.__name__ == "Text":
            value = getattr(current, "value", None)
            if value:
                return str(value)
        pending.extend(getattr(current, "controls", None) or [])
        content = getattr(current, "content", None)
        if content is not None:
            pending.append(content)
    return None
