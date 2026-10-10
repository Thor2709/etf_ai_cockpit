"""Data components: Tag, ScoreBar, Badge, ListRow, GlossaryItem, DataTable, EvidenceTableSwitcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.kit._base import (
    dot_colour,
    drops,
    hairline,
    hgradient,
    ring,
    sym,
    tag_semantics,
    txt,
    vgradient,
)
from etf_cockpit.app.components.kit.controls import Disclosure, Segmented, _safe_update
from etf_cockpit.app.components.kit.surfaces import EmptyState, GlassCard, Well
from etf_cockpit.app.components.chartkit.core import finite

TAG_KINDS = tuple(theme.TAG_TONES)


def Tag(text: str, kind: str = "mute", *, dense: bool = False, key: str | None = None) -> ft.Container:  # noqa: N802
    """Status pill (spec 3.4). Kinds: ok, warn, bad, mute. The text is the primary signal, colour secondary."""
    if kind not in theme.TAG_TONES:
        raise ValueError(f"kind must be one of {TAG_KINDS}")
    foreground, background = theme.TAG_TONES[kind]
    tag = ft.Container(
        content=txt(text, 11.5 if dense else 12.5, 650, foreground, trunc=True),
        bgcolor=background,
        border=ring(theme.rgba(255, 255, 255, 0.12)),
        border_radius=theme.RADIUS_PILL,
        padding=sym(12, 4),
    )
    tag_semantics(tag, key=key, label=None)
    tag.data = {"kit": "Tag", "kind": kind, "text": text}
    return tag


def score_colors(value: float, maximum: float = 10.0) -> tuple[str, str]:
    """Gradient colours of a score on its canonical 0-10 scale: >=6 default, 5-5.9 gold, <5 red-to-gold."""
    scaled = value * 10.0 / maximum if maximum else value
    if scaled >= 6.0:
        return (theme.ACC, theme.CHART_POS)
    if scaled >= 5.0:
        return ("#c9a45e", "#e6c27a")
    return ("#c8625a", "#e6c27a")


def ScoreBar(  # noqa: N802
    value: float | None,
    color: Sequence[str] | None = None,
    *,
    maximum: float = 10.0,
    decimals: int | None = None,
    expand: bool | int = True,
    width: float | None = None,
    key: str | None = None,
) -> ft.Row:
    """8px track with a gradient fill and a 30px value slot (spec 3.5).

    Scores use the canonical 0-10 scale (one decimal, colour rule applies). Weight bars pass ``maximum=100``
    with the value in percent; they keep the default colour. ``None`` renders an empty track and an em dash.
    """
    value = finite(value)
    if value is not None and maximum <= 0:
        raise ValueError("maximum must be positive")
    shown = max(0.0, min(maximum, value)) if value is not None else None
    if decimals is None:
        decimals = 1 if maximum == 10.0 else 0
    if shown is None:
        fill: ft.Control = ft.Container()
        label = "—"
        flex_fill = 0
    else:
        colours = list(color) if color else (list(score_colors(shown, maximum)) if maximum == 10.0 else [theme.ACC, theme.CHART_POS])
        flex_fill = round(shown / maximum * 1000)
        fill = ft.Container(
            gradient=hgradient(colours),
            border_radius=theme.RADIUS_TRACK,
            expand=max(flex_fill, 1),
        )
        label = f"{shown:.{decimals}f}"
    track_children: list[ft.Control] = []
    if flex_fill > 0:
        track_children.append(fill)
    if flex_fill < 1000:
        track_children.append(ft.Container(expand=max(1000 - flex_fill, 1)))
    track = ft.Container(
        content=ft.Row(track_children, spacing=0),
        height=8,
        border_radius=theme.RADIUS_TRACK,
        bgcolor=theme.rgba(0, 0, 0, 0.28),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        expand=True,
    )
    value_slot = ft.Container(
        content=txt(label, 13.5, 650, theme.INK, text_align=ft.TextAlign.RIGHT, no_wrap=True),
        width=30,
        alignment=ft.Alignment(1, 0),
    )
    row = ft.Row([track, value_slot], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                 expand=expand or None, width=width)
    tag_semantics(row, key=key, label=None)
    row.data = {"kit": "ScoreBar", "value": shown, "maximum": maximum, "label": label}
    return row


def Badge(n: int, *, key: str | None = None) -> ft.Container:  # noqa: N802
    """21px red count badge; hidden when n = 0 (spec 3.21)."""
    badge = ft.Container(
        content=txt("99+" if n > 99 else str(n), 12, 700, "#ffffff", text_align=ft.TextAlign.CENTER, no_wrap=True),
        height=21,
        width=21 if n < 10 else None,
        padding=sym(0 if n < 10 else 6, 0),
        alignment=ft.Alignment(0, 0),
        border_radius=11,
        gradient=vgradient(("#ff8f80", "#e0432f")),
        border=ring(theme.rgba(255, 255, 255, 0.85)),
        shadow=drops(((0, 2, 6, 0, theme.rgba(0, 0, 0, 0.4)),)),
        visible=n > 0,
    )
    tag_semantics(badge, key=key, label=None)
    badge.data = {"kit": "Badge", "n": n}
    return badge


def ListRow(  # noqa: N802
    dot_color: str,
    title: str,
    sub: str = "",
    tag: ft.Control | tuple[str, str] | None = None,
    *,
    last: bool = False,
    on_click: Callable[[object], object] | None = None,
    key: str | None = None,
) -> ft.Column:
    """Status-dot row with title, sub-line and optional tag; bottom hairline except on the last row (spec 3.13)."""
    colour = dot_colour(dot_color)
    dot = ft.Container(
        width=12,
        height=12,
        border_radius=6,
        bgcolor=colour,
        shadow=drops(((0, 0, 10, 0, colour),)),
    )
    text_column: list[ft.Control] = [txt(title, 14.5, 650, trunc=True)]
    if sub:
        text_column.append(txt(sub, 12.5, 400, theme.INK2, trunc=True))
    cells: list[ft.Control] = [dot, ft.Column(text_column, spacing=4, expand=True, tight=True)]
    if tag is not None:
        cells.append(tag if isinstance(tag, ft.Control) else Tag(tag[0], tag[1]))
    body = ft.Container(
        content=ft.Row(cells, spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=sym(0, 16),
        on_click=on_click,
        ink=on_click is not None,
    )
    column = ft.Column([body] if last else [body, hairline(theme.rgba(255, 255, 255, 0.08))], spacing=0)
    tag_semantics(column, key=key, label=None)
    column.data = {"kit": "ListRow", "title": title, "dot": colour, "last": last}
    return column


def GlossaryItem(  # noqa: N802
    term: str,
    gloss: str,
    selected: bool = False,
    *,
    on_click: Callable[[object], object] | None = None,
    key: str | None = None,
) -> ft.Container:
    """Full-width 49px glossary row; selected uses the quail-green fill (spec 3.14)."""
    item = ft.Container(
        content=ft.Row(
            [
                txt(term, 14, 600, theme.SELECTED_INK if selected else theme.INK2, trunc=True, expand=1, expand_loose=True),
                txt(gloss, 14, 500, theme.SELECTED_INK if selected else theme.INK2, opacity=0.80, trunc=True,
                    text_align=ft.TextAlign.RIGHT, expand=1, expand_loose=True),
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=49,
        padding=sym(16, 0),
        border_radius=14,
        gradient=vgradient(theme.SELECTED_BG, (0, 0.55, 1)) if selected else None,
        border=ring(theme.SELECTED_RIM) if selected else None,
        shadow=drops(((0, 2, 0, 0, theme.SELECTED_UNDER),)) if selected else None,
        on_click=on_click,
        ink=on_click is not None,
        ink_color=theme.HOVER_OVERLAY,
    )
    tag_semantics(item, key=key, label=None)
    item.data = {"kit": "GlossaryItem", "term": term, "selected": selected}
    return item


# ---------------------------------------------------------------------------
# DataTable
# ---------------------------------------------------------------------------

CellValue = str | float | int | None | ft.Control | tuple[str, str]

INITIAL_ROWS = 200  # rows built eagerly; larger tables append ROW_CHUNK more near the end of the scroll
ROW_CHUNK = 200
LOAD_AHEAD_ROWS = 20


@dataclass(frozen=True)
class TableColumn:
    """One DataTable column. ``flex`` is used when ``width`` is None; numeric columns right-align."""

    key: str
    label: str
    width: float | None = None
    flex: int = 1
    numeric: bool = False
    sortable: bool = True


def _cell(value: CellValue, column: TableColumn) -> ft.Control:
    if isinstance(value, ft.Control):
        return value
    align = ft.TextAlign.RIGHT if column.numeric else ft.TextAlign.LEFT
    if value is None:
        return txt("—", 13.5, 400, theme.INK3, text_align=align)
    if isinstance(value, tuple):
        return ft.Column(
            [
                txt(value[0], 13.5, 650, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                txt(value[1], 11.5, 400, theme.INK3, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ],
            spacing=2,
            tight=True,
        )
    return txt(str(value), 13.5, 400, text_align=align, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)


def _sized(control: ft.Control, column: TableColumn) -> ft.Container:
    return ft.Container(
        content=control,
        width=column.width,
        expand=None if column.width is not None else column.flex,
        alignment=ft.Alignment(1, 0) if column.numeric else ft.Alignment(-1, 0),
    )


def DataTable(  # noqa: N802
    columns: Sequence[TableColumn],
    rows: Sequence[Mapping[str, CellValue]],
    *,
    row_height: float = 44,
    sort_key: str | None = None,
    descending: bool = False,
    on_sort: Callable[[str, bool], object] | None = None,
    selected_index: int | None = None,
    on_select: Callable[[int], object] | None = None,
    max_visible_rows: int = 12,
    height: float | None = None,
    expand: bool | int = False,
    empty_title: str = "No rows",
    empty_reason: str = "Nothing to show yet. This is an explicit unavailable state, not zero.",
    key: str | None = None,
) -> ft.Control:
    """Virtualised table: fixed header, hairline rows, no zebra, right-aligned numerics (spec 3.3).

    Row cells are strings, numbers, ``None`` (shown as an em dash), a ``(main, sub)`` tuple for two-line name
    cells, or a ready control (Tag, ScoreBar...). Clicking a sortable header calls ``on_sort(key, descending)``;
    the caller re-sorts and rebuilds. Selected row shows the left accent bar and fill.
    """
    if not rows:
        return EmptyState(empty_title, empty_reason, expand=expand or None, height=height, key=key)
    header_cells: list[ft.Control] = []
    for column in columns:
        active = column.key == sort_key
        label = txt(column.label, 11, 600, theme.INK3, tracking=0.08, upper=True, trunc=True)
        parts: list[ft.Control] = [label]
        if active:
            parts.append(txt("▼" if descending else "▲", 9, 400, theme.INK3))
        cell = ft.Row(parts, spacing=4, alignment=ft.MainAxisAlignment.END if column.numeric
                      else ft.MainAxisAlignment.START, tight=True)
        sized = _sized(cell, column)
        if column.sortable and on_sort is not None:
            sized.on_click = lambda _event, name=column.key, flip=(not descending if active else False): on_sort(
                name, flip
            )
            sized.ink = True
            sized.ink_color = theme.HOVER_OVERLAY
        header_cells.append(sized)
    header = ft.Column(
        [
            ft.Container(content=ft.Row(header_cells, spacing=8), padding=sym(12, 8)),
            hairline(theme.HAIRLINE_STRONG),
        ],
        spacing=0,
    )

    def make_row(index: int, row: Mapping[str, CellValue]) -> ft.Control:
        is_selected = index == selected_index
        cells = [_sized(_cell(row.get(column.key), column), column) for column in columns]
        content: ft.Control = ft.Row(
            [
                ft.Container(width=3, height=row_height - 1, bgcolor=theme.ACC if is_selected else None),
                ft.Container(
                    content=ft.Row(cells, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=sym(8, 0),
                    expand=True,
                ),
            ],
            spacing=0,
        )
        line = ft.Container(
            content=ft.Column([ft.Container(content=content, height=row_height - 1), hairline(theme.HAIRLINE)],
                              spacing=0),
            height=row_height,
            bgcolor=theme.ROW_SELECTED_FILL if is_selected else None,
            on_click=(lambda _event, position=index: on_select(position)) if on_select else None,
            ink=on_select is not None,
            ink_color=theme.ROW_HOVER,
        )
        line.data = {"kit": "DataTableRow", "index": index, "selected": is_selected}
        return line

    # Only the first window of rows is materialised; the rest is appended as the user scrolls
    # (all rows stay reachable, the row order and content are unchanged).
    materialised = max(INITIAL_ROWS, (selected_index or 0) + 1)
    body_rows: list[ft.Control] = [make_row(index, row) for index, row in enumerate(rows[:materialised])]
    visible = min(len(rows), max_visible_rows)
    body = ft.ListView(
        body_rows,
        item_extent=row_height,
        spacing=0,
        height=None if expand else (height - 36 if height else visible * row_height),
        expand=expand or None,
    )
    if len(rows) > len(body.controls):

        def load_more(event: ft.OnScrollEvent) -> None:
            loaded = len(body.controls)
            if loaded >= len(rows) or event.pixels < event.max_scroll_extent - LOAD_AHEAD_ROWS * row_height:
                return
            body.controls.extend(make_row(index, rows[index]) for index in range(loaded, min(len(rows), loaded + ROW_CHUNK)))
            try:
                body.update()
            except Exception:  # not mounted yet (tests / pre-mount): rows stay appended for the next paint
                pass

        body.on_scroll = load_more
        body.on_scroll_interval = 50
    scroller: ft.Control = body
    if len(rows) > visible and not expand:
        # Overflow scrolls inside the card and the last visible row fades out (visible edge fade).
        fade = ft.Container(
            left=0,
            right=0,
            bottom=0,
            height=24,
            gradient=vgradient((theme.rgba(9, 16, 32, 0), theme.rgba(9, 16, 32, 0.85))),
            ignore_interactions=True,
        )
        scroller = ft.Stack([body, fade], height=visible * row_height)
    table = ft.Column([header, scroller], spacing=8, tight=not expand, expand=expand or None)
    tag_semantics(table, key=key, label=None)
    table.data = {"kit": "DataTable", "columns": [column.key for column in columns], "rows": len(rows),
                  "sort": (sort_key, descending)}
    return table


# ---------------------------------------------------------------------------
# EvidenceTableSwitcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceTable:
    """One evidence table: its columns/rows plus the file name and source path for the Disclosure."""

    name: str
    columns: Sequence[TableColumn]
    rows: Sequence[Mapping[str, CellValue]] = field(default_factory=tuple)
    file_name: str | None = None
    source_path: str | None = None


def _row_count(count: int) -> str:
    return f"{count} row" if count == 1 else f"{count} rows"


def EvidenceTableSwitcher(  # noqa: N802
    tables: Sequence[EvidenceTable],
    *,
    selected: str | None = None,
    title: str = "Evidence tables",
    row_height: float = 40,
    max_visible_rows: int = 12,
    key: str | None = None,
) -> ft.Container:
    """One glass card that picks one of several evidence tables with a Segmented (a dropdown above 6) (spec 3.27)."""
    if not tables:
        raise ValueError("tables must not be empty")
    by_name = {table.name: table for table in tables}
    current = {"name": selected if selected in by_name else tables[0].name}
    content = ft.Column(spacing=12, tight=True)

    def render() -> None:
        table = by_name[current["name"]]
        parts: list[ft.Control] = []
        if table.rows:
            parts.append(Well(DataTable(table.columns, table.rows, row_height=row_height,
                                        max_visible_rows=max_visible_rows), padding=sym(8, 8)))
        else:
            file_name = table.file_name or table.name
            parts.append(
                EmptyState(
                    "No rows",
                    f"{file_name} has no rows. This is an explicit unavailable state, not zero.",
                    expand=False,
                    height=140,
                )
            )
        if table.source_path:
            parts.append(Disclosure("source path", table.source_path))
        content.controls = parts
        content.data = {"kit": "EvidenceTableBody", "table": table.name, "rows": len(table.rows)}

    def choose(name: str) -> None:
        current["name"] = name
        render()
        note = card.data["note_control"]
        note.value = _row_count(len(by_name[name].rows))
        _safe_update(note)
        _safe_update(content)

    names = [table.name for table in tables]
    picker: ft.Control
    if len(names) > 6:
        from etf_cockpit.app.components.kit.controls import Field

        picker = Field("Table", options=names, value=current["name"], on_change=choose, width=320)
    else:
        picker = Segmented(names, current["name"], on_change=choose)
    render()
    card = GlassCard(
        title,
        note=_row_count(len(by_name[current["name"]].rows)),
        body=[ft.Row([picker], scroll=ft.ScrollMode.AUTO), content],
        key=key,
    )
    card.data = {**card.data, "kit": "EvidenceTableSwitcher", "tables": names}
    return card
