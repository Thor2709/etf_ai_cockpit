from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Callable

import flet as ft
import pandas as pd

from etf_cockpit.app.components.charts import score_meter
from etf_cockpit.app.theme import MUTED, TEXT
from etf_cockpit.core.types import SignalResult


@dataclass(frozen=True)
class AccessibleTable:
    """Table view metadata kept alongside the Flet control for text-first QA."""

    control: ft.DataTable
    table_id: str
    search_label: str
    sortable_columns: tuple[str, ...]
    status_text: str
    frame: pd.DataFrame
    search_callback: object
    sort_callback: object
    search_control: ft.TextField
    status_control: ft.Text
    empty_control: ft.Text | None = None
    compact: bool = False
    page_size: int = 50
    page_count: int = 1
    page_control: ft.Text | None = None
    previous_control: ft.TextButton | None = None
    next_control: ft.TextButton | None = None
    reset_control: ft.TextButton | None = None
    page_callback: Callable[[int], pd.DataFrame] | None = None
    reset_callback: Callable[[], pd.DataFrame] | None = None

    def search(self, query: str) -> pd.DataFrame:
        return self.search_callback(query)

    def sort(self, column: str, ascending: bool = True) -> pd.DataFrame:
        return self.sort_callback(column, ascending)

    def page(self, number: int) -> pd.DataFrame:
        """Show a bounded page and return the complete page data frame."""

        if self.page_callback is None:
            return self.frame.copy()
        # The public helper is intentionally one-based (as the visible page
        # indicator is), while the private callback remains zero-based for
        # straightforward button arithmetic.  Keep page(0) as a forgiving
        # alias for callers that used the original headless test convention.
        return self.page_callback(max(0, int(number) - 1) if int(number) > 0 else 0)

    def reset(self) -> pd.DataFrame:
        """Clear search/sort paging state and show the first bounded page."""

        if self.reset_callback is None:
            return self.frame.copy()
        return self.reset_callback()

    @property
    def controls(self) -> tuple[ft.Control, ...]:
        """Return the complete keyboard-addressable presentation controls."""

        controls: list[ft.Control] = [self.search_control]
        if self.reset_control is not None:
            controls.append(self.reset_control)
        controls.append(self.control)
        if self.empty_control is not None:
            controls.append(self.empty_control)
        controls.append(self.status_control)
        if self.previous_control is not None:
            controls.append(self.previous_control)
        if self.page_control is not None:
            controls.append(self.page_control)
        if self.next_control is not None:
            controls.append(self.next_control)
        return tuple(controls)


