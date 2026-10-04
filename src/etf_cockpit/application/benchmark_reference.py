"""Application access to the canonical benchmark/cash reference contract.

The implementation is domain logic and lives in
:mod:`etf_cockpit.portfolio.benchmark_reference` (ADR-0002). Presentation and
application callers keep importing it from this module.
"""

from __future__ import annotations

from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    adjusted_price_binding_for_reference,
    adjusted_price_snapshot_binding,
    clip_to_decision_window,
    context_from_snapshot,
    resolve_canonical_reference,
    unavailable_reference_projection,
    validate_benchmark_reference,
)

__all__ = [
    "CanonicalReferenceContext",
    "adjusted_price_binding_for_reference",
    "adjusted_price_snapshot_binding",
    "clip_to_decision_window",
    "context_from_snapshot",
    "resolve_canonical_reference",
    "unavailable_reference_projection",
    "validate_benchmark_reference",
]
