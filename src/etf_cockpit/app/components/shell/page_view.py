"""Contract between the shell and the pages (final UI spec §5.2, §6, §7).

A page builder keeps its signature ``<name>_page(page, state)`` and returns either a plain
``ft.Control`` (legacy, shown with the route's default title) or a :class:`PageView`. The shell
draws the top bar from ``PageView.chrome`` and places ``PageView.body`` in the main grid area
between the top bar and the footer rail. Pages never draw shell parts themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import flet as ft


@dataclass(frozen=True)
class SegmentGroup:
    """One top-bar ``Segmented`` group (max three per page; > 6 items get a ``More ▾`` overflow)."""

    key: str
    items: Sequence[str]
    selected: str
    on_change: Callable[[str], None] | None = None  # page updates its own body in place, never navigates


@dataclass(frozen=True)
class PageChrome:
    title: str
    subtitle: str
    segment_groups: Sequence[SegmentGroup] = field(default_factory=tuple)


@dataclass(frozen=True)
class PageView:
    chrome: PageChrome
    body: ft.Control
