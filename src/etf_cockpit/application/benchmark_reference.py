"""Application boundary for the canonical benchmark/cash request."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence

from etf_cockpit.portfolio.benchmark_reference_contract import (
    AnalysisResolution,
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
)


@dataclass(frozen=True)
class CanonicalReferenceContext:
    """Resolved benchmark/cash evidence shared by production entry paths."""

    registry: CanonicalBenchmarkRegistry
    resolution: AnalysisResolution | None
    projection: dict[str, object]

    @property
    def benchmark_data_id(self) -> str | None:
        """Return one explicitly mapped price-series id, never an arbitrary id."""

        resolution = self.resolution
        if (
            resolution is None
            or resolution.benchmark.status != "available"
            or resolution.cash.status != "available"
        ):
            return None
        selected_id = resolution.benchmark.selected_id
        if not selected_id:
            return None
        definitions = [
            item
            for item in self.registry.benchmarks
            if item.benchmark_id == selected_id
            and item.version == resolution.benchmark.version
            and item.digest() == resolution.benchmark.content_hash
        ]
        if len(definitions) != 1:
            return None
        available_ids = set(definitions[0].constituents)
        if selected_id in available_ids:
            return selected_id
        if len(available_ids) == 1:
            return next(iter(available_ids))
        return None


def unavailable_reference_projection(
    registry: CanonicalBenchmarkRegistry | None = None,
    *,
    blocker: str = "reference_resolution_unavailable",
) -> dict[str, object]:
    """Build the explicit unavailable declaration used at application edges."""

    registry_hash = "unavailable"
    if registry is not None:
        try:
            registry_hash = str(registry.as_payload()["registry_hash"])
        except (BenchmarkReferenceError, TypeError, ValueError, KeyError):
            registry_hash = "unavailable"
    return {
        "contract": "benchmark-reference-contract.v1",
        "status": "unavailable",
        "benchmark": {"id": None, "version": None, "status": "unavailable", "display": "N/A"},
        "cash": {"id": None, "version": None, "status": "unavailable", "display": "N/A"},
        "peer_set": {"id": None, "version": None, "status": "unavailable", "display": "N/A"},
        "references": [],
        "blockers": [blocker],
        "registry_hash": registry_hash,
        "provenance": {"registry_hash": registry_hash, "selected_records": {}},
        "execution_allowed": False,
    }


def resolve_canonical_reference(
    registry: CanonicalBenchmarkRegistry,
    *,
    analysis_id: str,
    purpose: str,
    instrument_id: str,
    instrument: Mapping[str, object] | None,
    currency: str | None,
    horizon_years: float | None,
    start_date: str | None,
    end_date: str | None,
    decision_time: str | None,
    reference_portfolio_ids: Sequence[str],
) -> CanonicalReferenceContext:
    """Resolve one explicit request, failing closed with a declaration."""

    unavailable = unavailable_reference_projection(registry)
    if (
        instrument is None
        or currency is None
        or horizon_years is None
        or start_date is None
        or end_date is None
        or decision_time is None
    ):
        unavailable["blockers"] = ["reference_resolution_inputs_unavailable"]
        return CanonicalReferenceContext(registry, None, unavailable)
    try:
        resolution = registry.resolve_analysis(
            analysis_id=analysis_id,
            purpose=purpose,  # type: ignore[arg-type]
            instrument_id=instrument_id,
            instrument=instrument,
            currency=currency,
            horizon_years=horizon_years,
            start_date=start_date,
            end_date=end_date,
            decision_time=decision_time,
            reference_portfolio_ids=reference_portfolio_ids,
        )
        projection = registry.ui_projection(resolution)
    except (BenchmarkReferenceError, TypeError, ValueError, KeyError) as exc:
        unavailable["blockers"] = [f"reference_resolution_invalid:{type(exc).__name__}"]
        return CanonicalReferenceContext(registry, None, unavailable)
    projection["status"] = "available" if not resolution.blockers else "unavailable"
    return CanonicalReferenceContext(registry, resolution, projection)


def context_from_snapshot(
    snapshot: object,
    *,
    purpose: str,
    analysis_id: str,
    instrument_id: str = "VWCE",
) -> CanonicalReferenceContext:
    """Resolve the snapshot's one canonical request for a production caller."""

    registry = getattr(snapshot, "benchmark_reference_registry", None)
    if not isinstance(registry, CanonicalBenchmarkRegistry):
        registry = CanonicalBenchmarkRegistry()
    raw_reference_ids = getattr(snapshot, "benchmark_reference_portfolio_ids", ())
    reference_ids = (
        tuple(raw_reference_ids)
        if isinstance(raw_reference_ids, Sequence)
        and not isinstance(raw_reference_ids, (str, bytes))
        and all(isinstance(item, str) for item in raw_reference_ids)
        else ()
    )
    return resolve_canonical_reference(
        registry,
        analysis_id=analysis_id,
        purpose=purpose,
        instrument_id=instrument_id,
        instrument=getattr(snapshot, "benchmark_reference_instrument", None),
        currency=getattr(snapshot, "benchmark_reference_currency", None),
        horizon_years=getattr(snapshot, "benchmark_reference_horizon_years", None),
        start_date=getattr(snapshot, "benchmark_reference_start_date", None),
        end_date=getattr(snapshot, "benchmark_reference_end_date", None),
        decision_time=getattr(snapshot, "benchmark_reference_decision_time", None),
        reference_portfolio_ids=reference_ids,
    )


__all__ = [
    "CanonicalReferenceContext",
    "context_from_snapshot",
    "resolve_canonical_reference",
    "unavailable_reference_projection",
]
