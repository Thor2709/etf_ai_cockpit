"""Point-in-time corporate-action, total-return and FX services.

The module deliberately keeps raw prices separate from immutable action and FX
observations.  Derived series are reproducible projections: corrections append
new revisions, decision-time queries never see later knowledge, and no result
has execution authority.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence, cast

import pandas as pd

from etf_cockpit.data.bitemporal import BitemporalError, BitemporalObservation, BitemporalStore


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ACTION_DATASET = "market.corporate_actions.v1"
_ACTION_COVERAGE_DATASET = "market.corporate_action_coverage.v1"
_FX_DATASET = "market.fx_observations.v1"
_TOTAL_RETURN_CONVENTIONS = {"reinvest_on_ex_date", "cash_on_payable_date", "price_plus_reinvested_income", "split_adjusted"}


class MarketAdjustmentError(ValueError):
    """Raised when market evidence cannot be used without inventing facts."""


class CorporateActionType(StrEnum):
    SPLIT = "split"
    DIVIDEND = "dividend"
    CASH_DIVIDEND = "cash_dividend"
    STOCK_DIVIDEND = "stock_dividend"
    CAPITAL_GAIN = "capital_gain"
    DISTRIBUTION = "distribution"
    INTEREST = "interest"
    RIGHTS = "rights"
    SPIN_OFF = "spin_off"
    MERGER = "merger"
    SYMBOL_CHANGE = "symbol_change"
    CURRENCY_CHANGE = "currency_change"
    COUPON = "coupon"
    ACCRUED_SETTLEMENT = "accrued_settlement"
    PRINCIPAL_REDEMPTION = "principal_redemption"
    REDEMPTION = "redemption"
    CALL = "call"
    PUT = "put"
    AMORTISATION = "amortisation"
    TENDER = "tender"
    EXCHANGE = "exchange"
    DEFAULT = "default"
    RECOVERY = "recovery"


_INCOME_ACTIONS = {
    CorporateActionType.DIVIDEND,
    CorporateActionType.CASH_DIVIDEND,
    CorporateActionType.CAPITAL_GAIN,
    CorporateActionType.DISTRIBUTION,
    CorporateActionType.COUPON,
    CorporateActionType.INTEREST,
    CorporateActionType.ACCRUED_SETTLEMENT,
    CorporateActionType.RECOVERY,
}
_PRINCIPAL_ACTIONS = {
    CorporateActionType.PRINCIPAL_REDEMPTION,
    CorporateActionType.REDEMPTION,
    CorporateActionType.CALL,
    CorporateActionType.PUT,
    CorporateActionType.AMORTISATION,
    CorporateActionType.TENDER,
}
_CASH_ACTIONS = _INCOME_ACTIONS | _PRINCIPAL_ACTIONS


def _utc(value: str | datetime, field_name: str) -> str:
    try:
        parsed = pd.Timestamp(value)
    except Exception as exc:
        raise MarketAdjustmentError(f"{field_name} must be an ISO timestamp") from exc
    if pd.isna(parsed):
        raise MarketAdjustmentError(f"{field_name} must be an ISO timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.isoformat().replace("+00:00", "Z")


def _optional_utc(value: str | datetime | None, field_name: str) -> str | None:
    return None if value is None or str(value).strip() == "" else _utc(value, field_name)


def _text(value: object, field_name: str) -> str:
    result = str(value).strip()
    if not result:
        raise MarketAdjustmentError(f"{field_name} is required")
    return result


def _currency(value: str | None, *, required: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        if required:
            raise MarketAdjustmentError("currency is required")
        return None
    result = str(value).strip().upper()
    if not _CURRENCY_RE.fullmatch(result):
        raise MarketAdjustmentError(f"invalid currency code: {value}")
    return result


def _checksum(value: str) -> str:
    result = str(value).lower()
    if result.startswith("sha256:"):
        return hashlib.sha256(result.encode("utf-8")).hexdigest()
    if not _SHA256_RE.fullmatch(result):
        raise MarketAdjustmentError("source_checksum must be a 64-character SHA-256 value")
    return result


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    instrument_id: str
    action_type: str
    announced_at: str
    effective_at: str
    ex_date: str | None
    payable_at: str | None
    known_at: str
    revision: int
    source: str
    source_id: str
    source_checksum: str
    ratio: float | None = None
    amount: float | None = None
    currency: str | None = None
    withholding_rate: float = 0.0
    status: str = "active"
    terms: Mapping[str, object] = field(default_factory=dict)
    execution_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _text(self.action_id, "action_id"))
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "action_type", str(self.action_type).strip().lower())
        object.__setattr__(self, "source_checksum", _checksum(self.source_checksum))
        if int(self.revision) < 1:
            raise MarketAdjustmentError("revision must be positive")
        object.__setattr__(self, "revision", int(self.revision))
        object.__setattr__(self, "announced_at", _utc(self.announced_at, "announced_at"))
        object.__setattr__(self, "effective_at", _utc(self.effective_at, "effective_at"))
        object.__setattr__(self, "known_at", _utc(self.known_at, "known_at"))
        object.__setattr__(self, "ex_date", None if self.ex_date is None else str(self.ex_date)[:10])
        object.__setattr__(self, "payable_at", _optional_utc(self.payable_at, "payable_at"))
        if pd.Timestamp(self.known_at) < pd.Timestamp(self.announced_at):
            raise MarketAdjustmentError("known_at cannot precede announced_at")
        ratio = None if self.ratio is None else float(self.ratio)
        amount = None if self.amount is None else float(self.amount)
        withholding = float(self.withholding_rate)
        object.__setattr__(self, "ratio", ratio)
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "withholding_rate", withholding)
        object.__setattr__(self, "currency", _currency(self.currency))
        if self.status not in {"active", "superseded", "retracted"}:
            raise MarketAdjustmentError(f"unsupported action status: {self.status}")
        object.__setattr__(self, "terms", dict(self.terms))

    @property
    def event_at(self) -> str:
        return self.ex_date or self.effective_at

    @property
    def quantity_factor(self) -> float:
        return 1.0 if self.ratio is None else self.ratio

    @property
    def cash_amount(self) -> float:
        return 0.0 if self.amount is None else self.amount

    @property
    def external_flow(self) -> bool:
        return False

    @property
    def cash_flow_classification(self) -> str:
        kind = CorporateActionType(self.action_type)
        if kind in _INCOME_ACTIONS:
            return "investment_income"
        if kind in _PRINCIPAL_ACTIONS:
            return "security_principal"
        if kind is CorporateActionType.DEFAULT:
            return "credit_loss"
        return "non_cash_security_event"

    @property
    def net_cash_amount(self) -> float:
        return self.cash_amount * (1.0 - self.withholding_rate)

    def validate(self) -> None:
        try:
            kind = CorporateActionType(self.action_type)
        except ValueError as exc:
            raise MarketAdjustmentError(f"unsupported corporate action: {self.action_type}") from exc
        if self.ratio is not None and (not math.isfinite(self.ratio) or self.ratio <= 0):
            raise MarketAdjustmentError("ratio must be positive")
        if self.amount is not None and (not math.isfinite(self.amount) or self.amount < 0):
            raise MarketAdjustmentError("amount cannot be negative")
        if not math.isfinite(self.withholding_rate) or not 0 <= self.withholding_rate <= 1:
            raise MarketAdjustmentError("withholding_rate must be between zero and one")
        if kind is CorporateActionType.SPLIT and (self.ratio is None or math.isclose(self.ratio, 1.0)):
            raise MarketAdjustmentError("split requires a non-unit ratio")
        if kind in _CASH_ACTIONS and (self.amount is None or self.amount <= 0):
            raise MarketAdjustmentError(f"{kind.value} requires a positive amount")
        if self.cash_amount > 0 and self.currency is None:
            raise MarketAdjustmentError("cash corporate actions require currency")

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["cash_flow_classification"] = self.cash_flow_classification
        value["net_cash_amount"] = self.net_cash_amount
        return value


@dataclass(frozen=True)
class CorporateActionCoverage:
    instrument_id: str
    coverage_through: str
    published_at: str
    retrieved_at: str
    known_at: str
    revision: int
    source: str
    source_id: str
    source_checksum: str
    status: str = "active"
    _canonical_evidence_digest: str = field(default="", init=False, repr=False, compare=False)
    execution_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        object.__setattr__(self, "coverage_through", _utc(self.coverage_through, "coverage_through"))
        object.__setattr__(self, "published_at", _utc(self.published_at, "published_at"))
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        object.__setattr__(self, "known_at", _utc(self.known_at, "known_at"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "source_checksum", _checksum(self.source_checksum))
        if int(self.revision) < 1:
            raise MarketAdjustmentError("revision must be positive")
        object.__setattr__(self, "revision", int(self.revision))
        if pd.Timestamp(self.retrieved_at) < pd.Timestamp(self.published_at):
            raise MarketAdjustmentError("retrieved_at cannot precede published_at")
        if pd.Timestamp(self.known_at) < max(pd.Timestamp(self.published_at), pd.Timestamp(self.retrieved_at)):
            raise MarketAdjustmentError("known_at cannot precede publication or retrieval")
        if pd.Timestamp(self.known_at) < pd.Timestamp(self.coverage_through):
            raise MarketAdjustmentError("known_at cannot precede coverage_through")
        if self.status not in {"active", "superseded", "retracted"}:
            raise MarketAdjustmentError(f"unsupported coverage status: {self.status}")

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("_canonical_evidence_digest", None)
        return value


def _coverage_evidence_digest(coverage: CorporateActionCoverage) -> str:
    payload = json.dumps(
        coverage.as_dict(),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mark_canonical_coverage(coverage: CorporateActionCoverage) -> CorporateActionCoverage:
    object.__setattr__(coverage, "_canonical_evidence_digest", _coverage_evidence_digest(coverage))
    return coverage


def is_canonical_corporate_action_coverage(value: object) -> bool:
    """Return whether coverage came through the append-only canonical store unchanged."""

    return (
        isinstance(value, CorporateActionCoverage)
        and bool(value._canonical_evidence_digest)
        and value._canonical_evidence_digest == _coverage_evidence_digest(value)
    )


@dataclass(frozen=True)
class FXObservation:
    observation_id: str
    base_currency: str
    quote_currency: str
    rate: object
    valid_at: str
    published_at: str
    retrieved_at: str
    known_at: str
    revision: int
    source: str
    source_id: str
    source_checksum: str
    is_reference: bool = True
    executable: bool = False
    authority: str = "official"
    status: str = "active"
    execution_allowed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _text(self.observation_id, "observation_id"))
        object.__setattr__(self, "base_currency", _currency(self.base_currency, required=True))
        object.__setattr__(self, "quote_currency", _currency(self.quote_currency, required=True))
        if self.base_currency == self.quote_currency:
            raise MarketAdjustmentError("FX base and quote currencies must differ")
        object.__setattr__(self, "valid_at", _utc(self.valid_at, "valid_at"))
        object.__setattr__(self, "published_at", _utc(self.published_at, "published_at"))
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        object.__setattr__(self, "known_at", _utc(self.known_at, "known_at"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "source_checksum", _checksum(self.source_checksum))
        if int(self.revision) < 1:
            raise MarketAdjustmentError("revision must be positive")
        object.__setattr__(self, "revision", int(self.revision))
        if self.authority not in {"official", "regulated", "provider", "broker", "manual"}:
            raise MarketAdjustmentError(f"unsupported FX authority: {self.authority}")
        if self.status not in {"active", "superseded", "retracted"}:
            raise MarketAdjustmentError(f"unsupported FX status: {self.status}")
        if pd.Timestamp(self.retrieved_at) < pd.Timestamp(self.published_at):
            raise MarketAdjustmentError("retrieved_at cannot precede published_at")
        if pd.Timestamp(self.known_at) < max(pd.Timestamp(self.published_at), pd.Timestamp(self.retrieved_at)):
            raise MarketAdjustmentError("known_at cannot precede publication or retrieval")

    @property
    def pair(self) -> str:
        return f"{self.base_currency}/{self.quote_currency}"

    @property
    def valuation_at(self) -> str:
        return self.valid_at

    @property
    def available_at(self) -> str:
        return self.known_at

    @property
    def rate_label(self) -> str:
        return "reference" if self.is_reference else "executable" if self.executable else "indicative"

    def validate(self) -> None:
        rate = float(str(self.rate))
        if not math.isfinite(rate) or rate <= 0:
            raise MarketAdjustmentError("FX rate must be positive")
        if self.is_reference and self.executable:
            raise MarketAdjustmentError("a reference FX rate cannot be executable")

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["rate"] = str(self.rate)
        value["pair"] = self.pair
        value["valuation_at"] = self.valuation_at
        value["rate_label"] = self.rate_label
        return value


class _ObservationStore:
    dataset_id: str

    def __init__(self, root: Path):
        self.root = Path(root)
        self._store = BitemporalStore(self.root)

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> _ObservationStore:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def _append(self, *, entity_id: str, stable_id: str, value: Mapping[str, object], revision: int, source_id: str, source_checksum: str, valid_from: str, known_at: str, published_at: str, status: str) -> BitemporalObservation:
        history = [item for item in self._store.observations(self.dataset_id, entity_id=entity_id) if item.stable_id == stable_id]
        if history:
            maximum = max(item.revision for item in history)
            if revision <= maximum:
                raise MarketAdjustmentError(f"revision must advance beyond {maximum} for {stable_id}")
            latest_known_at = max(pd.Timestamp(item.available_at) for item in history)
            if pd.Timestamp(known_at) < latest_known_at:
                raise MarketAdjustmentError(f"known_at cannot move backwards for {stable_id}")
        try:
            return self._store.record_observation(
                dataset_id=self.dataset_id,
                entity_id=entity_id,
                stable_id=stable_id,
                run_id=f"{self.dataset_id}:{source_id}:{revision}",
                value=dict(value),
                source_id=source_id,
                source_checksum=source_checksum,
                revision=revision,
                valid_from=valid_from,
                available_at=known_at,
                observed_at=known_at,
                published_at=published_at,
                status=status,
                require_revision_advance=True,
            )
        except BitemporalError as exc:
            raise MarketAdjustmentError(str(exc)) from exc

    def _values(self, *, entity_id: str | None = None, decision_time: str | datetime | None = None) -> list[dict[str, object]]:
        if decision_time is None:
            observations = self._store.observations(self.dataset_id, entity_id=entity_id)
            return [dict(item.value) for item in observations]
        frame = self._store.as_of(self.dataset_id, _utc(decision_time, "decision_time"), entity_id=entity_id)
        if frame.empty:
            return []
        return [dict(value) for value in frame["value"].tolist()]


class CorporateActionStore(_ObservationStore):
    """Append-only action/cash-flow store using the shared bitemporal ledger."""

    dataset_id = _ACTION_DATASET

    def append(self, action: CorporateAction) -> CorporateAction:
        if not isinstance(action, CorporateAction):
            raise TypeError("append requires CorporateAction")
        action.validate()
        self._append(
            entity_id=action.instrument_id,
            stable_id=f"{action.action_id}:{action.source_id}",
            value=action.as_dict(),
            revision=action.revision,
            source_id=action.source_id,
            source_checksum=action.source_checksum,
            valid_from=action.effective_at,
            known_at=action.known_at,
            published_at=action.announced_at,
            status=action.status,
        )
        return action

    record = append

    def query(self, instrument_id: str | None = None) -> tuple[CorporateAction, ...]:
        return tuple(_action_from_value(value) for value in self._values(entity_id=instrument_id))

    def as_of(self, instrument_id: str, decision_time: str | datetime | None = None, *, known_at: str | datetime | None = None) -> tuple[CorporateAction, ...]:
        cutoff_value = known_at or decision_time
        if cutoff_value is None:
            raise MarketAdjustmentError("known_at is required")
        values = self._values(entity_id=instrument_id, decision_time=cutoff_value)
        actions = [_action_from_value(value) for value in values]
        cutoff = pd.Timestamp(_utc(cutoff_value, "known_at"))
        return tuple(sorted((item for item in actions if pd.Timestamp(item.known_at) <= cutoff and item.status == "active"), key=lambda item: (item.event_at, item.action_id, item.source_id)))

    def replay(self, instrument_id: str, *, effective_at: str | datetime, known_at: str | datetime) -> tuple[CorporateAction, ...]:
        cutoff = pd.Timestamp(_utc(effective_at, "effective_at"))
        return tuple(item for item in self.as_of(instrument_id, known_at=known_at) if pd.Timestamp(item.effective_at) <= cutoff)


class CorporateActionCoverageStore(_ObservationStore):
    """Persist explicit source coverage so unknown actions never mean no actions."""

    dataset_id = _ACTION_COVERAGE_DATASET

    def append(self, coverage: CorporateActionCoverage) -> CorporateActionCoverage:
        if not isinstance(coverage, CorporateActionCoverage):
            raise TypeError("append requires CorporateActionCoverage")
        self._append(
            entity_id=coverage.instrument_id,
            stable_id=f"{coverage.instrument_id}:{coverage.source_id}",
            value=coverage.as_dict(),
            revision=coverage.revision,
            source_id=coverage.source_id,
            source_checksum=coverage.source_checksum,
            valid_from=coverage.coverage_through,
            known_at=coverage.known_at,
            published_at=coverage.published_at,
            status=coverage.status,
        )
        return _mark_canonical_coverage(coverage)

    record = append

    def as_of(self, instrument_id: str, *, valid_at: str | datetime, known_at: str | datetime) -> tuple[CorporateActionCoverage, ...]:
        values = self._values(entity_id=instrument_id, decision_time=known_at)
        valid_cutoff = pd.Timestamp(_utc(valid_at, "valid_at"))
        known_cutoff = pd.Timestamp(_utc(known_at, "known_at"))
        rows = [_mark_canonical_coverage(_coverage_from_value(value)) for value in values]
        return tuple(
            sorted(
                (
                    item
                    for item in rows
                    if item.status == "active"
                    and pd.Timestamp(item.known_at) <= known_cutoff
                    and pd.Timestamp(item.coverage_through) >= valid_cutoff
                ),
                key=lambda item: (item.coverage_through, item.source_id),
            )
        )


class FXObservationStore(_ObservationStore):
    """Append-only dated FX store with source and reference/executable labels."""

    dataset_id = _FX_DATASET

    def append(self, observation: FXObservation) -> FXObservation:
        if not isinstance(observation, FXObservation):
            raise TypeError("append requires FXObservation")
        observation.validate()
        self._append(
            entity_id=observation.pair,
            stable_id=f"{observation.observation_id}:{observation.source_id}",
            value=observation.as_dict(),
            revision=observation.revision,
            source_id=observation.source_id,
            source_checksum=observation.source_checksum,
            valid_from=observation.valuation_at,
            known_at=observation.known_at,
            published_at=observation.published_at,
            status=observation.status,
        )
        return observation

    record = append

    def query(self, base_currency: str | None = None, quote_currency: str | None = None) -> tuple[FXObservation, ...]:
        pair = None
        if base_currency is not None and quote_currency is not None:
            pair = f"{_currency(base_currency, required=True)}/{_currency(quote_currency, required=True)}"
        elif base_currency is not None:
            pair = str(base_currency)
        return tuple(_fx_from_value(value) for value in self._values(entity_id=pair))

    def snapshot(self, *, known_at: str | datetime) -> tuple[FXObservation, ...]:
        """Return one active revision per stable lineage at a knowledge cutoff."""

        return tuple(_fx_from_value(value) for value in self._values(decision_time=known_at))

    def as_of(self, base_currency: str, quote_currency: str, *, valid_at: str | datetime, known_at: str | datetime) -> tuple[FXObservation, ...]:
        pair = f"{_currency(base_currency, required=True)}/{_currency(quote_currency, required=True)}"
        values = self._values(entity_id=pair, decision_time=known_at)
        cutoff = pd.Timestamp(_utc(known_at, "known_at"))
        valid_cutoff = pd.Timestamp(_utc(valid_at, "valid_at"))
        rows = [_fx_from_value(value) for value in values]
        eligible = [item for item in rows if pd.Timestamp(item.known_at) <= cutoff and pd.Timestamp(item.valid_at) <= valid_cutoff and item.status == "active"]
        if not eligible:
            return ()
        latest_valid = max(pd.Timestamp(item.valid_at) for item in eligible)
        return tuple(sorted((item for item in eligible if pd.Timestamp(item.valid_at) == latest_valid), key=lambda item: (item.valid_at, item.source_id)))

    replay = as_of


@dataclass(frozen=True)
class ProviderReconciliation:
    status: str
    observations: tuple[CorporateAction | FXObservation, ...]
    discrepancies: tuple[str, ...]
    selected_source_id: str | None
    tolerance: float
    execution_allowed: bool = False

    @property
    def available(self) -> bool:
        return self.status == "reconciled"

    @property
    def candidates(self) -> tuple[Mapping[str, object], ...]:
        return tuple(item.as_dict() for item in self.observations)


def _candidate_signature(action: CorporateAction) -> tuple[float, float, str | None, float, str]:
    return (action.quantity_factor, action.cash_amount, action.currency, action.withholding_rate, action.event_at)


def reconcile_provider_observations(*groups: Sequence[CorporateAction | FXObservation], tolerance: float = 1e-8) -> ProviderReconciliation:
    """Retain all provider candidates and quarantine material disagreement."""

    if tolerance < 0:
        raise MarketAdjustmentError("tolerance cannot be negative")
    observations = tuple(item for group in groups for item in group)
    if not observations:
        return ProviderReconciliation("unavailable", (), ("no_provider_observations",), None, tolerance)
    discrepancies: list[str] = []
    first = observations[0]
    for other in observations[1:]:
        if isinstance(first, CorporateAction) and isinstance(other, CorporateAction):
            left = _candidate_signature(first)
            right = _candidate_signature(other)
            if left[2:] != right[2:] or not math.isclose(left[0], right[0], rel_tol=tolerance, abs_tol=tolerance) or not math.isclose(left[1], right[1], rel_tol=tolerance, abs_tol=tolerance):
                discrepancies.append(f"{first.source_id}!={other.source_id}:action_terms")
        elif isinstance(first, FXObservation) and isinstance(other, FXObservation):
            if first.pair != other.pair or first.valuation_at != other.valuation_at or not math.isclose(float(str(first.rate)), float(str(other.rate)), rel_tol=tolerance, abs_tol=tolerance):
                discrepancies.append(f"{first.source_id}!={other.source_id}:fx_rate")
        else:
            discrepancies.append("mixed_observation_types")
    if discrepancies:
        return ProviderReconciliation("quarantined", observations, tuple(discrepancies), None, tolerance)
    ranked = sorted(observations, key=lambda item: (_authority_rank(getattr(item, "authority", "provider")), item.source_id))
    return ProviderReconciliation("reconciled", observations, (), ranked[0].source_id, tolerance)


@dataclass(frozen=True)
class AdjustmentResult:
    status: str
    frame: pd.DataFrame
    convention: str
    action_reconciliation: tuple[ProviderReconciliation, ...]
    warnings: tuple[str, ...] = ()
    price_return: float | None = None
    income_return: float | None = None
    total_return: float | None = None
    adjusted_prices: tuple[float, ...] = ()
    action_ids: tuple[str, ...] = ()
    applied_ratio: float = 1.0
    raw_prices: tuple[float, ...] = ()
    execution_allowed: bool = False
    _canonical_derivation_digest: str = field(default="", init=False, repr=False, compare=False)

    @property
    def available(self) -> bool:
        return self.status == "available"

    def round_trip(self, _raw_prices: Sequence[float] | None = None) -> tuple[float, ...]:
        if self.raw_prices:
            return self.raw_prices
        return tuple(float(value) for value in (_raw_prices or ()))


def _adjustment_frame_digest(frame: pd.DataFrame) -> str:
    payload = frame.to_json(
        orient="split",
        date_format="iso",
        date_unit="ns",
        double_precision=15,
        index=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _adjustment_derivation_digest(result: AdjustmentResult) -> str:
    payload = {
        "status": result.status,
        "frame_sha256": _adjustment_frame_digest(result.frame),
        "convention": result.convention,
        "action_reconciliation": [asdict(item) for item in result.action_reconciliation],
        "warnings": list(result.warnings),
        "price_return": result.price_return,
        "income_return": result.income_return,
        "total_return": result.total_return,
        "adjusted_prices": list(result.adjusted_prices),
        "action_ids": list(result.action_ids),
        "applied_ratio": result.applied_ratio,
        "raw_prices": list(result.raw_prices),
        "execution_allowed": result.execution_allowed,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mark_canonical_adjustment(result: AdjustmentResult) -> AdjustmentResult:
    object.__setattr__(result, "_canonical_derivation_digest", _adjustment_derivation_digest(result))
    return result


def is_canonical_adjustment_result(value: object) -> bool:
    """Return whether the canonical adjustment generator issued this unchanged result."""

    return (
        isinstance(value, AdjustmentResult)
        and bool(value._canonical_derivation_digest)
        and value._canonical_derivation_digest == _adjustment_derivation_digest(value)
    )


def apply_total_return_adjustments(
    raw_prices: pd.DataFrame | Sequence[float] | None = None,
    actions: Sequence[CorporateAction] = (),
    *,
    prices: Sequence[float] | None = None,
    convention: str = "reinvest_on_ex_date",
    discrepancy_tolerance: float = 1e-8,
) -> AdjustmentResult:
    """Derive adjusted and total-return series without modifying raw prices."""

    if prices is not None:
        raw_prices = prices
    if raw_prices is None:
        raise MarketAdjustmentError("prices are required")
    if convention not in _TOTAL_RETURN_CONVENTIONS:
        raise MarketAdjustmentError(f"unsupported total-return convention: {convention}")
    for action in actions:
        action.validate()
    if not isinstance(raw_prices, pd.DataFrame):
        values = tuple(float(value) for value in raw_prices)
        if len(values) < 2 or any(not math.isfinite(value) or value <= 0 for value in values):
            raise MarketAdjustmentError("prices require at least two positive values")
        ratio = math.prod(item.quantity_factor for item in actions if item.action_type == "split")
        adjusted = (*tuple(value / ratio for value in values[:-1]), values[-1])
        price_return = values[-1] * ratio / values[0] - 1.0
        income_return = sum(item.net_cash_amount for item in actions if item.cash_flow_classification == "investment_income") / values[0]
        security_cash = sum(item.net_cash_amount for item in actions)
        total_return = (values[-1] * ratio + security_cash) / values[0] - 1.0
        return _mark_canonical_adjustment(AdjustmentResult(
            "available",
            pd.DataFrame({"raw_close": values, "adjusted_close": adjusted}),
            convention,
            (),
            (),
            price_return,
            income_return,
            total_return,
            adjusted,
            tuple(item.action_id for item in actions),
            ratio,
            values,
        ))
    required = {"date", "close"}
    missing = required - set(raw_prices.columns)
    if missing:
        raise MarketAdjustmentError(f"raw prices require columns: {', '.join(sorted(missing))}")
    frame = raw_prices.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if frame["date"].isna().any() or frame["close"].isna().any() or frame["close"].le(0).any():
        raise MarketAdjustmentError("raw prices contain invalid dates or non-positive close values")
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    frame["raw_close"] = frame["close"].astype(float)

    by_identity: dict[tuple[str, str], list[CorporateAction]] = defaultdict(list)
    for action in actions:
        by_identity[(action.action_id, action.action_type)].append(action)
    reconciliations: list[ProviderReconciliation] = []
    selected: list[CorporateAction] = []
    warnings: list[str] = []
    for candidates in by_identity.values():
        report = reconcile_provider_observations(candidates, tolerance=discrepancy_tolerance)
        reconciliations.append(report)
        if not report.available or report.selected_source_id is None:
            warnings.append(f"quarantined_action:{candidates[0].action_id}")
            continue
        selected.append(next(item for item in candidates if item.source_id == report.selected_source_id))
    if any(item.status == "quarantined" for item in reconciliations):
        return _mark_canonical_adjustment(AdjustmentResult("quarantined", _unavailable_adjustment_frame(frame), convention, tuple(reconciliations), tuple(warnings)))

    events: dict[pd.Timestamp, list[CorporateAction]] = defaultdict(list)
    for action in selected:
        event_value = action.event_at if convention == "reinvest_on_ex_date" else action.payable_at or action.event_at
        event_date = pd.Timestamp(_utc(event_value, "action_event_at")).normalize()
        events[event_date].append(action)

    local_returns: list[float] = [math.nan]
    price_returns: list[float] = [math.nan]
    quantities: list[float] = [1.0]
    cashflows: list[float] = [0.0]
    income: list[float] = [0.0]
    principal: list[float] = [0.0]
    action_ids: list[str] = [""]
    for index in range(1, len(frame)):
        previous = float(frame.loc[index - 1, "raw_close"])
        current = float(frame.loc[index, "raw_close"])
        day_actions = events.get(pd.Timestamp(frame.loc[index, "date"]).normalize(), [])
        quantity_factor = math.prod(item.quantity_factor for item in day_actions)
        net_cash = sum(item.net_cash_amount for item in day_actions)
        income_cash = sum(item.net_cash_amount for item in day_actions if item.cash_flow_classification == "investment_income")
        principal_cash = sum(item.net_cash_amount for item in day_actions if item.cash_flow_classification == "security_principal")
        price_return = current / previous - 1.0
        total_return = (current * quantity_factor + net_cash) / previous - 1.0
        price_returns.append(price_return)
        local_returns.append(total_return)
        quantities.append(quantity_factor)
        cashflows.append(net_cash)
        income.append(income_cash)
        principal.append(principal_cash)
        action_ids.append(",".join(sorted(item.action_id for item in day_actions)))
    frame["price_return"] = price_returns
    frame["local_total_return"] = local_returns
    frame["quantity_factor"] = quantities
    frame["security_cash_flow"] = cashflows
    frame["investment_income"] = income
    frame["security_principal"] = principal
    frame["external_flow"] = 0.0
    frame["action_ids"] = action_ids
    wealth = (1.0 + frame["local_total_return"].fillna(0.0)).cumprod()
    frame["total_return_index"] = 100.0 * wealth
    frame["adjusted_close"] = frame["total_return_index"] * float(frame["raw_close"].iloc[-1]) / float(frame["total_return_index"].iloc[-1])
    frame["total_return_convention"] = convention
    frame["execution_allowed"] = False
    return _mark_canonical_adjustment(AdjustmentResult("available", frame, convention, tuple(reconciliations), tuple(warnings)))


def _unavailable_adjustment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    unavailable = frame.copy()
    for column in ("price_return", "local_total_return", "total_return_index", "adjusted_close"):
        unavailable[column] = math.nan
    unavailable["execution_allowed"] = False
    return unavailable


@dataclass(frozen=True)
class AdjustmentReconciliation:
    status: str
    max_residual: float | None
    rows_checked: int
    discrepancies: tuple[str, ...]
    reconciled: bool = False
    action_ids: tuple[str, ...] = ()
    execution_allowed: bool = False


    @property
    def available(self) -> bool:
        return self.status == "available"


def reconcile_adjustments(
    result: AdjustmentResult | pd.DataFrame | Sequence[float] | None = None,
    adjusted_prices: Sequence[float] | None = None,
    actions: Sequence[CorporateAction] = (),
    *,
    raw_prices: Sequence[float] | None = None,
    tolerance: float = 1e-10,
) -> AdjustmentReconciliation:
    if raw_prices is not None:
        result = raw_prices
    if result is None:
        return AdjustmentReconciliation("unavailable", None, 0, ("missing_adjustment_data",))
    if not isinstance(result, (AdjustmentResult, pd.DataFrame)):
        raw = tuple(float(value) for value in result)
        adjusted = tuple(float(value) for value in (adjusted_prices or ()))
        if len(raw) != len(adjusted) or not raw:
            return AdjustmentReconciliation("unavailable", None, 0, ("mismatched_price_series",))
        ratio = math.prod(item.quantity_factor for item in actions if item.action_type == "split")
        expected = (*tuple(value / ratio for value in raw[:-1]), raw[-1])
        sequence_residuals = [abs(left - right) for left, right in zip(expected, adjusted, strict=True)]
        maximum = max(sequence_residuals, default=0.0)
        discrepancies = () if maximum <= tolerance else (f"adjustment_residual={maximum:.12g}",)
        return AdjustmentReconciliation("available" if not discrepancies else "quarantined", maximum, len(raw), discrepancies, not discrepancies, tuple(item.action_id for item in actions))
    frame = result.frame if isinstance(result, AdjustmentResult) else result
    required = {"raw_close", "local_total_return", "quantity_factor", "security_cash_flow"}
    if not required.issubset(frame.columns):
        return AdjustmentReconciliation("unavailable", None, 0, ("missing_adjustment_columns",))
    residuals: list[float] = []
    for index in range(1, len(frame)):
        observed = float(frame.iloc[index]["local_total_return"])
        expected_return = (float(frame.iloc[index]["raw_close"]) * float(frame.iloc[index]["quantity_factor"]) + float(frame.iloc[index]["security_cash_flow"])) / float(frame.iloc[index - 1]["raw_close"]) - 1.0
        residuals.append(abs(observed - expected_return))
    maximum = max(residuals, default=0.0)
    discrepancies = () if maximum <= tolerance else (f"adjustment_identity_residual={maximum:.12g}",)
    return AdjustmentReconciliation("available" if not discrepancies else "quarantined", maximum, len(residuals), discrepancies, not discrepancies)


@dataclass(frozen=True)
class FXRateResult:
    status: str
    rate: float | None
    base_currency: str
    quote_currency: str
    valuation_at: str
    source_ids: tuple[str, ...]
    source_checksums: tuple[str, ...]
    path: tuple[str, ...]
    rate_label: str | None
    discrepancies: tuple[str, ...] = ()
    execution_allowed: bool = False

    @property
    def available(self) -> bool:
        return self.status == "available" and self.rate is not None

    @property
    def executable(self) -> bool:
        return self.available and self.rate_label == "executable"


def _authority_rank(authority: str) -> int:
    return {"official": 0, "regulated": 1, "broker": 2, "provider": 3, "manual": 4}.get(str(authority), 9)


def _dated_candidates(observations: Sequence[FXObservation], valuation_at: str | datetime, decision_time: str | datetime | None, max_age_days: int) -> list[FXObservation]:
    target = pd.Timestamp(_utc(valuation_at, "valuation_at"))
    decision = pd.Timestamp(_utc(decision_time or valuation_at, "decision_time"))
    eligible = [item for item in observations if item.status == "active" and pd.Timestamp(item.valuation_at) <= target and pd.Timestamp(item.available_at or item.known_at) <= decision]
    if not eligible:
        return []
    latest_date = max(pd.Timestamp(item.valuation_at) for item in eligible)
    if target - latest_date > timedelta(days=max_age_days):
        return []
    return [item for item in eligible if pd.Timestamp(item.valuation_at) == latest_date]


def _select_fx_edge(candidates: Sequence[FXObservation], *, tolerance: float) -> tuple[float | None, tuple[FXObservation, ...], tuple[str, ...], str | None]:
    if not candidates:
        return None, (), ("missing_or_stale_fx",), None
    best_rank = min(_authority_rank(item.authority) for item in candidates)
    ranked = tuple(item for item in candidates if _authority_rank(item.authority) == best_rank)
    reference = float(str(ranked[0].rate))
    if any(not math.isclose(float(str(item.rate)), reference, rel_tol=tolerance, abs_tol=tolerance) for item in ranked[1:]):
        return None, ranked, ("conflicted_fx_sources",), None
    labels = {item.rate_label for item in ranked}
    label = "executable" if labels == {"executable"} else "reference" if "reference" in labels else "indicative"
    return reference, ranked, (), label


def derive_fx_cross(
    observations: Sequence[FXObservation] | FXObservationStore,
    base_currency: str,
    quote_currency: str,
    valuation_at: str | datetime | None = None,
    *,
    as_of: str | datetime | None = None,
    decision_time: str | datetime | None = None,
    tolerance: float = 1e-6,
    max_age_days: int = 3,
) -> FXRateResult:
    """Resolve a dated direct/inverse/cross rate and reject inconsistent paths."""

    target_value = as_of or valuation_at
    if target_value is None:
        raise MarketAdjustmentError("as_of is required")
    if isinstance(observations, FXObservationStore):
        observations = observations.snapshot(known_at=decision_time or target_value)
    base = _currency(base_currency, required=True) or ""
    quote = _currency(quote_currency, required=True) or ""
    target = _utc(target_value, "valuation_at")
    if base == quote:
        return FXRateResult("available", 1.0, base, quote, target, (), (), (base,), "reference")
    edges: dict[str, list[tuple[str, float, tuple[FXObservation, ...], str]]] = defaultdict(list)
    pairs = {(item.base_currency, item.quote_currency) for item in observations}
    discrepancies: list[str] = []
    for left, right in pairs:
        dated = _dated_candidates([item for item in observations if item.base_currency == left and item.quote_currency == right], target_value, decision_time, max_age_days)
        rate, selected, errors, label = _select_fx_edge(dated, tolerance=tolerance)
        discrepancies.extend(f"{left}/{right}:{error}" for error in errors)
        if rate is None or label is None:
            continue
        edges[left].append((right, rate, selected, label))
        edges[right].append((left, 1.0 / rate, selected, label))
    requested_pair_conflicts = {
        f"{base}/{quote}:conflicted_fx_sources",
        f"{quote}/{base}:conflicted_fx_sources",
    }
    if requested_pair_conflicts.intersection(discrepancies):
        return FXRateResult("quarantined", None, base, quote, target, (), (), (), None, tuple(sorted(set(discrepancies))))
    if discrepancies and not edges:
        return FXRateResult("quarantined" if any("conflicted" in item for item in discrepancies) else "unavailable", None, base, quote, target, (), (), (), None, tuple(sorted(discrepancies)))

    paths: list[tuple[float, tuple[str, ...], tuple[FXObservation, ...], str]] = []
    queue: deque[tuple[str, float, tuple[str, ...], tuple[FXObservation, ...], str]] = deque([(base, 1.0, (base,), (), "executable")])
    while queue:
        currency, rate, path, used, label = queue.popleft()
        if len(path) > 4:
            continue
        for neighbour, edge_rate, sources, edge_label in edges.get(currency, []):
            if neighbour in path:
                continue
            next_path = (*path, neighbour)
            next_used = (*used, *sources)
            next_label = "executable" if label == edge_label == "executable" else "reference" if "reference" in {label, edge_label} else "indicative"
            next_rate = rate * edge_rate
            if neighbour == quote:
                paths.append((next_rate, next_path, next_used, next_label))
            else:
                queue.append((neighbour, next_rate, next_path, next_used, next_label))
    if not paths:
        status = "quarantined" if any("conflicted" in item for item in discrepancies) else "unavailable"
        return FXRateResult(status, None, base, quote, target, (), (), (), None, tuple(sorted(set(discrepancies or ["missing_or_stale_fx"]))))
    shortest = min(len(item[1]) for item in paths)
    comparable = [item for item in paths if len(item[1]) <= shortest + 1]
    chosen = sorted(comparable, key=lambda item: (len(item[1]), item[1]))[0]
    if any(not math.isclose(item[0], chosen[0], rel_tol=tolerance, abs_tol=tolerance) for item in comparable[1:]):
        return FXRateResult("quarantined", None, base, quote, target, (), (), (), None, ("triangular_inconsistency",))
    used = chosen[2]
    return FXRateResult(
        "available",
        chosen[0],
        base,
        quote,
        target,
        tuple(item.source_id for item in used),
        tuple(item.source_checksum for item in used),
        tuple(f"{chosen[1][index]}/{chosen[1][index + 1]}" for index in range(len(chosen[1]) - 1)),
        chosen[3],
        tuple(sorted(set(discrepancies))),
    )


@dataclass(frozen=True)
class SelectedCurrencyReturn:
    status: str
    local_return: float | None
    fx_return: float | None
    output_return: float | None
    identity_residual: float | None
    transaction_at: str | None = None
    valuation_at: str | None = None
    transaction_rate: float | None = None
    valuation_rate: float | None = None
    reason_code: str | None = None
    rate_is_reference: bool = False
    executable: bool = False
    execution_allowed: bool = False
    source_ids: tuple[str, ...] = ()
    source_checksums: tuple[str, ...] = ()
    rate_label: str | None = None

    @property
    def available(self) -> bool:
        return self.status == "available"


def selected_currency_return(
    local_return: float | None,
    fx_return: float | None = None,
    *,
    start_rate: float | None = None,
    end_rate: float | None = None,
    transaction_at: str | datetime | None = None,
    valuation_at: str | datetime | None = None,
    base_currency: str | None = None,
    output_currency: str | None = None,
    fx_store: FXObservationStore | None = None,
    max_age_days: int = 3,
) -> SelectedCurrencyReturn:
    """Apply the canonical multiplicative local/FX realised-return identity."""

    if local_return is None:
        return SelectedCurrencyReturn("unavailable", None, None, None, None)
    local = float(local_return)
    if not math.isfinite(local) or local <= -1:
        raise MarketAdjustmentError("local_return must be finite and greater than -1")
    if fx_store is None:
        return SelectedCurrencyReturn("unavailable", local, None, None, None, reason_code="FX_SOURCE_UNLINKED")
    if fx_return is not None or start_rate is not None or end_rate is not None:
        return SelectedCurrencyReturn("unavailable", local, None, None, None, reason_code="FX_SOURCE_UNLINKED")
    reference_rate = False
    executable_rate = False
    source_ids: tuple[str, ...] = ()
    source_checksums: tuple[str, ...] = ()
    start: float | None = None
    end: float | None = None
    transaction_timestamp: str | None = None
    valuation_timestamp: str | None = None
    if fx_store is not None:
        if base_currency is None or output_currency is None or valuation_at is None:
            return SelectedCurrencyReturn("unavailable", local, None, None, None, reason_code="FX_MISSING")
        observations = fx_store.snapshot(known_at=valuation_at)
        if not observations:
            return SelectedCurrencyReturn("unavailable", local, None, None, None, reason_code="FX_MISSING")
        valuation_timestamp = _utc(valuation_at, "valuation_at")
        eligible = [item for item in observations if pd.Timestamp(item.valid_at) <= pd.Timestamp(valuation_timestamp) and pd.Timestamp(item.known_at) <= pd.Timestamp(valuation_timestamp)]
        if not eligible:
            return SelectedCurrencyReturn("unavailable", local, None, None, None, reason_code="FX_MISSING")
        transaction_timestamp = _utc(transaction_at, "transaction_at") if transaction_at is not None else min(item.valid_at for item in eligible)
        if pd.Timestamp(transaction_timestamp) > pd.Timestamp(valuation_timestamp):
            raise MarketAdjustmentError("valuation_at cannot precede transaction_at")
        start_result = derive_fx_cross(fx_store, base_currency, output_currency, as_of=transaction_timestamp, decision_time=transaction_timestamp, max_age_days=max_age_days)
        end_result = derive_fx_cross(fx_store, base_currency, output_currency, as_of=valuation_timestamp, decision_time=valuation_timestamp, max_age_days=max_age_days)
        failed = end_result if not end_result.available else start_result
        if not start_result.available or not end_result.available:
            conflicted = failed.status == "quarantined" or any("conflict" in item for item in failed.discrepancies)
            reason = "FX_CONFLICTED" if conflicted else "FX_STALE" if observations else "FX_MISSING"
            return SelectedCurrencyReturn("unavailable", local, None, None, None, transaction_timestamp, valuation_timestamp, reason_code=reason)
        start = float(start_result.rate or 0.0)
        end = float(end_result.rate or 0.0)
        fx_return = end / start - 1.0
        reference_rate = start_result.rate_label == "reference" or end_result.rate_label == "reference"
        executable_rate = start_result.executable and end_result.executable
        source_ids = tuple(dict.fromkeys((*start_result.source_ids, *end_result.source_ids)))
        source_checksums = tuple(dict.fromkeys((*start_result.source_checksums, *end_result.source_checksums)))
    fx = float(fx_return)
    if not math.isfinite(fx) or fx <= -1:
        raise MarketAdjustmentError("fx_return must be finite and greater than -1")
    output = (1.0 + local) * (1.0 + fx) - 1.0
    residual = output - (local + fx + local * fx)
    return SelectedCurrencyReturn(
        "available",
        local,
        fx,
        output,
        residual,
        transaction_timestamp,
        valuation_timestamp,
        start,
        end,
        None,
        reference_rate,
        executable_rate,
        False,
        source_ids,
        source_checksums,
        "reference" if reference_rate else "executable" if executable_rate else "indicative",
    )


def _action_from_value(value: Mapping[str, object]) -> CorporateAction:
    allowed = CorporateAction.__dataclass_fields__
    payload = {key: item for key, item in value.items() if key in allowed and key != "execution_allowed"}
    return CorporateAction(**cast(Any, payload))


def _coverage_from_value(value: Mapping[str, object]) -> CorporateActionCoverage:
    allowed = CorporateActionCoverage.__dataclass_fields__
    payload = {key: item for key, item in value.items() if key in allowed and key != "execution_allowed"}
    return CorporateActionCoverage(**cast(Any, payload))


def _fx_from_value(value: Mapping[str, object]) -> FXObservation:
    allowed = FXObservation.__dataclass_fields__
    payload = {key: item for key, item in value.items() if key in allowed and key != "execution_allowed"}
    payload["rate"] = Decimal(str(payload["rate"]))
    return FXObservation(**cast(Any, payload))


def evidence_checksum(values: Iterable[CorporateAction | CorporateActionCoverage | FXObservation]) -> str:
    payload = [item.as_dict() for item in values]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


__all__ = [
    "AdjustmentReconciliation",
    "AdjustmentResult",
    "CorporateAction",
    "CorporateActionCoverage",
    "CorporateActionCoverageStore",
    "CorporateActionStore",
    "CorporateActionType",
    "FXObservation",
    "FXObservationStore",
    "FXRateResult",
    "MarketAdjustmentError",
    "ProviderReconciliation",
    "SelectedCurrencyReturn",
    "apply_total_return_adjustments",
    "derive_fx_cross",
    "evidence_checksum",
    "reconcile_adjustments",
    "reconcile_provider_observations",
    "selected_currency_return",
]
