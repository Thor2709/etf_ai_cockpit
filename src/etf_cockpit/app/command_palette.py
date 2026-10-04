"""Deterministic page search used by the application shell command palette.

The Flet-free implementation lives in :mod:`etf_cockpit.core.navigation`.
"""

from __future__ import annotations

from etf_cockpit.core.navigation import PaletteCommand, all_commands, search_commands

__all__ = ["PaletteCommand", "all_commands", "search_commands"]
