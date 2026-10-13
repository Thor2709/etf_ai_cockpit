"""Application access to the canonical benchmark/cash reference contract.

The implementation is domain logic and lives in
:mod:`etf_cockpit.portfolio.benchmark_reference` (ADR-0002). Presentation and
application callers keep importing it from this module.
"""

from __future__ import annotations

from etf_cockpit.portfolio.benchmark_reference import (
    CanonicalReferenceContext,
    VwceReferenceSeriesCheck,
    adjusted_price_binding_for_reference,
    adjusted_price_snapshot_binding,
    clip_to_decision_window,
    context_from_snapshot,
    load_passive_default_policy,
    unavailable_reference_projection,
    validate_benchmark_reference,
    validate_vwce_reference_series,
    vwce_reference_status,
    vwce_series_source_hash,
)

__all__ = [
    "CanonicalReferenceContext",
    "VwceReferenceSeriesCheck",
    "adjusted_price_binding_for_reference",
    "adjusted_price_snapshot_binding",
    "clip_to_decision_window",
    "context_from_snapshot",
    "load_passive_default_policy",
    "unavailable_reference_projection",
    "validate_benchmark_reference",
    "validate_vwce_reference_series",
    "vwce_reference_status",
    "vwce_series_source_hash",
]
