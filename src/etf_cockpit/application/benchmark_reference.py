"""Application boundary for the canonical benchmark/cash request."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
import hashlib
import json
from types import MappingProxyType

import pandas as pd

from etf_cockpit.portfolio.benchmark_reference_contract import (
    AnalysisResolution,
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    unavailable_reference_projection as contract_unavailable_reference_projection,
)


@dataclass(frozen=True, init=False)
class CanonicalReferenceContext:
    """Resolved benchmark/cash evidence shared by production entry paths."""

    registry: CanonicalBenchmarkRegistry
    resolution: AnalysisResolution | None
    blocker: str = "reference_resolution_unavailable"
    instrument: Mapping[str, object] | None = None

    def __init__(
        self,
        registry: CanonicalBenchmarkRegistry,
        resolution: AnalysisResolution | None = None,
        legacy_projection: Mapping[str, object] | None = None,
        *,
        blocker: str | None = None,
        instrument: Mapping[str, object] | None = None,
    ) -> None:
        """Store canonical state only; never retain a caller projection.

        ``legacy_projection`` remains an ignored compatibility argument for
        older internal constructors.  Its authority fields are checked, but
        no value from it is used to build a persisted result.
        """

        if not isinstance(registry, CanonicalBenchmarkRegistry):
            raise BenchmarkReferenceError("canonical reference registry is invalid")
        if legacy_projection is not None:
            try:
                _assert_execution_disabled(legacy_projection)
            except RecursionError as exc:
                raise BenchmarkReferenceError("serialized evidence is malformed") from exc
        resolved_blocker = blocker or _projection_blocker(legacy_projection)
        object.__setattr__(self, "registry", registry)
        object.__setattr__(self, "resolution", resolution)
        object.__setattr__(self, "blocker", resolved_blocker)
        try:
            frozen_instrument = None if instrument is None else _freeze_mapping(instrument)
        except RecursionError as exc:
            raise BenchmarkReferenceError("instrument evidence is malformed") from exc
        object.__setattr__(self, "instrument", frozen_instrument)

    @property
    def projection(self) -> dict[str, object]:
        """Reconstruct a fresh JSON-safe projection from bound registry state."""

        if self.resolution is None:
            return unavailable_reference_projection(self.registry, blocker=self.blocker)
        try:
            projection = self.registry.ui_projection(self.resolution)
            projection["status"] = "available" if not self.resolution.blockers else "unavailable"
            projection["benchmark_data_id"] = self.benchmark_data_id
            declaration = self.resolution.declaration
            projection["analysis"] = {
                "instrument_id": declaration.instrument_id,
                "currency": declaration.currency,
                "horizon_years": declaration.horizon_years,
                "start_date": declaration.start_date,
                "end_date": declaration.end_date,
                "decision_time": declaration.decision_time,
            }
            _assert_execution_disabled(projection)
            return json.loads(json.dumps(projection, sort_keys=True, default=str))
        except (BenchmarkReferenceError, TypeError, ValueError, KeyError):
            return unavailable_reference_projection(
                self.registry,
                blocker="reference_projection_invalid",
            )

    @property
    def identity(self) -> dict[str, object]:
        """Return the deterministic cache/readback identity for this context."""

        projection = self.projection
        declaration = self.resolution.declaration if self.resolution is not None else None
        return {
            "schema": "benchmark-reference-cache.v1",
            "status": projection.get("status", "unavailable"),
            "registry_hash": projection.get("registry_hash", "unavailable"),
            "benchmark_data_id": self.benchmark_data_id,
            "selected_records": projection.get("selected_records", {}),
            "calculation_schema": "canonical-benchmark-cash.v1",
            "analysis": None if declaration is None else {
                "instrument_id": declaration.instrument_id,
                "currency": declaration.currency,
                "horizon_years": declaration.horizon_years,
                "start_date": declaration.start_date,
                "end_date": declaration.end_date,
                "decision_time": declaration.decision_time,
            },
            "execution_allowed": False,
        }

    @property
    def identity_hash(self) -> str:
        payload = json.dumps(self.identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def peer_member_ids(self) -> tuple[str, ...] | None:
        """Return members only from the exact digest-bound available peer set."""

        resolution = self.resolution
        if resolution is None or resolution.peer_set.status != "available":
            return None
        matches = [
            item
            for item in self.registry.peer_sets
            if item.peer_set_id == resolution.peer_set.selected_id
            and item.version == resolution.peer_set.version
            and item.digest() == resolution.peer_set.content_hash
            and item.status == "available"
        ]
        return matches[0].member_instrument_ids if len(matches) == 1 else None

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
    return contract_unavailable_reference_projection(registry_hash=registry_hash, blocker=blocker)


def validate_benchmark_reference(
    reference: Mapping[str, object] | None,
    benchmark_data_id: str | None,
) -> str | None:
    """Validate one shared, execution-disabled benchmark/cash projection.

    Relative consumers must agree on the selected benchmark data id and on the
    exact selected-record digests emitted by the canonical registry.  A
    malformed or incomplete projection is unavailable; an attempted execution
    authority escalation remains an explicit contract error.
    """

    if not isinstance(reference, Mapping):
        return None
    try:
        _assert_execution_disabled(reference)
    except RecursionError:
        return None
    if reference.get("status") != "available":
        return None
    if not isinstance(benchmark_data_id, str) or not benchmark_data_id.strip():
        return None
    benchmark = reference.get("benchmark")
    cash = reference.get("cash")
    selected_records = reference.get("selected_records")
    if (
        not isinstance(benchmark, Mapping)
        or not isinstance(cash, Mapping)
        or not isinstance(selected_records, Mapping)
        or benchmark.get("status") != "available"
        or cash.get("status") != "available"
        or reference.get("benchmark_data_id") != benchmark_data_id
        or not isinstance(reference.get("registry_hash"), str)
        or reference.get("registry_hash") in ("", "unavailable")
    ):
        return None
    benchmark_digest = benchmark.get("content_hash")
    cash_digest = cash.get("content_hash")
    if (
        not isinstance(benchmark_digest, str)
        or not isinstance(cash_digest, str)
        or selected_records.get("benchmark") != benchmark_digest
        or selected_records.get("cash") != cash_digest
    ):
        return None
    peer = reference.get("peer_set")
    if isinstance(peer, Mapping) and selected_records.get("peer_set") != peer.get("content_hash"):
        return None
    return benchmark_data_id


def clip_to_decision_window(
    frame: pd.DataFrame,
    *,
    start_date: object,
    end_date: object,
    decision_time: object,
) -> pd.DataFrame:
    """Clip dated evidence to the declared window and exact authority cutoff.

    Date-only observations on the cutoff date are treated as end-of-day
    observations.  They therefore cannot widen an intraday decision cutoff,
    while the existing end-of-day behaviour remains available for a cutoff at
    the end of the declared date.
    """

    if not isinstance(frame, pd.DataFrame) or "date" not in frame.columns:
        return pd.DataFrame()
    if not all(isinstance(value, str) and value for value in (start_date, end_date, decision_time)):
        return pd.DataFrame()
    try:
        start = pd.Timestamp(start_date, tz="UTC")
        end_date_ts = pd.Timestamp(end_date, tz="UTC")
        end_of_day = end_date_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        decision = pd.Timestamp(decision_time)
        if decision.tzinfo is None:
            decision = decision.tz_localize("UTC")
        decision = decision.tz_convert("UTC")
        upper = min(end_of_day, decision)
        if start > end_date_ts or upper < start:
            return pd.DataFrame()
        raw_dates = frame["date"]
        dates = pd.to_datetime(raw_dates, errors="coerce", utc=True, format="mixed")
        date_only = raw_dates.map(_is_date_only_observation)
        effective_dates = dates.copy()
        end_date_only = date_only & dates.dt.normalize().eq(end_date_ts)
        effective_dates.loc[end_date_only] = end_date_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    except (TypeError, ValueError, OverflowError):
        return pd.DataFrame()
    return frame.loc[(dates >= start) & (effective_dates <= upper)].copy()


def _is_date_only_observation(value: object) -> bool:
    if isinstance(value, (pd.Timestamp,)):
        return value.tzinfo is None and value == value.normalize()
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return getattr(value, "hour", 0) == 0 and getattr(value, "minute", 0) == 0 and getattr(value, "second", 0) == 0 and getattr(value, "microsecond", 0) == 0
    text = str(value).strip()
    return bool(pd.notna(value)) and len(text) == 10 and text[4] == "-" and text[7] == "-"


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
        return CanonicalReferenceContext(registry, None, blocker="reference_resolution_inputs_unavailable")
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
        registry.ui_projection(resolution)
    except (BenchmarkReferenceError, TypeError, ValueError, KeyError, RecursionError) as exc:
        unavailable["blockers"] = [f"reference_resolution_invalid:{type(exc).__name__}"]
        return CanonicalReferenceContext(registry, None, blocker=f"reference_resolution_invalid:{type(exc).__name__}")
    return CanonicalReferenceContext(registry, resolution, instrument=instrument)


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
    "clip_to_decision_window",
    "context_from_snapshot",
    "resolve_canonical_reference",
    "unavailable_reference_projection",
    "validate_benchmark_reference",
]


def _projection_blocker(projection: Mapping[str, object] | None) -> str:
    if not isinstance(projection, Mapping):
        return "reference_resolution_unavailable"
    blockers = projection.get("blockers")
    if isinstance(blockers, Sequence) and not isinstance(blockers, (str, bytes)):
        first = next((item for item in blockers if isinstance(item, str) and item), None)
        if first:
            return first
    return "reference_resolution_unavailable"


def _assert_execution_disabled(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "execution_allowed" and item is not False:
                raise BenchmarkReferenceError("serialized evidence cannot grant execution authority")
            _assert_execution_disabled(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_execution_disabled(item)


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    """Detach nested caller-owned instrument evidence before retaining it."""

    def freeze(item: object) -> object:
        if isinstance(item, Mapping):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, (list, tuple)):
            return tuple(freeze(child) for child in item)
        if isinstance(item, (set, frozenset)):
            return frozenset(freeze(child) for child in item)
        return item

    frozen = freeze(value)
    if not isinstance(frozen, Mapping):
        raise BenchmarkReferenceError("instrument mapping is invalid")
    return frozen
