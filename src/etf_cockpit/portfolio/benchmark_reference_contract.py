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
from importlib import resources
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
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
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@dataclass(frozen=True, order=True)
class _SemVer:
    major: int
    minor: int
    patch: int
    release: int
    prerelease: tuple[tuple[int, int | str], ...]


def _semver(value: str, field: str) -> _SemVer:
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise BenchmarkReferenceError(f"{field} must be semantic version text")
    prerelease = match.group(4)
    identifiers: list[tuple[int, int | str]] = []
    if prerelease:
        for identifier in prerelease.split("."):
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    raise BenchmarkReferenceError(f"{field} must be semantic version text")
                identifiers.append((0, int(identifier)))
            else:
                identifiers.append((1, identifier))
    return _SemVer(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        0 if prerelease else 1,
        tuple(identifiers),
    )


def _version_sort_key(value: str, field: str = "version") -> tuple[_SemVer, str]:
    """Sort by SemVer precedence, then raw text for build-tie determinism."""

    return _semver(value, field), value


class _HasCanonicalDigest(Protocol):
    @property
    def content_hash(self) -> str: ...

    def digest(self) -> str: ...

    def payload(self) -> dict[str, object]: ...


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


def _hashes(values: Sequence[str], field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if any(not isinstance(item, str) for item in values):
        raise BenchmarkReferenceError(f"{field} must contain SHA-256 hashes")
    result = tuple(sorted(item.lower() for item in values))
    if (not result and not allow_empty) or any(_SHA256.fullmatch(item) is None for item in result):
        raise BenchmarkReferenceError(f"{field} must contain SHA-256 hashes")
    return result


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise BenchmarkReferenceError("canonical mappings require string keys")
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_canonical(item) for item in value]
    return value


