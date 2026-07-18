"""Deterministic page search used by the application shell command palette."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class PaletteCommand:
    route: str
    title: str
    workspace: str


def all_commands(
    pages: Mapping[str, tuple[str, object]],
    workspace_groups: Sequence[tuple[str, Sequence[str]]],
) -> tuple[PaletteCommand, ...]:
    """Return every registered page in stable information-architecture order."""

    workspace_by_route = {
        route: workspace
        for workspace, routes in workspace_groups
        for route in routes
    }
    return tuple(
        PaletteCommand(route=route, title=str(pages[route][0]), workspace=workspace_by_route.get(route, "Other"))
        for workspace, routes in workspace_groups
        for route in routes
        if route in pages
    )


def search_commands(
    pages: Mapping[str, tuple[str, object]],
    workspace_groups: Sequence[tuple[str, Sequence[str]]],
    query: str,
    *,
    limit: int = 8,
) -> tuple[PaletteCommand, ...]:
    """Search page titles, routes and workspace names without regex semantics."""

    if limit <= 0:
        return ()
    needle = str(query or "").strip().casefold()
    commands = all_commands(pages, workspace_groups)
    if not needle:
        return commands[:limit]
    return tuple(
        command
        for command in commands
        if needle in f"{command.title} {command.route} {command.workspace}".casefold()
    )[:limit]


__all__ = ["PaletteCommand", "all_commands", "search_commands"]
