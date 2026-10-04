"""Application access to the import-boundary report shown in Diagnostics.

The checker is governance tooling and lives in
:mod:`etf_cockpit.governance.architecture_boundaries` (ADR-0002).
"""

from __future__ import annotations

from etf_cockpit.governance.architecture_boundaries import (
    ALLOWED_IMPLEMENTATION_MODULES,
    FORBIDDEN_PREFIXES,
    PRESENTATION_DIRS,
    BoundaryViolation,
    build_report,
    find_violations,
)

__all__ = [
    "ALLOWED_IMPLEMENTATION_MODULES",
    "FORBIDDEN_PREFIXES",
    "PRESENTATION_DIRS",
    "BoundaryViolation",
    "build_report",
    "find_violations",
]
