"""Point-in-time benchmark-relative return attribution diagnostics.

The report consumes supplied evidence.  It does not infer causality, prices,
FX conversion, recommendations, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping

MODEL_VERSION = "benchmark-relative-diagnostics-v1"
DIMENSIONS = (
    "instrument",
    "look_through",
    "sector_theme",
    "country",
    "currency_fx",
    "factor",
)
_ALL_DIMENSIONS = frozenset((*DIMENSIONS, "residual"))
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_AUTHORITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_TOLERANCE = 1e-12


class BenchmarkDiagnosticsError(ValueError):
    """Raised when supplied attribution evidence violates the report contract."""


@dataclass(frozen=True, slots=True)
class ReturnObservation:
    metric: Literal["adjusted_return", "total_return"]
    subject_kind: Literal["portfolio", "benchmark"]
    subject_id: str
    currency: str
    frequency: str
    horizon: str
    start_at: str
    end_at: str
    effective_at: str
    known_at: str
    value: float
    source_authority: str
    source_id: str
    source_checksum: str
    coverage: float = 1.0
    revision: int = 0


@dataclass(frozen=True, slots=True)
class AttributionEvidence:
    metric: Literal["relative_return_contribution"]
    dimension: str
    bucket: str
    portfolio_id: str
    benchmark_id: str
    currency: str
    frequency: str
    horizon: str
    start_at: str
    end_at: str
    effective_at: str
    known_at: str
    contribution: float
    source_authority: str
    source_id: str
    source_checksum: str
    coverage: float
    revision: int = 0
    lineage: Literal["direct", "indirect"] = "direct"
    parent_bucket: str | None = None
    unresolved_weight: float = 0.0
    uncertainty: str = ""
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Contribution:
    dimension: str
    bucket: str
    contribution: float
    coverage: float
    lineage: str
    parent_bucket: str | None
    unresolved_weight: float
    uncertainty: str
    limitations: tuple[str, ...]
    effective_at: str
    known_at: str
    revision: int
    source_authority: str
    source_id: str
    source_checksum: str


@dataclass(frozen=True, slots=True)
class DimensionDiagnostic:
    dimension: str
    status: Literal["available", "partial", "unavailable"]
    coverage: float
    unresolved_weight: float
    contributions: tuple[Contribution, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkRelativeReport:
    model_version: str
    status: Literal["available", "partial", "unavailable"]
    portfolio_id: str
    benchmark_id: str
    currency: str
    frequency: str
    horizon: str
    start_at: str
    end_at: str
    cutoff_at: str
    portfolio_return: float
    benchmark_return: float
    relative_return: float
    component_sum: float
    residual: float | None
    reconciliation_gap: float
    reconciliation_tolerance: float
    dimensions: tuple[DimensionDiagnostic, ...]
    coverage: float
    confidence: Literal["high", "limited", "unavailable"]
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]
    source_evidence: tuple[Mapping[str, object], ...]
    execution_allowed: Literal[False]
    report_hash: str


def build_benchmark_relative_report(
    *,
    portfolio_id: str,
    benchmark_id: str,
    cutoff_at: str,
    returns: Iterable[ReturnObservation],
    evidence: Iterable[AttributionEvidence],
    tolerance: float = _TOLERANCE,
) -> BenchmarkRelativeReport:
    """Build a deterministic read-only report from point-in-time evidence."""

    portfolio_id = _text(portfolio_id, "portfolio_id")
    benchmark_id = _text(benchmark_id, "benchmark_id")
    if portfolio_id == benchmark_id:
        raise BenchmarkDiagnosticsError("portfolio_id and benchmark_id must differ")
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    tolerance = _number(tolerance, "tolerance")
    if tolerance <= 0 or tolerance > 1e-8:
        raise BenchmarkDiagnosticsError(
            "tolerance must be positive and no greater than 1e-8"
        )

    selected_returns = _select_returns(
        tuple(returns), portfolio_id, benchmark_id, cutoff
    )
    portfolio = selected_returns["portfolio"]
    benchmark = selected_returns["benchmark"]
    _aligned_returns(portfolio, benchmark)

    selected = _select_evidence(
        tuple(evidence),
        portfolio_id=portfolio_id,
        benchmark_id=benchmark_id,
        cutoff=cutoff,
        template=portfolio,
    )

    relative_return = portfolio.value - benchmark.value
    residual_rows = [row for row in selected if row.dimension == "residual"]
    if len(residual_rows) > 1:
        raise BenchmarkDiagnosticsError(
            "exactly one residual contribution is permitted"
        )
    residual = residual_rows[0].contribution if residual_rows else None
    component_sum = math.fsum(
        row.contribution for row in selected if row.dimension != "residual"
    )
    reconciliation_gap = relative_return - component_sum - (residual or 0.0)

    diagnostics: list[DimensionDiagnostic] = []
    limitations: list[str] = ["attribution_is_supplied_evidence_not_causal_truth"]
    uncertainties: set[str] = set()
    for dimension in DIMENSIONS:
        rows = sorted(
            (row for row in selected if row.dimension == dimension),
            key=lambda row: (
                row.bucket.casefold(),
                row.source_authority,
                row.source_id,
            ),
        )
        contributions = tuple(_contribution(row) for row in rows)
        if not rows:
            status: Literal["available", "partial", "unavailable"] = "unavailable"
            coverage = 0.0
            unresolved = 0.0
            dimension_limits = (f"{dimension}_evidence_unavailable",)
            limitations.extend(dimension_limits)
        else:
            coverage = min(row.coverage for row in rows)
            unresolved = math.fsum(row.unresolved_weight for row in rows)
            partial = (
                coverage < 1.0
                or unresolved > tolerance
                or any(row.limitations for row in rows)
            )
            status = "partial" if partial else "available"
            dimension_limits = tuple(
                sorted({item for row in rows for item in row.limitations})
            )
            if partial:
                limitations.append(f"{dimension}_coverage_partial")
            uncertainties.update(row.uncertainty for row in rows if row.uncertainty)
        diagnostics.append(
            DimensionDiagnostic(
                dimension=dimension,
                status=status,
                coverage=coverage,
                unresolved_weight=unresolved,
                contributions=contributions,
                limitations=dimension_limits,
            )
        )

    reconciled = abs(reconciliation_gap) <= tolerance
    if not reconciled:
        limitations.append("contributions_do_not_reconcile")
    missing = any(item.status == "unavailable" for item in diagnostics)
    partial = (
        missing
        or any(item.status == "partial" for item in diagnostics)
        or not reconciled
        or residual is None
    )
    if residual is None:
        limitations.append("explicit_residual_unavailable")
    status = "partial" if partial else "available"
    coverage = math.fsum(item.coverage for item in diagnostics) / len(DIMENSIONS)
    confidence: Literal["high", "limited", "unavailable"] = (
        "high" if status == "available" else "limited"
    )

    source_evidence = tuple(
        MappingProxyType(
            {
                "metric": row.metric,
                "dimension": row.dimension,
                "bucket": row.bucket,
                "portfolio_id": row.portfolio_id,
                "benchmark_id": row.benchmark_id,
                "currency": row.currency,
                "horizon": row.horizon,
                "start_at": row.start_at,
                "end_at": row.end_at,
                "effective_at": row.effective_at,
                "known_at": row.known_at,
                "source_authority": row.source_authority,
                "source_id": row.source_id,
                "source_checksum": row.source_checksum,
                "coverage": row.coverage,
            }
        )
        for row in sorted(selected, key=_evidence_order)
    )
    report = BenchmarkRelativeReport(
        model_version=MODEL_VERSION,
        status=status,
        portfolio_id=portfolio_id,
        benchmark_id=benchmark_id,
        currency=portfolio.currency,
        frequency=portfolio.frequency,
        horizon=portfolio.horizon,
        start_at=portfolio.start_at,
        end_at=portfolio.end_at,
        cutoff_at=_iso(cutoff),
        portfolio_return=portfolio.value,
        benchmark_return=benchmark.value,
        relative_return=relative_return,
        component_sum=component_sum,
        residual=residual,
        reconciliation_gap=reconciliation_gap,
        reconciliation_tolerance=tolerance,
        dimensions=tuple(diagnostics),
        coverage=coverage,
        confidence=confidence,
        uncertainty=tuple(sorted(uncertainties)),
        limitations=tuple(sorted(set(limitations))),
        source_evidence=source_evidence,
        execution_allowed=False,
        report_hash="",
    )
    return replace(report, report_hash=canonical_report_hash(report))


def canonical_report_hash(report: BenchmarkRelativeReport) -> str:
    payload = _plain(report)
    payload["report_hash"] = ""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_benchmark_relative_report(report: BenchmarkRelativeReport) -> bool:
    """Strictly verify nested structure, authority, identity, arithmetic and hash."""

    if not isinstance(report, BenchmarkRelativeReport):
        raise BenchmarkDiagnosticsError("report must be a BenchmarkRelativeReport")
    if report.execution_allowed is not False or report.model_version != MODEL_VERSION:
        raise BenchmarkDiagnosticsError("unsafe report authority or model version")
    _text(report.portfolio_id, "portfolio_id")
    _text(report.benchmark_id, "benchmark_id")
    if report.portfolio_id == report.benchmark_id:
        raise BenchmarkDiagnosticsError("report identities conflict")
    for name in (
        "portfolio_return",
        "benchmark_return",
        "relative_return",
        "component_sum",
        "reconciliation_gap",
        "reconciliation_tolerance",
        "coverage",
    ):
        _number(getattr(report, name), name)
    if report.residual is not None:
        _number(report.residual, "residual")
    if report.relative_return != report.portfolio_return - report.benchmark_return:
        raise BenchmarkDiagnosticsError("relative return identity failed")
    expected_gap = (
        report.relative_return - report.component_sum - (report.residual or 0.0)
    )
    if not math.isclose(
        report.reconciliation_gap, expected_gap, rel_tol=0.0, abs_tol=1e-15
    ):
        raise BenchmarkDiagnosticsError("reconciliation identity failed")
    if tuple(item.dimension for item in report.dimensions) != DIMENSIONS:
        raise BenchmarkDiagnosticsError("dimension structure is malformed")
    contribution_sum = 0.0
    for dimension in report.dimensions:
        if not isinstance(dimension, DimensionDiagnostic):
            raise BenchmarkDiagnosticsError("nested dimension is malformed")
        for item in dimension.contributions:
            if (
                not isinstance(item, Contribution)
                or item.dimension != dimension.dimension
            ):
                raise BenchmarkDiagnosticsError("nested contribution is malformed")
            _authority(item.source_authority, "source_authority")
            _text(item.source_id, "source_id")
            _checksum(item.source_checksum)
            _number(item.contribution, "contribution")
            _proportion(item.coverage, "coverage")
            _proportion(item.unresolved_weight, "unresolved_weight")
            contribution_sum += item.contribution
    if not math.isclose(
        contribution_sum, report.component_sum, rel_tol=0.0, abs_tol=1e-15
    ):
        raise BenchmarkDiagnosticsError(
            "component sum does not match nested contributions"
        )
    for source in report.source_evidence:
        if not isinstance(source, Mapping):
            raise BenchmarkDiagnosticsError("nested source evidence is malformed")
        if (
            source.get("portfolio_id") != report.portfolio_id
            or source.get("benchmark_id") != report.benchmark_id
        ):
            raise BenchmarkDiagnosticsError("nested source identity mismatch")
        _authority(source.get("source_authority"), "source_authority")
        _checksum(source.get("source_checksum"))
    if (
        not _SHA256.fullmatch(report.report_hash)
        or canonical_report_hash(report) != report.report_hash
    ):
        raise BenchmarkDiagnosticsError("report hash verification failed")
    return True


def _select_returns(
    rows: tuple[ReturnObservation, ...],
    portfolio_id: str,
    benchmark_id: str,
    cutoff: datetime,
) -> dict[str, ReturnObservation]:
    wanted = {"portfolio": portfolio_id, "benchmark": benchmark_id}
    selected: dict[str, ReturnObservation] = {}
    for kind, subject_id in wanted.items():
        candidates = []
        for row in rows:
            _validate_return(row)
            if row.subject_kind == kind and row.subject_id == subject_id:
                if (
                    _timestamp(row.known_at, "known_at") <= cutoff
                    and _timestamp(row.effective_at, "effective_at") <= cutoff
                ):
                    candidates.append(row)
        if not candidates:
            raise BenchmarkDiagnosticsError(
                f"{kind} adjusted/total-return evidence is unavailable at cutoff"
            )
        selected[kind] = _latest(candidates, _return_identity)
    return selected


def _select_evidence(
    rows: tuple[AttributionEvidence, ...],
    *,
    portfolio_id: str,
    benchmark_id: str,
    cutoff: datetime,
    template: ReturnObservation,
) -> tuple[AttributionEvidence, ...]:
    grouped: dict[
        tuple[str, str, str, str, str, str, str, str, str, str],
        list[AttributionEvidence],
    ] = {}
    for row in rows:
        _validate_evidence(row)
        if row.portfolio_id != portfolio_id or row.benchmark_id != benchmark_id:
            raise BenchmarkDiagnosticsError("attribution evidence identity mismatch")
        if (
            row.horizon != template.horizon
            or row.frequency != template.frequency
            or row.start_at != template.start_at
            or row.end_at != template.end_at
        ):
            raise BenchmarkDiagnosticsError(
                "attribution evidence horizon/frequency mismatch"
            )
        if row.currency != template.currency and row.dimension != "currency_fx":
            raise BenchmarkDiagnosticsError("attribution evidence currency mismatch")
        if (
            _timestamp(row.known_at, "known_at") > cutoff
            or _timestamp(row.effective_at, "effective_at") > cutoff
        ):
            continue
        key = (
            row.metric,
            row.dimension,
            row.bucket,
            row.portfolio_id,
            row.benchmark_id,
            row.currency,
            row.frequency,
            row.horizon,
            row.start_at,
            row.end_at,
        )
        grouped.setdefault(key, []).append(row)
    return tuple(_latest(group, _evidence_identity) for group in grouped.values())


def _latest(rows: list[Any], identity: Any) -> Any:
    latest_effective = max(_timestamp(row.effective_at, "effective_at") for row in rows)
    period = [
        row
        for row in rows
        if _timestamp(row.effective_at, "effective_at") == latest_effective
    ]
    latest_known = max(_timestamp(row.known_at, "known_at") for row in period)
    vintage = [
        row for row in period if _timestamp(row.known_at, "known_at") == latest_known
    ]
    revision = max(row.revision for row in vintage)
    finalists = [row for row in vintage if row.revision == revision]
    identities = {identity(row) for row in finalists}
    if len(identities) != 1:
        raise BenchmarkDiagnosticsError(
            "conflicting evidence at the same effective/known/revision vintage"
        )
    return sorted(
        finalists,
        key=lambda row: (row.source_authority, row.source_id, row.source_checksum),
    )[0]


def _aligned_returns(
    portfolio: ReturnObservation, benchmark: ReturnObservation
) -> None:
    if portfolio.metric not in {
        "adjusted_return",
        "total_return",
    } or benchmark.metric not in {
        "adjusted_return",
        "total_return",
    }:
        raise BenchmarkDiagnosticsError("raw-close return inference is forbidden")
    if portfolio.currency != benchmark.currency:
        raise BenchmarkDiagnosticsError(
            "portfolio and benchmark returns require the same measurement currency"
        )
    fields = ("frequency", "horizon", "start_at", "end_at")
    if any(getattr(portfolio, field) != getattr(benchmark, field) for field in fields):
        raise BenchmarkDiagnosticsError(
            "portfolio and benchmark returns require the identical dated horizon"
        )


def _validate_return(row: ReturnObservation) -> None:
    if not isinstance(row, ReturnObservation):
        raise BenchmarkDiagnosticsError(
            "returns must contain ReturnObservation instances"
        )
    _text(row.subject_id, "subject_id")
    _text(row.currency, "currency")
    _text(row.frequency, "frequency")
    _text(row.horizon, "horizon")
    _chronology(row.start_at, row.end_at, row.effective_at, row.known_at)
    _number(row.value, "value")
    _proportion(row.coverage, "coverage")
    _revision(row.revision)
    _authority(row.source_authority, "source_authority")
    _text(row.source_id, "source_id")
    _checksum(row.source_checksum)


def _validate_evidence(row: AttributionEvidence) -> None:
    if not isinstance(row, AttributionEvidence):
        raise BenchmarkDiagnosticsError(
            "evidence must contain AttributionEvidence instances"
        )
    if (
        row.metric != "relative_return_contribution"
        or row.dimension not in _ALL_DIMENSIONS
    ):
        raise BenchmarkDiagnosticsError("unsupported evidence metric or dimension")
    for value, name in (
        (row.bucket, "bucket"),
        (row.portfolio_id, "portfolio_id"),
        (row.benchmark_id, "benchmark_id"),
        (row.currency, "currency"),
        (row.frequency, "frequency"),
        (row.horizon, "horizon"),
        (row.source_id, "source_id"),
    ):
        _text(value, name)
    _chronology(row.start_at, row.end_at, row.effective_at, row.known_at)
    _number(row.contribution, "contribution")
    _proportion(row.coverage, "coverage")
    _proportion(row.unresolved_weight, "unresolved_weight")
    _revision(row.revision)
    _authority(row.source_authority, "source_authority")
    _checksum(row.source_checksum)
    if row.dimension == "look_through" and row.lineage not in {"direct", "indirect"}:
        raise BenchmarkDiagnosticsError(
            "look-through lineage must be direct or indirect"
        )
    if row.dimension != "look_through" and (
        row.parent_bucket is not None or row.unresolved_weight
    ):
        raise BenchmarkDiagnosticsError(
            "look-through lineage fields are restricted to look_through evidence"
        )
    if not isinstance(row.limitations, tuple) or any(
        not isinstance(item, str) or not item for item in row.limitations
    ):
        raise BenchmarkDiagnosticsError(
            "limitations must be non-empty strings in a tuple"
        )


def _chronology(start: str, end: str, effective: str, known: str) -> None:
    start_at = _timestamp(start, "start_at")
    end_at = _timestamp(end, "end_at")
    effective_at = _timestamp(effective, "effective_at")
    known_at = _timestamp(known, "known_at")
    if start_at >= end_at:
        raise BenchmarkDiagnosticsError("start_at must precede end_at")
    if end_at > effective_at:
        raise BenchmarkDiagnosticsError("effective_at cannot precede end_at")
    if effective_at > known_at:
        raise BenchmarkDiagnosticsError("known_at cannot precede effective_at")


def _return_identity(row: ReturnObservation) -> tuple[object, ...]:
    return (
        row.metric,
        row.value,
        row.currency,
        row.source_authority,
        row.source_id,
        row.source_checksum,
        row.coverage,
    )


def _evidence_identity(row: AttributionEvidence) -> tuple[object, ...]:
    return (
        row.contribution,
        row.coverage,
        row.lineage,
        row.parent_bucket,
        row.unresolved_weight,
        row.uncertainty,
        row.limitations,
        row.source_authority,
        row.source_id,
        row.source_checksum,
    )


def _evidence_order(row: AttributionEvidence) -> tuple[object, ...]:
    return (
        row.dimension,
        row.bucket.casefold(),
        row.effective_at,
        row.known_at,
        row.revision,
        row.source_id,
    )


def _contribution(row: AttributionEvidence) -> Contribution:
    return Contribution(
        dimension=row.dimension,
        bucket=row.bucket,
        contribution=row.contribution,
        coverage=row.coverage,
        lineage=row.lineage,
        parent_bucket=row.parent_bucket,
        unresolved_weight=row.unresolved_weight,
        uncertainty=row.uncertainty,
        limitations=row.limitations,
        effective_at=row.effective_at,
        known_at=row.known_at,
        revision=row.revision,
        source_authority=row.source_authority,
        source_id=row.source_id,
        source_checksum=row.source_checksum,
    )


def _plain(value: object) -> dict[str, Any]:
    result = _json_value(value)
    if not isinstance(result, dict):
        raise BenchmarkDiagnosticsError("report payload is malformed")
    return result


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkDiagnosticsError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkDiagnosticsError(
            f"{name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise BenchmarkDiagnosticsError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise BenchmarkDiagnosticsError(f"{name} must be a non-empty safe string")
    return value.strip()


def _authority(value: object, name: str) -> str:
    text = _text(value, name)
    if not _SAFE_AUTHORITY.fullmatch(text) or ".." in text or "://" in text:
        raise BenchmarkDiagnosticsError(f"{name} is unsafe")
    return text


def _checksum(value: object) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise BenchmarkDiagnosticsError(
            "source_checksum must be a lowercase SHA-256 digest"
        )
    return value


def _number(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise BenchmarkDiagnosticsError(f"{name} must be a finite non-boolean number")
    return float(value)


def _proportion(value: object, name: str) -> float:
    number = _number(value, name)
    if not 0.0 <= number <= 1.0:
        raise BenchmarkDiagnosticsError(f"{name} must be between 0 and 1")
    return number


def _revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BenchmarkDiagnosticsError("revision must be a non-negative integer")
    return value


__all__ = [
    "AttributionEvidence",
    "BenchmarkDiagnosticsError",
    "BenchmarkRelativeReport",
    "Contribution",
    "DimensionDiagnostic",
    "MODEL_VERSION",
    "ReturnObservation",
    "build_benchmark_relative_report",
    "canonical_report_hash",
    "verify_benchmark_relative_report",
]
