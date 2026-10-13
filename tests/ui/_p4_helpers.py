"""Shared helpers for the P4 page tests (walk the control tree, collect text)."""

from __future__ import annotations

import flet as ft


def walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from walk(child)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from walk(getattr(cell, "content", None))


def all_text(root) -> str:
    return "\n".join(str(c.value) for c in walk(root) if isinstance(c, ft.Text) and c.value is not None)


def card_titles(root) -> list[str]:
    return [
        c.data["title"]
        for c in walk(root)
        if isinstance(getattr(c, "data", None), dict) and c.data.get("kit") == "GlassCard"
    ]


def kit_names(root) -> set[str]:
    return {c.data["kit"] for c in walk(root) if isinstance(getattr(c, "data", None), dict) and "kit" in c.data}