def accessible_table(
    frame: pd.DataFrame,
    *,
    table_id: str,
    searchable: bool = True,
    sortable: bool = True,
    compact: bool = False,
    empty_message: str = "No matching rows found.",
    page_size: int = 50,
) -> AccessibleTable:
    if isinstance(page_size, bool) or int(page_size) < 1:
        raise ValueError("page_size must be a positive integer")
    page_size = int(page_size)
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    columns = tuple(str(column) for column in data.columns)

    def _is_structured_cell(value: object) -> bool:
        return isinstance(value, (dict, list, tuple, set))

    sortable_columns = tuple(
        column
        for column in columns
        if sortable and not data[column].map(_is_structured_cell).any()
    )

    def _cell_text(value: object) -> str:
        if _is_structured_cell(value):
            return str(value)
        missing = pd.isna(value)
        return "" if isinstance(missing, bool) and missing else str(value)

    def _rows(view: pd.DataFrame) -> list[ft.DataRow]:
        return [
            ft.DataRow(
                cells=[
                    ft.DataCell(
                        ft.Text(
                            _cell_text(value),
                            selectable=True,
                            tooltip=_cell_text(value) if len(_cell_text(value)) > 30 else None,
                            overflow=ft.TextOverflow.ELLIPSIS if len(_cell_text(value)) > 30 else None,
                        )
                    )
                    for value in row
                ]
            )
            for row in view.itertuples(index=False, name=None)
        ]

    def search_callback(query: str) -> pd.DataFrame:
        text = str(query or "").strip().casefold()
        if not text:
            return data.copy()
        # Search text is user input, not a regular expression.  Treating it
        # literally keeps punctuation such as ``[`` and ``(`` safe and
        # predictable while still matching case-insensitively.
        mask = data.astype("string").apply(lambda column: column.str.casefold().str.contains(text, na=False, regex=False)).any(axis=1)
        return data.loc[mask].copy()

    def sort_callback(column: str, ascending: bool = True) -> pd.DataFrame:
        if column not in sortable_columns:
            return data.copy()
        return data.sort_values(column, ascending=bool(ascending), kind="stable", na_position="last").reset_index(drop=True)

    status_control = ft.Text(
        f"{len(data)} rows; status is shown as text",
        key=f"{table_id}.status",
        selectable=True,
    )
    empty_control = ft.Text(
        empty_message,
        key=f"{table_id}.empty",
        color=MUTED,
        visible=len(data) == 0,
        selectable=True,
    )
    page_control = ft.Text(f"Page 1 of {max(1, ceil(len(data) / page_size))}", key=f"{table_id}.page", selectable=True)
    page_count = max(1, ceil(len(data) / page_size))
    state = {"view": data.copy(), "page": 0}

    def _is_detached_control_error(exc: RuntimeError) -> bool:
        return " ".join(str(exc).casefold().split()).endswith("control must be added to the page first")

    def _update_view(view: pd.DataFrame, *, page: int = 0) -> pd.DataFrame:
        state["view"] = view.copy()
        page_count_current = max(1, ceil(len(view) / page_size))
        state["page"] = min(max(int(page), 0), page_count_current - 1)
        start = state["page"] * page_size
        visible = view.iloc[start : start + page_size]
        control.rows = _rows(visible)
        end = min(start + len(visible), len(view))
        if len(view) == 0:
            status_control.value = "0 rows; status is shown as text"
        elif len(view) > page_size:
            status_control.value = f"Showing {start + 1}-{end} of {len(view)} rows; status is shown as text"
        else:
            status_control.value = f"{len(view)} rows; status is shown as text"
        empty_control.visible = len(view) == 0
        page_control.value = f"Page {state['page'] + 1} of {page_count_current}"
        previous_control.disabled = state["page"] == 0
        next_control.disabled = state["page"] >= page_count_current - 1
        update = getattr(control, "update", None)
        if callable(update):
            try:
                update()
            except RuntimeError as exc:
                # Flet controls can be filtered before they are mounted on a
                # page (for example in headless tests).  The in-memory view
                # is still updated; a mounted page will redraw on its normal
                # event loop.
                if not _is_detached_control_error(exc):
                    raise
        status_update = getattr(status_control, "update", None)
        if callable(status_update):
            try:
                status_update()
            except RuntimeError as exc:
                if not _is_detached_control_error(exc):
                    raise
        empty_update = getattr(empty_control, "update", None)
        if callable(empty_update):
            try:
                empty_update()
            except RuntimeError as exc:
                if not _is_detached_control_error(exc):
                    raise
        page_update = getattr(page_control, "update", None)
        if callable(page_update):
            try:
                page_update()
            except RuntimeError as exc:
                if not _is_detached_control_error(exc):
                    raise
        return visible.copy()

    def _search_changed(event: ft.ControlEvent) -> None:
        query = getattr(event, "data", None)
        if query is None:
            query = search_control.value
        _update_view(search_callback(str(query or "")), page=0)

    search_control = ft.TextField(
        key=f"{table_id}.search",
        label=f"Search {table_id}" if searchable else "",
        hint_text=f"Filter {table_id}..." if searchable else "",
        tooltip=f"Filter {table_id} rows by keyword",
        visible=searchable,
        dense=True,
        on_change=_search_changed if searchable else None,
    )

    def _sort_event(column: str):
        def callback(event: ft.ControlEvent) -> None:
            ascending = bool(getattr(event, "ascending", True))
            _update_view(sort_callback(column, ascending), page=0)

        return callback

    table_columns: list[ft.DataColumn] = []
    for column in columns:
        callback = _sort_event(column) if column in sortable_columns else None
        label = ft.Text(column, tooltip=f"Sort by {column}" if callback else None)
        try:
            table_columns.append(ft.DataColumn(label, on_sort=callback))
        except TypeError:
            # Keep compatibility with older Flet releases while preserving
            # truthful callback metadata for accessibility and tests.
            data_column = ft.DataColumn(label)
            data_column.on_sort = callback
            table_columns.append(data_column)

    control = ft.DataTable(
        key=f"{table_id}.table",
        columns=table_columns,
        rows=[],
        data_row_min_height=28 if compact else 36,
        data_row_max_height=42 if compact else 56,
        column_spacing=8 if compact else 14,
    )

    def _go_to_page(number: int) -> pd.DataFrame:
        return _update_view(state["view"], page=number)

    def _previous(_event: ft.ControlEvent) -> None:
        _go_to_page(state["page"] - 1)

    def _next(_event: ft.ControlEvent) -> None:
        _go_to_page(state["page"] + 1)

    def _reset(_event: ft.ControlEvent | None = None) -> None:
        search_control.value = ""
        _update_view(data, page=0)

    previous_control = ft.TextButton(
        "Previous",
        key=f"{table_id}.previous",
        tooltip="Show the previous table page",
        on_click=_previous,
        disabled=True,
    )
    next_control = ft.TextButton(
        "Next",
        key=f"{table_id}.next",
        tooltip="Show the next table page",
        on_click=_next,
        disabled=page_count <= 1,
    )
    reset_control = ft.TextButton(
        "Reset",
        key=f"{table_id}.reset",
        tooltip="Clear table search and sorting",
        on_click=_reset,
    )
    _update_view(data, page=0)

    return AccessibleTable(
        control=control,
        table_id=str(table_id),
        search_label=f"Search {table_id}" if searchable else "",
        sortable_columns=sortable_columns,
        status_text=f"{len(data)} rows; status is shown as text",
        frame=data,
        search_callback=search_callback,
        sort_callback=sort_callback,
        search_control=search_control,
        status_control=status_control,
        empty_control=empty_control,
        compact=compact,
        page_size=page_size,
        page_count=page_count,
        page_control=page_control,
        previous_control=previous_control,
        next_control=next_control,
        reset_control=reset_control,
        page_callback=_go_to_page,
        reset_callback=lambda: (_reset() or state["view"].copy()),
    )