def _freeze(value: object) -> object:
    """Recursively detach and seal caller-owned evidence."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_thaw(item) for item in value]
    return value


def _selector(value: object, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise BenchmarkReferenceError(f"{field} must contain non-empty exact values")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[_text(key, f"{field} key")] = _text(item, f"{field} value")
    return MappingProxyType(result)


def _assert_no_execution(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "execution_allowed" and item is not False:
                raise BenchmarkReferenceError("serialized evidence cannot grant execution authority")
            _assert_no_execution(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_no_execution(item)


def _nested_fact_is_available(value: object) -> bool:
    if isinstance(value, Mapping):
        if not value:
            return False
        metadata_keys = {
            "status", "reason", "version", "execution_allowed",
            "source_hash", "source_hashes", "effective_at", "known_at", "as_of",
            "authority", "source", "published_at", "publication_date", "timestamp",
            "content_hash",
        }
        facts = [
            item for key, item in value.items()
            if key not in metadata_keys
        ]
        return bool(facts) and all(_nested_fact_is_available(item) for item in facts)
    if isinstance(value, (list, tuple, set, frozenset)):
        return bool(value) and all(_nested_fact_is_available(item) for item in value)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    return True


def _nested_statuses_are_available(value: object) -> bool:
    if isinstance(value, Mapping):
        if "status" in value:
            status = value["status"]
            if not isinstance(status, str) or status != "available":
                return False
        return all(
            _nested_statuses_are_available(item)
            for key, item in value.items()
            if key != "status"
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return all(_nested_statuses_are_available(item) for item in value)
    return True


def _nested_evidence_is_available(value: object) -> bool:
    """Return whether nested product evidence contains available facts."""

    return (
        isinstance(value, Mapping)
        and bool(value)
        and _nested_statuses_are_available(value)
        and _nested_fact_is_available(value)
    )


def _content_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalise_ids(values: Sequence[str], field: str) -> tuple[str, ...]:
    result = tuple(sorted({_text(value, field) for value in values}))
    if not result:
        raise BenchmarkReferenceError(f"{field} must not be empty")
    return result


def _reference_ids(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(_text(value, "reference_portfolio_ids") for value in values)
    if len(normalized) != len(set(normalized)):
        raise BenchmarkReferenceError("reference_portfolio_ids must not contain duplicates")
    return _normalise_ids(normalized, "reference_portfolio_ids")


def _horizon(value: object, field: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise BenchmarkReferenceError(f"{field} must be a finite number")
    return float(value)


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
        object.__setattr__(self, "selector", _selector(self.selector, "benchmark selector"))
        if self.currency != self.currency.upper() or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("benchmark currency must be an ISO-4217 code")
        minimum_horizon = _horizon(self.minimum_horizon_years, "benchmark minimum_horizon_years")
        maximum_horizon = _horizon(self.maximum_horizon_years, "benchmark maximum_horizon_years")
        if minimum_horizon is None or maximum_horizon is None or not 0 <= minimum_horizon <= maximum_horizon:
            raise BenchmarkReferenceError("benchmark horizon bounds are invalid")
        _validate_window(self.effective_at, self.known_at, self.start_date, self.end_date)
        _text(self.methodology, "methodology")
        object.__setattr__(self, "constituents", _normalise_ids(self.constituents, "constituents"))
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("benchmark status is unsupported")
        object.__setattr__(
            self, "source_hashes",
            _hashes(self.source_hashes, "source_hashes", allow_empty=self.status == "unavailable"),
        )
        if type(self.opportunity_anchor) is not bool:
            raise BenchmarkReferenceError("opportunity_anchor must be a boolean")
        if self.canonical_identity is not None:
            _text(self.canonical_identity, "canonical_identity")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("benchmark contract cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "version": self.version,
            "hierarchy": self.hierarchy,
            "selector": _thaw(self.selector),
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
        object.__setattr__(self, "selector", _selector(self.selector, "cash selector"))
        if self.currency != self.currency.upper() or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("cash currency must be an ISO-4217 code")
        minimum_horizon = _horizon(self.minimum_horizon_years, "cash minimum_horizon_years")
        maximum_horizon = _horizon(self.maximum_horizon_years, "cash maximum_horizon_years")
        if minimum_horizon is None or maximum_horizon is None or not 0 <= minimum_horizon <= maximum_horizon:
            raise BenchmarkReferenceError("cash horizon bounds are invalid")
        _validate_window(self.effective_at, self.known_at, self.start_date, self.end_date)
        _text(self.methodology, "methodology")
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("cash status is unsupported")
        object.__setattr__(
            self, "source_hashes",
            _hashes(self.source_hashes, "source_hashes", allow_empty=self.status == "unavailable"),
        )
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("cash contract cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "proxy_id": self.proxy_id,
            "version": self.version,
            "selector": _thaw(self.selector),
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
        object.__setattr__(self, "selector", _selector(self.selector, "peer selector"))
        object.__setattr__(self, "member_instrument_ids", _normalise_ids(self.member_instrument_ids, "member_instrument_ids"))
        if _timestamp(self.effective_at, "effective_at") > _timestamp(self.known_at, "known_at"):
            raise BenchmarkReferenceError("effective_at cannot be after known_at")
        _text(self.methodology, "methodology")
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("peer set status is unsupported")
        object.__setattr__(
            self, "source_hashes",
            _hashes(self.source_hashes, "source_hashes", allow_empty=self.status == "unavailable"),
        )
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("peer contract cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "peer_set_id": self.peer_set_id,
            "version": self.version,
            "hierarchy": self.hierarchy,
            "selector": _thaw(self.selector),
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
    currency: str | None = None
    minimum_horizon_years: float | None = None
    maximum_horizon_years: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    source_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.portfolio_id, "portfolio_id")
        _semver(self.version, "version")
        if self.method not in REFERENCE_METHODS:
            raise BenchmarkReferenceError("reference portfolio method is unsupported")
        object.__setattr__(self, "constituent_instrument_ids", _normalise_ids(self.constituent_instrument_ids, "constituent_instrument_ids"))
        _text(self.methodology, "methodology")
        effective_at = _timestamp(self.effective_at, "effective_at")
        known_at = _timestamp(self.known_at, "known_at")
        if effective_at > known_at:
            raise BenchmarkReferenceError("effective_at cannot be after known_at")
        if self.currency is not None and (self.currency != self.currency.upper() or not re.fullmatch(r"[A-Z]{3}", self.currency)):
            raise BenchmarkReferenceError("reference portfolio currency must be an ISO-4217 code")
        if self.minimum_horizon_years is not None or self.maximum_horizon_years is not None:
            if (
                self.minimum_horizon_years is None
                or self.maximum_horizon_years is None
                or _horizon(self.minimum_horizon_years, "reference minimum_horizon_years") is None
                or _horizon(self.maximum_horizon_years, "reference maximum_horizon_years") is None
                or not 0 <= float(self.minimum_horizon_years) <= float(self.maximum_horizon_years)
            ):
                raise BenchmarkReferenceError("reference portfolio horizon bounds are invalid")
        if self.start_date is not None or self.end_date is not None:
            if self.start_date is None or self.end_date is None or _date(self.start_date, "start_date") > _date(self.end_date, "end_date"):
                raise BenchmarkReferenceError("reference portfolio date coverage is invalid")
        if self.source_hashes:
            object.__setattr__(self, "source_hashes", _hashes(self.source_hashes, "source_hashes"))
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
            object.__setattr__(self, "current_weights", _freeze(self.current_weights))
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
            "current_weights": None if self.current_weights is None else _thaw(self.current_weights),
            "currency": self.currency,
            "minimum_horizon_years": self.minimum_horizon_years,
            "maximum_horizon_years": self.maximum_horizon_years,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "source_hashes": list(self.source_hashes),
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
        if not isinstance(self.source_hash, str) or (
            not (self.status == "unavailable" and self.source_hash == "")
            and _SHA256.fullmatch(self.source_hash.lower()) is None
        ):
            raise BenchmarkReferenceError("listing source_hash must be SHA-256")
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("listing status is unsupported")


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
    minimum_horizon_years: float | None = None
    maximum_horizon_years: float | None = None
    status: Literal["available", "stale", "unavailable"] = "available"
    content_hash: str = ""
    execution_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if self.canonical_isin != VWCE_CANONICAL_ISIN:
            raise BenchmarkReferenceError("VWCE anchor must use the canonical ISIN")
        if self.canonical_share_class_id != VWCE_CANONICAL_SHARE_CLASS:
            raise BenchmarkReferenceError("VWCE anchor must use the canonical share class")
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
        risk_version = self.product_risk_indicator.get("version")
        if not isinstance(risk_version, str) or not risk_version.strip():
            raise BenchmarkReferenceError("risk indicator must be a versioned string fact")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise BenchmarkReferenceError("VWCE currency must be an ISO-4217 code")
        if self.status not in {"available", "stale", "unavailable"}:
            raise BenchmarkReferenceError("VWCE status is unsupported")
        object.__setattr__(
            self, "source_hashes",
            _hashes(self.source_hashes, "source_hashes", allow_empty=self.status == "unavailable"),
        )
        if not self.listing_observations:
            raise BenchmarkReferenceError("at least one VWCE listing observation is required")
        object.__setattr__(self, "listing_observations", tuple(self.listing_observations))
        anchor_effective = _timestamp(self.effective_at, "effective_at")
        anchor_known = _timestamp(self.known_at, "known_at")
        if anchor_effective > anchor_known:
            raise BenchmarkReferenceError("VWCE effective_at cannot be after known_at")
        for observation in self.listing_observations:
            if _timestamp(observation.effective_at, "listing effective_at") < anchor_effective:
                raise BenchmarkReferenceError("listing effective_at precedes anchor authority")
            if _timestamp(observation.known_at, "listing known_at") > anchor_known:
                raise BenchmarkReferenceError("listing known_at exceeds anchor authority")
        if self.minimum_horizon_years is not None or self.maximum_horizon_years is not None:
            if (
                self.minimum_horizon_years is None
                or self.maximum_horizon_years is None
                or _horizon(self.minimum_horizon_years, "VWCE minimum_horizon_years") is None
                or _horizon(self.maximum_horizon_years, "VWCE maximum_horizon_years") is None
                or not 0 <= float(self.minimum_horizon_years) <= float(self.maximum_horizon_years)
            ):
                raise BenchmarkReferenceError("VWCE horizon bounds are invalid")
        known_date = _timestamp(self.known_at, "known_at").date()
        if any(_date(value, field) > known_date for field, value in (
            ("official_facts_as_of", self.official_facts_as_of),
            ("benchmark_as_of", self.benchmark_as_of),
            ("fees_as_of", self.fees_as_of),
            ("tracking_as_of", self.tracking_as_of),
            ("risk_indicator_as_of", self.risk_indicator_as_of),
        )):
            raise BenchmarkReferenceError("VWCE fact date cannot be after known_at")
        object.__setattr__(self, "fees", _freeze(self.fees))
        object.__setattr__(self, "tracking", _freeze(self.tracking))
        object.__setattr__(self, "product_risk_indicator", _freeze(self.product_risk_indicator))
        _assert_no_execution(self.fees)
        _assert_no_execution(self.tracking)
        _assert_no_execution(self.product_risk_indicator)
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("VWCE evidence cannot grant execution authority")

    def payload(self) -> dict[str, object]:
        return {
            "canonical_isin": self.canonical_isin,
            "canonical_share_class_id": self.canonical_share_class_id,
            "official_facts_as_of": self.official_facts_as_of,
            "benchmark_name": self.benchmark_name,
            "benchmark_as_of": self.benchmark_as_of,
            "fees": _thaw(self.fees),
            "fees_as_of": self.fees_as_of,
            "tracking": _thaw(self.tracking),
            "tracking_as_of": self.tracking_as_of,
            "product_risk_indicator": _thaw(self.product_risk_indicator),
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
            "minimum_horizon_years": self.minimum_horizon_years,
            "maximum_horizon_years": self.maximum_horizon_years,
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
    content_hash: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"benchmark", "cash", "peer"}:
            raise BenchmarkReferenceError("selection kind is unsupported")
        if self.status not in {"available", "unavailable", "ambiguous"}:
            raise BenchmarkReferenceError("selection status is unsupported")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("selection cannot grant execution authority")
        if self.content_hash is not None and (
            not isinstance(self.content_hash, str)
            or _SHA256.fullmatch(self.content_hash.lower()) is None
        ):
            raise BenchmarkReferenceError("selection content_hash must be SHA-256")

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
        horizon = _horizon(self.horizon_years, "analysis horizon_years")
        if horizon is None or horizon <= 0:
            raise BenchmarkReferenceError("analysis horizon must be positive")
        _validate_window(self.decision_time, self.decision_time, self.start_date, self.end_date)
        if _date(self.start_date, "start_date") >= _date(self.end_date, "end_date"):
            raise BenchmarkReferenceError("analysis period must be positive")
        if self.benchmark_id is None:
            raise BenchmarkReferenceError("every analysis must declare a benchmark, including unavailable")
        if self.cash_proxy_id is None:
            raise BenchmarkReferenceError("every analysis must declare a cash alternative, including unavailable")
        object.__setattr__(self, "reference_portfolio_ids", _reference_ids(self.reference_portfolio_ids))
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

    def __post_init__(self) -> None:
        self.validate_invariants()

    def validate_invariants(self) -> None:
        """Revalidate slot, declaration, and reference consistency."""

        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("analysis resolution cannot grant execution authority")
        nested = (self.declaration, self.benchmark, self.cash, self.peer_set, *self.references)
        if any(getattr(item, "execution_allowed", None) is not False for item in nested):
            raise BenchmarkReferenceError("analysis resolution contains execution authority")
        if (
            self.benchmark.kind != "benchmark"
            or self.cash.kind != "cash"
            or self.peer_set.kind != "peer"
        ):
            raise BenchmarkReferenceError("analysis resolution selection slots are invalid")
        expected_benchmark_id = (
            self.benchmark.selected_id
            if self.benchmark.status == "available"
            else "unavailable:benchmark"
        )
        expected_cash_id = (
            self.cash.selected_id
            if self.cash.status == "available"
            else "unavailable:cash"
        )
        expected_peer_id = self.peer_set.selected_id if self.peer_set.status == "available" else None
        if self.declaration.benchmark_id != expected_benchmark_id:
            raise BenchmarkReferenceError("analysis declaration benchmark does not match resolution")
        if self.declaration.cash_proxy_id != expected_cash_id:
            raise BenchmarkReferenceError("analysis declaration cash proxy does not match resolution")
        if self.declaration.peer_set_id != expected_peer_id:
            raise BenchmarkReferenceError("analysis declaration peer set does not match resolution")
        resolved_ids = tuple(item.portfolio_id for item in self.references)
        unavailable_ids = tuple(
            blocker.removeprefix("reference:unavailable:")
            for blocker in self.blockers
            if blocker.startswith("reference:unavailable:")
        )
        if (
            len(resolved_ids) != len(set(resolved_ids))
            or len(unavailable_ids) != len(set(unavailable_ids))
            or len(self.declaration.reference_portfolio_ids)
            != len(set(self.declaration.reference_portfolio_ids))
            or set(resolved_ids) & set(unavailable_ids)
            or set(self.declaration.reference_portfolio_ids)
            != set(resolved_ids) | set(unavailable_ids)
        ):
            raise BenchmarkReferenceError("analysis declaration references do not match resolution")

_CanonicalRecord = (
    BenchmarkDefinition
    | CashProxyDefinition
    | PeerSetDefinition
    | ReferencePortfolioDefinition
    | VwceAnchorEvidence
)


def _typed_payload(kind: object, content: dict[str, object]) -> _CanonicalRecord:
    fields: dict[str, frozenset[str]] = {
        "benchmark": frozenset({
            "benchmark_id", "version", "hierarchy", "selector", "currency",
            "minimum_horizon_years", "maximum_horizon_years", "effective_at", "known_at",
            "start_date", "end_date", "methodology", "constituents", "source_hashes",
            "status", "opportunity_anchor", "canonical_identity", "execution_allowed",
        }),
        "cash": frozenset({
            "proxy_id", "version", "selector", "currency", "minimum_horizon_years",
            "maximum_horizon_years", "effective_at", "known_at", "start_date", "end_date",
            "methodology", "source_hashes", "status", "execution_allowed",
        }),
        "peer": frozenset({
            "peer_set_id", "version", "hierarchy", "selector", "member_instrument_ids",
            "effective_at", "known_at", "methodology", "source_hashes", "status",
            "execution_allowed",
        }),
        "reference": frozenset({
            "portfolio_id", "version", "method", "constituent_instrument_ids", "methodology",
            "effective_at", "known_at", "current_weights", "currency", "minimum_horizon_years",
            "maximum_horizon_years", "start_date", "end_date", "execution_allowed",
            "source_hashes",
        }),
        "vwce_anchor": frozenset({
            "canonical_isin", "canonical_share_class_id", "official_facts_as_of", "benchmark_name",
            "benchmark_as_of", "fees", "fees_as_of", "tracking", "tracking_as_of",
            "product_risk_indicator", "risk_indicator_as_of", "currency", "source_hashes",
            "listing_observations", "effective_at", "known_at", "minimum_horizon_years",
            "maximum_horizon_years", "status", "execution_allowed",
        }),
    }
    if kind not in fields or set(content) != fields[kind]:
        raise BenchmarkReferenceError("registry record payload fields are invalid")
    value = dict(content)
    for field in ("constituents", "source_hashes", "member_instrument_ids", "constituent_instrument_ids"):
        if field in value:
            serialized_values = value[field]
            if not isinstance(serialized_values, list):
                raise BenchmarkReferenceError(f"{field} must be a serialized list")
            value[field] = tuple(serialized_values)
    if "selector" in value and not isinstance(value["selector"], dict):
        raise BenchmarkReferenceError("selector must be a serialized object")
    if "current_weights" in value and value["current_weights"] is not None and not isinstance(value["current_weights"], dict):
        raise BenchmarkReferenceError("current_weights must be a serialized object or null")
    if kind == "vwce_anchor":
        observations = value["listing_observations"]
        if not isinstance(observations, list):
            raise BenchmarkReferenceError("listing_observations must be a serialized list")
        typed_observations: list[VwceListingObservation] = []
        expected = {"listing_id", "ticker", "venue", "currency", "effective_at", "known_at", "source_hash", "status"}
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) != expected:
                raise BenchmarkReferenceError("VWCE listing observation is invalid")
            _assert_no_execution(observation)
            typed_observations.append(VwceListingObservation(**observation))
        value["listing_observations"] = tuple(typed_observations)
    if not isinstance(kind, str):
        raise BenchmarkReferenceError("registry record kind is unsupported")
    if kind == "benchmark":
        return BenchmarkDefinition(**value)  # type: ignore[arg-type]
    if kind == "cash":
        return CashProxyDefinition(**value)  # type: ignore[arg-type]
    if kind == "peer":
        return PeerSetDefinition(**value)  # type: ignore[arg-type]
    if kind == "reference":
        return ReferencePortfolioDefinition(**value)  # type: ignore[arg-type]
    return VwceAnchorEvidence(**value)  # type: ignore[arg-type]


@dataclass(frozen=True)
class VwceAnchorResolution:
    status: Literal["available", "unavailable", "ambiguous"]
    canonical_share_class_id: str | None
    listing_id: str | None
    reason: str | None
    observation_effective_at: str | None = None
    observation_known_at: str | None = None
    output_currency: str | None = None
    horizon_years: float | None = None
    anchor_digest: str | None = None
    conversion_digest: str | None = None
    execution_allowed: Literal[False] = False
    effective_date: str | None = None
    decision_time: str | None = None
    replay_digest: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"available", "unavailable", "ambiguous"}:
            raise BenchmarkReferenceError("anchor resolution status is unsupported")
        if self.execution_allowed is not False:
            raise BenchmarkReferenceError("anchor resolution cannot grant execution authority")


class CanonicalBenchmarkRegistry:
    """Immutable in-memory registry with deterministic point-in-time mapping."""

    __slots__ = (
        "benchmarks",
        "cash_proxies",
        "peer_sets",
        "reference_portfolios",
        "vwce_anchors",
        "_sealed",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("canonical benchmark registry is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        benchmarks: Sequence[BenchmarkDefinition] = (),
        cash_proxies: Sequence[CashProxyDefinition] = (),
        peer_sets: Sequence[PeerSetDefinition] = (),
        reference_portfolios: Sequence[ReferencePortfolioDefinition] = (),
        vwce_anchors: Sequence[VwceAnchorEvidence] = (),
    ) -> None:
        self.benchmarks = tuple(sorted(benchmarks, key=lambda item: (item.benchmark_id, _version_sort_key(item.version))))
        self.cash_proxies = tuple(sorted(cash_proxies, key=lambda item: (item.proxy_id, _version_sort_key(item.version))))
        self.peer_sets = tuple(sorted(peer_sets, key=lambda item: (item.peer_set_id, _version_sort_key(item.version))))
        self.reference_portfolios = tuple(sorted(reference_portfolios, key=lambda item: (item.portfolio_id, _version_sort_key(item.version))))
        self.vwce_anchors = tuple(sorted(vwce_anchors, key=lambda item: (
            item.canonical_share_class_id,
            _timestamp(item.known_at, "known_at"),
            _timestamp(item.effective_at, "effective_at"),
            item.digest(),
        )))
        self._check_unique((item.benchmark_id, item.version) for item in self.benchmarks)
        self._check_unique((item.proxy_id, item.version) for item in self.cash_proxies)
        self._check_unique((item.peer_set_id, item.version) for item in self.peer_sets)
        self._check_unique((item.portfolio_id, item.version) for item in self.reference_portfolios)
        self._check_unique(
            (
                item.canonical_isin,
                item.canonical_share_class_id,
                item.effective_at,
                item.known_at,
            )
            for item in self.vwce_anchors
        )
        self._validate_content_hashes(self.benchmarks)
        self._validate_content_hashes(self.cash_proxies)
        self._validate_content_hashes(self.peer_sets)
        self._validate_content_hashes(self.reference_portfolios)
        self._validate_content_hashes(self.vwce_anchors)
        object.__setattr__(self, "_sealed", True)

    @staticmethod
    def _check_unique(values: Iterable[tuple[str, ...]]) -> None:
        pairs = tuple(values)
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
        normalized_reference_ids = _reference_ids(reference_portfolio_ids)
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
            reference_portfolio_ids=normalized_reference_ids,
        )
        references: list[ReferencePortfolioDefinition] = []
        reference_blockers: set[str] = set()
        for reference_id in normalized_reference_ids:
            try:
                references.append(
                    self._reference(
                        reference_id,
                        currency=currency,
                        horizon=horizon_years,
                        start=start_date,
                        end=end_date,
                        cutoff=decision_time,
                    )
                )
            except BenchmarkReferenceError:
                reference_blockers.add(f"reference:unavailable:{reference_id}")
        blockers = tuple(sorted({f"{selection.kind}:{selection.reason}" for selection in (benchmark, cash, peer) if selection.status != "available" and selection.reason} | reference_blockers))
        return AnalysisResolution(declaration, benchmark, cash, peer, tuple(references), blockers)

    def ui_projection(
        self,
        resolution: AnalysisResolution,
        *,
        selected_vwce_anchor_digest: str | None = None,
    ) -> dict[str, object]:
        """Return a read-only comparison projection with explicit blockers."""

        resolution.validate_invariants()
        registry_hash = str(self.as_payload()["registry_hash"])
        if selected_vwce_anchor_digest is not None:
            anchor_matches = sum(
                anchor.digest() == selected_vwce_anchor_digest
                for anchor in self.vwce_anchors
            )
            if anchor_matches != 1:
                raise BenchmarkReferenceError("selected VWCE anchor is not uniquely bound to registry")

        def definition(selection: Selection) -> _HasCanonicalDigest | None:
            if selection.status != "available":
                return None
            collections: dict[str, Sequence[_HasCanonicalDigest]] = {
                "benchmark": self.benchmarks,
                "cash": self.cash_proxies,
                "peer": self.peer_sets,
            }
            matches = [
                item
                for item in collections[selection.kind]
                if _definition_id(item) == selection.selected_id
                and getattr(item, "version", None) == selection.version
                and item.digest() == selection.content_hash
            ]
            if len(matches) != 1:
                raise BenchmarkReferenceError(
                    f"selected {selection.kind} is not uniquely bound to registry"
                )
            return matches[0]

        def item(selection: Selection) -> dict[str, object]:
            selected = definition(selection)
            return {
                "status": selection.status,
                "display": selection.display_name,
                "id": selection.selected_id,
                "version": selection.version,
                "reason": selection.reason,
                "specificity": selection.specificity,
                "content_hash": None if selected is None else selected.digest(),
            }

        for reference in resolution.references:
            matches = [
                item
                for item in self.reference_portfolios
                if item.portfolio_id == reference.portfolio_id
                and item.version == reference.version
                and item.digest() == reference.digest()
            ]
            if len(matches) != 1:
                raise BenchmarkReferenceError(
                    "selected reference is not uniquely bound to registry"
                )

        selected_records: dict[str, object] = {
            "benchmark": item(resolution.benchmark)["content_hash"],
            "cash": item(resolution.cash)["content_hash"],
            "peer_set": item(resolution.peer_set)["content_hash"],
            "references": {
                f"{reference.portfolio_id}@{reference.version}": reference.digest()
                for reference in resolution.references
            },
        }
        if selected_vwce_anchor_digest is not None:
            selected_records["vwce_anchor"] = selected_vwce_anchor_digest

        return {
            "contract": CONTRACT,
            "analysis_id": resolution.declaration.analysis_id,
            "purpose": resolution.declaration.purpose,
            "benchmark": item(resolution.benchmark),
            "cash": item(resolution.cash),
            "peer_set": item(resolution.peer_set),
            "references": [
                {
                    "id": reference.portfolio_id,
                    "version": reference.version,
                    "method": reference.method,
                    "content_hash": reference.digest(),
                    "constituent_instrument_ids": list(reference.constituent_instrument_ids),
                    "current_weights": None if reference.current_weights is None else _thaw(reference.current_weights),
                    "effective_at": _timestamp(reference.effective_at, "effective_at").isoformat(),
                    "known_at": _timestamp(reference.known_at, "known_at").isoformat(),
                    "source_hashes": list(reference.source_hashes),
                }
                for reference in resolution.references
            ],
            "blockers": list(resolution.blockers),
            "registry_hash": registry_hash,
            "selected_records": selected_records,
            "provenance": {
                "registry_hash": registry_hash,
                "selected_records": selected_records,
                "selected_vwce_anchor_digest": selected_vwce_anchor_digest,
            },
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

        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"contract", "schema_version", "records", "execution_allowed", "registry_hash"}
            or payload.get("contract") != CONTRACT
            or payload.get("schema_version") != SCHEMA_VERSION
            or payload.get("execution_allowed") is not False
        ):
            raise BenchmarkReferenceError("registry envelope is invalid")
        records = payload.get("records")
        supplied = payload.get("registry_hash")
        unsigned = {key: payload[key] for key in payload if key != "registry_hash"}
        if not isinstance(records, list) or not isinstance(supplied, str) or supplied != _content_hash(unsigned):
            raise BenchmarkReferenceError("registry hash mismatch")
        typed_records: list[tuple[str, _CanonicalRecord]] = []
        for record in records:
            if not isinstance(record, dict) or set(record) != {"kind", "payload", "content_hash"}:
                raise BenchmarkReferenceError("registry record envelope is invalid")
            kind = record.get("kind")
            if kind not in {"benchmark", "cash", "peer", "reference", "vwce_anchor"}:
                raise BenchmarkReferenceError("registry record kind is unsupported")
            content = record.get("payload")
            content_hash = record.get("content_hash")
            if not isinstance(content, dict) or not isinstance(content_hash, str):
                raise BenchmarkReferenceError("registry record hash mismatch")
            _assert_no_execution(content)
            try:
                typed = _typed_payload(kind, content)
            except (BenchmarkReferenceError, TypeError, ValueError, KeyError, AttributeError) as exc:
                raise BenchmarkReferenceError("registry record payload is semantically invalid") from exc
            if typed.digest() != content_hash or typed.payload() != content:
                raise BenchmarkReferenceError("registry record payload is not canonical")
            typed_records.append((kind, typed))
        reconstructed = CanonicalBenchmarkRegistry(
            benchmarks=tuple(item for kind, item in typed_records if kind == "benchmark" and isinstance(item, BenchmarkDefinition)),
            cash_proxies=tuple(item for kind, item in typed_records if kind == "cash" and isinstance(item, CashProxyDefinition)),
            peer_sets=tuple(item for kind, item in typed_records if kind == "peer" and isinstance(item, PeerSetDefinition)),
            reference_portfolios=tuple(item for kind, item in typed_records if kind == "reference" and isinstance(item, ReferencePortfolioDefinition)),
            vwce_anchors=tuple(item for kind, item in typed_records if kind == "vwce_anchor" and isinstance(item, VwceAnchorEvidence)),
        )
        if reconstructed.as_payload() != dict(payload):
            raise BenchmarkReferenceError("registry payload is not canonical")
        return dict(payload)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> CanonicalBenchmarkRegistry:
        """Validate and semantically reconstruct one canonical registry envelope."""

        validated = cls.validate_payload(payload)
        records = validated["records"]
        if not isinstance(records, list):
            raise BenchmarkReferenceError("registry records are invalid")
        typed_records: list[tuple[str, _CanonicalRecord]] = []
        for record in records:
            if not isinstance(record, dict):
                raise BenchmarkReferenceError("registry record envelope is invalid")
            kind = record.get("kind")
            content = record.get("payload")
            if not isinstance(kind, str) or not isinstance(content, dict):
                raise BenchmarkReferenceError("registry record payload is invalid")
            typed_records.append((kind, _typed_payload(kind, content)))
        return cls(
            benchmarks=tuple(
                item for kind, item in typed_records
                if kind == "benchmark" and isinstance(item, BenchmarkDefinition)
            ),
            cash_proxies=tuple(
                item for kind, item in typed_records
                if kind == "cash" and isinstance(item, CashProxyDefinition)
            ),
            peer_sets=tuple(
                item for kind, item in typed_records
                if kind == "peer" and isinstance(item, PeerSetDefinition)
            ),
            reference_portfolios=tuple(
                item for kind, item in typed_records
                if kind == "reference" and isinstance(item, ReferencePortfolioDefinition)
            ),
            vwce_anchors=tuple(
                item for kind, item in typed_records
                if kind == "vwce_anchor" and isinstance(item, VwceAnchorEvidence)
            ),
        )
    def _select_benchmark(self, instrument: Mapping[str, object], currency: str, horizon: float, start: str, end: str, cutoff: str, version: str | None) -> Selection:
        candidates = [item for item in self.benchmarks if _selector_matches(item.selector, instrument) and (version is None or item.version == version)]
        candidates = [item for item in candidates if _pit(item.effective_at, item.known_at, start, cutoff)]
        if not candidates:
            return _unavailable("benchmark", "no_point_in_time_mapping")
        candidates = _best_by_id(candidates)
        if len(candidates) != 1:
            return Selection("benchmark", "ambiguous", None, None, "ambiguous_mapping", max(len(item.selector) for item in candidates))
        item = candidates[0]
        if item.status != "available":
            return _unavailable("benchmark", "benchmark_stale_or_unavailable")
        alignment_reason = _alignment_reason(item.currency, currency, item.minimum_horizon_years, item.maximum_horizon_years, horizon, item.start_date, item.end_date, start, end)
        if alignment_reason:
            return _unavailable("benchmark", alignment_reason)
        return Selection(
            "benchmark", "available", item.benchmark_id, item.version, None,
            len(item.selector), content_hash=item.digest(),
        )

    def _select_cash(self, instrument: Mapping[str, object], currency: str, horizon: float, start: str, end: str, cutoff: str, version: str | None) -> Selection:
        candidates = [item for item in self.cash_proxies if _selector_matches(item.selector, instrument) and (version is None or item.version == version)]
        candidates = [item for item in candidates if _pit(item.effective_at, item.known_at, start, cutoff)]
        if not candidates:
            return _unavailable("cash", "no_point_in_time_mapping")
        candidates = _best_by_id(candidates)
        if len(candidates) != 1:
            return Selection("cash", "ambiguous", None, None, "ambiguous_mapping", max(len(item.selector) for item in candidates))
        item = candidates[0]
        if item.status != "available":
            return _unavailable("cash", "cash_stale_or_unavailable")
        alignment_reason = _alignment_reason(item.currency, currency, item.minimum_horizon_years, item.maximum_horizon_years, horizon, item.start_date, item.end_date, start, end)
        if alignment_reason:
            return _unavailable("cash", alignment_reason)
        return Selection(
            "cash", "available", item.proxy_id, item.version, None,
            len(item.selector), content_hash=item.digest(),
        )

    def _select_peer(self, instrument: Mapping[str, object], start: str, cutoff: str, version: str | None) -> Selection:
        candidates = [item for item in self.peer_sets if _selector_matches(item.selector, instrument) and (version is None or item.version == version) and _pit(item.effective_at, item.known_at, start, cutoff)]
        if not candidates:
            return _unavailable("peer", "peer_set_unavailable")
        candidates = _best_by_id(candidates)
        if len(candidates) != 1:
            return Selection("peer", "ambiguous", None, None, "ambiguous_mapping", max(len(item.selector) for item in candidates))
        item = candidates[0]
        if item.status != "available":
            return _unavailable("peer", "peer_set_stale_or_unavailable")
        return Selection(
            "peer", "available", item.peer_set_id, item.version, None,
            len(item.selector), content_hash=item.digest(),
        )

    def _reference(
        self,
        reference_id: str,
        *,
        currency: str,
        horizon: float,
        start: str,
        end: str,
        cutoff: str,
    ) -> ReferencePortfolioDefinition:
        cutoff_time = _timestamp(cutoff, "decision_time")
        effective_cutoff = datetime.combine(
            _date(start, "start_date"), datetime.min.time(), tzinfo=timezone.utc
        )
        matches = [
            item
            for item in self.reference_portfolios
            if item.portfolio_id == reference_id
            and _timestamp(item.effective_at, "effective_at")
            <= (cutoff_time if item.method == "no_trade" else effective_cutoff)
            and _timestamp(item.known_at, "known_at") <= cutoff_time
        ]
        if not matches:
            raise BenchmarkReferenceError(f"reference portfolio is unavailable: {reference_id}")
        matches.sort(
            key=lambda item: (
                _timestamp(item.effective_at, "effective_at"),
                _version_sort_key(item.version),
            ),
            reverse=True,
        )
        authoritative = matches[0]
        if (
            authoritative.currency != currency
            or authoritative.minimum_horizon_years is None
            or authoritative.maximum_horizon_years is None
            or not authoritative.minimum_horizon_years <= horizon <= authoritative.maximum_horizon_years
            or authoritative.start_date is None
            or authoritative.end_date is None
            or _date(authoritative.start_date, "start_date") > _date(start, "start_date")
            or _date(authoritative.end_date, "end_date") < _date(end, "end_date")
        ):
            raise BenchmarkReferenceError(f"reference portfolio is unavailable: {reference_id}")
        return authoritative


def load_canonical_benchmark_registry(path: Path | None = None) -> CanonicalBenchmarkRegistry:
    """Load one durable local registry, rejecting duplicate keys and tampering."""

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise BenchmarkReferenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        text = (
            path.read_text(encoding="utf-8")
            if path is not None
            else resources.files("etf_cockpit.resources")
            .joinpath("benchmark_reference_registry.json")
            .read_text(encoding="utf-8")
        )
        raw = json.loads(text, object_pairs_hook=reject_duplicates)
    except BenchmarkReferenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ModuleNotFoundError) as exc:
        raise BenchmarkReferenceError("canonical registry is unavailable or malformed") from exc
    if not isinstance(raw, dict):
        raise BenchmarkReferenceError("canonical registry envelope must be a JSON object")
    try:
        return CanonicalBenchmarkRegistry.from_payload(raw)
    except BenchmarkReferenceError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise BenchmarkReferenceError("canonical registry is malformed or tampered") from exc


def _validate_period(currency: str, horizon: float, start: str, end: str, cutoff: str) -> None:
    if not re.fullmatch(r"[A-Z]{3}", currency) or currency != currency.upper():
        raise BenchmarkReferenceError("analysis currency must be an ISO-4217 code")
    validated_horizon = _horizon(horizon, "analysis horizon_years")
    if validated_horizon is None or validated_horizon <= 0:
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
    candidates = sorted(candidates, key=lambda item: (_timestamp(item.effective_at, "effective_at"), _version_sort_key(item.version)), reverse=True)
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
    currency: str | None = None,
    minimum_horizon_years: float | None = None,
    maximum_horizon_years: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    source_hashes: tuple[str, ...] = (),
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
            currency=currency,
            minimum_horizon_years=minimum_horizon_years,
            maximum_horizon_years=maximum_horizon_years,
            start_date=start_date,
            end_date=end_date,
            source_hashes=source_hashes,
        )
        for method in REFERENCE_METHODS
    )


def resolve_vwce_anchor(
    anchor: VwceAnchorEvidence,
    *,
    listing_id: str,
    effective_date: str,
    decision_time: str,
    currency: str | None = None,
    horizon_years: float | None = None,
    conversion_evidence: Mapping[str, object] | None = None,
) -> VwceAnchorResolution:
    """Resolve one listing to the canonical VWCE share class at two cutoffs."""

    anchor_digest = anchor.digest()
    canonical_share_class_id = anchor.canonical_share_class_id

    def unavailable(reason: str) -> VwceAnchorResolution:
        return VwceAnchorResolution(
            "unavailable",
            canonical_share_class_id,
            listing_id,
            reason,
            anchor_digest=anchor_digest,
        )

    effective_cutoff = _date(effective_date, "effective_date")
    cutoff = _timestamp(decision_time, "decision_time")
    if currency is None or not re.fullmatch(r"[A-Z]{3}", currency) or currency != currency.upper():
        return unavailable("currency_alignment_unavailable")
    try:
        validated_horizon = _horizon(horizon_years, "VWCE horizon_years")
    except BenchmarkReferenceError:
        return unavailable("horizon_alignment_unavailable")
    if validated_horizon is None or validated_horizon <= 0:
        return unavailable("horizon_alignment_unavailable")
    if anchor.status != "available" or _timestamp(anchor.known_at, "known_at") > cutoff:
        return unavailable("anchor_stale_or_unavailable")
    if not all(
        _nested_evidence_is_available(value)
        for value in (anchor.fees, anchor.tracking, anchor.product_risk_indicator)
    ):
        return unavailable("vwce_nested_evidence_unavailable")
    effective_cutoff_time = datetime.combine(effective_cutoff, datetime.min.time(), tzinfo=timezone.utc)
    if _timestamp(anchor.effective_at, "effective_at") > effective_cutoff_time:
        return unavailable("anchor_not_yet_effective")
    fact_dates = (
        anchor.official_facts_as_of,
        anchor.benchmark_as_of,
        anchor.fees_as_of,
        anchor.tracking_as_of,
        anchor.risk_indicator_as_of,
    )
    if any(_date(value, "VWCE fact date") > effective_cutoff or datetime.combine(_date(value, "VWCE fact date"), datetime.min.time(), tzinfo=timezone.utc) > cutoff for value in fact_dates):
        return unavailable("vwce_facts_unavailable_at_cutoff")
    if anchor.minimum_horizon_years is None or anchor.maximum_horizon_years is None or not anchor.minimum_horizon_years <= validated_horizon <= anchor.maximum_horizon_years:
        return unavailable("horizon_alignment_unavailable")
    matches = [
        item for item in anchor.listing_observations
        if item.listing_id == listing_id
        and _timestamp(item.effective_at, "effective_at") <= effective_cutoff_time
        and _timestamp(item.known_at, "known_at") <= cutoff
    ]
    if not matches:
        return unavailable("listing_unavailable_at_cutoff")
    latest_effective = max(_timestamp(item.effective_at, "effective_at") for item in matches)
    matches = [item for item in matches if _timestamp(item.effective_at, "effective_at") == latest_effective]
    latest_known = max(_timestamp(item.known_at, "known_at") for item in matches)
    matches = [item for item in matches if _timestamp(item.known_at, "known_at") == latest_known]
    if any(item.source_hash not in anchor.source_hashes for item in matches):
        return unavailable("listing_provenance_unavailable")
    if any(item.status != "available" for item in matches):
        return unavailable("listing_stale_or_unavailable")
    identities = {(item.ticker, item.venue, item.currency) for item in matches}
    if len(identities) > 1:
        return VwceAnchorResolution(
            "ambiguous",
            canonical_share_class_id,
            listing_id,
            "ambiguous_listing_observation",
            anchor_digest=anchor_digest,
        )
    selected = min(matches, key=lambda item: (item.ticker, item.venue, item.currency, item.source_hash))
    conversion_digest: str | None = None
    if selected.currency != currency:
        if not _conversion_is_available(
            conversion_evidence,
            from_currency=selected.currency,
            to_currency=currency,
            effective_cutoff=effective_cutoff_time,
            known_cutoff=cutoff,
        ):
            return unavailable("currency_alignment_unavailable")
        conversion_digest = _content_hash(conversion_evidence) if isinstance(conversion_evidence, Mapping) else None
    replay_fields = {
        "anchor_digest": anchor_digest,
        "listing_id": listing_id,
        "effective_date": effective_date,
        "decision_time": decision_time,
        "output_currency": currency,
        "horizon_years": validated_horizon,
        "conversion_digest": conversion_digest,
    }
    return VwceAnchorResolution(
        "available",
        canonical_share_class_id,
        listing_id,
        None,
        selected.effective_at,
        selected.known_at,
        currency,
        validated_horizon,
        anchor_digest,
        conversion_digest,
        False,
        effective_date,
        decision_time,
        _content_hash(replay_fields),
    )


def _conversion_is_available(
    evidence: Mapping[str, object] | None,
    *,
    from_currency: str,
    to_currency: str,
    effective_cutoff: datetime,
    known_cutoff: datetime,
) -> bool:
    if not isinstance(evidence, Mapping) or set(evidence) != {"from_currency", "to_currency", "effective_at", "known_at", "source_hash"}:
        return False
    source_hash = evidence.get("source_hash")
    try:
        conversion_effective = _timestamp(evidence.get("effective_at"), "conversion effective_at")
        conversion_known = _timestamp(evidence.get("known_at"), "conversion known_at")
        return (
            evidence.get("from_currency") == from_currency
            and evidence.get("to_currency") == to_currency
            and isinstance(source_hash, str)
            and _SHA256.fullmatch(source_hash.lower()) is not None
            and conversion_effective <= conversion_known
            and conversion_effective <= effective_cutoff
            and conversion_known <= known_cutoff
        )
    except (BenchmarkReferenceError, TypeError, AttributeError):
        return False


def project_profile_relative_analysis(
    raw_analysis: Mapping[str, object],
    anchor_resolution: VwceAnchorResolution,
    *,
    anchor: VwceAnchorEvidence | None = None,
    registry: CanonicalBenchmarkRegistry | None = None,
    conversion_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Block only profile-relative claims when the VWCE anchor is unavailable."""

    _assert_no_execution(raw_analysis)
    registry_anchor_bound = (
        anchor is not None
        and registry is not None
        and sum(item.digest() == anchor.digest() for item in registry.vwce_anchors) == 1
    )
    complete_available = registry_anchor_bound and _complete_available_anchor_resolution(
        anchor_resolution,
        anchor=anchor,
        conversion_evidence=conversion_evidence,
    )
    projected_status = "available" if complete_available else "unavailable"
    projected_reason = anchor_resolution.reason if anchor_resolution.reason else (
        None if complete_available else (
            "registry_anchor_membership_unavailable"
            if not registry_anchor_bound
            else "anchor_resolution_incomplete"
        )
    )
    anchor_projection = {
        "status": projected_status,
        "reason": projected_reason,
        "canonical_share_class_id": anchor_resolution.canonical_share_class_id,
        "listing_id": anchor_resolution.listing_id,
        "observation_effective_at": anchor_resolution.observation_effective_at,
        "observation_known_at": anchor_resolution.observation_known_at,
        "output_currency": anchor_resolution.output_currency,
        "horizon_years": anchor_resolution.horizon_years,
        "effective_date": anchor_resolution.effective_date,
        "knowledge_cutoff": anchor_resolution.decision_time,
        "anchor_digest": anchor_resolution.anchor_digest,
        "conversion_digest": anchor_resolution.conversion_digest,
        "replay_digest": anchor_resolution.replay_digest,
        "execution_allowed": False,
    }
    anchor_projection["resolution_digest"] = _content_hash(anchor_projection)
    result = {
        "contract": CONTRACT,
        "raw_analysis": deepcopy(dict(raw_analysis)),
        "profile_relative_status": projected_status,
        "profile_relative_claims_allowed": complete_available,
        "anchor_reason": projected_reason,
        "anchor_resolution": anchor_projection,
        "blockers": [] if complete_available else ["vwce_anchor_unavailable"],
        "execution_allowed": False,
    }
    _assert_no_execution(result)
    return result


