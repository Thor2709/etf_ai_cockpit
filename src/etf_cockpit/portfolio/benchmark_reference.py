"""Canonical benchmark/cash reference contract (domain; ADR-0002)."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from collections import OrderedDict
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd
import yaml

from etf_cockpit.core.frame_signature import columns_key
from etf_cockpit.core.paths import CONFIG_DIR

from etf_cockpit.portfolio.benchmark_reference_contract import (
    AnalysisDeclaration,
    AnalysisResolution,
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    VWCE_CANONICAL_ISIN,
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
        cash_definitions = [
            item
            for item in self.registry.cash_proxies
            if item.proxy_id == resolution.cash.selected_id
            and item.version == resolution.cash.version
            and item.digest() == resolution.cash.content_hash
            and item.status == "available"
        ]
        if len(cash_definitions) != 1:
            return None
        if resolution.peer_set.status == "available":
            peer_definitions = [
                item
                for item in self.registry.peer_sets
                if item.peer_set_id == resolution.peer_set.selected_id
                and item.version == resolution.peer_set.version
                and item.digest() == resolution.peer_set.content_hash
                and item.status == "available"
            ]
            if len(peer_definitions) != 1:
                return None
        definitions = [
            item
            for item in self.registry.benchmarks
            if item.benchmark_id == selected_id
            and item.version == resolution.benchmark.version
            and item.digest() == resolution.benchmark.content_hash
            and item.status == "available"
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
    *,
    registry: CanonicalBenchmarkRegistry | None = None,
) -> str | None:
    """Validate one shared, execution-disabled benchmark/cash projection.

    Relative consumers must agree on the selected benchmark data id and on the
    exact selected-record digests emitted by the canonical registry.  A
    malformed or incomplete projection is unavailable; an attempted execution
    authority escalation remains an explicit contract error.
    """

    if not isinstance(reference, Mapping) or not isinstance(registry, CanonicalBenchmarkRegistry):
        return None
    try:
        _assert_execution_disabled(reference)
    except RecursionError:
        return None
    if reference.get("execution_allowed") is not False:
        return None
    if reference.get("status") != "available":
        return None
    if not isinstance(benchmark_data_id, str) or not benchmark_data_id.strip():
        return None
    benchmark = reference.get("benchmark")
    cash = reference.get("cash")
    selected_records = reference.get("selected_records")
    provenance = reference.get("provenance")
    if (
        not isinstance(benchmark, Mapping)
        or not isinstance(cash, Mapping)
        or not isinstance(selected_records, Mapping)
        or not isinstance(provenance, Mapping)
        or benchmark.get("status") != "available"
        or cash.get("status") != "available"
        or reference.get("benchmark_data_id") != benchmark_data_id
        or not isinstance(reference.get("registry_hash"), str)
        or reference.get("registry_hash") in ("", "unavailable")
    ):
        return None
    expected_provenance = {
        "registry_hash": reference.get("registry_hash"),
        "selected_records": selected_records,
        "selected_vwce_anchor_digest": selected_records.get("vwce_anchor"),
    }
    if set(provenance) != set(expected_provenance) or any(
        provenance.get(field) != value for field, value in expected_provenance.items()
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
    if not isinstance(peer, Mapping):
        return None
    if selected_records.get("peer_set") != peer.get("content_hash"):
        return None
    try:
        registry_payload = registry.as_payload()
        if reference.get("registry_hash") != registry_payload.get("registry_hash"):
            return None
        benchmark_matches = [
            item
            for item in registry.benchmarks
            if item.benchmark_id == benchmark.get("id")
            and item.version == benchmark.get("version")
            and item.digest() == benchmark_digest
            and item.status == "available"
        ]
        cash_matches = [
            item
            for item in registry.cash_proxies
            if item.proxy_id == cash.get("id")
            and item.version == cash.get("version")
            and item.digest() == cash_digest
            and item.status == "available"
        ]
        if len(benchmark_matches) != 1 or len(cash_matches) != 1:
            return None
        benchmark_record = benchmark_matches[0]
        cash_record = cash_matches[0]
        canonical_data_id = (
            benchmark_record.benchmark_id
            if benchmark_record.benchmark_id in benchmark_record.constituents
            else benchmark_record.constituents[0]
            if len(benchmark_record.constituents) == 1
            else None
        )
        if benchmark_data_id != canonical_data_id:
            return None
        if peer.get("status") == "available":
            peer_matches = [
                item
                for item in registry.peer_sets
                if item.peer_set_id == peer.get("id")
                and item.version == peer.get("version")
                and item.digest() == peer.get("content_hash")
                and item.status == "available"
            ]
            if len(peer_matches) != 1:
                return None
            projected_members = peer.get("member_instrument_ids")
            if (
                not isinstance(projected_members, Sequence)
                or isinstance(projected_members, (str, bytes))
                or tuple(projected_members) != peer_matches[0].member_instrument_ids
            ):
                return None
        elif peer.get("status") == "unavailable":
            projected_members = peer.get("member_instrument_ids")
            if (
                any(peer.get(field) is not None for field in ("id", "version", "content_hash"))
                or (
                    projected_members is not None
                    and (
                        not isinstance(projected_members, Sequence)
                        or isinstance(projected_members, (str, bytes))
                        or len(projected_members) != 0
                    )
                )
            ):
                return None
        else:
            return None

        analysis = reference.get("analysis")
        projected_references = reference.get("references")
        selected_references = selected_records.get("references")
        if (
            not isinstance(analysis, Mapping)
            or not isinstance(projected_references, Sequence)
            or isinstance(projected_references, (str, bytes))
            or not isinstance(selected_references, Mapping)
        ):
            return None
        matched_references = []
        expected_selected_references: dict[str, str] = {}
        for projected in projected_references:
            if not isinstance(projected, Mapping):
                return None
            matches = [
                item
                for item in registry.reference_portfolios
                if item.portfolio_id == projected.get("id")
                and item.version == projected.get("version")
                and item.digest() == projected.get("content_hash")
            ]
            if len(matches) != 1:
                return None
            matched = matches[0]
            expected_projection = {
                "method": matched.method,
                "constituent_instrument_ids": list(matched.constituent_instrument_ids),
                "current_weights": None if matched.current_weights is None else dict(matched.current_weights),
                "effective_at": pd.Timestamp(matched.effective_at).isoformat(),
                "known_at": pd.Timestamp(matched.known_at).isoformat(),
                "source_hashes": list(matched.source_hashes),
            }
            if any(projected.get(field) != value for field, value in expected_projection.items()):
                return None
            matched_references.append(matched)
            expected_selected_references[f"{matched.portfolio_id}@{matched.version}"] = matched.digest()
        if dict(selected_references) != expected_selected_references:
            return None

        declaration = AnalysisDeclaration(
            analysis_id=reference.get("analysis_id"),  # type: ignore[arg-type]
            purpose=reference.get("purpose"),  # type: ignore[arg-type]
            instrument_id=analysis.get("instrument_id"),  # type: ignore[arg-type]
            currency=analysis.get("currency"),  # type: ignore[arg-type]
            horizon_years=analysis.get("horizon_years"),  # type: ignore[arg-type]
            start_date=analysis.get("start_date"),  # type: ignore[arg-type]
            end_date=analysis.get("end_date"),  # type: ignore[arg-type]
            decision_time=analysis.get("decision_time"),  # type: ignore[arg-type]
            benchmark_id=benchmark.get("id"),  # type: ignore[arg-type]
            cash_proxy_id=cash.get("id"),  # type: ignore[arg-type]
            peer_set_id=peer.get("id") if peer.get("status") == "available" else None,  # type: ignore[arg-type]
            reference_portfolio_ids=tuple(item.portfolio_id for item in matched_references),
        )
        effective_cutoff = pd.Timestamp(declaration.start_date).tz_localize("UTC")
        decision_cutoff = pd.Timestamp(declaration.decision_time).tz_convert("UTC")

        def aligned_record(item: object) -> bool:
            return (
                pd.Timestamp(getattr(item, "effective_at")).tz_convert("UTC") <= effective_cutoff
                and pd.Timestamp(getattr(item, "known_at")).tz_convert("UTC") <= decision_cutoff
                and getattr(item, "currency") == declaration.currency
                and getattr(item, "minimum_horizon_years") <= declaration.horizon_years
                <= getattr(item, "maximum_horizon_years")
                and date.fromisoformat(getattr(item, "start_date")) <= date.fromisoformat(declaration.start_date)
                and date.fromisoformat(getattr(item, "end_date")) >= date.fromisoformat(declaration.end_date)
            )

        if not aligned_record(benchmark_record) or not aligned_record(cash_record):
            return None
        if peer.get("status") == "available":
            peer_record = peer_matches[0]
            if (
                pd.Timestamp(peer_record.effective_at).tz_convert("UTC") > effective_cutoff
                or pd.Timestamp(peer_record.known_at).tz_convert("UTC") > decision_cutoff
            ):
                return None
        elif any(
            item.status == "available"
            and pd.Timestamp(item.effective_at).tz_convert("UTC") <= effective_cutoff
            and pd.Timestamp(item.known_at).tz_convert("UTC") <= decision_cutoff
            for item in registry.peer_sets
        ):
            return None
        for item in matched_references:
            reference_effective_cutoff = decision_cutoff if item.method == "no_trade" else effective_cutoff
            if (
                pd.Timestamp(item.effective_at).tz_convert("UTC") > reference_effective_cutoff
                or pd.Timestamp(item.known_at).tz_convert("UTC") > decision_cutoff
                or item.currency != declaration.currency
                or item.minimum_horizon_years is None
                or item.maximum_horizon_years is None
                or not item.minimum_horizon_years <= declaration.horizon_years <= item.maximum_horizon_years
                or item.start_date is None
                or item.end_date is None
                or date.fromisoformat(item.start_date) > date.fromisoformat(declaration.start_date)
                or date.fromisoformat(item.end_date) < date.fromisoformat(declaration.end_date)
            ):
                return None

        selected_vwce_anchor = selected_records.get("vwce_anchor")
        if selected_vwce_anchor is not None and sum(
            item.digest() == selected_vwce_anchor and item.status == "available"
            for item in registry.vwce_anchors
        ) != 1:
            return None
    except (BenchmarkReferenceError, AttributeError, KeyError, RecursionError, TypeError, ValueError):
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


def adjusted_price_snapshot_binding(
    prices: pd.DataFrame,
    *,
    calculation_window: Mapping[str, object],
) -> dict[str, object] | None:
    """Return the deterministic adjusted-price identity for one exact window."""

    required_window = ("start_date", "end_date", "decision_time")
    if not all(isinstance(calculation_window.get(key), str) and calculation_window.get(key) for key in required_window):
        return None
    if not isinstance(prices, pd.DataFrame) or not {"date", "etf_id", "adjusted_close"}.issubset(prices.columns):
        return None
    window = {key: str(calculation_window[key]) for key in required_window}
    # Pure function of the three price columns and the window: memoised on their exact content.
    prices_key = columns_key(prices, ("date", "etf_id", "adjusted_close"))
    if prices_key is None:
        return _adjusted_price_snapshot_binding(prices, window)
    key = (prices_key, tuple(window[name] for name in required_window))
    with _BINDING_CACHE_LOCK:
        if key in _BINDING_CACHE:
            _BINDING_CACHE.move_to_end(key)
            return deepcopy(_BINDING_CACHE[key])
    binding = _adjusted_price_snapshot_binding(prices, window)
    with _BINDING_CACHE_LOCK:
        _BINDING_CACHE[key] = deepcopy(binding)
        while len(_BINDING_CACHE) > _BINDING_CACHE_SIZE:
            _BINDING_CACHE.popitem(last=False)
    return binding


_BINDING_CACHE: OrderedDict[tuple[object, ...], dict[str, object] | None] = OrderedDict()
_BINDING_CACHE_LOCK = threading.Lock()
_BINDING_CACHE_SIZE = 16


def _adjusted_price_snapshot_binding(prices: pd.DataFrame, window: dict[str, str]) -> dict[str, object] | None:
    clipped = clip_to_decision_window(prices, **window)
    if clipped.empty:
        return None
    frame = clipped[["date", "etf_id", "adjusted_close"]].copy()
    frame["etf_id"] = frame["etf_id"].map(lambda value: str(value).strip())
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed")
    if dates.isna().any() or frame["etf_id"].eq("").any() or frame["adjusted_close"].isna().any():
        return None
    if not frame["adjusted_close"].map(math.isfinite).all() or (frame["adjusted_close"] <= 0).any():
        return None
    frame["date"] = dates.map(pd.Timestamp.isoformat)
    duplicate_values = frame.groupby(["etf_id", "date"], sort=True)["adjusted_close"].nunique(dropna=False)
    if duplicate_values.gt(1).any():
        return None
    frame = frame.sort_values(["etf_id", "date"], kind="stable").drop_duplicates(["etf_id", "date"])
    payload = json.dumps(
        frame.to_dict(orient="records"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    checksum = hashlib.sha256(payload).hexdigest()
    return {
        "price_snapshot_checksum": checksum,
        "price_snapshot_revision": checksum,
        "effective_cutoff": window["decision_time"],
        "calculation_window": window,
    }


def adjusted_price_binding_for_reference(
    prices: pd.DataFrame,
    reference_identity: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Resolve a price binding only from a populated canonical analysis identity."""

    if not isinstance(reference_identity, Mapping):
        return None
    analysis = reference_identity.get("analysis")
    if not isinstance(analysis, Mapping):
        return None
    return adjusted_price_snapshot_binding(prices, calculation_window=analysis)


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
        not isinstance(instrument, Mapping)
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


