"""Point-in-time fixed-income terms and contractual cash-flow schedules.

This module is deliberately limited to fixed-rate and zero-coupon government
and corporate bonds. It stores immutable source/overlay versions, delegates
calendar adjustment to :class:`MarketCalendarService`, and never grants
pricing, screening, proposal, or execution authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping

from etf_cockpit.data.classification import InstrumentContextV2
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
    storage_layout,
)
from etf_cockpit.data.market_calendar import (
    BusinessDayConvention,
    DayCountConvention,
    MarketCalendarService,
    MarketClockError,
    SettlementCalendarEvidence,
)


FIXED_INCOME_TERMS_SCHEMA_VERSION = 1
FIXED_INCOME_TERMS_CONTRACT = "fixed-income-terms.v1"
_ENTITY_TYPE = "fixed_income_terms_v1"
_SUPPORTED_COUPON_TYPES = frozenset({"fixed_rate", "zero_coupon"})
_SUPPORTED_SECURITY_TYPES = frozenset({"government_bond", "corporate_bond"})
_CURRENCIES = re.compile(r"^[A-Z]{3}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FixedIncomeTermsError(ValueError):
    """Raised when terms cannot be represented without inventing evidence."""


class FixedIncomeTermsSchemaError(RuntimeError):
    """Raised when persisted terms are corrupt or use an unknown contract."""


@dataclass(frozen=True)
class SettlementConvention:
    settlement_business_days: int
    business_day_convention: BusinessDayConvention
    payment_calendar: SettlementCalendarEvidence
    ex_coupon_business_days: int = 0


@dataclass(frozen=True)
class OptionalitySchedule:
    features: tuple[str, ...] = ()
    source_id: str = ""

    @property
    def unsupported_features(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(feature).strip().lower()
                    for feature in self.features
                    if str(feature).strip()
                }
            )
        )


@dataclass(frozen=True)
class FixedIncomeSecurityTerms:
    instrument_id: str
    issuer_id: str
    security_type: str
    currency: str
    issue_date: date
    maturity_date: date
    face_value: Decimal
    minimum_denomination: Decimal
    denomination_increment: Decimal
    coupon_type: str
    coupon_rate: Decimal
    coupon_frequency: int
    day_count: DayCountConvention
    settlement: SettlementConvention
    source_id: str
    source_checksum: str
    valid_from: datetime
    known_at: datetime
    retrieved_at: datetime
    revision: int = 1
    valid_to: datetime | None = None
    overlay_of: str | None = None
    confidence: str = "high"
    conflict_ids: tuple[str, ...] = ()
    optionality: OptionalitySchedule = OptionalitySchedule()
    guarantor_id: str | None = None
    seniority: str | None = None
    secured_status: str | None = None
    cfi: str | None = None
    country: str | None = None
    source_document: str | None = None
    schema_version: int = FIXED_INCOME_TERMS_SCHEMA_VERSION

    @property
    def version_id(self) -> str:
        return _hash(_terms_payload(self))


@dataclass(frozen=True)
class CouponPayment:
    sequence: int
    accrual_start: date
    accrual_end: date
    contractual_date: date
    payment_date: date
    ex_coupon_date: date
    amount: Decimal
    currency: str
    source_version_id: str
    source_id: str
    source_checksum: str


@dataclass(frozen=True)
class CouponSchedule:
    instrument_id: str
    payments: tuple[CouponPayment, ...]
    source_version_id: str


@dataclass(frozen=True)
class RedemptionPayment:
    contractual_date: date
    payment_date: date
    amount: Decimal
    currency: str
    source_version_id: str
    source_id: str
    source_checksum: str


@dataclass(frozen=True)
class RedemptionSchedule:
    instrument_id: str
    payments: tuple[RedemptionPayment, ...]
    source_version_id: str


@dataclass(frozen=True)
class FixedIncomeTermsResolution:
    terms: FixedIncomeSecurityTerms | None
    coupon_schedule: CouponSchedule | None
    redemption_schedule: RedemptionSchedule | None
    history: tuple[FixedIncomeSecurityTerms, ...]
    excluded_versions: tuple[FixedIncomeSecurityTerms, ...]
    status: str
    reason_codes: tuple[str, ...]
    capability_flags: Mapping[str, bool]
    execution_allowed: bool = False
    pricing_allowed: bool = False
    screening_allowed: bool = False
    proposal_allowed: bool = False


class FixedIncomeTermsStore:
    """Append-only local terms store sharing canonical identity and storage."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        try:
            self._store = TransactionalStore(self.root)
        except (StorageSchemaError, sqlite3.DatabaseError, OSError) as exc:
            raise FixedIncomeTermsSchemaError(
                f"fixed-income terms storage is unavailable: {exc}"
            ) from exc
        try:
            self._validate_records()
        except Exception:
            self._store.close()
            raise

    def __enter__(self) -> FixedIncomeTermsStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._store.close()

    def append(
        self, terms: Iterable[FixedIncomeSecurityTerms]
    ) -> tuple[str, ...]:
        items = tuple(_normalise_terms(item) for item in terms)
        if not items:
            return ()
        for item in items:
            try:
                with IdentityMasterStore(self.root) as identity:
                    resolved_identity = identity.resolve(item.instrument_id)
            except KeyError as exc:
                raise FixedIncomeTermsError(
                    f"canonical identity unavailable for {item.instrument_id}"
                ) from exc
            object_keys = {
                (value.object_type, value.object_id)
                for value in resolved_identity.objects
            }
            instrument_key_present = any(
                object_id == item.instrument_id
                and object_type in {"instrument", "security", "debt_series"}
                for object_type, object_id in object_keys
            )
            issuer_key_present = any(
                object_id == item.issuer_id
                and object_type in {"issuer", "entity", "legal_entity"}
                for object_type, object_id in object_keys
            )
            if (
                not instrument_key_present
                or not issuer_key_present
                or any(
                    conflict.requires_manual_review
                    for conflict in resolved_identity.conflicts
                )
            ):
                raise FixedIncomeTermsError(
                    "shared identity is incomplete or conflicted for fixed-income terms"
                )
        existing = {item.version_id: item for item in self._load()}
        incoming = {item.version_id: item for item in items}
        for item in items:
            if item.overlay_of is None:
                continue
            parent = existing.get(item.overlay_of) or incoming.get(item.overlay_of)
            if parent is None or parent.instrument_id != item.instrument_id:
                raise FixedIncomeTermsError(
                    "overlay_of must reference retained terms for the same security"
                )
            if item.revision <= parent.revision:
                raise FixedIncomeTermsError(
                    "overlay revision must advance the referenced terms"
                )
        records = tuple(
            (_ENTITY_TYPE, item.version_id, _record_payload(item)) for item in items
        )
        try:
            self._store.put_many(records, immutable=True)
        except (StorageRevisionConflict, sqlite3.DatabaseError, TypeError, ValueError) as exc:
            raise FixedIncomeTermsSchemaError(
                f"fixed-income terms append rejected: {exc}"
            ) from exc
        return tuple(item.version_id for item in items)

    def resolve(
        self,
        instrument_id: str,
        *,
        effective_at: datetime | None = None,
        decision_time: datetime | None = None,
        classification: InstrumentContextV2 | None = None,
    ) -> FixedIncomeTermsResolution:
        canonical_id = str(instrument_id).strip()
        if not canonical_id:
            raise FixedIncomeTermsError("instrument_id is required")
        if classification is not None and classification.instrument_id != canonical_id:
            raise FixedIncomeTermsError("classification identity does not match terms")
        records = tuple(
            item
            for item in self._load()
            if item.instrument_id == canonical_id
        )
        if not records:
            raise KeyError(f"fixed-income terms unavailable for {canonical_id}")
        decision = _utc(decision_time or datetime.now(timezone.utc), "decision_time")
        effective = _utc(effective_at or decision, "effective_at")
        visible_history = tuple(
            item
            for item in records
            if item.known_at <= decision
            and item.retrieved_at <= decision
        )
        eligible = tuple(
            item
            for item in visible_history
            if item.valid_from <= effective
            and (item.valid_to is None or effective < item.valid_to)
        )
        if not eligible:
            return _unavailable(
                visible_history, "terms_not_known_at_decision_time"
            )
        highest_revision = max(item.revision for item in eligible)
        latest = tuple(
            item for item in eligible if item.revision == highest_revision
        )
        fingerprints = {_critical_fingerprint(item) for item in latest}
        selected = sorted(latest, key=lambda item: item.version_id)[-1]
        reasons: list[str] = []
        if len(fingerprints) > 1 or any(item.conflict_ids for item in latest):
            reasons.append("critical_terms_conflict")
        unsupported = selected.optionality.unsupported_features
        if selected.coupon_type not in _SUPPORTED_COUPON_TYPES:
            unsupported = tuple(sorted(set(unsupported) | {selected.coupon_type}))
        if selected.security_type not in _SUPPORTED_SECURITY_TYPES:
            unsupported = tuple(sorted(set(unsupported) | {selected.security_type}))
        if unsupported:
            reasons.append("unsupported_structure")
        if classification is not None:
            if classification.classification_status not in {"resolved", "reviewed"}:
                reasons.append("classification_unresolved")
            if classification.coupon_type and (
                classification.coupon_type.casefold() != selected.coupon_type
            ):
                reasons.append("classification_terms_conflict")
        if reasons:
            return FixedIncomeTermsResolution(
                terms=selected,
                coupon_schedule=None,
                redemption_schedule=None,
                history=tuple(sorted(visible_history, key=_version_sort_key)),
                excluded_versions=(),
                status="quarantined",
                reason_codes=tuple(dict.fromkeys(reasons)),
                capability_flags=_capabilities(False, unsupported),
            )
        try:
            coupons, redemptions = generate_contractual_schedules(
                selected, decision_time=decision
            )
        except (FixedIncomeTermsError, MarketClockError) as exc:
            return FixedIncomeTermsResolution(
                terms=selected,
                coupon_schedule=None,
                redemption_schedule=None,
                history=tuple(sorted(visible_history, key=_version_sort_key)),
                excluded_versions=(),
                status="quarantined",
                reason_codes=(f"schedule_invalid:{type(exc).__name__}",),
                capability_flags=_capabilities(False, ()),
            )
        return FixedIncomeTermsResolution(
            terms=selected,
            coupon_schedule=coupons,
            redemption_schedule=redemptions,
            history=tuple(sorted(visible_history, key=_version_sort_key)),
            excluded_versions=(),
            status="available",
            reason_codes=(),
            capability_flags=_capabilities(True, ()),
        )

    def projection(
        self,
        instrument_id: str,
        *,
        effective_at: datetime | None = None,
        decision_time: datetime | None = None,
        classification: InstrumentContextV2 | None = None,
    ) -> dict[str, object]:
        result = self.resolve(
            instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
            classification=classification,
        )
        terms = _jsonable(asdict(result.terms)) if result.terms else None
        coupons = (
            [_jsonable(asdict(item)) for item in result.coupon_schedule.payments]
            if result.coupon_schedule
            else []
        )
        redemptions = (
            [_jsonable(asdict(item)) for item in result.redemption_schedule.payments]
            if result.redemption_schedule
            else []
        )
        return {
            "schema_version": FIXED_INCOME_TERMS_SCHEMA_VERSION,
            "contract": FIXED_INCOME_TERMS_CONTRACT,
            "status": result.status,
            "instrument_id": instrument_id,
            "terms": terms,
            "coupon_schedule": coupons,
            "redemption_schedule": redemptions,
            "optionality_schedule": (
                _jsonable(asdict(result.terms.optionality)) if result.terms else None
            ),
            "history": [_jsonable(asdict(item)) for item in result.history],
            "excluded_versions": [
                _jsonable(asdict(item)) for item in result.excluded_versions
            ],
            "reason_codes": list(result.reason_codes),
            "capability_flags": dict(result.capability_flags),
            "pricing_allowed": False,
            "screening_allowed": False,
            "proposal_allowed": False,
            "execution_allowed": False,
        }

    def _load(self) -> tuple[FixedIncomeSecurityTerms, ...]:
        try:
            return tuple(_terms_from_payload(item.payload) for item in self._store.list(_ENTITY_TYPE))
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            raise FixedIncomeTermsSchemaError(
                f"fixed-income terms store is corrupt: {exc}"
            ) from exc

    def _validate_records(self) -> None:
        self._load()


