from __future__ import annotations

import flet as ft


def padding_symmetric(horizontal: int = 0, vertical: int = 0) -> ft.Padding:
    return ft.Padding(left=horizontal, right=horizontal, top=vertical, bottom=vertical)


def border_all(width: int, color: str) -> ft.Border:
    side = ft.BorderSide(width=width, color=color)
    return ft.Border(left=side, top=side, right=side, bottom=side)


def border_only(
    *,
    left: ft.BorderSide | None = None,
    top: ft.BorderSide | None = None,
    right: ft.BorderSide | None = None,
    bottom: ft.BorderSide | None = None,
) -> ft.Border:
    return ft.Border(left=left, top=top, right=right, bottom=bottom)
