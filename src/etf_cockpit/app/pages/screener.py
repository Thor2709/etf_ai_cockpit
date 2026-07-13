"""Read-only fundamentals evidence surface for the local screener."""

from __future__ import annotations

import math

import flet as ft
import pandas as pd

from etf_cockpit.app import theme
from etf_cockpit.app.components.cards import evidence_chip, metric_card, panel, section_header
from etf_cockpit.app.state import AppState
from etf_cockpit.data.fundamentals import FUNDAMENTAL_CLEAN_PATH, latest_fundamental_rows, load_fundamental_evidence


_FUNDAMENTAL_FIELDS = (
    ("valuation", "Valuation"),
    ("profitability", "Profitability"),
    ("leverage", "Leverage"),
    ("growth", "Growth"),
    ("shareholder_return", "Shareholder return"),
)


def screener_page(_page: ft.Page, _state: AppState) -> ft.Control:
    """Render canonical fundamentals without changing score or action authority."""

    frame = load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    frame = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if "instrument_id" not in frame.columns:
        frame = pd.DataFrame()
    if "instrument_id" in frame.columns:
        frame = latest_fundamental_rows(frame)

    rows = _table_rows(frame)
    available_count = sum(_has_five_values(row) for _, row in frame.iterrows()) if not frame.empty else 0
    eligible_count = 0
    if "eligibility" in frame.columns:
        eligible_count = int(frame["eligibility"].astype(str).str.startswith("eligible").sum())
    status = "Canonical rows available" if not frame.empty else "No canonical rows"
    status_colour = theme.GREEN if not frame.empty else theme.AMBER

    controls: list[ft.Control] = [
        panel(
            ft.Column(
                [
                    section_header(
                        "Fundamentals Screener",
                        "Canonical five-section fundamental evidence from the local clean store. Values are context only; they do not alter score weights, actions or broker authority.",
                    ),
                    ft.Row(
                        [
                            evidence_chip("Authority", "advisory/context only", theme.CYAN),
                            evidence_chip("Missing data", "N/A, not invented", theme.AMBER),
                            evidence_chip("Broker execution", "disabled", theme.GREEN),
                            evidence_chip("Source", str(FUNDAMENTAL_CLEAN_PATH), theme.BLUE_GREY),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=10,
            )
        ),
        _summary(
            frame,
            available_count,
            eligible_count,
            status,
            status_colour,
            narrow=float(getattr(_page, "width", 0) or _state.snapshot.config.ui.window_width) < 760,
        ),
        panel(
            ft.Column(
                [
                    section_header(
                        "Instrument fundamentals",
                        "Every canonical row shows valuation, profitability, leverage, growth and shareholder return plus eligibility, provenance, freshness and limitations.",
                    ),
                    ft.Text("executable_authority=false | fundamentals are not an action or broker authority", color=theme.MUTED, size=11, selectable=True),
                    _table_body(frame, rows),
                ],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
            )
        ),
    ]
    return ft.Column(controls, spacing=14, expand=True, scroll=ft.ScrollMode.AUTO)


def _summary(
    frame: pd.DataFrame,
    available_count: int,
    eligible_count: int,
    status: str,
    status_colour: str,
    *,
    narrow: bool,
) -> ft.Control:
    total = len(frame)
    cards = [
        metric_card("Canonical instruments", str(total), status, status_colour),
        metric_card("Complete five-section", str(available_count), "all five values present", theme.GREEN if available_count else theme.AMBER),
        metric_card("Score eligible", str(eligible_count), "eligibility is evidence metadata", theme.CYAN if eligible_count else theme.AMBER),
    ]
    return ft.Column(cards, spacing=8) if narrow else ft.Row(cards, spacing=12)


def _table_body(frame: pd.DataFrame, rows: list[ft.DataRow]) -> ft.Control:
    if frame.empty:
        return ft.Text(
            "Fundamentals unavailable: no canonical rows are present at the clean path. This is an explicit no-data state; missing metrics are not inferred or scored.",
            color=theme.MUTED,
            selectable=True,
        )
    return ft.Row(
        [
            ft.DataTable(
                columns=[ft.DataColumn(ft.Text(label, color=theme.TEXT, size=11)) for label in _column_labels()],
                rows=rows,
                data_row_min_height=42,
                data_row_max_height=120,
            )
        ],
        scroll=ft.ScrollMode.AUTO,
    )


def _table_rows(frame: pd.DataFrame) -> list[ft.DataRow]:
    if frame.empty:
        return []
    rows: list[ft.DataRow] = []
    for _, record in frame.iterrows():
        cells = [
            ft.DataCell(ft.Text(_display(record.get("instrument_id")), color=theme.TEXT, size=11, selectable=True)),
            *[
                ft.DataCell(ft.Text(_display(record.get(field)), color=theme.TEXT if _is_value(record.get(field)) else theme.AMBER, size=11, selectable=True))
                for field, _label in _FUNDAMENTAL_FIELDS
            ],
            ft.DataCell(ft.Text(_display(record.get("eligibility"), fallback="unavailable"), color=theme.CYAN, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("source", record.get("source_authority")), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("as_of_date", record.get("as_of")), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("missing_fields"), fallback="none recorded"), color=theme.AMBER if _is_value(record.get("missing_fields")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("warnings"), fallback="none recorded"), color=theme.AMBER if _is_value(record.get("warnings")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("limitations"), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_status"), fallback="unavailable"), color=theme.CYAN if _is_value(record.get("sector_relative_status")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_value"), fallback="unavailable"), color=theme.CYAN if _is_value(record.get("sector_relative_value")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_peer"), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_benchmark"), fallback="unavailable"), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_delta"), fallback="unavailable"), color=theme.CYAN if _is_value(record.get("sector_relative_delta")) else theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text(_display(record.get("sector_relative_limitation"), fallback="No sector-relative comparison evidence supplied."), color=theme.MUTED, size=11, selectable=True)),
            ft.DataCell(ft.Text("false", color=theme.GREEN, size=11, selectable=True)),
        ]
        rows.append(ft.DataRow(cells=cells))
    return rows


def _column_labels() -> tuple[str, ...]:
    return (
        "Instrument",
        *(label for _field, label in _FUNDAMENTAL_FIELDS),
        "Eligibility",
        "Source",
        "As of",
        "Missing",
        "Warnings",
        "Limitations",
        "Sector-relative",
        "Sector value",
        "Sector peer",
        "Sector benchmark",
        "Sector delta",
        "Sector limitation",
        "Executable authority",
    )


def _has_five_values(record: pd.Series) -> bool:
    return all(_is_value(record.get(field)) for field, _label in _FUNDAMENTAL_FIELDS)


def _is_value(value: object) -> bool:
    if value is None:
        return False
    if value is pd.NA or value is pd.NaT:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        # Array-like metadata (for example a list of limitations) is valid
        # evidence and is rendered as joined text below.
        return True
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return True


def _display(value: object, *, fallback: str = "N/A") -> str:
    if not _is_value(value):
        return fallback
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value) or fallback
    return str(value)


__all__ = ["screener_page"]