def fixed_income_terms_exists(root: Path) -> bool:
    path = storage_layout(root).transactional_path
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='transactional_records'"
            ).fetchone()
            if table is None:
                return False
            return (
                connection.execute(
                    "SELECT 1 FROM transactional_records "
                    "WHERE entity_type=? AND deleted_at IS NULL LIMIT 1",
                    (_ENTITY_TYPE,),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise FixedIncomeTermsSchemaError(
            f"fixed-income terms store is unreadable: {exc}"
        ) from exc


def generate_contractual_schedules(
    terms: FixedIncomeSecurityTerms, *, decision_time: datetime
) -> tuple[CouponSchedule, RedemptionSchedule]:
    item = _normalise_terms(terms)
    calendar = MarketCalendarService()
    cutoff = _utc(decision_time, "decision_time")
    version_id = item.version_id
    contractual_dates: list[date] = []
    if item.coupon_type == "fixed_rate":
        months = 12 // item.coupon_frequency
        cursor = item.maturity_date
        while cursor > item.issue_date:
            contractual_dates.append(cursor)
            cursor = _add_months(cursor, -months)
        if cursor != item.issue_date:
            raise FixedIncomeTermsError(
                "irregular or stub coupon schedules require explicit unsupported terms"
            )
        contractual_dates.reverse()
    elif item.coupon_type != "zero_coupon":
        raise FixedIncomeTermsError("coupon structure is unsupported")
    payments: list[CouponPayment] = []
    accrual_start = item.issue_date
    coupon_amount = (
        item.face_value * item.coupon_rate / Decimal(item.coupon_frequency)
        if item.coupon_frequency
        else Decimal("0")
    )
    for sequence, contractual_date in enumerate(contractual_dates, start=1):
        if contractual_date <= accrual_start:
            raise FixedIncomeTermsError("coupon dates must be strictly monotonic")
        payment_date = calendar.coupon_date(
            item.settlement.payment_calendar,
            contractual_date,
            item.settlement.business_day_convention,
            knowledge_cutoff=cutoff,
        )
        ex_date = calendar.ex_date(
            item.settlement.payment_calendar,
            payment_date,
            item.settlement.ex_coupon_business_days,
            knowledge_cutoff=cutoff,
        )
        payments.append(
            CouponPayment(
                sequence,
                accrual_start,
                contractual_date,
                contractual_date,
                payment_date,
                ex_date,
                coupon_amount,
                item.currency,
                version_id,
                item.source_id,
                item.source_checksum,
            )
        )
        accrual_start = contractual_date
    redemption_date = calendar.coupon_date(
        item.settlement.payment_calendar,
        item.maturity_date,
        item.settlement.business_day_convention,
        knowledge_cutoff=cutoff,
    )
    return (
        CouponSchedule(item.instrument_id, tuple(payments), version_id),
        RedemptionSchedule(
            item.instrument_id,
            (
                RedemptionPayment(
                    item.maturity_date,
                    redemption_date,
                    item.face_value,
                    item.currency,
                    version_id,
                    item.source_id,
                    item.source_checksum,
                ),
            ),
            version_id,
        ),
    )


def _normalise_terms(terms: FixedIncomeSecurityTerms) -> FixedIncomeSecurityTerms:
    if not isinstance(terms, FixedIncomeSecurityTerms):
        raise FixedIncomeTermsError("terms must be FixedIncomeSecurityTerms")
    if terms.schema_version != FIXED_INCOME_TERMS_SCHEMA_VERSION:
        raise FixedIncomeTermsError("unsupported fixed-income terms schema")
    required = {
        "instrument_id": terms.instrument_id,
        "issuer_id": terms.issuer_id,
        "security_type": terms.security_type,
        "source_id": terms.source_id,
    }
    if any(not str(value).strip() for value in required.values()):
        raise FixedIncomeTermsError("identity and source fields are required")
    currency = str(terms.currency).strip().upper()
    if not _CURRENCIES.fullmatch(currency):
        raise FixedIncomeTermsError("currency must be an ISO-style three-letter code")
    if terms.maturity_date <= terms.issue_date:
        raise FixedIncomeTermsError("maturity_date must follow issue_date")
    face = _positive_decimal(terms.face_value, "face_value")
    minimum = _positive_decimal(terms.minimum_denomination, "minimum_denomination")
    increment = _positive_decimal(terms.denomination_increment, "denomination_increment")
    if minimum < increment or minimum % increment:
        raise FixedIncomeTermsError(
            "minimum denomination must be an exact increment multiple"
        )
    coupon_type = str(terms.coupon_type).strip().lower()
    rate = _decimal(terms.coupon_rate, "coupon_rate")
    if rate < 0 or rate > 1:
        raise FixedIncomeTermsError("coupon_rate must be between zero and one")
    if coupon_type == "zero_coupon" and (rate != 0 or terms.coupon_frequency != 0):
        raise FixedIncomeTermsError("zero-coupon terms require zero rate and frequency")
    if coupon_type == "fixed_rate" and (
        rate <= 0 or terms.coupon_frequency not in {1, 2, 4, 12}
    ):
        raise FixedIncomeTermsError("fixed-rate frequency/rate is invalid")
    if terms.revision < 1:
        raise FixedIncomeTermsError("revision must be positive")
    valid_from = _utc(terms.valid_from, "valid_from")
    known_at = _utc(terms.known_at, "known_at")
    retrieved_at = _utc(terms.retrieved_at, "retrieved_at")
    valid_to = _utc(terms.valid_to, "valid_to") if terms.valid_to else None
    if valid_to is not None and valid_to <= valid_from:
        raise FixedIncomeTermsError("valid_to must follow valid_from")
    if retrieved_at < known_at:
        raise FixedIncomeTermsError("retrieved_at cannot precede known_at")
    if not _SHA256.fullmatch(str(terms.source_checksum).casefold()):
        raise FixedIncomeTermsError("source_checksum must be SHA-256")
    if terms.confidence not in {"high", "medium", "low", "manual_review"}:
        raise FixedIncomeTermsError("confidence state is unsupported")
    settlement = terms.settlement
    if settlement.settlement_business_days < 0 or settlement.ex_coupon_business_days < 0:
        raise FixedIncomeTermsError("settlement and ex-coupon days cannot be negative")
    if settlement.payment_calendar.instrument_id != terms.instrument_id:
        raise FixedIncomeTermsError("settlement calendar identity mismatch")
    if terms.optionality.features and not str(terms.optionality.source_id).strip():
        raise FixedIncomeTermsError("optionality features require source lineage")
    return FixedIncomeSecurityTerms(
        **{
            **asdict(terms),
            "instrument_id": str(terms.instrument_id).strip(),
            "issuer_id": str(terms.issuer_id).strip(),
            "security_type": str(terms.security_type).strip().lower(),
            "currency": currency,
            "face_value": face,
            "minimum_denomination": minimum,
            "denomination_increment": increment,
            "coupon_type": coupon_type,
            "coupon_rate": rate,
            "day_count": DayCountConvention(terms.day_count),
            "settlement": SettlementConvention(
                int(settlement.settlement_business_days),
                BusinessDayConvention(settlement.business_day_convention),
                settlement.payment_calendar,
                int(settlement.ex_coupon_business_days),
            ),
            "valid_from": valid_from,
            "known_at": known_at,
            "retrieved_at": retrieved_at,
            "valid_to": valid_to,
            "source_checksum": str(terms.source_checksum).casefold(),
            "conflict_ids": tuple(sorted(set(terms.conflict_ids))),
            "optionality": OptionalitySchedule(
                tuple(sorted(set(terms.optionality.features))),
                str(terms.optionality.source_id).strip(),
            ),
        }
    )


def _record_payload(terms: FixedIncomeSecurityTerms) -> dict[str, object]:
    return {
        "schema_version": FIXED_INCOME_TERMS_SCHEMA_VERSION,
        "contract": FIXED_INCOME_TERMS_CONTRACT,
        "terms": _jsonable(asdict(terms)),
    }


def _terms_from_payload(payload: Mapping[str, Any]) -> FixedIncomeSecurityTerms:
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != FIXED_INCOME_TERMS_SCHEMA_VERSION
        or payload.get("contract") != FIXED_INCOME_TERMS_CONTRACT
        or not isinstance(payload.get("terms"), Mapping)
    ):
        raise FixedIncomeTermsSchemaError("fixed-income terms contract is unsupported")
    body = dict(payload["terms"])
    try:
        settlement_body = dict(body.pop("settlement"))
        calendar_body = dict(settlement_body.pop("payment_calendar"))
        optionality_body = dict(body.pop("optionality"))
        issue_date = date.fromisoformat(body.pop("issue_date"))
        maturity_date = date.fromisoformat(body.pop("maturity_date"))
        face_value = Decimal(body.pop("face_value"))
        minimum_denomination = Decimal(body.pop("minimum_denomination"))
        denomination_increment = Decimal(body.pop("denomination_increment"))
        coupon_rate = Decimal(body.pop("coupon_rate"))
        day_count = DayCountConvention(body.pop("day_count"))
        valid_from = _utc_text(body.pop("valid_from"))
        known_at = _utc_text(body.pop("known_at"))
        retrieved_at = _utc_text(body.pop("retrieved_at"))
        valid_to_raw = body.pop("valid_to", None)
        conflict_ids = tuple(body.pop("conflict_ids", ()))
        calendar_valid_from = date.fromisoformat(calendar_body.pop("valid_from"))
        calendar_valid_to_raw = calendar_body.pop("valid_to", None)
        calendar_known_at = _utc_text(calendar_body.pop("known_at"))
        calendar_conflicts = tuple(calendar_body.pop("conflict_ids", ()))
        terms = FixedIncomeSecurityTerms(
            **body,
            issue_date=issue_date,
            maturity_date=maturity_date,
            face_value=face_value,
            minimum_denomination=minimum_denomination,
            denomination_increment=denomination_increment,
            coupon_rate=coupon_rate,
            day_count=day_count,
            settlement=SettlementConvention(
                payment_calendar=SettlementCalendarEvidence(
                    **calendar_body,
                    valid_from=calendar_valid_from,
                    valid_to=(
                        date.fromisoformat(calendar_valid_to_raw)
                        if calendar_valid_to_raw
                        else None
                    ),
                    known_at=calendar_known_at,
                    conflict_ids=calendar_conflicts,
                ),
                settlement_business_days=int(
                    settlement_body["settlement_business_days"]
                ),
                business_day_convention=BusinessDayConvention(
                    settlement_body["business_day_convention"]
                ),
                ex_coupon_business_days=int(
                    settlement_body.get("ex_coupon_business_days", 0)
                ),
            ),
            optionality=OptionalitySchedule(
                tuple(optionality_body.get("features", ())),
                str(optionality_body.get("source_id", "")),
            ),
            valid_from=valid_from,
            known_at=known_at,
            retrieved_at=retrieved_at,
            valid_to=_utc_text(valid_to_raw) if valid_to_raw else None,
            conflict_ids=conflict_ids,
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise FixedIncomeTermsSchemaError(
            f"fixed-income terms payload is corrupt: {exc}"
        ) from exc
    return _normalise_terms(terms)


def _terms_payload(terms: FixedIncomeSecurityTerms) -> dict[str, object]:
    return {
        "schema_version": terms.schema_version,
        "terms": _jsonable(asdict(terms)),
        "execution_allowed": False,
    }


def _critical_fingerprint(terms: FixedIncomeSecurityTerms) -> str:
    payload = _terms_payload(terms)
    encoded_terms = payload["terms"]
    if not isinstance(encoded_terms, Mapping):
        raise FixedIncomeTermsError("terms fingerprint payload is invalid")
    body = dict(encoded_terms)
    for key in (
        "source_id",
        "source_checksum",
        "known_at",
        "retrieved_at",
        "confidence",
        "conflict_ids",
        "source_document",
    ):
        body.pop(key, None)
    return _hash(body)


def _unavailable(
    history: tuple[FixedIncomeSecurityTerms, ...],
    reason: str,
) -> FixedIncomeTermsResolution:
    return FixedIncomeTermsResolution(
        None,
        None,
        None,
        tuple(sorted(history, key=_version_sort_key)),
        (),
        "unavailable",
        (reason,),
        _capabilities(False, ()),
    )


def _capabilities(
    schedules_available: bool, unsupported: tuple[str, ...]
) -> dict[str, bool]:
    return {
        "terms_available": schedules_available,
        "contractual_schedule_available": schedules_available,
        "fixed_rate_supported": not unsupported,
        "zero_coupon_supported": not unsupported,
        "unsupported_structure_present": bool(unsupported),
        "pricing_allowed": False,
        "screening_allowed": False,
        "proposal_allowed": False,
        "execution_allowed": False,
    }


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - date.resolution).day
    return date(year, month, min(value.day, last_day))


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FixedIncomeTermsError(f"{field} must be decimal") from exc
    if not result.is_finite():
        raise FixedIncomeTermsError(f"{field} must be finite")
    return result


def _positive_decimal(value: object, field: str) -> Decimal:
    result = _decimal(value, field)
    if result <= 0:
        raise FixedIncomeTermsError(f"{field} must be positive")
    return result


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FixedIncomeTermsError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_text(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _utc(parsed, "timestamp")


def _version_sort_key(
    terms: FixedIncomeSecurityTerms,
) -> tuple[datetime, datetime, int, str]:
    return terms.known_at, terms.retrieved_at, terms.revision, terms.version_id


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
