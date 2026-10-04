"""Application access to the deterministic screening contracts.

The query engine is domain logic and lives in :mod:`etf_cockpit.analysis.screening`
(ADR-0002). Presentation and application callers keep importing it from here.
"""

from __future__ import annotations

from etf_cockpit.analysis.screening import (
    FilterOperator,
    ScreenFilter,
    ScreenQuery,
    ScreenResult,
    ScreenSort,
    bind_query,
    records_checksum,
    run_screen,
)

__all__ = [
    "FilterOperator",
    "ScreenFilter",
    "ScreenQuery",
    "ScreenResult",
    "ScreenSort",
    "bind_query",
    "records_checksum",
    "run_screen",
]
