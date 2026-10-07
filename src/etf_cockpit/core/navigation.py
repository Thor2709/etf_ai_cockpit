"""Flet-free route, workspace and command-palette registry (shared; ADR-0002).

The router binds each route to its page renderer. UI acceptance and governance
checks read routes, titles and workspace groups here without importing the Flet
application shell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# Registered routes and page titles, in shell registration order.
ROUTE_TITLES: tuple[tuple[str, str], ...] = (
    ("/", "Simple Scores"),
    ("/portfolio", "Portfolio Sandbox"),
    ("/portfolio-optimiser", "Portfolio Optimiser Lab"),
    ("/signals", "Scores"),
    ("/strategy-builder", "Strategy Builder"),
    ("/screener", "Fundamentals Screener"),
    ("/comparison", "Comparison"),
    ("/stock-research", "Stock Research"),
    ("/risk", "Risk Evidence"),
    ("/stress-lab", "Stress Lab"),
    ("/etf", "Instrument Detail"),
    ("/backtests", "Backtests"),
    ("/chatgpt", "Audit Notes"),
    ("/providers", "Provider Status"),
    ("/evidence", "Evidence Ledger"),
    ("/filings", "Filings & Statements"),
    ("/etf-disclosures", "ETF Disclosures"),
    ("/news-context", "News & Context"),
    ("/data-models", "Data & Models"),
    ("/forecasts", "Forecast Lab"),
    ("/training-centre", "Training Centre"),
    ("/feature-catalogue", "Feature Catalogue"),
    ("/catalogue", "Data Catalogue"),
    ("/macro", "Macro and Factors"),
    ("/settings", "Settings"),
    ("/diagnostics", "Diagnostics"),
    ("/errors", "Errors & Recovery"),
    ("/data-health", "Data Health"),
    ("/universe", "Universe"),
    ("/onboarding", "First-run Setup"),
    ("/what-changed", "What Changed"),
    ("/instrument", "Instrument Detail"),
    ("/import-export", "Import & Export"),
    ("/system-map", "System Map"),
    ("/help", "Help & Glossary"),
    ("/decision-journal", "Decision Journal"),
    ("/forward-evidence", "Forward Evidence Diary"),
    ("/jobs", "Jobs & Activity"),
    ("/operations", "Operations Centre"),
    ("/release-readiness", "Release Readiness"),
    ("/roadmap", "Programme Map"),
    ("/sectors", "Sectors & Countries"),
)

# Dock order and page-menu order of FINAL_UI_SPEC 7.0 (the first route is the workspace default).
# One stable information architecture for the existing routes. The pages stay
# independently testable while the shell gives them a decision-oriented home.
WORKSPACE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Home", ("/", "/onboarding")),
    ("Universe", ("/universe", "/data-health", "/providers", "/catalogue", "/filings", "/etf-disclosures", "/news-context")),
    ("Research", ("/stock-research", "/instrument", "/etf", "/signals", "/screener", "/strategy-builder")),
    ("Portfolio", ("/portfolio", "/risk", "/portfolio-optimiser", "/stress-lab", "/decision-journal", "/forward-evidence", "/operations")),
    ("Compare", ("/comparison",)),
    ("Lab", ("/forecasts", "/backtests", "/training-centre", "/feature-catalogue", "/data-models")),
    ("Map", ("/sectors", "/macro")),
    ("Changes", ("/what-changed", "/jobs")),
    ("Help", ("/help", "/settings", "/import-export", "/diagnostics", "/errors", "/evidence", "/chatgpt", "/system-map", "/release-readiness", "/roadmap")),
)


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
        return "navigate_palette_command"

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


__all__ = ["PaletteCommand", "ROUTE_TITLES", "WORKSPACE_GROUPS", "all_commands", "search_commands"]
