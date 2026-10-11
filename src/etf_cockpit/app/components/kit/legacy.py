from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components.flet_compat import border_all
from etf_cockpit.core.paths import DATA_DIR


def _gradient(colors: Sequence[str], *, horizontal: bool = False) -> ft.LinearGradient:
    begin = ft.Alignment(-1, 0) if horizontal else ft.Alignment(0, -1)
    end = ft.Alignment(1, 0) if horizontal else ft.Alignment(0, 1)
    return ft.LinearGradient(colors=list(colors), begin=begin, end=end)


def _shadow(color: str, *, blur: float, x: float = 0, y: float = 0) -> ft.BoxShadow:
    return ft.BoxShadow(color=color, blur_radius=blur, offset=ft.Offset(x, y))


def _control_border(*, selected: bool = False) -> ft.Border:
    # Flutter paints a non-uniform Border as a square rectangle and ignores border_radius,
    # which drew a box around every pill; keep all four sides identical.
    del selected
    return border_all(1, theme.HAIRLINE_BORDER)


def _accessible(control: ft.Control, *, key: str, label: str) -> ft.Control:
    control.key = key
    control.tooltip = label
    return control


def _well(content: ft.Control, *, expand: bool = False, padding: int = 14) -> ft.Container:
    return ft.Container(
        content=content,
        gradient=_gradient(("#e0091020", "#b8091020")),
        border=border_all(1, theme.RECESSED_WELL_BORDER),
        border_radius=theme.INNER_RADIUS,
        shadow=[_shadow("#47000000", blur=12, y=3)],
        padding=padding,
        expand=expand or None,
    )


def glass_panel(
    content: ft.Control,
    *,
    key: str,
    label: str,
    expand: bool | int = False,
    padding: int = 22,
) -> ft.Container:
    """Place content on the translucent, softly raised theme-25 glass surface."""
    return _accessible(
        ft.Container(
            content=content,
            gradient=_gradient(("#4c0e1830", "#38081024")),
            blur=theme.GLASS_PANEL_BLUR,
            border=border_all(1, theme.GLASS_PANEL_BORDER),
            border_radius=theme.CARD_RADIUS,
            shadow=[_shadow("#59020614", blur=30, y=14)],
            padding=padding,
            expand=expand or None,
        ),
        key=key,
        label=label,
    )


