"""Canonical benchmark, cash, peer and reference-portfolio contracts.

This module is deliberately a local contract boundary.  It maps already
imported, versioned evidence; it does not fetch prices, perform FX conversion,
or create execution authority.  An unavailable mapping is a first-class
result and is never replaced with the first instrument in a collection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import re
from typing import Literal, Protocol, TypeVar


CONTRACT = "benchmark-reference-contract.v1"
SCHEMA_VERSION = "1.0"
VWCE_CANONICAL_ISIN = "IE00BK5BQT80"
VWCE_CANONICAL_SHARE_CLASS = "vanguard-ftse-all-world-ucits-etf-usd-accumulating"
HIERARCHIES = (
    "asset",
    "exposure",
    "country_region",
    "sector",
    "duration",
    "rating",
    "currency",
)
ReferenceMethod = Literal["equal_weight", "maximum_diversification", "no_trade"]
REFERENCE_METHODS: tuple[ReferenceMethod, ...] = (
    "equal_weight",
    "maximum_diversification",
    "no_trade",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


class _HasCanonicalDigest(Protocol):
    @property
    def content_hash(self) -> str: ...

    def digest(self) -> str: ...


class _SelectableDefinition(Protocol):
    @property
    def selector(self) -> Mapping[str, str]: ...

    @property
    def effective_at(self) -> str: ...

    @property
    def version(self) -> str: ...


_SelectableT = TypeVar("_SelectableT", bound=_SelectableDefinition)


class BenchmarkReferenceError(ValueError):
    """Raised when canonical evidence or a selection is invalid."""


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkReferenceError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkReferenceError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise BenchmarkReferenceError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _date(value: object, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise BenchmarkReferenceError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BenchmarkReferenceError(f"{field} must be YYYY-MM-DD") from exc


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkReferenceError(f"{field} must be non-empty text")
    return value.strip()


def _hashes(values: Sequence[str], field: str) -> tuple[str, ...]:
    result = tuple(sorted(str(item).lower() for item in values))
    if not result or any(_SHA256.fullmatch(item) is None for item in result):
        raise BenchmarkReferenceError(f"{field} must contain SHA-256 hashes")
    return result


def _semver(value: str, field: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise BenchmarkReferenceError(f"{field} must be semantic version text")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_canonical(item) for item in value]
    return value


def _content_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalise_ids(values: Sequence[str], field: str) -> tuple[str, ...]:
    result = tuple(sorted({_text(value, field) for value in values}))
    if not result:
        raise BenchmarkReferenceError(f"{field} must not be empty")
    return result


def _validate_window(
    effective_at: str,
    known_at: str,
    start_date: str,
    end_date: str,
) -> None:
    if _timestamp(effective_at, "effective_at") > _timestamp(known_at, "known_at"):
        raise BenchmarkReferenceError("effective_at cannot be after known_at")
    if _date(start_date, "start_date") > _date(end_date, "end_date"):
        raise BenchmarkReferenceError("start_date cannot be after end_date")


@dataclass(frozen=True)
class BenchmarkDefinition:
    benchmark_id: str
    version: str
    hierarchy: str
    selector: Mapping[str, str]
    currency: str
    minimum_horizon_years: float
    maximum_horizon_years: float
    effective_at: str
    known_at: str
    start_date: str
    end_date: str
    methodology: str
    constituents: tuple[str, ...]
    source_hashes: tuple[str, ...]
    status: Literal["available", "stale", "unavailable"] = "available"
    opportunity_anchor: bool = False
    canonical_identity: str | None = None
    content_hash: str = ""
    execution_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        _text(self.benchmark_id, "benchmark_id")
        _semver(self.version, "version")
        if self.hierarchy not in HIERARCHIES:
            raise BenchmarkReferenceError("benchmark hierarchy is unsupported")
        if not self.selector or any(not _text(k, "selector key") or not _text(v, "selector value") for k, v in self.selector.items()):
            raise BenchmarkReferenceError("benchmark selector must contain non-empty exact values")
        if self.currency != self.currency.upper() or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("benchmark currency must be an ISO-4217 code")
        if not 0 <= self.minimum_horizon_years <= self.maximum_horizon_years:
            raise BenchmarkReferenceError("benchmark horizon bounds are invalid")
        _validate_window(self.effective_at, self.known_at, self.start_date, self.end_date)
        _text(self.methodology, "methodology")
        object.__setattr__(self, "constituents", _normalise_ids(self.constituents, "constituents"))
        object.__setattr__(self, "source_hashes", _hashes(self.source_hashes, "source_hashes"))
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("benchmark status is unsupported")
        if self.canonical_identity is not None:
            _text(self.canonical_identity, "canonical_identity")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("benchmark contract cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "version": self.version,
            "hierarchy": self.hierarchy,
            "selector": dict(self.selector),
            "currency": self.currency,
            "minimum_horizon_years": self.minimum_horizon_years,
            "maximum_horizon_years": self.maximum_horizon_years,
            "effective_at": _timestamp(self.effective_at, "effective_at").isoformat(),
            "known_at": _timestamp(self.known_at, "known_at").isoformat(),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "methodology": self.methodology,
            "constituents": list(self.constituents),
            "source_hashes": list(self.source_hashes),
            "status": self.status,
            "opportunity_anchor": self.opportunity_anchor,
            "canonical_identity": self.canonical_identity,
            "execution_allowed": False,
        }

    def digest(self) -> str:
        return _content_hash(self.payload())


@dataclass(frozen=True)
class CashProxyDefinition:
    proxy_id: str
    version: str
    selector: Mapping[str, str]
    currency: str
    minimum_horizon_years: float
    maximum_horizon_years: float
    effective_at: str
    known_at: str
    start_date: str
    end_date: str
    methodology: str
    source_hashes: tuple[str, ...]
    status: Literal["available", "stale", "unavailable"] = "available"
    content_hash: str = ""
    execution_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        _text(self.proxy_id, "proxy_id")
        _semver(self.version, "version")
        if not self.selector or any(not _text(k, "selector key") or not _text(v, "selector value") for k, v in self.selector.items()):
            raise BenchmarkReferenceError("cash selector must contain non-empty exact values")
        if self.currency != self.currency.upper() or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("cash currency must be an ISO-4217 code")
        if not 0 <= self.minimum_horizon_years <= self.maximum_horizon_years:
            raise BenchmarkReferenceError("cash horizon bounds are invalid")
        _validate_window(self.effective_at, self.known_at, self.start_date, self.end_date)
        _text(self.methodology, "methodology")
        object.__setattr__(self, "source_hashes", _hashes(self.source_hashes, "source_hashes"))
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("cash status is unsupported")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("cash contract cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "proxy_id": self.proxy_id,
            "version": self.version,
            "selector": dict(self.selector),
            "currency": self.currency,
            "minimum_horizon_years": self.minimum_horizon_years,
            "maximum_horizon_years": self.maximum_horizon_years,
            "effective_at": _timestamp(self.effective_at, "effective_at").isoformat(),
            "known_at": _timestamp(self.known_at, "known_at").isoformat(),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "methodology": self.methodology,
            "source_hashes": list(self.source_hashes),
            "status": self.status,
            "execution_allowed": False,
        }

    def digest(self) -> str:
        return _content_hash(self.payload())


@dataclass(frozen=True)
class PeerSetDefinition:
    peer_set_id: str
    version: str
    hierarchy: str
    selector: Mapping[str, str]
    member_instrument_ids: tuple[str, ...]
    effective_at: str
    known_at: str
    methodology: str
    source_hashes: tuple[str, ...]
    status: Literal["available", "stale", "unavailable"] = "available"
    content_hash: str = ""
    execution_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        _text(self.peer_set_id, "peer_set_id")
        _semver(self.version, "version")
        if self.hierarchy not in HIERARCHIES:
            raise BenchmarkReferenceError("peer hierarchy is unsupported")
        if not self.selector or any(not _text(k, "selector key") or not _text(v, "selector value") for k, v in self.selector.items()):
            raise BenchmarkReferenceError("peer selector must contain non-empty exact values")
        object.__setattr__(self, "member_instrument_ids", _normalise_ids(self.member_instrument_ids, "member_instrument_ids"))
        if _timestamp(self.effective_at, "effective_at") > _timestamp(self.known_at, "known_at"):
            raise BenchmarkReferenceError("effective_at cannot be after known_at")
        _text(self.methodology, "methodology")
        object.__setattr__(self, "source_hashes", _hashes(self.source_hashes, "source_hashes"))
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("peer set status is unsupported")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("peer contract cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "peer_set_id": self.peer_set_id,
            "version": self.version,
            "hierarchy": self.hierarchy,
            "selector": dict(self.selector),
            "member_instrument_ids": list(self.member_instrument_ids),
            "effective_at": _timestamp(self.effective_at, "effective_at").isoformat(),
            "known_at": _timestamp(self.known_at, "known_at").isoformat(),
            "methodology": self.methodology,
            "source_hashes": list(self.source_hashes),
            "status": self.status,
            "execution_allowed": False,
        }

    def digest(self) -> str:
        return _content_hash(self.payload())


@dataclass(frozen=True)
class ReferencePortfolioDefinition:
    portfolio_id: str
    version: str
    method: ReferenceMethod
    constituent_instrument_ids: tuple[str, ...]
    methodology: str
    effective_at: str
    known_at: str
    current_weights: Mapping[str, float] | None = None
    content_hash: str = ""
    execution_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        _text(self.portfolio_id, "portfolio_id")
        _semver(self.version, "version")
        if self.method not in REFERENCE_METHODS:
            raise BenchmarkReferenceError("reference portfolio method is unsupported")
        object.__setattr__(self, "constituent_instrument_ids", _normalise_ids(self.constituent_instrument_ids, "constituent_instrument_ids"))
        _text(self.methodology, "methodology")
        _timestamp(self.effective_at, "effective_at")
        _timestamp(self.known_at, "known_at")
        if self.method == "no_trade" and self.current_weights is None:
            raise BenchmarkReferenceError("no_trade reference requires current weights")
        if self.current_weights is not None:
            expected = set(self.constituent_instrument_ids)
            if set(self.current_weights) != expected:
                raise BenchmarkReferenceError("current weights must cover reference constituents exactly")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
                for value in self.current_weights.values()
            ):
                raise BenchmarkReferenceError("current weights must be finite non-negative numbers")
            if self.method == "no_trade" and not math.isclose(
                sum(float(value) for value in self.current_weights.values()),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise BenchmarkReferenceError("no_trade current weights must sum to 1.0")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("reference portfolio cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "portfolio_id": self.portfolio_id,
            "version": self.version,
            "method": self.method,
            "constituent_instrument_ids": list(self.constituent_instrument_ids),
            "methodology": self.methodology,
            "effective_at": _timestamp(self.effective_at, "effective_at").isoformat(),
            "known_at": _timestamp(self.known_at, "known_at").isoformat(),
            "current_weights": None if self.current_weights is None else {key: self.current_weights[key] for key in sorted(self.current_weights)},
            "execution_allowed": False,
        }

    def digest(self) -> str:
        return _content_hash(self.payload())


@dataclass(frozen=True)
class VwceListingObservation:
    listing_id: str
    ticker: str
    venue: str
    currency: str
    effective_at: str
    known_at: str
    source_hash: str
    status: Literal["available", "stale", "unavailable"] = "available"

    def __post_init__(self) -> None:
        _text(self.listing_id, "listing_id")
        _text(self.ticker, "ticker")
        _text(self.venue, "venue")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("listing currency must be an ISO-4217 code")
        if _timestamp(self.effective_at, "effective_at") > _timestamp(self.known_at, "known_at"):
            raise BenchmarkReferenceError("listing effective_at cannot be after known_at")
        if _SHA256.fullmatch(self.source_hash.lower()) is None:
            raise BenchmarkReferenceError("listing source_hash must be SHA-256")


@dataclass(frozen=True)
class VwceAnchorEvidence:
    canonical_isin: str
    canonical_share_class_id: str
    official_facts_as_of: str
    benchmark_name: str
    benchmark_as_of: str
    fees: Mapping[str, object]
    fees_as_of: str
    tracking: Mapping[str, object]
    tracking_as_of: str
    product_risk_indicator: Mapping[str, object]
    risk_indicator_as_of: str
    currency: str
    source_hashes: tuple[str, ...]
    listing_observations: tuple[VwceListingObservation, ...]
    effective_at: str
    known_at: str
    status: Literal["available", "stale", "unavailable"] = "available"
    content_hash: str = ""
    execution_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if self.canonical_isin != VWCE_CANONICAL_ISIN:
            raise BenchmarkReferenceError("VWCE anchor must use the canonical ISIN")
        _text(self.canonical_share_class_id, "canonical_share_class_id")
        for field, value in (
            ("official_facts_as_of", self.official_facts_as_of),
            ("benchmark_as_of", self.benchmark_as_of),
            ("fees_as_of", self.fees_as_of),
            ("tracking_as_of", self.tracking_as_of),
            ("risk_indicator_as_of", self.risk_indicator_as_of),
        ):
            _date(value, field)
        _text(self.benchmark_name, "benchmark_name")
        if not isinstance(self.fees, Mapping) or not self.fees:
            raise BenchmarkReferenceError("fees evidence is required")
        if not isinstance(self.tracking, Mapping) or not self.tracking:
            raise BenchmarkReferenceError("tracking evidence is required")
        if not isinstance(self.product_risk_indicator, Mapping) or not self.product_risk_indicator:
            raise BenchmarkReferenceError("product risk indicator evidence is required")
        if not _text(str(self.product_risk_indicator.get("version") or ""), "risk indicator version"):
            raise BenchmarkReferenceError("risk indicator must be a versioned fact")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("VWCE currency must be an ISO-4217 code")
        object.__setattr__(self, "source_hashes", _hashes(self.source_hashes, "source_hashes"))
        if not self.listing_observations:
            raise BenchmarkReferenceError("at least one VWCE listing observation is required")
        if _timestamp(self.effective_at, "effective_at") > _timestamp(self.known_at, "known_at"):
            raise BenchmarkReferenceError("VWCE effective_at cannot be after known_at")
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("VWCE status is unsupported")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("VWCE evidence cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "canonical_isin": self.canonical_isin,
            "canonical_share_class_id": self.canonical_share_class_id,
            "official_facts_as_of": self.official_facts_as_of,
            "benchmark_name": self.benchmark_name,
            "benchmark_as_of": self.benchmark_as_of,
            "fees": dict(self.fees),
            "fees_as_of": self.fees_as_of,
            "tracking": dict(self.tracking),
            "tracking_as_of": self.tracking_as_of,
            "product_risk_indicator": dict(self.product_risk_indicator),
            "risk_indicator_as_of": self.risk_indicator_as_of,
            "currency": self.currency,
            "source_hashes": list(self.source_hashes),
            "listing_observations": [
                {
                    "listing_id": item.listing_id,
                    "ticker": item.ticker,
                    "venue": item.venue,
                    "currency": item.currency,
                    "effective_at": _timestamp(item.effective_at, "effective_at").isoformat(),
                    "known_at": _timestamp(item.known_at, "known_at").isoformat(),
                    "source_hash": item.source_hash,
                    "status": item.status,
                }
                for item in sorted(
                    self.listing_observations,
                    key=lambda item: (
                        item.listing_id,
                        _timestamp(item.effective_at, "effective_at"),
                        _timestamp(item.known_at, "known_at"),
                        item.ticker,
                        item.venue,
                        item.currency,
                        item.source_hash,
                        item.status,
                    ),
                )
            ],
            "effective_at": _timestamp(self.effective_at, "effective_at").isoformat(),
            "known_at": _timestamp(self.known_at, "known_at").isoformat(),
            "status": self.status,
            "execution_allowed": False,
        }

    def digest(self) -> str:
        return _content_hash(self.payload())


@dataclass(frozen=True)
class Selection:
    kind: Literal["benchmark", "cash", "peer"]
    status: Literal["available", "unavailable", "ambiguous"]
    selected_id: str | None
    version: str | None
    reason: str | None
    specificity: int | None = None
    execution_allowed: Literal[False] = False

    @property
    def display_name(self) -> str:
        return self.selected_id if self.status == "available" and self.selected_id else "N/A"


@dataclass(frozen=True)
class AnalysisDeclaration:
    analysis_id: str
    purpose: Literal["attribution", "validation", "comparison"]
    instrument_id: str
    currency: str
    horizon_years: float
    start_date: str
    end_date: str
    decision_time: str
    benchmark_id: str | None
    cash_proxy_id: str | None
    peer_set_id: str | None
    reference_portfolio_ids: tuple[str, ...]
    execution_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        _text(self.analysis_id, "analysis_id")
        _text(self.instrument_id, "instrument_id")
        if self.purpose not in {"attribution", "validation", "comparison"}:
            raise BenchmarkReferenceError("analysis purpose is unsupported")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("analysis currency must be an ISO-4217 code")
        if self.horizon_years <= 0:
            raise BenchmarkReferenceError("analysis horizon must be positive")
        _validate_window(self.decision_time, self.decision_time, self.start_date, self.end_date)
        if _date(self.start_date, "start_date") >= _date(self.end_date, "end_date"):
            raise BenchmarkReferenceError("analysis period must be positive")
        if self.benchmark_id is None:
            raise BenchmarkReferenceError("every analysis must declare a benchmark, including unavailable")
        if self.cash_proxy_id is None:
            raise BenchmarkReferenceError("every analysis must declare a cash alternative, including unavailable")
        object.__setattr__(self, "reference_portfolio_ids", _normalise_ids(self.reference_portfolio_ids, "reference_portfolio_ids"))
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("analysis cannot grant execution authority")


@dataclass(frozen=True)
class AnalysisResolution:
    declaration: AnalysisDeclaration
    benchmark: Selection
    cash: Selection
    peer_set: Selection
    references: tuple[ReferencePortfolioDefinition, ...]
    blockers: tuple[str, ...]
    execution_allowed: Literal[False] = False


@dataclass(frozen=True)
class VwceAnchorResolution:
    status: Literal["available", "unavailable", "ambiguous"]
    canonical_share_class_id: str | None
    listing_id: str | None
    reason: str | None
    observation_effective_at: str | None = None
    observation_known_at: str | None = None
    execution_allowed: Literal[False] = False


class CanonicalBenchmarkRegistry:
    """Immutable in-memory registry with deterministic point-in-time mapping."""

    def __init__(
        self,
        benchmarks: Sequence[BenchmarkDefinition] = (),
        cash_proxies: Sequence[CashProxyDefinition] = (),
        peer_sets: Sequence[PeerSetDefinition] = (),
        reference_portfolios: Sequence[ReferencePortfolioDefinition] = (),
        vwce_anchors: Sequence[VwceAnchorEvidence] = (),
    ) -> None:
        self.benchmarks = tuple(sorted(benchmarks, key=lambda item: (item.benchmark_id, _semver(item.version, "version"))))
        self.cash_proxies = tuple(sorted(cash_proxies, key=lambda item: (item.proxy_id, _semver(item.version, "version"))))
        self.peer_sets = tuple(sorted(peer_sets, key=lambda item: (item.peer_set_id, _semver(item.version, "version"))))
        self.reference_portfolios = tuple(sorted(reference_portfolios, key=lambda item: (item.portfolio_id, _semver(item.version, "version"))))
        self.vwce_anchors = tuple(sorted(vwce_anchors, key=lambda item: (item.canonical_share_class_id, _timestamp(item.known_at, "known_at"))))
        self._check_unique((item.benchmark_id, item.version) for item in self.benchmarks)
        self._check_unique((item.proxy_id, item.version) for item in self.cash_proxies)
        self._check_unique((item.peer_set_id, item.version) for item in self.peer_sets)
        self._check_unique((item.portfolio_id, item.version) for item in self.reference_portfolios)
        self._validate_content_hashes(self.benchmarks)
        self._validate_content_hashes(self.cash_proxies)
        self._validate_content_hashes(self.peer_sets)
        self._validate_content_hashes(self.reference_portfolios)
        self._validate_content_hashes(self.vwce_anchors)

    @staticmethod
    def _check_unique(values: Iterable[tuple[str, str]]) -> None:
        pairs: tuple[tuple[str, str], ...] = tuple(values)
        if len(pairs) != len(set(pairs)):
            raise BenchmarkReferenceError("registry contains duplicate versioned identifiers")

    @staticmethod
    def _validate_content_hashes(items: Sequence[_HasCanonicalDigest]) -> None:
        for item in items:
            if item.content_hash and item.content_hash != item.digest():
                raise BenchmarkReferenceError("content hash does not match canonical payload")

    def map_instrument(
        self,
        instrument: Mapping[str, object],
        *,
        currency: str,
        horizon_years: float,
        start_date: str,
        end_date: str,
        decision_time: str,
        benchmark_version: str | None = None,
        cash_version: str | None = None,
        peer_version: str | None = None,
    ) -> tuple[Selection, Selection, Selection]:
        _validate_period(currency, horizon_years, start_date, end_date, decision_time)
        benchmark = self._select_benchmark(instrument, currency, horizon_years, start_date, end_date, decision_time, benchmark_version)
        cash = self._select_cash(instrument, currency, horizon_years, start_date, end_date, decision_time, cash_version)
        peer = self._select_peer(instrument, start_date, decision_time, peer_version)
        return benchmark, cash, peer

    def resolve_analysis(
        self,
        *,
        analysis_id: str,
        purpose: Literal["attribution", "validation", "comparison"],
        instrument_id: str,
        instrument: Mapping[str, object],
        currency: str,
        horizon_years: float,
        start_date: str,
        end_date: str,
        decision_time: str,
        reference_portfolio_ids: Sequence[str],
        benchmark_version: str | None = None,
        cash_version: str | None = None,
        peer_version: str | None = None,
    ) -> AnalysisResolution:
        benchmark, cash, peer = self.map_instrument(
            instrument,
            currency=currency,
            horizon_years=horizon_years,
            start_date=start_date,
            end_date=end_date,
            decision_time=decision_time,
            benchmark_version=benchmark_version,
            cash_version=cash_version,
            peer_version=peer_version,
        )
        declaration = AnalysisDeclaration(
            analysis_id=analysis_id,
            purpose=purpose,
            instrument_id=instrument_id,
            currency=currency,
            horizon_years=horizon_years,
            start_date=start_date,
            end_date=end_date,
            decision_time=decision_time,
            benchmark_id=benchmark.selected_id or f"unavailable:{benchmark.kind}",
            cash_proxy_id=cash.selected_id or f"unavailable:{cash.kind}",
            peer_set_id=peer.selected_id,
            reference_portfolio_ids=tuple(reference_portfolio_ids),
        )
        references: list[ReferencePortfolioDefinition] = []
        reference_blockers: set[str] = set()
        for reference_id in reference_portfolio_ids:
            try:
                references.append(self._reference(reference_id, decision_time))
            except BenchmarkReferenceError:
                reference_blockers.add(f"reference:unavailable:{reference_id}")
        blockers = tuple(sorted({f"{selection.kind}:{selection.reason}" for selection in (benchmark, cash, peer) if selection.status != "available" and selection.reason} | reference_blockers))
        return AnalysisResolution(declaration, benchmark, cash, peer, tuple(references), blockers)

    def ui_projection(self, resolution: AnalysisResolution) -> dict[str, object]:
        """Return a read-only comparison projection with explicit blockers."""

        def item(selection: Selection) -> dict[str, object]:
            return {
                "status": selection.status,
                "display": selection.display_name,
                "id": selection.selected_id,
                "version": selection.version,
                "reason": selection.reason,
                "specificity": selection.specificity,
            }

        return {
            "contract": CONTRACT,
            "analysis_id": resolution.declaration.analysis_id,
            "purpose": resolution.declaration.purpose,
            "benchmark": item(resolution.benchmark),
            "cash": item(resolution.cash),
            "peer_set": item(resolution.peer_set),
            "references": [
                {"id": reference.portfolio_id, "version": reference.version, "method": reference.method}
                for reference in resolution.references
            ],
            "blockers": list(resolution.blockers),
            "execution_allowed": False,
        }

    def as_payload(self) -> dict[str, object]:
        records = [
            {"kind": "benchmark", "payload": item.payload(), "content_hash": item.digest()}
            for item in self.benchmarks
        ] + [
            {"kind": "cash", "payload": item.payload(), "content_hash": item.digest()}
            for item in self.cash_proxies
        ] + [
            {"kind": "peer", "payload": item.payload(), "content_hash": item.digest()}
            for item in self.peer_sets
        ] + [
            {"kind": "reference", "payload": item.payload(), "content_hash": item.digest()}
            for item in self.reference_portfolios
        ] + [
            {"kind": "vwce_anchor", "payload": item.payload(), "content_hash": item.digest()}
            for item in self.vwce_anchors
        ]
        payload = {"contract": CONTRACT, "schema_version": SCHEMA_VERSION, "records": records, "execution_allowed": False}
        return {**payload, "registry_hash": _content_hash(payload)}

    @staticmethod
    def validate_payload(payload: Mapping[str, object]) -> dict[str, object]:
        """Validate a serialized registry envelope without accepting tampering."""

        if not isinstance(payload, Mapping) or payload.get("contract") != CONTRACT or payload.get("schema_version") != SCHEMA_VERSION or payload.get("execution_allowed") is not False:
            raise BenchmarkReferenceError("registry envelope is invalid")
        records = payload.get("records")
        supplied = payload.get("registry_hash")
        unsigned = {key: payload[key] for key in payload if key != "registry_hash"}
        if not isinstance(records, list) or not isinstance(supplied, str) or supplied != _content_hash(unsigned):
            raise BenchmarkReferenceError("registry hash mismatch")
        for record in records:
            if not isinstance(record, Mapping) or set(record) != {"kind", "payload", "content_hash"}:
                raise BenchmarkReferenceError("registry record envelope is invalid")
            if record.get("kind") not in {"benchmark", "cash", "peer", "reference", "vwce_anchor"}:
                raise BenchmarkReferenceError("registry record kind is unsupported")
            content = record.get("payload")
            content_hash = record.get("content_hash")
            if not isinstance(content, Mapping) or not isinstance(content_hash, str) or content_hash != _content_hash(content):
                raise BenchmarkReferenceError("registry record hash mismatch")
        return dict(payload)

    def _select_benchmark(self, instrument: Mapping[str, object], currency: str, horizon: float, start: str, end: str, cutoff: str, version: str | None) -> Selection:
        candidates = [item for item in self.benchmarks if _selector_matches(item.selector, instrument) and (version is None or item.version == version)]
        candidates = [item for item in candidates if _pit(item.effective_at, item.known_at, start, cutoff)]
        candidates = [item for item in candidates if item.status == "available"]
        if not candidates:
            matching = [item for item in self.benchmarks if _selector_matches(item.selector, instrument) and (version is None or item.version == version)]
            reason = "benchmark_stale_or_unavailable" if any(item.status != "available" for item in matching) else "no_point_in_time_mapping"
            return _unavailable("benchmark", reason)
        candidates = _best_by_id(candidates)
        if len(candidates) != 1:
            return Selection("benchmark", "ambiguous", None, None, "ambiguous_mapping", max(len(item.selector) for item in candidates))
        item = candidates[0]
        alignment_reason = _alignment_reason(item.currency, currency, item.minimum_horizon_years, item.maximum_horizon_years, horizon, item.start_date, item.end_date, start, end)
        if alignment_reason:
            return _unavailable("benchmark", alignment_reason)
        return Selection("benchmark", "available", item.benchmark_id, item.version, None, len(item.selector))

    def _select_cash(self, instrument: Mapping[str, object], currency: str, horizon: float, start: str, end: str, cutoff: str, version: str | None) -> Selection:
        candidates = [item for item in self.cash_proxies if _selector_matches(item.selector, instrument) and (version is None or item.version == version)]
        candidates = [item for item in candidates if _pit(item.effective_at, item.known_at, start, cutoff) and item.status == "available"]
        if not candidates:
            matching = [item for item in self.cash_proxies if _selector_matches(item.selector, instrument) and (version is None or item.version == version)]
            reason = "cash_stale_or_unavailable" if any(item.status != "available" for item in matching) else "no_point_in_time_mapping"
            return _unavailable("cash", reason)
        candidates = _best_by_id(candidates)
        if len(candidates) != 1:
            return Selection("cash", "ambiguous", None, None, "ambiguous_mapping", max(len(item.selector) for item in candidates))
        item = candidates[0]
        alignment_reason = _alignment_reason(item.currency, currency, item.minimum_horizon_years, item.maximum_horizon_years, horizon, item.start_date, item.end_date, start, end)
        if alignment_reason:
            return _unavailable("cash", alignment_reason)
        return Selection("cash", "available", item.proxy_id, item.version, None, len(item.selector))

    def _select_peer(self, instrument: Mapping[str, object], start: str, cutoff: str, version: str | None) -> Selection:
        candidates = [item for item in self.peer_sets if _selector_matches(item.selector, instrument) and (version is None or item.version == version) and _pit(item.effective_at, item.known_at, start, cutoff) and item.status == "available"]
        if not candidates:
            return _unavailable("peer", "peer_set_unavailable")
        candidates = _best_by_id(candidates)
        if len(candidates) != 1:
            return Selection("peer", "ambiguous", None, None, "ambiguous_mapping", max(len(item.selector) for item in candidates))
        item = candidates[0]
        return Selection("peer", "available", item.peer_set_id, item.version, None, len(item.selector))

    def _reference(self, reference_id: str, cutoff: str) -> ReferencePortfolioDefinition:
        cutoff_time = _timestamp(cutoff, "decision_time")
        matches = [
            item
            for item in self.reference_portfolios
            if item.portfolio_id == reference_id
            and _timestamp(item.effective_at, "effective_at") <= cutoff_time
            and _timestamp(item.known_at, "known_at") <= cutoff_time
        ]
        if not matches:
            raise BenchmarkReferenceError(f"reference portfolio is unavailable: {reference_id}")
        matches.sort(key=lambda item: (_timestamp(item.effective_at, "effective_at"), _semver(item.version, "version")), reverse=True)
        return matches[0]


def _validate_period(currency: str, horizon: float, start: str, end: str, cutoff: str) -> None:
    if not re.fullmatch(r"[A-Z]{3}", currency) or currency != currency.upper():
        raise BenchmarkReferenceError("analysis currency must be an ISO-4217 code")
    if horizon <= 0:
        raise BenchmarkReferenceError("analysis horizon must be positive")
    _date(start, "start_date")
    _date(end, "end_date")
    if _date(start, "start_date") >= _date(end, "end_date"):
        raise BenchmarkReferenceError("analysis period must be positive")
    _timestamp(cutoff, "decision_time")


def _selector_matches(selector: Mapping[str, str], instrument: Mapping[str, object]) -> bool:
    return all(str(instrument.get(key, "")) == value for key, value in selector.items())


def _pit(effective_at: str, known_at: str, effective_cutoff: str, known_cutoff: str) -> bool:
    return _timestamp(effective_at, "effective_at") <= datetime.combine(_date(effective_cutoff, "effective_cutoff"), datetime.min.time(), tzinfo=timezone.utc) and _timestamp(known_at, "known_at") <= _timestamp(known_cutoff, "known_cutoff")


def _definition_id(item: object) -> str:
    for field in ("benchmark_id", "proxy_id", "peer_set_id"):
        value = getattr(item, field, None)
        if isinstance(value, str):
            return value
    raise BenchmarkReferenceError("selectable definition has no canonical identifier")


def _best_by_id(candidates: Sequence[_SelectableT]) -> list[_SelectableT]:
    max_specificity = max(len(item.selector) for item in candidates)
    candidates = [item for item in candidates if len(item.selector) == max_specificity]
    ids = {_definition_id(item) for item in candidates}
    if len(ids) > 1:
        return list(candidates)
    candidates = sorted(candidates, key=lambda item: (_timestamp(item.effective_at, "effective_at"), _semver(item.version, "version")), reverse=True)
    return [candidates[0]]


def _alignment_reason(definition_currency: str, currency: str, minimum: float, maximum: float, horizon: float, coverage_start: str, coverage_end: str, start: str, end: str) -> str | None:
    if definition_currency != currency:
        return "currency_mismatch_no_fx_substitution"
    if not minimum <= horizon <= maximum:
        return "horizon_mismatch"
    if _date(start, "start_date") < _date(coverage_start, "coverage_start") or _date(end, "end_date") > _date(coverage_end, "coverage_end"):
        return "date_coverage_unavailable"
    return None


def _unavailable(kind: Literal["benchmark", "cash", "peer"], reason: str) -> Selection:
    return Selection(kind, "unavailable", None, None, reason)


def declare_reference_portfolios(
    instrument_ids: Sequence[str],
    *,
    current_weights: Mapping[str, float],
    effective_at: str,
    known_at: str,
    version: str = "1.0.0",
) -> tuple[ReferencePortfolioDefinition, ...]:
    """Declare the three comparison baselines used by rebalance evaluation."""

    ids = _normalise_ids(instrument_ids, "instrument_ids")
    return tuple(
        ReferencePortfolioDefinition(
            portfolio_id=f"reference:{method}",
            version=version,
            method=method,
            constituent_instrument_ids=ids,
            methodology={
                "equal_weight": "PortfolioOptimiser equal_weight over canonical constituents.",
                "maximum_diversification": "PortfolioOptimiser maximum_diversification over canonical adjusted-return covariance.",
                "no_trade": "Current positions and cash are held with zero proposed turnover.",
            }[method],
            effective_at=effective_at,
            known_at=known_at,
            current_weights=dict(current_weights) if method == "no_trade" else None,
        )
        for method in REFERENCE_METHODS
    )


def resolve_vwce_anchor(
    anchor: VwceAnchorEvidence,
    *,
    listing_id: str,
    effective_date: str,
    decision_time: str,
) -> VwceAnchorResolution:
    """Resolve one listing to the canonical VWCE share class at two cutoffs."""

    _date(effective_date, "effective_date")
    cutoff = _timestamp(decision_time, "decision_time")
    if anchor.status != "available" or _timestamp(anchor.known_at, "known_at") > cutoff:
        return VwceAnchorResolution("unavailable", None, None, "anchor_stale_or_unavailable")
    if _timestamp(anchor.effective_at, "effective_at") > datetime.combine(_date(effective_date, "effective_date"), datetime.min.time(), tzinfo=timezone.utc):
        return VwceAnchorResolution("unavailable", None, None, "anchor_not_yet_effective")
    matches = [
        item for item in anchor.listing_observations
        if item.listing_id == listing_id
        and item.status == "available"
        and _timestamp(item.effective_at, "effective_at") <= datetime.combine(_date(effective_date, "effective_date"), datetime.min.time(), tzinfo=timezone.utc)
        and _timestamp(item.known_at, "known_at") <= cutoff
    ]
    if not matches:
        return VwceAnchorResolution("unavailable", None, None, "listing_unavailable_at_cutoff")
    latest_effective = max(_timestamp(item.effective_at, "effective_at") for item in matches)
    matches = [item for item in matches if _timestamp(item.effective_at, "effective_at") == latest_effective]
    latest_known = max(_timestamp(item.known_at, "known_at") for item in matches)
    matches = [item for item in matches if _timestamp(item.known_at, "known_at") == latest_known]
    identities = {(item.ticker, item.venue, item.currency) for item in matches}
    if len(identities) > 1:
        return VwceAnchorResolution("ambiguous", None, None, "ambiguous_listing_observation")
    selected = min(matches, key=lambda item: (item.ticker, item.venue, item.currency, item.source_hash))
    return VwceAnchorResolution(
        "available",
        anchor.canonical_share_class_id,
        listing_id,
        None,
        selected.effective_at,
        selected.known_at,
    )


def project_profile_relative_analysis(
    raw_analysis: Mapping[str, object],
    anchor_resolution: VwceAnchorResolution,
) -> dict[str, object]:
    """Block only profile-relative claims when the VWCE anchor is unavailable."""

    result = {
        "contract": CONTRACT,
        "raw_analysis": deepcopy(dict(raw_analysis)),
        "profile_relative_status": "available" if anchor_resolution.status == "available" else "unavailable",
        "profile_relative_claims_allowed": anchor_resolution.status == "available",
        "anchor_reason": anchor_resolution.reason,
        "blockers": [] if anchor_resolution.status == "available" else ["vwce_anchor_unavailable"],
        "execution_allowed": False,
    }
    return result


__all__ = [
    "AnalysisDeclaration",
    "AnalysisResolution",
    "BenchmarkDefinition",
    "BenchmarkReferenceError",
    "CONTRACT",
    "CanonicalBenchmarkRegistry",
    "CashProxyDefinition",
    "HIERARCHIES",
    "PeerSetDefinition",
    "REFERENCE_METHODS",
    "ReferencePortfolioDefinition",
    "SCHEMA_VERSION",
    "Selection",
    "VWCE_CANONICAL_ISIN",
    "VWCE_CANONICAL_SHARE_CLASS",
    "VwceAnchorEvidence",
    "VwceAnchorResolution",
    "VwceListingObservation",
    "declare_reference_portfolios",
    "project_profile_relative_analysis",
    "resolve_vwce_anchor",
]
