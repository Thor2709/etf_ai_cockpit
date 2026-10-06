from __future__ import annotations

from dataclasses import dataclass

import flet as ft
import pandas as pd



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

    def search(self, query: str) -> pd.DataFrame:
        return self.search_callback(query)

    def sort(self, column: str, ascending: bool = True) -> pd.DataFrame:
        return self.sort_callback(column, ascending)


def accessible_table(
    frame: pd.DataFrame,
    *,
    table_id: str,
    searchable: bool = True,
    sortable: bool = True,
) -> AccessibleTable:
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    columns = tuple(str(column) for column in data.columns)

    def _is_structured_cell(value: object) -> bool:
        return isinstance(value, (dict, list, tuple, set))

    sortable_columns = tuple(
        column
        for column in columns
        if sortable and not data[column].map(_is_structured_cell).any()
    )
    active_query = ""
    active_sort: tuple[str, bool] | None = None

    def _cell_text(value: object) -> str:
        if _is_structured_cell(value):
            return str(value)
        missing = pd.isna(value)
        return "" if isinstance(missing, bool) and missing else str(value)

    def _rows(view: pd.DataFrame) -> list[ft.DataRow]:
        return [
            ft.DataRow(cells=[ft.DataCell(ft.Text(_cell_text(value), selectable=True)) for value in row])
            for row in view.itertuples(index=False, name=None)
        ]

    def search_callback(query: str) -> pd.DataFrame:
        nonlocal active_query
        active_query = str(query or "").strip().casefold()
        return _current_view()

    def _current_view() -> pd.DataFrame:
        view = data
        if active_query:
            # Search text is user input, not a regular expression.  Treating it
            # literally keeps punctuation such as ``[`` and ``(`` safe and
            # predictable while still matching case-insensitively.
            mask = data.astype("string").apply(lambda column: column.str.casefold().str.contains(active_query, na=False, regex=False)).any(axis=1)
            view = data.loc[mask]
        if active_sort is not None and active_sort[0] in sortable_columns:
            column, ascending = active_sort
            view = view.sort_values(column, ascending=ascending, kind="stable", na_position="last")
        return view.reset_index(drop=True).copy()

    def sort_callback(column: str, ascending: bool = True) -> pd.DataFrame:
        nonlocal active_sort
        if column not in sortable_columns:
            return data.copy()
        active_sort = (column, bool(ascending))
        return _current_view()

    status_control = ft.Text(f"{len(data)} rows; status is shown as text", selectable=True)

    def _is_detached_control_error(exc: RuntimeError) -> bool:
        return " ".join(str(exc).casefold().split()).endswith("control must be added to the page first")

    def _update_view(view: pd.DataFrame) -> None:
        control.rows = _rows(view)
        status_control.value = f"{len(view)} rows; status is shown as text"
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

    def _search_changed(event: ft.ControlEvent) -> None:
        query = getattr(event, "data", None)
        if query is None:
            query = search_control.value
        _update_view(search_callback(str(query or "")))

    search_control = ft.TextField(
        key=f"{table_id}.search",
        label=f"Search {table_id}" if searchable else "",
        visible=searchable,
        dense=True,
        on_change=_search_changed if searchable else None,
    )

    def _sort_event(column: str):
        def callback(event: ft.ControlEvent) -> None:
            ascending = bool(getattr(event, "ascending", True))
            _update_view(sort_callback(column, ascending))

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
        columns=table_columns,
        rows=_rows(data),
        data_row_min_height=36,
        data_row_max_height=56,
        column_spacing=14,
    )

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
    )
