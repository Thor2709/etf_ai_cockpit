"""Typed, local-only ETF economics evidence and point-in-time analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from etf_cockpit.core.paths import (
    ETF_CLOSURE_POLICY_PATH,
    ETF_ECONOMICS_PATH,
    ETF_FUND_TOTAL_RETURN_PATH,
    ETF_BENCHMARK_TOTAL_RETURN_PATH,
)


ETF_ECONOMICS_MODEL_ID = "etf-economics-analysis-v2"
_BUSINESS_DAILY = "business_daily"
_SUPPORTED_FEE_UNITS = {"decimal_fraction", "percent"}
_CURRENCY_AMOUNT_UNIT = "currency_units"
_SUPPORTED_TOTAL_RETURN_CONVENTIONS = {
    "reinvest_on_ex_date",
    "cash_on_payable_date",
    "price_plus_reinvested_income",
    "split_adjusted",
}


class EtfEconomicsError(ValueError):
    """Raised when local ETF economics evidence cannot be used safely."""


def _missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().casefold() in {"", "nan", "nat", "none", "<na>"}:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(result, bool) and result


def _text(value: object) -> str | None:
    if _missing(value):
        return None
    result = str(value).strip()
    return result or None


def _timestamp(value: object, field_name: str, *, required: bool = False) -> str | None:
    if _missing(value):
        if required:
            raise EtfEconomicsError(f"{field_name} is required")
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True, format="mixed")
    if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
        raise EtfEconomicsError(f"{field_name} must be an ISO date or timestamp")
    return parsed.isoformat().replace("+00:00", "Z")


def _number(value: object, field_name: str, *, minimum: float | None = None) -> float | None:
    if _missing(value):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EtfEconomicsError(f"{field_name} must be numeric") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise EtfEconomicsError(f"{field_name} is outside its allowed range")
    return result


def _currency(value: object, field_name: str, *, required: bool = False) -> str | None:
    result = _text(value)
    if result is None:
        if required:
            raise EtfEconomicsError(f"{field_name} is required")
        return None
    result = result.upper()
    if len(result) != 3 or not result.isalpha():
        raise EtfEconomicsError(f"{field_name} must be a three-letter currency")
    return result


def _as_record(value: object) -> "EtfEconomicsObservation":
    if isinstance(value, EtfEconomicsObservation):
        return value
    if isinstance(value, Mapping):
        return EtfEconomicsObservation.from_mapping(value)
    raise EtfEconomicsError("ETF economics records must be mappings or EtfEconomicsObservation values")


def _normalise_fee(value: object, field_name: str, unit: str | None) -> float | None:
    parsed = _number(value, field_name, minimum=0.0)
    if parsed is None:
        return None
    if unit not in _SUPPORTED_FEE_UNITS:
        raise EtfEconomicsError(f"{field_name} requires fee_unit=decimal_fraction or fee_unit=percent")
    return parsed / 100.0 if unit == "percent" else parsed


@dataclass(frozen=True)
class EtfEconomicsObservation:
    """One effective-dated fund or share-class economics revision."""

    instrument_id: str
    as_of: str
    known_at: str | None = None
    scope: str = "fund"
    share_class_id: str | None = None
    currency: str | None = None
    benchmark_id: str | None = None
    benchmark_name: str | None = None
    benchmark_currency: str | None = None
    ter: float | None = None
    ocf: float | None = None
    fee_unit: str | None = None
    ter_unit: str | None = None
    ocf_unit: str | None = None
    tracking_difference: float | None = None
    tracking_error: float | None = None
    aum: float | None = None
    aum_unit: str | None = None
    flows: float | None = None
    flows_unit: str | None = None
    flow_period_days: int | None = None
    inception_date: str | None = None
    share_class_structure: str | None = None
    distribution_frequency: str | None = None
    distribution_amount: float | None = None
    distributions: tuple[float, ...] = ()
    document_id: str | None = None
    document_date: str | None = None
    document_page: str | None = None
    revision_id: str | None = None
    source_id: str | None = None
    source_provenance: str | None = None
    source_checksum: str | None = None
    confidence: str | None = None
    benchmark_source_id: str | None = None
    benchmark_source_provenance: str | None = None
    benchmark_source_checksum: str | None = None
    execution_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        instrument_id = _text(self.instrument_id)
        if instrument_id is None:
            raise EtfEconomicsError("instrument_id is required")
        object.__setattr__(self, "instrument_id", instrument_id)
        effective_as_of = _timestamp(self.as_of, "as_of", required=True) or ""
        known_at = _timestamp(self.known_at, "known_at", required=True) or ""
        if pd.Timestamp(known_at) < pd.Timestamp(effective_as_of):
            raise EtfEconomicsError("known_at cannot precede as_of")
        object.__setattr__(self, "as_of", effective_as_of)
        object.__setattr__(self, "known_at", known_at)
        scope = (_text(self.scope) or "fund").casefold()
        if scope not in {"fund", "share_class"}:
            raise EtfEconomicsError("scope must be fund or share_class")
        share_class_id = _text(self.share_class_id)
        if scope == "share_class" and share_class_id is None:
            raise EtfEconomicsError("share_class_id is required for share-class observations")
        if scope == "fund" and share_class_id is not None:
            raise EtfEconomicsError("fund observations cannot carry share_class_id")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "share_class_id", share_class_id)
        object.__setattr__(self, "currency", _currency(self.currency, "currency"))
        object.__setattr__(self, "benchmark_id", _text(self.benchmark_id))
        object.__setattr__(self, "benchmark_name", _text(self.benchmark_name))
        object.__setattr__(self, "benchmark_currency", _currency(self.benchmark_currency, "benchmark_currency"))

        units = {_text(value).casefold() for value in (self.fee_unit, self.ter_unit, self.ocf_unit) if _text(value) is not None}
        if len(units) > 1:
            raise EtfEconomicsError("TER and OCF fee units must agree")
        fee_unit = next(iter(units), None)
        if fee_unit not in _SUPPORTED_FEE_UNITS and (not _missing(self.ter) or not _missing(self.ocf)):
            raise EtfEconomicsError("fees require explicit fee_unit=decimal_fraction or fee_unit=percent")
        object.__setattr__(self, "fee_unit", fee_unit)
        object.__setattr__(self, "ter", _normalise_fee(self.ter, "ter", fee_unit))
        object.__setattr__(self, "ocf", _normalise_fee(self.ocf, "ocf", fee_unit))

        for field_name, minimum in (("aum", 0.0), ("distribution_amount", 0.0)):
            object.__setattr__(self, field_name, _number(getattr(self, field_name), field_name, minimum=minimum))
        object.__setattr__(self, "flows", _number(self.flows, "flows"))
        for value_field, unit_field in (("aum", "aum_unit"), ("flows", "flows_unit")):
            unit = _text(getattr(self, unit_field))
            if getattr(self, value_field) is not None and unit != _CURRENCY_AMOUNT_UNIT:
                raise EtfEconomicsError(f"{value_field} requires explicit {unit_field}=currency_units")
            if unit not in {None, _CURRENCY_AMOUNT_UNIT}:
                raise EtfEconomicsError(f"{unit_field} must be currency_units")
            object.__setattr__(self, unit_field, unit)
        flow_period = _number(self.flow_period_days, "flow_period_days", minimum=1.0)
        object.__setattr__(self, "flow_period_days", int(flow_period) if flow_period is not None else None)
        object.__setattr__(self, "tracking_difference", _number(self.tracking_difference, "tracking_difference"))
        object.__setattr__(self, "tracking_error", _number(self.tracking_error, "tracking_error", minimum=0.0))
        distribution_values: list[float] = []
        if not _missing(self.distributions):
            if isinstance(self.distributions, (str, bytes)) or not isinstance(self.distributions, Sequence):
                raise EtfEconomicsError("distributions must be a sequence of non-negative numbers")
            for item in self.distributions:
                parsed = _number(item, "distributions", minimum=0.0)
                if parsed is not None:
                    distribution_values.append(parsed)
        object.__setattr__(self, "distributions", tuple(distribution_values))
        object.__setattr__(self, "inception_date", _timestamp(self.inception_date, "inception_date"))
        document_date = _timestamp(self.document_date, "document_date")
        if document_date is not None and pd.Timestamp(document_date) > pd.Timestamp(known_at):
            raise EtfEconomicsError("document_date cannot be later than known_at")
        object.__setattr__(self, "document_date", document_date)
        for field_name in (
            "share_class_structure", "distribution_frequency", "document_id", "document_page", "revision_id",
            "source_id", "source_provenance", "source_checksum", "confidence", "benchmark_source_id",
            "benchmark_source_provenance", "benchmark_source_checksum",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "EtfEconomicsObservation":
        aliases = {
            "flow": "flows",
            "flow_period": "flow_period_days",
            "share_class": "share_class_id",
            "document_page_number": "document_page",
            "document_revision": "revision_id",
            "provenance": "source_provenance",
            "checksum": "source_checksum",
        }
        payload = dict(value)
        if any(alias in payload for alias in ("ter_pct", "ocf_pct", "ter_percent", "ocf_percent")):
            raise EtfEconomicsError("ambiguous percent fee aliases require explicit fee_unit=percent")
        for alias, canonical in aliases.items():
            if canonical not in payload and alias in payload:
                payload[canonical] = payload[alias]
        allowed = {key for key in cls.__dataclass_fields__ if key != "execution_allowed"}
        return cls(**{key: payload[key] for key in allowed if key in payload})

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def history_key(self) -> tuple[str, str, str | None, str]:
        return (self.instrument_id, self.scope, self.share_class_id, self.as_of)


class EtfEconomicsStore:
    """Immutable local record collection with known-at point-in-time replay."""

    def __init__(self, records: Iterable[EtfEconomicsObservation | Mapping[str, object]] = ()) -> None:
        if isinstance(records, pd.DataFrame):
            records = records.to_dict("records")
        normalised = [_as_record(item) for item in records]
        seen: dict[tuple[str, str, str | None, str, str], EtfEconomicsObservation] = {}
        for record in normalised:
            key = (*record.history_key, record.known_at or "")
            previous = seen.get(key)
            if previous is not None and previous != record:
                raise EtfEconomicsError(f"conflicting duplicate economics evidence for {record.history_key}")
            seen[key] = record
        self._records = tuple(sorted(seen.values(), key=lambda item: (item.instrument_id, item.scope, item.share_class_id or "", item.as_of, item.known_at or "")))

    @classmethod
    def from_frame(cls, frame: pd.DataFrame | None) -> "EtfEconomicsStore":
        return cls(()) if not isinstance(frame, pd.DataFrame) else cls(frame.to_dict("records"))

    @property
    def records(self) -> tuple[EtfEconomicsObservation, ...]:
        return self._records

    def history(self, instrument_id: str, *, decision_time: object = None) -> tuple[EtfEconomicsObservation, ...]:
        cutoff = _timestamp(decision_time, "decision_time") if decision_time is not None else None
        return tuple(
            record for record in self._records
            if record.instrument_id == str(instrument_id)
            and (cutoff is None or (pd.Timestamp(record.as_of) <= pd.Timestamp(cutoff) and pd.Timestamp(record.known_at) <= pd.Timestamp(cutoff)))
        )

    def as_of(self, instrument_id: str, decision_time: object = None) -> tuple[EtfEconomicsObservation, ...]:
        selected: dict[tuple[str, str | None], EtfEconomicsObservation] = {}
        for record in self.history(instrument_id, decision_time=decision_time):
            key = (record.scope, record.share_class_id)
            previous = selected.get(key)
            if previous is None or (pd.Timestamp(record.as_of), pd.Timestamp(record.known_at)) > (pd.Timestamp(previous.as_of), pd.Timestamp(previous.known_at)):
                selected[key] = record
        return tuple(sorted(selected.values(), key=lambda item: (item.scope, item.share_class_id or "")))


@dataclass(frozen=True)
class ClosureProxyPolicy:
    """Explicit immutable policy for a currency-scoped closure-quality proxy."""

    version: str
    base_currency: str
    amount_unit: str
    aum_threshold: float
    flow_period_days: int
    flow_threshold: float
    young_age_years: float
    source_id: str
    source_provenance: str
    source_checksum: str
    effective_from: str | None = None
    effective_until: str | None = None
    known_at: str | None = None
    execution_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        version = _text(self.version)
        if version is None:
            raise EtfEconomicsError("closure policy version is required")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "base_currency", _currency(self.base_currency, "base_currency", required=True) or "")
        if _text(self.amount_unit) != _CURRENCY_AMOUNT_UNIT:
            raise EtfEconomicsError("closure policy amount_unit must be currency_units")
        object.__setattr__(self, "amount_unit", _CURRENCY_AMOUNT_UNIT)
        for name in ("source_id", "source_provenance", "source_checksum"):
            value = _text(getattr(self, name))
            if value is None:
                raise EtfEconomicsError(f"closure policy {name} is required")
            object.__setattr__(self, name, value)
        effective_from = _timestamp(self.effective_from, "closure policy effective_from", required=True) or ""
        effective_until = _timestamp(self.effective_until, "closure policy effective_until", required=True) or ""
        known_at = _timestamp(self.known_at, "closure policy known_at", required=True) or ""
        if pd.Timestamp(effective_until) < pd.Timestamp(effective_from):
            raise EtfEconomicsError("closure policy effective_until cannot precede effective_from")
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "effective_until", effective_until)
        object.__setattr__(self, "known_at", known_at)
        for name in ("aum_threshold", "flow_threshold", "young_age_years"):
            value = _number(getattr(self, name), name, minimum=0.0)
            if value is None or value == 0:
                raise EtfEconomicsError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        period = _number(self.flow_period_days, "flow_period_days", minimum=1.0)
        if period is None:
            raise EtfEconomicsError("flow_period_days is required")
        object.__setattr__(self, "flow_period_days", int(period))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ClosureProxyPolicy":
        return cls(**{key: value[key] for key in cls.__dataclass_fields__ if key != "execution_allowed" and key in value})


def _reconciliation_signature(reconciliations: Sequence[object]) -> tuple[object, ...]:
    return tuple(
        (
            getattr(item, "status", None),
            getattr(item, "selected_source_id", None),
            tuple(getattr(item, "discrepancies", ())),
            tuple(
                (
                    getattr(observation, "action_id", None),
                    getattr(observation, "instrument_id", None),
                    getattr(observation, "source_id", None),
                    getattr(observation, "source_checksum", None),
                    getattr(observation, "known_at", None),
                    getattr(observation, "event_at", None),
                )
                for observation in getattr(item, "observations", ())
            ),
        )
        for item in reconciliations
    )


def _coverage_signature(coverage: object) -> tuple[object, ...]:
    return tuple(
        getattr(coverage, field_name, None)
        for field_name in (
            "instrument_id",
            "coverage_through",
            "published_at",
            "retrieved_at",
            "known_at",
            "revision",
            "source",
            "source_id",
            "source_checksum",
            "status",
            "execution_allowed",
        )
    )


def _validate_corporate_action_coverage(
    coverage: object,
    *,
    instrument_id: str,
    frame: pd.DataFrame,
    as_of: object,
    known_at: object,
    cutoff: str | None = None,
) -> None:
    from etf_cockpit.data.market_adjustments import CorporateActionCoverage

    if not isinstance(coverage, CorporateActionCoverage):
        raise EtfEconomicsError("total-return evidence requires trusted CorporateActionCoverage")
    if coverage.instrument_id != instrument_id:
        raise EtfEconomicsError("corporate-action coverage instrument mismatch")
    if coverage.status != "active" or coverage.execution_allowed:
        raise EtfEconomicsError("corporate-action coverage must be active and non-executable")
    evidence_as_of = _timestamp(as_of, "total-return as_of", required=True) or ""
    evidence_known_at = _timestamp(known_at, "total-return known_at", required=True) or ""
    frame_dates = pd.to_datetime(frame.get("date"), errors="coerce", utc=True, format="mixed")
    if not isinstance(frame_dates, pd.Series) or frame_dates.empty or frame_dates.isna().any():
        raise EtfEconomicsError("total-return frame requires valid date evidence")
    required_through = max(pd.Timestamp(evidence_as_of), frame_dates.max())
    if pd.Timestamp(coverage.coverage_through) < required_through:
        raise EtfEconomicsError("corporate-action coverage does not cover the total-return frame and as_of")
    if pd.Timestamp(coverage.known_at) > pd.Timestamp(evidence_known_at):
        raise EtfEconomicsError("corporate-action coverage is known after the total-return evidence envelope")
    if cutoff is not None and pd.Timestamp(coverage.known_at) > pd.Timestamp(cutoff):
        raise EtfEconomicsError("corporate-action coverage is not known at decision time")


@dataclass(frozen=True)
class _TrustedTotalReturnBinding:
    """Snapshot binding to the canonical AdjustmentResult artifact."""

    artifact: object = field(repr=False, compare=False)
    frame_checksum: str
    reconciliation_signature: tuple[object, ...]
    convention: str
    corporate_action_coverage: object = field(repr=False, compare=False)
    coverage_signature: tuple[object, ...]

    def verify(
        self,
        frame: pd.DataFrame,
        convention: str,
        instrument_id: str,
        as_of: str,
        known_at: str,
        cutoff: str | None,
    ) -> None:
        artifact_frame = getattr(self.artifact, "frame", None)
        reconciliations = getattr(self.artifact, "action_reconciliation", None)
        if (
            not isinstance(artifact_frame, pd.DataFrame)
            or _frame_checksum(artifact_frame) != self.frame_checksum
            or getattr(self.artifact, "status", None) != "available"
            or getattr(self.artifact, "convention", None) != self.convention
            or convention != self.convention
        ):
            raise EtfEconomicsError("total-return canonical AdjustmentResult artifact changed after binding")
        if _frame_checksum(frame) != self.frame_checksum:
            raise EtfEconomicsError("total-return payload is not the bound canonical artifact")
        if _reconciliation_signature(tuple(reconciliations or ())) != self.reconciliation_signature:
            raise EtfEconomicsError("total-return corporate-action reconciliation changed after binding")
        if _coverage_signature(self.corporate_action_coverage) != self.coverage_signature:
            raise EtfEconomicsError("total-return corporate-action coverage changed after binding")
        _validate_corporate_action_coverage(
            self.corporate_action_coverage,
            instrument_id=instrument_id,
            frame=frame,
            as_of=as_of,
            known_at=known_at,
            cutoff=cutoff,
        )


@dataclass(frozen=True)
class TotalReturnEvidence:
    """Canonical total-return series bound to identity, convention and provenance."""

    instrument_id: str
    currency: str
    total_return_convention: str
    status: str
    reconciliation_status: str
    source_id: str
    provenance: str
    checksum: str
    known_at: str
    as_of: str
    frame: pd.DataFrame = field(repr=False, compare=False)
    frequency: str = _BUSINESS_DAILY
    _binding: object | None = field(default=None, repr=False, compare=False)
    execution_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        instrument_id = _text(self.instrument_id)
        if instrument_id is None:
            raise EtfEconomicsError("total-return instrument_id is required")
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "currency", _currency(self.currency, "total-return currency", required=True) or "")
        convention = _text(self.total_return_convention)
        if convention not in _SUPPORTED_TOTAL_RETURN_CONVENTIONS:
            raise EtfEconomicsError("total-return convention is not canonical")
        object.__setattr__(self, "total_return_convention", convention)
        if self.status != "available" or self.reconciliation_status != "reconciled":
            raise EtfEconomicsError("total-return evidence must be available and reconciled")
        for name in ("source_id", "provenance", "checksum"):
            value = _text(getattr(self, name))
            if value is None:
                raise EtfEconomicsError(f"total-return {name} is required")
            object.__setattr__(self, name, value)
        if not isinstance(self._binding, _TrustedTotalReturnBinding):
            raise EtfEconomicsError("total-return evidence requires a trusted canonical AdjustmentResult binding")
        object.__setattr__(self, "known_at", _timestamp(self.known_at, "total-return known_at", required=True) or "")
        object.__setattr__(self, "as_of", _timestamp(self.as_of, "total-return as_of", required=True) or "")
        if pd.Timestamp(self.known_at) < pd.Timestamp(self.as_of):
            raise EtfEconomicsError("total-return known_at cannot precede as_of")
        if self.frequency != _BUSINESS_DAILY:
            raise EtfEconomicsError("only declared business_daily total-return evidence is supported")
        if not isinstance(self.frame, pd.DataFrame):
            raise EtfEconomicsError("total-return frame must be a pandas DataFrame")
        if "date" not in self.frame.columns:
            raise EtfEconomicsError("total-return frame requires date evidence")
        dates = pd.to_datetime(self.frame["date"], errors="coerce", utc=True, format="mixed")
        if dates.isna().any() or (dates > pd.Timestamp(self.as_of)).any():
            raise EtfEconomicsError("total-return frame extends beyond its as_of envelope")
        if self.checksum != _frame_checksum(self.frame):
            raise EtfEconomicsError("total-return payload checksum mismatch")

    @staticmethod
    def checksum_for_frame(frame: pd.DataFrame) -> str:
        return _frame_checksum(frame)

    @classmethod
    def from_adjustment_result(
        cls,
        result: object,
        *,
        instrument_id: str,
        currency: str,
        known_at: object,
        as_of: object,
        source_id: str,
        provenance: str,
        corporate_action_coverage: object = None,
        checksum: str | None = None,
        frequency: str = _BUSINESS_DAILY,
    ) -> "TotalReturnEvidence":
        from etf_cockpit.data.market_adjustments import AdjustmentResult, CorporateAction

        if not isinstance(result, AdjustmentResult):
            raise EtfEconomicsError("authoritative total-return evidence must be created from AdjustmentResult")
        frame = result.frame.copy(deep=True)
        if "total_return_index" not in frame.columns:
            raise EtfEconomicsError("AdjustmentResult does not contain canonical total_return_index evidence")
        reconciliations = tuple(result.action_reconciliation)
        if reconciliations and any(
            not item.available
            or item.selected_source_id is None
            or not item.observations
            or any(not isinstance(observation, CorporateAction) for observation in item.observations)
            for item in reconciliations
        ):
            raise EtfEconomicsError("AdjustmentResult action reconciliation must be positive, selected and observed")
        _validate_corporate_action_coverage(
            corporate_action_coverage,
            instrument_id=instrument_id,
            frame=frame,
            as_of=as_of,
            known_at=known_at,
        )
        actual_checksum = checksum or _frame_checksum(frame)
        binding = _TrustedTotalReturnBinding(
            artifact=result,
            frame_checksum=_frame_checksum(frame),
            reconciliation_signature=_reconciliation_signature(reconciliations),
            convention=result.convention,
            corporate_action_coverage=corporate_action_coverage,
            coverage_signature=_coverage_signature(corporate_action_coverage),
        )
        return cls(
            instrument_id=instrument_id,
            currency=currency,
            total_return_convention=result.convention,
            status=result.status,
            reconciliation_status="reconciled",
            source_id=source_id,
            provenance=provenance,
            checksum=actual_checksum,
            known_at=str(known_at),
            as_of=str(as_of),
            frame=frame,
            frequency=frequency,
            _binding=binding,
        )

    @classmethod
    def from_local_frame(cls, frame: pd.DataFrame) -> "TotalReturnEvidence":
        required = {"instrument_id", "currency", "total_return_convention", "status", "reconciliation_status", "source_id", "provenance", "checksum", "known_at", "as_of", "frequency"}
        missing = required - set(frame.columns)
        if missing or frame.empty:
            raise EtfEconomicsError(f"local total-return evidence missing metadata: {', '.join(sorted(missing))}")
        for column in required - {"known_at"}:
            if frame[column].map(lambda value: _text(value)).nunique(dropna=True) != 1:
                raise EtfEconomicsError(f"local total-return metadata is inconsistent: {column}")
        known_at = pd.to_datetime(frame["known_at"], errors="coerce", utc=True, format="mixed")
        if known_at.isna().any():
            raise EtfEconomicsError("local total-return evidence has missing known_at")
        raise EtfEconomicsError("local total-return evidence requires a trusted canonical AdjustmentResult binding")

    def as_dict(self) -> dict[str, object]:
        payload = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
            if key not in {"frame", "_binding", "execution_allowed"}
        }
        payload["artifact_checksum"] = self._binding.frame_checksum
        payload["corporate_action_coverage"] = self._binding.corporate_action_coverage.as_dict()
        payload["execution_allowed"] = False
        return payload

    @property
    def artifact_checksum(self) -> str:
        return self._binding.frame_checksum


CanonicalTotalReturnEvidence = TotalReturnEvidence


@dataclass(frozen=True)
class EtfEconomicsReport:
    instrument_id: str
    status: str
    message: str
    model_id: str = ETF_ECONOMICS_MODEL_ID
    as_of: str = "unavailable"
    benchmark_id: str | None = None
    benchmark_name: str | None = None
    benchmark_currency: str | None = None
    benchmark_source_id: str | None = None
    benchmark_source_provenance: str | None = None
    benchmark_source_checksum: str | None = None
    benchmark_total_return_convention: str | None = None
    benchmark_total_return_known_at: str | None = None
    benchmark_total_return_as_of: str | None = None
    fund_source_id: str | None = None
    fund_source_provenance: str | None = None
    fund_source_checksum: str | None = None
    fund_total_return_convention: str | None = None
    fund_total_return_known_at: str | None = None
    fund_total_return_as_of: str | None = None
    currency: str | None = None
    horizon_days: int | None = None
    sampling_frequency: str = _BUSINESS_DAILY
    matched_start: str | None = None
    matched_end: str | None = None
    coverage: str = "unavailable"
    coverage_ratio: float | None = None
    matched_rows: int = 0
    tracking_difference: float | None = None
    tracking_error: float | None = None
    tracking_unit: str = "decimal_fraction"
    tracking_status: str = "unavailable"
    fund_metrics: Mapping[str, object] = field(default_factory=dict)
    share_class_metrics: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    fee_history: tuple[Mapping[str, object], ...] = ()
    fee_changes: tuple[Mapping[str, object], ...] = ()
    history: tuple[Mapping[str, object], ...] = ()
    closure_risk_proxy: Mapping[str, object] = field(default_factory=dict)
    missing_evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    execution_allowed: bool = field(default=False, init=False)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _frame_checksum(frame: pd.DataFrame) -> str:
    canonical = frame.drop(columns=["checksum"], errors="ignore").copy(deep=True)
    for column in ("date", "known_at", "as_of"):
        if column in canonical.columns:
            parsed = pd.to_datetime(canonical[column], errors="coerce", utc=True, format="mixed")
            canonical[column] = parsed.map(
                lambda value: None if pd.isna(value) else value.isoformat().replace("+00:00", "Z")
            )
    if "total_return_index" in canonical.columns:
        canonical["total_return_index"] = pd.to_numeric(
            canonical["total_return_index"], errors="coerce"
        ).astype(float)
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    payload = canonical.to_json(orient="split", date_format="iso", double_precision=15)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_local_frame(path: Path) -> pd.DataFrame | None:
    candidates = [path]
    if path.suffix.lower() == ".parquet":
        candidates.append(path.with_suffix(".csv"))
    elif path.suffix.lower() == ".csv":
        candidates.append(path.with_suffix(".parquet"))
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            return pd.read_csv(candidate) if candidate.suffix.lower() == ".csv" else pd.read_parquet(candidate)
        except (OSError, ValueError, ImportError):
            return None
    return None


def load_etf_economics_records(path: Path | None = None) -> tuple[EtfEconomicsObservation, ...]:
    frame = _read_local_frame(path or ETF_ECONOMICS_PATH)
    if frame is None:
        return ()
    try:
        return EtfEconomicsStore.from_frame(frame).records
    except (EtfEconomicsError, TypeError, ValueError):
        return ()


def load_total_return_evidence(path: Path | None = None) -> TotalReturnEvidence | None:
    frame = _read_local_frame(path) if path is not None else None
    if frame is None:
        return None
    try:
        return TotalReturnEvidence.from_local_frame(frame)
    except (EtfEconomicsError, TypeError, ValueError):
        return None


def load_closure_proxy_policy(path: Path | None = None) -> ClosureProxyPolicy | None:
    """Load one immutable local closure policy from JSON or one-row CSV."""

    target = path or ETF_CLOSURE_POLICY_PATH
    candidates = [target]
    if target.suffix.lower() == ".json":
        candidates.append(target.with_suffix(".csv"))
    elif target.suffix.lower() == ".csv":
        candidates.append(target.with_suffix(".json"))
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            if candidate.suffix.lower() == ".json":
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(payload, Mapping):
                    return None
            else:
                frame = pd.read_csv(candidate)
                if len(frame) != 1:
                    return None
                payload = frame.iloc[0].to_dict()
            return ClosureProxyPolicy.from_mapping(payload)
        except (EtfEconomicsError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
    return None


def _series_frame(evidence: object, label: str, expected_identity: str, cutoff: str | None) -> pd.DataFrame:
    if not isinstance(evidence, TotalReturnEvidence):
        raise EtfEconomicsError(f"{label} total-return evidence is untyped or unavailable")
    if evidence.checksum != _frame_checksum(evidence.frame):
        raise EtfEconomicsError(f"{label} total-return payload checksum mismatch at consumption")
    evidence._binding.verify(
        evidence.frame,
        evidence.total_return_convention,
        evidence.instrument_id,
        evidence.as_of,
        evidence.known_at,
        cutoff,
    )
    if evidence.instrument_id != expected_identity:
        raise EtfEconomicsError(f"{label} total-return identity mismatch")
    has_row_known_at = "known_at" in evidence.frame.columns
    if not has_row_known_at and cutoff is not None and (pd.Timestamp(evidence.known_at) > pd.Timestamp(cutoff) or pd.Timestamp(evidence.as_of) > pd.Timestamp(cutoff)):
        raise EtfEconomicsError(f"{label} total-return evidence is not known at decision time")
    frame = evidence.frame.copy(deep=True)
    if "total_return_index" not in frame.columns or "date" not in frame.columns:
        raise EtfEconomicsError(f"{label} total-return evidence lacks canonical date/index columns")
    for identity_column in ("instrument_id", "etf_id", "benchmark_id", "id"):
        if identity_column in frame.columns and not frame[identity_column].astype(str).eq(expected_identity).all():
            raise EtfEconomicsError(f"{label} total-return frame identity mismatch")
    if "currency" in frame.columns and not frame["currency"].map(lambda value: _currency(value, "currency")).eq(evidence.currency).all():
        raise EtfEconomicsError(f"{label} total-return frame currency mismatch")
    if "total_return_convention" in frame.columns and not frame["total_return_convention"].astype(str).eq(evidence.total_return_convention).all():
        raise EtfEconomicsError(f"{label} total-return frame convention mismatch")
    parsed_dates = pd.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed")
    values = pd.to_numeric(frame["total_return_index"], errors="coerce")
    finite_values = values.map(lambda value: math.isfinite(float(value)) if not pd.isna(value) else False)
    if parsed_dates.isna().any() or values.isna().any() or not finite_values.all() or values.le(0).any():
        raise EtfEconomicsError(f"{label} total-return evidence has invalid observations")
    selected = pd.DataFrame({"date": parsed_dates, label: values}, index=frame.index)
    if has_row_known_at:
        known = pd.to_datetime(frame["known_at"], errors="coerce", utc=True, format="mixed")
        if known.isna().any():
            raise EtfEconomicsError(f"{label} total-return evidence has missing known_at")
        if (known < parsed_dates).any():
            raise EtfEconomicsError(f"{label} total-return row known_at cannot precede observation date")
        conflict_columns = [
            column
            for column in ("total_return_index", "instrument_id", "currency", "total_return_convention", "source_id", "provenance", "checksum")
            if column in frame.columns
        ]
        conflict_frame = frame.assign(_date=parsed_dates, _known_at=known)
        for (_, _), candidates in conflict_frame.groupby(["_date", "_known_at"], sort=False, dropna=False):
            if any(candidates[column].astype(str).nunique(dropna=False) > 1 for column in conflict_columns):
                raise EtfEconomicsError(f"conflicting {label} total-return revisions at the same date and known_at")
        selected["known_at"] = known
        if cutoff is not None:
            eligible = (selected["known_at"] <= pd.Timestamp(cutoff)) & (selected["date"] <= pd.Timestamp(cutoff))
            selected = selected.loc[eligible].copy()
        selected = selected.sort_values(["date", "known_at"], kind="stable").drop_duplicates(["date", "known_at"], keep="last")
        selected = selected.drop_duplicates("date", keep="last").drop(columns="known_at")
    elif cutoff is not None:
        selected = selected.loc[selected["date"] <= pd.Timestamp(cutoff)].copy()
    if selected.empty:
        return pd.DataFrame(columns=["date", label])
    selected = selected.sort_values("date", kind="stable").reset_index(drop=True)
    if not selected["date"].is_monotonic_increasing or selected["date"].duplicated().any():
        raise EtfEconomicsError(f"{label} total-return dates must be monotonic and unique")
    if selected["date"].dt.dayofweek.ge(5).any():
        raise EtfEconomicsError(f"{label} total-return sampling must use business dates")
    return selected


def _latest_by_scope(records: Sequence[EtfEconomicsObservation]) -> tuple[EtfEconomicsObservation | None, dict[str, EtfEconomicsObservation]]:
    fund = next((item for item in records if item.scope == "fund"), None)
    classes = {item.share_class_id or "unavailable": item for item in records if item.scope == "share_class"}
    return fund, classes


def _fee_payload(record: EtfEconomicsObservation) -> dict[str, object]:
    return {
        "scope": record.scope, "share_class_id": record.share_class_id, "as_of": record.as_of, "known_at": record.known_at,
        "ter": record.ter, "ocf": record.ocf, "fee_unit": "decimal_fraction" if record.fee_unit else None,
        "document_id": record.document_id, "document_date": record.document_date, "document_page": record.document_page,
        "revision_id": record.revision_id, "source_id": record.source_id, "source_provenance": record.source_provenance,
        "source_checksum": record.source_checksum, "confidence": record.confidence,
    }


def _closure_proxy(fund: EtfEconomicsObservation | None, as_of: str | None, policy: ClosureProxyPolicy | None) -> dict[str, object]:
    label = "proxy/model; not an observed fact or probability"
    unavailable = {"status": "unavailable", "label": label, "method": "versioned age/AUM/flow proxy", "score": None, "factor_coverage": {"available": 0, "total": 3, "ratio": 0.0}, "uncertainty": "high"}
    if fund is None or policy is None:
        return {**unavailable, "reason": "fund economics or explicit closure policy unavailable"}
    if as_of is None or pd.Timestamp(as_of) < pd.Timestamp(policy.effective_from) or (
        policy.effective_until is not None and pd.Timestamp(as_of) > pd.Timestamp(policy.effective_until)
    ) or pd.Timestamp(policy.known_at) > pd.Timestamp(as_of):
        return {
            **unavailable,
            "reason": "closure policy is not applicable at the requested point in time",
            "policy_version": policy.version,
            "policy_provenance": {
                "source_id": policy.source_id,
                "source_provenance": policy.source_provenance,
                "source_checksum": policy.source_checksum,
                "effective_from": policy.effective_from,
                "effective_until": policy.effective_until,
                "known_at": policy.known_at,
            },
        }
    if fund.currency != policy.base_currency or fund.aum_unit not in {None, policy.amount_unit} or fund.flows_unit not in {None, policy.amount_unit}:
        return {**unavailable, "reason": "policy base currency does not match AUM/flow currency", "policy_version": policy.version, "base_currency": policy.base_currency}
    factors: dict[str, float] = {}
    missing: list[str] = []
    if fund.aum is not None:
        factors["aum"] = round(max(0.0, min(1.0, 1.0 - fund.aum / policy.aum_threshold)), 8)
    else:
        missing.append("aum")
    if fund.flows is not None and fund.flow_period_days == policy.flow_period_days:
        factors["flows"] = round(max(0.0, min(1.0, -fund.flows / policy.flow_threshold)), 8)
    else:
        missing.append("flows")
    if fund.inception_date is not None and as_of is not None:
        age_years = max(0.0, (pd.Timestamp(as_of) - pd.Timestamp(fund.inception_date)).days / 365.25)
        factors["age"] = round(max(0.0, min(1.0, 1.0 - age_years / policy.young_age_years)), 8)
    else:
        missing.append("age")
    coverage = len(factors) / 3.0
    return {
        "status": "available" if coverage == 1.0 else "unavailable", "label": label, "method": "versioned age/AUM/flow proxy",
        "policy_version": policy.version, "base_currency": policy.base_currency, "amount_unit": policy.amount_unit,
        "policy_interval": {"effective_from": policy.effective_from, "effective_until": policy.effective_until, "known_at": policy.known_at},
        "policy_assumptions": {"aum_threshold": policy.aum_threshold, "flow_period_days": policy.flow_period_days, "flow_threshold": policy.flow_threshold, "young_age_years": policy.young_age_years},
        "policy_provenance": {"source_id": policy.source_id, "source_provenance": policy.source_provenance, "source_checksum": policy.source_checksum},
        "score": round(sum(factors.values()) / len(factors), 8) if factors else None,
        "factors": factors, "missing_factors": tuple(missing), "factor_coverage": {"available": len(factors), "total": 3, "ratio": round(coverage, 8)},
        "uncertainty": "low" if coverage == 1.0 else "medium" if coverage >= 2 / 3 else "high",
    }


def _unavailable(instrument: str, message: str, *, missing: Iterable[str] = (), **values: object) -> EtfEconomicsReport:
    return EtfEconomicsReport(instrument, "unavailable", message, missing_evidence=tuple(sorted(set(missing))), warnings=(message,), **values)


def calculate_etf_economics(
    instrument_id: str,
    records: Iterable[EtfEconomicsObservation | Mapping[str, object]] = (),
    *,
    fund_total_return: object = None,
    benchmark_total_return: object = None,
    as_of: object = None,
    horizon_days: int = 252,
    benchmark_id: str | None = None,
    currency: str | None = None,
    closure_policy: ClosureProxyPolicy | Mapping[str, object] | None = None,
) -> EtfEconomicsReport:
    """Build a point-in-time report; authoritative tracking requires typed evidence."""

    instrument = _text(instrument_id) or "unknown"
    try:
        cutoff = _timestamp(as_of, "as_of") if as_of is not None else None
        store = records if isinstance(records, EtfEconomicsStore) else EtfEconomicsStore(records)
        history = store.history(instrument, decision_time=cutoff)
        selected = store.as_of(instrument, cutoff)
        fund, classes = _latest_by_scope(selected)
        canonical_benchmark = fund.benchmark_id if fund else None
        if benchmark_id is not None and _text(benchmark_id) != canonical_benchmark:
            return _unavailable(instrument, "benchmark override does not match canonical benchmark identity", missing=("benchmark_identity",), benchmark_id=canonical_benchmark)
        benchmark = canonical_benchmark
        requested_currency = _currency(currency, "currency") if currency is not None else None
        if requested_currency is not None and fund is not None and requested_currency != fund.currency:
            return _unavailable(instrument, "currency override does not match canonical fund currency", missing=("currency_match",), currency=fund.currency)
        output_currency = fund.currency if fund else requested_currency
        benchmark_currency = fund.benchmark_currency if fund else None
        effective_as_of = cutoff or (fund.as_of if fund else (history[-1].as_of if history else None))
        missing: set[str] = set()
        if fund is None:
            missing.add("fund_economics")
        if benchmark is None:
            missing.add("benchmark_identity")
        if output_currency is None:
            missing.add("currency")
        if benchmark_currency is None:
            missing.add("benchmark_currency")
        if benchmark_currency is not None and output_currency is not None and benchmark_currency != output_currency:
            missing.add("currency_match")
        if fund is not None and any(
            _text(getattr(fund, field_name)) is None
            for field_name in ("source_id", "source_provenance", "source_checksum")
        ):
            missing.add("fund_economics_provenance")

        requested_horizon = int(horizon_days)
        if requested_horizon < 1:
            raise EtfEconomicsError("horizon_days must be positive")
        evidence_cutoff = cutoff or effective_as_of
        fund_frame = _series_frame(fund_total_return, "fund", instrument, evidence_cutoff) if fund_total_return is not None else pd.DataFrame()
        benchmark_frame = _series_frame(benchmark_total_return, "benchmark", benchmark, evidence_cutoff) if benchmark_total_return is not None and benchmark is not None else pd.DataFrame()
        if fund_total_return is None:
            missing.add("fund_total_return")
        if benchmark_total_return is None:
            missing.add("benchmark_total_return")
        if isinstance(fund_total_return, TotalReturnEvidence) and output_currency != fund_total_return.currency:
            missing.add("fund_currency")
        if isinstance(benchmark_total_return, TotalReturnEvidence) and benchmark_currency != benchmark_total_return.currency:
            missing.add("benchmark_currency")
        if isinstance(fund_total_return, TotalReturnEvidence) and isinstance(benchmark_total_return, TotalReturnEvidence):
            if fund_total_return.total_return_convention != benchmark_total_return.total_return_convention:
                missing.add("total_return_convention")
        merged = pd.merge(fund_frame, benchmark_frame, on="date", how="inner") if not fund_frame.empty and not benchmark_frame.empty else pd.DataFrame(columns=["date", "fund", "benchmark"])
        if not merged.empty:
            merged = merged.sort_values("date", kind="stable").reset_index(drop=True)
        expected_rows = requested_horizon + 1
        selected_window = merged.tail(expected_rows).reset_index(drop=True)
        coverage_ratio = len(selected_window) / expected_rows if not merged.empty else None
        tracking_difference = tracking_error = None
        tracking_status = "unavailable"
        if len(selected_window) == expected_rows and not missing:
            start = pd.Timestamp(selected_window["date"].iloc[0])
            end = pd.Timestamp(selected_window["date"].iloc[-1])
            expected_dates = pd.bdate_range(start=start, end=end, tz="UTC")
            if len(expected_dates) != expected_rows or not selected_window["date"].equals(pd.Series(expected_dates, name="date")):
                missing.add("business_daily_coverage")
            else:
                fund_return = float(selected_window["fund"].iloc[-1] / selected_window["fund"].iloc[0] - 1.0)
                benchmark_return = float(selected_window["benchmark"].iloc[-1] / selected_window["benchmark"].iloc[0] - 1.0)
                active = selected_window["fund"].pct_change().iloc[1:] - selected_window["benchmark"].pct_change().iloc[1:]
                tracking_difference = round(fund_return - benchmark_return, 10)
                tracking_error = round(float(active.std(ddof=1) * math.sqrt(252)), 10) if len(active) >= 2 else None
                tracking_status = "available"
        else:
            missing.add("matched_total_return")
        if tracking_difference is None:
            missing.add("matched_total_return")

        fund_metrics: dict[str, object] = {
            "ter": fund.ter if fund else None, "ocf": fund.ocf if fund else None, "fee_unit": "decimal_fraction" if fund and fund.fee_unit else None, "aum": fund.aum if fund else None,
            "source_id": fund.source_id if fund else None, "source_provenance": fund.source_provenance if fund else None, "source_checksum": fund.source_checksum if fund else None,
            "aum_unit": fund.aum_unit if fund else None, "flows": fund.flows if fund else None, "flows_unit": fund.flows_unit if fund else None,
            "flow_period_days": fund.flow_period_days if fund else None, "inception_date": fund.inception_date if fund else None,
            "age_years": None if fund is None or fund.inception_date is None or effective_as_of is None else round(max(0.0, (pd.Timestamp(effective_as_of) - pd.Timestamp(fund.inception_date)).days / 365.25), 8),
            "distribution_frequency": fund.distribution_frequency if fund else None, "distribution_amount": fund.distribution_amount if fund else None,
            "distributions": fund.distributions if fund else (), "share_class_structure": fund.share_class_structure if fund else None,
        }
        share_class_metrics = {key: {**_fee_payload(value), "aum": value.aum, "aum_unit": value.aum_unit, "flows": value.flows, "flows_unit": value.flows_unit, "flow_period_days": value.flow_period_days, "distribution_frequency": value.distribution_frequency, "distribution_amount": value.distribution_amount, "distributions": value.distributions} for key, value in classes.items()}
        fee_history = tuple(_fee_payload(item) for item in history if item.ter is not None or item.ocf is not None)
        fee_changes: list[dict[str, object]] = []
        previous: dict[tuple[str, str | None], EtfEconomicsObservation] = {}
        for item in history:
            if item.ter is None and item.ocf is None:
                continue
            key = (item.scope, item.share_class_id)
            prior = previous.get(key)
            if prior is not None and prior.as_of != item.as_of and (prior.ter != item.ter or prior.ocf != item.ocf):
                fee_changes.append({"scope": item.scope, "share_class_id": item.share_class_id, "from_as_of": prior.as_of, "to_as_of": item.as_of, "from_ter": prior.ter, "to_ter": item.ter, "from_ocf": prior.ocf, "to_ocf": item.ocf})
            previous[key] = item
        policy = closure_policy if isinstance(closure_policy, ClosureProxyPolicy) else ClosureProxyPolicy.from_mapping(closure_policy) if isinstance(closure_policy, Mapping) else None
        closure_report = _closure_proxy(fund, effective_as_of, policy)
        if policy is None:
            missing.add("closure_policy")
        elif closure_report.get("status") != "available":
            missing.add("closure_proxy")
        status = "available" if fund is not None and not missing else "partial" if fund is not None else "unavailable"
        return EtfEconomicsReport(
            instrument, status, "ETF economics evidence is local, point-in-time and non-executable.", as_of=effective_as_of or "unavailable",
            benchmark_id=benchmark, benchmark_name=fund.benchmark_name if fund else None, benchmark_currency=benchmark_currency,
            benchmark_source_id=benchmark_total_return.source_id if isinstance(benchmark_total_return, TotalReturnEvidence) else (fund.benchmark_source_id if fund else None),
            benchmark_source_provenance=benchmark_total_return.provenance if isinstance(benchmark_total_return, TotalReturnEvidence) else (fund.benchmark_source_provenance if fund else None),
            benchmark_source_checksum=benchmark_total_return.checksum if isinstance(benchmark_total_return, TotalReturnEvidence) else (fund.benchmark_source_checksum if fund else None),
            benchmark_total_return_convention=benchmark_total_return.total_return_convention if isinstance(benchmark_total_return, TotalReturnEvidence) else None,
            benchmark_total_return_known_at=benchmark_total_return.known_at if isinstance(benchmark_total_return, TotalReturnEvidence) else None,
            benchmark_total_return_as_of=benchmark_total_return.as_of if isinstance(benchmark_total_return, TotalReturnEvidence) else None,
            fund_source_id=fund_total_return.source_id if isinstance(fund_total_return, TotalReturnEvidence) else None,
            fund_source_provenance=fund_total_return.provenance if isinstance(fund_total_return, TotalReturnEvidence) else None,
            fund_source_checksum=fund_total_return.checksum if isinstance(fund_total_return, TotalReturnEvidence) else None,
            fund_total_return_convention=fund_total_return.total_return_convention if isinstance(fund_total_return, TotalReturnEvidence) else None,
            fund_total_return_known_at=fund_total_return.known_at if isinstance(fund_total_return, TotalReturnEvidence) else None,
            fund_total_return_as_of=fund_total_return.as_of if isinstance(fund_total_return, TotalReturnEvidence) else None,
            currency=output_currency, horizon_days=requested_horizon, matched_start=None if selected_window.empty else pd.Timestamp(selected_window["date"].iloc[0]).isoformat().replace("+00:00", "Z"),
            matched_end=None if selected_window.empty else pd.Timestamp(selected_window["date"].iloc[-1]).isoformat().replace("+00:00", "Z"), sampling_frequency=_BUSINESS_DAILY,
            coverage=f"{len(selected_window)}/{expected_rows} business_daily observations" if not selected_window.empty else "unavailable", coverage_ratio=None if coverage_ratio is None else round(coverage_ratio, 8), matched_rows=len(selected_window),
            tracking_difference=tracking_difference, tracking_error=tracking_error, tracking_status=tracking_status, fund_metrics=fund_metrics,
            share_class_metrics=share_class_metrics, fee_history=fee_history, fee_changes=tuple(fee_changes), history=tuple(item.as_dict() for item in history),
            closure_risk_proxy=closure_report, missing_evidence=tuple(sorted(missing)), warnings=(),
        )
    except (EtfEconomicsError, TypeError, ValueError, OverflowError) as exc:
        return _unavailable(instrument, str(exc), missing=("economics_records",))


__all__ = [
    "ETF_ECONOMICS_MODEL_ID", "EtfEconomicsError", "EtfEconomicsObservation", "EtfEconomicsReport", "EtfEconomicsStore",
    "ClosureProxyPolicy", "TotalReturnEvidence", "CanonicalTotalReturnEvidence", "calculate_etf_economics", "load_etf_economics_records",
    "load_total_return_evidence", "load_closure_proxy_policy", "ETF_ECONOMICS_PATH", "ETF_FUND_TOTAL_RETURN_PATH",
    "ETF_BENCHMARK_TOTAL_RETURN_PATH", "ETF_CLOSURE_POLICY_PATH",
]
