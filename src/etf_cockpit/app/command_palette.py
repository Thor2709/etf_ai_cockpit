"""Deterministic page search used by the application shell command palette."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class PaletteCommand:
    route: str
    title: str
    workspace: str

    @property
    def command_id(self) -> str:
        """Stable command identity independent of result ordering or labels."""

        return f"palette:{self.route.strip('/').replace('/', '-') or 'home'}"

    @property
    def callback(self) -> str:
        return "select_palette_command"

    @property
    def success_signal(self) -> str:
        return "route_changed"

    @property
    def controlled_error_signal(self) -> str:
        return "no_matching_workspace"


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