def _complete_available_anchor_resolution(
    resolution: VwceAnchorResolution,
    *,
    anchor: VwceAnchorEvidence | None,
    conversion_evidence: Mapping[str, object] | None,
) -> bool:
    if (
        resolution.status != "available"
        or resolution.reason is not None
        or resolution.execution_allowed is not False
        or anchor is None
        or resolution.anchor_digest != anchor.digest()
        or resolution.canonical_share_class_id != anchor.canonical_share_class_id
    ):
        return False
    if (
        resolution.canonical_share_class_id != VWCE_CANONICAL_SHARE_CLASS
        or not isinstance(resolution.listing_id, str)
        or not resolution.listing_id.strip()
        or not isinstance(resolution.output_currency, str)
        or re.fullmatch(r"[A-Z]{3}", resolution.output_currency) is None
        or not isinstance(resolution.anchor_digest, str)
        or _SHA256.fullmatch(resolution.anchor_digest.lower()) is None
    ):
        return False
    try:
        effective = _timestamp(resolution.observation_effective_at, "observation_effective_at")
        known = _timestamp(resolution.observation_known_at, "observation_known_at")
        horizon = _horizon(resolution.horizon_years, "horizon_years")
    except BenchmarkReferenceError:
        return False
    if effective > known or horizon is None or horizon <= 0:
        return False
    if resolution.conversion_digest is None:
        if conversion_evidence is not None:
            return False
    elif not (
        isinstance(resolution.conversion_digest, str)
        and _SHA256.fullmatch(resolution.conversion_digest.lower()) is not None
        and isinstance(conversion_evidence, Mapping)
        and resolution.conversion_digest == _content_hash(conversion_evidence)
    ):
        return False
    if (
        not isinstance(resolution.effective_date, str)
        or not isinstance(resolution.decision_time, str)
        or not isinstance(resolution.replay_digest, str)
        or _SHA256.fullmatch(resolution.replay_digest.lower()) is None
    ):
        return False
    replay_fields = {
        "anchor_digest": resolution.anchor_digest,
        "listing_id": resolution.listing_id,
        "effective_date": resolution.effective_date,
        "decision_time": resolution.decision_time,
        "output_currency": resolution.output_currency,
        "horizon_years": horizon,
        "conversion_digest": resolution.conversion_digest,
    }
    if resolution.replay_digest != _content_hash(replay_fields):
        return False
    try:
        replayed = resolve_vwce_anchor(
            anchor,
            listing_id=resolution.listing_id,
            effective_date=resolution.effective_date,
            decision_time=resolution.decision_time,
            currency=resolution.output_currency,
            horizon_years=horizon,
            conversion_evidence=conversion_evidence,
        )
    except (BenchmarkReferenceError, TypeError, ValueError):
        return False
    return replayed == resolution


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
    "load_canonical_benchmark_registry",
    "project_profile_relative_analysis",
    "resolve_vwce_anchor",
]