VWCE_LISTING_TICKER = "VWCE.DE"
VWCE_QUOTE_CURRENCY = "EUR"
VWCE_BENCHMARK_ID = "benchmark:ftse-all-world"
# Documented defaults: a one-day move above 25% in either price column is a split/adjustment discontinuity, and
# the adjusted/raw price ratio of an accumulating share class must stay constant to within one part in a million.
DEFAULT_MAX_DAILY_MOVE = 0.25
DEFAULT_ADJUSTMENT_TOLERANCE = 1e-6
_SHA256_TEXT = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VwceReferenceSeriesCheck:
    """Contract verdict for one candidate VWCE price series (never a guessed value)."""

    status: Literal["available", "unavailable"]
    reasons: tuple[str, ...]
    source_hash: str | None
    known_at: str | None
    observations: int
    first_date: str | None
    last_date: str | None
    execution_allowed: Literal[False] = False


def vwce_series_source_hash(frame: pd.DataFrame) -> str:
    """Hash the canonical (date, close, adjusted close) rows of a candidate series."""

    from etf_cockpit.data.provenance import sha256_dataframe

    return sha256_dataframe(frame)



def validate_vwce_reference_series(
    frame: pd.DataFrame | None,
    *,
    known_at: object,
    provider_metadata: object = None,
    isin: str = VWCE_CANONICAL_ISIN,
    ticker: str = VWCE_LISTING_TICKER,
    currency: str = VWCE_QUOTE_CURRENCY,
    accumulating: bool = True,
    fx_converted: bool = False,
    declared_source_hash: str | None = None,
    max_daily_move: float = DEFAULT_MAX_DAILY_MOVE,
    adjustment_tolerance: float = DEFAULT_ADJUSTMENT_TOLERANCE,
) -> VwceReferenceSeriesCheck:
    """Check VWCE identity, price/currency invariants and corporate-action consistency; fail closed.

    The series is the EUR-quoted Xetra listing, so the fund's USD base currency is never converted again
    (``fx_converted``); the OCF is already in the NAV and no fee is subtracted. An accumulating share class
    distributes nothing, so a ``dividends`` entry or an adjusted/raw ratio that changes is an artificial
    distribution (a distribution would be counted twice: once in the adjusted close, once as cash).
    """

    from etf_cockpit.core.types import DatasetMetadata

    reasons: list[str] = []
    if (not isinstance(provider_metadata, DatasetMetadata)
            or provider_metadata.source_name != "yfinance" or provider_metadata.source_type != "prices"
            or provider_metadata.currency != "EUR" or provider_metadata.ingested_at is None
            or provider_metadata.ingested_at.tzinfo is None
            or not isinstance(frame, pd.DataFrame)
            or provider_metadata.checksum != vwce_series_source_hash(frame)):
        reasons.append("provider_provenance_unverified")
    else:
        try:
            if pd.Timestamp(known_at) != pd.Timestamp(provider_metadata.ingested_at):
                reasons.append("known_at_conflicts_with_provider_provenance")
        except (TypeError, ValueError):
            reasons.append("known_at_conflicts_with_provider_provenance")
    if isinstance(frame, pd.DataFrame):
        for column, expected in (("provider_symbol", VWCE_LISTING_TICKER), ("currency", VWCE_QUOTE_CURRENCY), ("source", "yfinance")):
            if column not in frame or frame[column].isna().any() or not frame[column].eq(expected).all():
                reasons.append(f"provider_identity_unverified:{column}")
        for column, expected in (("ticker", VWCE_LISTING_TICKER), ("isin", VWCE_CANONICAL_ISIN)):
            if column in frame and not frame[column].eq(expected).all():
                reasons.append(f"provider_identity_conflict:{column}")
        if "is_adjusted" not in frame or not frame["is_adjusted"].eq(True).all():
            reasons.append("provider_adjusted_evidence_missing")
        for column in ("stock_splits", "splits", "Stock Splits"):
            if column in frame:
                splits = pd.to_numeric(frame[column], errors="coerce")
                if splits.isna().any() or not splits.isin([0, 1]).all():
                    reasons.append("explicit_split_requires_verified_adjustment")
        if "stock_splits" not in frame:
            reasons.append("corporate_action_evidence_missing")
        for column in ("dividends", "capital_gains"):
            if column not in frame:
                reasons.append(f"corporate_action_evidence_missing:{column}")
            elif pd.to_numeric(frame[column], errors="coerce").ne(0).any():
                reasons.append("distribution_on_accumulating_share_class")
    if isin != VWCE_CANONICAL_ISIN:
        reasons.append("identity_isin_mismatch")
    if ticker != VWCE_LISTING_TICKER:
        reasons.append("identity_listing_mismatch")
    if currency != VWCE_QUOTE_CURRENCY:
        reasons.append("quote_currency_not_eur")
    if accumulating is not True:
        reasons.append("distribution_policy_not_accumulating")
    if fx_converted is not False:
        reasons.append("double_fx_conversion")
    known_stamp: pd.Timestamp | None
    try:
        known_stamp = pd.Timestamp(known_at)
    except (TypeError, ValueError):
        known_stamp = None
    if known_stamp is None or pd.isna(known_stamp):
        reasons.append("known_at_unavailable")
        known_stamp = None
    elif known_stamp.tzinfo is None:
        reasons.append("known_at_not_timezone_aware")
        known_stamp = None
    adjusted_column = next(
        (name for name in ("adjusted_close", "adj_close") if isinstance(frame, pd.DataFrame) and name in frame.columns),
        None,
    )
    if (
        not isinstance(frame, pd.DataFrame)
        or "date" not in frame.columns
        or "close" not in frame.columns
        or adjusted_column is None
    ):
        reasons.append("series_columns_missing")
        return _series_check(reasons, None, known_stamp, 0, None, None)
    if len(frame) < 2:
        reasons.append("series_too_short")
        return _series_check(reasons, None, known_stamp, len(frame), None, None)
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any():
        reasons.append("invalid_dates")
        return _series_check(reasons, None, known_stamp, len(frame), None, None)
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
    dates = dates.dt.normalize()
    if dates.duplicated().any():
        reasons.append("duplicate_dates")
    elif not dates.is_monotonic_increasing:
        reasons.append("dates_not_sorted")
    first_date = dates.min().date().isoformat()
    last_date = dates.max().date().isoformat()
    if known_stamp is not None and dates.max().date() > known_stamp.tz_convert("UTC").date():
        reasons.append("observation_after_known_at")
    close = pd.to_numeric(frame["close"], errors="coerce")
    adjusted = pd.to_numeric(frame[adjusted_column], errors="coerce")
    valid_prices = bool(
        np.isfinite(close.to_numpy(dtype=float)).all()
        and np.isfinite(adjusted.to_numpy(dtype=float)).all()
        and (close > 0).all()
        and (adjusted > 0).all()
    )
    if not valid_prices:
        reasons.append("prices_missing_or_non_positive")
    else:
        if "dividends" in frame.columns:
            dividends = pd.to_numeric(frame["dividends"], errors="coerce")
            if dividends.isna().any() or (dividends != 0).any():
                reasons.append("distribution_on_accumulating_share_class")
        ratio = adjusted / close
        if float(ratio.max() / ratio.min() - 1.0) > adjustment_tolerance:
            reasons.append("adjusted_price_embeds_distribution")
        for label, prices in (("close", close), ("adjusted_close", adjusted)):
            moves = prices.pct_change().abs().iloc[1:]
            if bool((moves > max_daily_move).any()):
                reasons.append(f"split_or_adjustment_discontinuity:{label}")
    computed = vwce_series_source_hash(frame) if valid_prices else None
    if declared_source_hash is not None and (
        not isinstance(declared_source_hash, str)
        or _SHA256_TEXT.fullmatch(declared_source_hash) is None
        or declared_source_hash != computed
    ):
        reasons.append("source_hash_mismatch")
    return _series_check(reasons, computed, known_stamp, len(frame), first_date, last_date)