def signals_table(signals: list[SignalResult], allocation_lookup: dict[str, dict[str, float]]) -> ft.DataTable:
    rows: list[ft.DataRow] = []
    for signal in sorted(signals, key=lambda item: (-item.total_score, item.action == "no_trade", -item.confidence)):
        metrics = signal.supporting_metrics
        model_text = f"Toto {signal.components.toto:+.2f} | TimesFM {signal.components.timesfm:+.2f}"
        context = ", ".join(signal.blocked_by or signal.warnings) or f"edge {float(metrics.get('expected_edge_bps') or 0):+.0f} bps"
        cost_warning = metrics.get("cost_stress_warning")
        if cost_warning:
            context = f"{context} | costs: {cost_warning}"
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(signal.etf_id, color=TEXT, size=12, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(score_meter(signal.total_score)),
                    ft.DataCell(ft.Text(model_text, color=TEXT, size=11)),
                    ft.DataCell(ft.Text(signal.reason_short, color=TEXT, size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Text(context, color=MUTED, size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)),
                ]
            )
        )
    return ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Instrument")),
            ft.DataColumn(ft.Text("Evidence score")),
            ft.DataColumn(ft.Text("Models")),
            ft.DataColumn(ft.Text("Explanation")),
            ft.DataColumn(ft.Text("Context")),
        ],
        rows=rows,
        column_spacing=14,
        data_row_min_height=56,
        data_row_max_height=68,
    )