def card(
    title: str,
    body: ft.Control,
    note: str = "",
    insight: str | None = None,
    *,
    key: str,
    label: str | None = None,
) -> ft.Container:
    """Render the shared title, note, optional insight, and recessed-well card."""
    heading: list[ft.Control] = [
        ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=theme.TEXT, expand=True)
    ]
    if note:
        heading.append(ft.Text(note, size=12, color=theme.BLUE_GREY, text_align=ft.TextAlign.RIGHT))
    contents: list[ft.Control] = [
        ft.Row(heading, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    ]
    if insight:
        contents.append(
            ft.Text(insight, size=12, color=theme.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        )
    contents.append(_well(body, expand=True))
    return glass_panel(
        ft.Column(contents, spacing=8, expand=True),
        key=key,
        label=label or title,
        expand=True,
    )


def kpi_tile(label: str, value: str, detail: str = "", *, key: str) -> ft.Container:
    content: list[ft.Control] = [
        ft.Text(label, size=11, color=theme.BLUE_GREY, weight=ft.FontWeight.W_600),
        ft.Text(value, size=26, color=theme.TEXT, weight=ft.FontWeight.W_500),
    ]
    if detail:
        content.append(ft.Text(detail, size=12, color=theme.MUTED))
    return _accessible(_well(ft.Column(content, spacing=3), padding=14), key=key, label=label)


def status_tag(text: str, tone: str = "g", *, key: str) -> ft.Container:
    """Show status in text and colour; the text remains the primary signal."""
    tones = {
        "g": ("#296fcfa6", theme.GREEN),
        "w": ("#29e6c27a", theme.AMBER),
        "b": ("#29e8897c", theme.RED),
    }
    if tone not in tones:
        raise ValueError("tone must be one of 'g', 'w', or 'b'")
    background, foreground = tones[tone]
    return _accessible(
        ft.Container(
            content=ft.Text(text, size=12, color=foreground, weight=ft.FontWeight.W_600),
            bgcolor=background,
            border=border_all(1, theme.HAIRLINE_BORDER),
            border_radius=999,
            padding=ft.Padding(left=10, top=4, right=10, bottom=4),
        ),
        key=key,
        label=text,
    )


def score_bar(
    score: float,
    *,
    key: str,
    label: str = "Score",
    maximum: float = 100,
) -> ft.Row:
    if maximum <= 0 or score < 0 or score > maximum:
        raise ValueError("score must be between zero and a positive maximum")
    fraction = score / maximum
    track = ft.Container(
        content=ft.Container(
            width=160 * fraction,
            height=8,
            gradient=_gradient((theme.CYAN, theme.GREEN), horizontal=True),
            border_radius=5,
        ),
        width=160,
        height=8,
        bgcolor="#47000000",
        border_radius=5,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        expand=True,
    )
    return _accessible(
        ft.Row(
            [
                ft.Text(label, size=12, color=theme.MUTED),
                track,
                ft.Text(f"{score:g}", size=12, color=theme.TEXT, weight=ft.FontWeight.W_600),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        key=key,
        label=f"{label}: {score:g} of {maximum:g}",
    )


def pill_group(
    options: Sequence[str],
    selected: str,
    *,
    key: str,
    label: str,
    on_change: Callable[[str], object] | None = None,
) -> ft.Container:
    if not options or sum(option == selected for option in options) != 1:
        raise ValueError("selected must match exactly one option")
    pills: list[ft.Control] = []
    for index, option in enumerate(options):
        is_selected = option == selected

        def select(_event: object, value: str = option) -> None:
            if on_change is not None:
                on_change(value)

        pills.append(
            ft.Container(
                content=ft.Text(
                    option,
                    size=13,
                    color=theme.QUAIL_SELECTED_INK if is_selected else theme.MUTED,
                    weight=ft.FontWeight.W_600,
                ),
                gradient=_gradient(theme.QUAIL_SELECTED_COLORS) if is_selected else _gradient(
                    ("#14ffffff", "#0dffffff")
                ),
                border=_control_border(selected=is_selected),
                border_radius=12,
                shadow=[_shadow(theme.QUAIL_SELECTED_SHADOW, blur=0, y=3)] if is_selected else None,
                padding=ft.Padding(left=14, top=7, right=14, bottom=7),
                data="selected" if is_selected else "unselected",
                key=f"{key}:{index}",
                tooltip=f"{label}: {option}",
                on_click=select,
            )
        )
    return _accessible(
        ft.Container(
            content=ft.Row(pills, spacing=4, tight=True),
            bgcolor="#73040a1a",
            border=border_all(1, theme.HAIRLINE_BORDER),
            border_radius=14,
            padding=4,
        ),
        key=key,
        label=label,
    )


def toggle(
    label: str,
    value: bool,
    *,
    key: str,
    on_change: Callable[[bool], object] | None = None,
) -> ft.Container:
    def change(_event: object) -> None:
        if on_change is not None:
            on_change(not value)

    knob = ft.Container(
        width=18,
        height=18,
        bgcolor="#e6edff",
        border_radius=999,
        shadow=[_shadow("#73000000", blur=4, y=2)],
    )
    track = ft.Container(
        content=knob,
        alignment=ft.Alignment(1 if value else -1, 0),
        width=40,
        height=22,
        gradient=_gradient(theme.QUAIL_SELECTED_COLORS) if value else None,
        bgcolor=None if value else "#59000000",
        border_radius=12,
        border=_control_border(selected=value),
        shadow=[_shadow("#73000000", blur=5)],
    )
    return _accessible(
        ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        label,
                        color=theme.QUAIL_SELECTED_INK if value else theme.MUTED,
                        size=13,
                    ),
                    track,
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=change,
            ink=True,
            padding=4,
        ),
        key=key,
        label=label,
    )


def cta_button(
    text: str,
    *,
    key: str,
    label: str,
    primary: bool = True,
    on_click: Callable[[object], object] | None = None,
) -> ft.Container:
    selected = primary
    return _accessible(
        ft.Container(
            content=ft.Text(
                text,
                size=13,
                color=theme.QUAIL_SELECTED_INK if selected else theme.TEXT,
                weight=ft.FontWeight.W_700,
            ),
            gradient=_gradient(theme.QUAIL_SELECTED_COLORS) if selected else _gradient(
                ("#33ffffff", "#12ffffff")
            ),
            border=_control_border(selected=selected),
            border_radius=13,
            shadow=[_shadow(theme.QUAIL_SELECTED_SHADOW, blur=0, y=3), _shadow("#4c000000", blur=14, y=8)],
            padding=ft.Padding(left=18, top=10, right=18, bottom=10),
            on_click=on_click,
            ink=True,
        ),
        key=key,
        label=label,
    )


def table_style(table: ft.Control, *, key: str, label: str) -> ft.Container:
    """Place a Flet table inside the dark recessed plate used by data cards."""
    return _accessible(_well(table, padding=8), key=key, label=label)


def cylinder_bar(
    values: Sequence[tuple[str, float]],
    *,
    axis_label: str,
    unit: str,
    maximum: float,
    key: str,
    label: str,
) -> ft.Container:
    """Draw labelled horizontal bars with the theme's three-stop cylinder gradient."""
    if maximum <= 0 or any(value < 0 or value > maximum for _, value in values):
        raise ValueError("bar values must be between zero and a positive maximum")
    rows: list[ft.Control] = []
    for row_label, value in values:
        rows.append(
            ft.Row(
                [
                    ft.Text(row_label, width=116, size=12, color=theme.MUTED),
                    ft.Container(
                        content=ft.Container(
                            width=240 * value / maximum,
                            height=15,
                            gradient=ft.LinearGradient(
                                colors=list(theme.CYLINDER_BAR_COLORS),
                                stops=[0, 0.32, 1],
                                begin=ft.Alignment(-1, 0),
                                end=ft.Alignment(1, 0),
                            ),
                            border=border_all(1, "#29ffffff"),
                            border_radius=999,
                        ),
                        width=240,
                        height=15,
                        bgcolor="#3d000000",
                        border_radius=999,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                    ft.Text(f"{value:g} {unit}", size=12, color=theme.TEXT),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
    chart = ft.Column(
        [
            ft.Text(f"{axis_label} ({unit})", size=12, color=theme.TEXT, weight=ft.FontWeight.W_600),
            *rows,
            ft.Row(
                [
                    ft.Container(width=116),
                    ft.Row(
                        [
                            ft.Text(f"0 {unit}", size=11, color=theme.BLUE_GREY),
                            ft.Text(f"{maximum:g} {unit}", size=11, color=theme.BLUE_GREY),
                        ],
                        width=240,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=10,
            ),
        ],
        spacing=8,
    )
    return _accessible(chart, key=key, label=label)


def backdrop(
    content: ft.Control,
    *,
    user_data_dir: str | Path | None = None,
    key: str = "page-backdrop",
    label: str = "Page backdrop",
) -> ft.Stack:
    """Place page content over a local blurred image or deterministic gradient."""
    data_dir = Path(user_data_dir) if user_data_dir is not None else DATA_DIR
    image_path = data_dir / "ui" / "backdrop.jpg"
    if image_path.is_file():
        background: ft.Control = ft.Image(src=str(image_path), fit=ft.BoxFit.COVER, expand=True)
        softened: ft.Control = ft.Container(
            expand=True,
            bgcolor="transparent",
            blur=4,
            ignore_interactions=True,
        )
    else:
        background = ft.Container(
            expand=True,
            gradient=_gradient(("#0b1424", "#0c2231", "#0a312f")),
        )
        softened = ft.Container(expand=True, ignore_interactions=True)
    return _accessible(
        ft.Stack(
            [
                background,
                softened,
                ft.Container(content=content, expand=True),
            ],
            expand=True,
            fit=ft.StackFit.EXPAND,
        ),
        key=key,
        label=label,
    )