def _series_check(
    reasons: list[str],
    source_hash: str | None,
    known_stamp: pd.Timestamp | None,
    observations: int,
    first_date: str | None,
    last_date: str | None,
) -> VwceReferenceSeriesCheck:
    failed = bool(reasons) or source_hash is None or known_stamp is None
    return VwceReferenceSeriesCheck(
        "unavailable" if failed else "available",
        tuple(dict.fromkeys(reasons)) or (("series_unverifiable",) if failed else ()),
        None if failed else source_hash,
        None if known_stamp is None else known_stamp.isoformat(),
        observations,
        first_date,
        last_date,
    )


def vwce_reference_status(
    registry: CanonicalBenchmarkRegistry,
    check: VwceReferenceSeriesCheck,
    *,
    benchmark_id: str = VWCE_BENCHMARK_ID,
) -> dict[str, object]:
    """Report ``available`` only when the registry record AND the series contract both pass.

    The shipped registry stays ``unavailable`` until a source-backed record carrying the series source hash
    is imported; a passing series alone never upgrades it.
    """

    def unavailable(reason: str) -> dict[str, object]:
        return {
            "status": "unavailable",
            "reason": reason,
            "benchmark_id": benchmark_id,
            "source_hash": None,
            "execution_allowed": False,
        }

    if not isinstance(registry, CanonicalBenchmarkRegistry) or not isinstance(check, VwceReferenceSeriesCheck):
        return unavailable("reference_inputs_invalid")
    if check.status != "available" or not check.source_hash:
        return unavailable("series_contract_failed:" + ",".join(check.reasons))
    records = [item for item in registry.benchmarks if item.benchmark_id == benchmark_id]
    if not records:
        return unavailable("registry_record_missing")
    available = [item for item in records if item.status == "available" and item.source_hashes]
    if not available:
        return unavailable("registry_record_not_available")
    if not any(check.source_hash in item.source_hashes for item in available):
        return unavailable("series_hash_not_in_registry")
    return {
        "status": "available",
        "reason": None,
        "benchmark_id": benchmark_id,
        "source_hash": check.source_hash,
        "known_at": check.known_at,
        "execution_allowed": False,
    }


def load_passive_default_policy(path: Path | None = None) -> dict[str, object]:
    """Load the versioned passive-default policy; unavailable until the owner has approved it."""

    def unavailable(reason: str) -> dict[str, object]:
        return {"status": "unavailable", "reason": reason, "execution_allowed": False}

    target = path or CONFIG_DIR / "portfolio_policy_v1.yaml"
    try:
        payload = yaml.safe_load(Path(target).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return unavailable("policy_unreadable")
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "portfolio-policy.v1":
        return unavailable("policy_schema_invalid")
    if payload.get("execution_allowed") is not False:
        return unavailable("policy_execution_authority_forbidden")
    default = payload.get("passive_default")
    approval = payload.get("approval")
    if (
        not isinstance(default, Mapping)
        or default.get("instrument_id") != "VWCE"
        or default.get("isin") != VWCE_CANONICAL_ISIN
        or default.get("listing") != VWCE_LISTING_TICKER
        or default.get("currency") != VWCE_QUOTE_CURRENCY
        or default.get("active_edge_evidence") != "cash_flow_matched_vwce_shadow_account"
        or default.get("applies_when") != "no_active_edge_shown"
        or not isinstance(payload.get("version"), str)
    ):
        return unavailable("policy_default_invalid")
    if (
        not isinstance(approval, Mapping)
        or approval.get("status") != "approved"
        or not approval.get("approved_by")
        or not approval.get("approved_at")
    ):
        return unavailable("owner_approval_pending")
    return {
        "status": "available",
        "reason": None,
        "policy_id": payload.get("policy_id"),
        "version": payload["version"],
        "default_instrument_id": "VWCE",
        "applies_when": "no_active_edge_shown",
        "execution_allowed": False,
    }


__all__ = [
    "CanonicalReferenceContext",
    "adjusted_price_binding_for_reference",
    "adjusted_price_snapshot_binding",
    "clip_to_decision_window",
    "context_from_snapshot",
    "VwceReferenceSeriesCheck",
    "load_passive_default_policy",
    "resolve_canonical_reference",
    "unavailable_reference_projection",
    "validate_benchmark_reference",
    "validate_vwce_reference_series",
    "vwce_reference_status",
    "vwce_series_source_hash",
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
