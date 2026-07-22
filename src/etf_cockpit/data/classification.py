"""Point-in-time economic classification with explicit confidence and fallback.

Classification evidence is append-only local state.  The resolver prefers
official and issuer evidence, retains alternatives and conflicts, applies only
overrides known at the requested decision cut-off, and never grants execution
authority.  Instrument wrapper type and economic look-through are deliberately
separate: for example, a bond ETF remains an ETF whose asset class is fixed
income.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
    storage_layout,
)


CLASSIFICATION_SCHEMA_VERSION = 2
CLASSIFICATION_CONTRACT = "instrument-context.v2"
DEFAULT_LEAF_CONFIDENCE = 0.75

_META_TYPE = "classification_meta"
_META_ID = "schema"
_EVIDENCE_TYPE = "classification_evidence_v2"
_OVERRIDE_TYPE = "classification_override_v2"

_MULTI_FIELDS = frozenset(
    {
        "strategy_label",
        "business_model_tag",
        "revenue_region",
        "asset_region",
        "special_structure",
    }
)
_PROPRIETARY_FIELDS = frozenset(
    {
        "gics",
        "gics_code",
        "gics_industry",
        "gics_sector",
        "icb",
        "icb_code",
        "icb_industry",
        "icb_sector",
    }
)
_SUPPORTED_FIELDS = frozenset(
    {
        "entity_id",
        "share_class_id",
        "listing_or_quotation_id",
        "instrument_type",
        "asset_class",
        "sector",
        "industry",
        "strategy_label",
        "business_model_tag",
        "legal_domicile",
        "regulatory_country",
        "operating_country",
        "primary_listing_country",
        "revenue_region",
        "asset_region",
        "accounting_standard",
        "reporting_currency",
        "trading_currency",
        "dealing_currency",
        "share_class_currency",
        "hedging_currency",
        "market_cap_eur",
        "cap_bucket",
        "liquidity_bucket",
        "bond_type",
        "issuer_sector",
        "issuer_type",
        "seniority",
        "secured_status",
        "coupon_type",
        "rating_bucket",
        "maturity_bucket",
        "duration_bucket",
        "fund_structure",
        "management_style",
        "mandate",
        "benchmark",
        "distribution_policy",
        "fee_tier",
        "dealing_liquidity_class",
        "special_structure",
    }
)
_INSTRUMENT_TYPE_ALIASES = {
    "stock": "stock",
    "equity": "stock",
    "share": "stock",
    "common_stock": "stock",
    "equity_certificate": "stock",
    "certificate": "stock",
    "etf": "etf",
    "exchange_traded_fund": "etf",
    "ordinary_fund": "ordinary_fund",
    "fund": "ordinary_fund",
    "mutual_fund": "ordinary_fund",
    "open_end_fund": "ordinary_fund",
    "bond": "bond",
    "debt_security": "bond",
    "fixed_income_security": "bond",
}
_ASSET_CLASS_ALIASES = {
    "equity": "equity",
    "equities": "equity",
    "stock": "equity",
    "fixed_income": "fixed_income",
    "fixed income": "fixed_income",
    "bond": "fixed_income",
    "bonds": "fixed_income",
    "multi_asset": "multi_asset",
    "multi asset": "multi_asset",
    "cash": "cash",
    "commodity": "commodity",
    "commodities": "commodity",
    "real_estate": "real_estate",
    "real estate": "real_estate",
    "alternatives": "alternatives",
}


class ClassificationSchemaError(RuntimeError):
    """Raised when classification evidence cannot be decoded safely."""


@dataclass(frozen=True)
class ClassificationEvidence:
    """One immutable field-level source fact."""

    evidence_id: str
    instrument_id: str
    field: str
    value: str
    source: str
    authority: SourceAuthority
    source_id: str
    confidence: float
    valid_from: str | None = None
    valid_to: str | None = None
    available_at: str | None = None
    revision: int = 1
    source_checksum: str = ""
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassificationOverride:
    """One historically versioned user decision for a classification field."""

    override_id: str
    instrument_id: str
    field: str
    value: str
    reason: str
    reviewer: str
    valid_from: str
    available_at: str
    valid_to: str | None = None
    revision: int = 1
    dependent_score_keys: tuple[str, ...] = ()
    source_checksum: str = ""


@dataclass(frozen=True)
class AdapterRoute:
    """Fail-closed routing decision for sector-specific analysis."""

    allowed: bool
    adapter_id: str | None
    reason_code: str
    confidence: float
    context_version: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class InstrumentContextV2:
    """Resolved classification context kept separate from instrument identity."""

    instrument_id: str
    entity_id: str | None
    share_class_id: str | None
    listing_or_quotation_id: str | None
    instrument_type: str | None
    asset_class: str | None
    sector: str | None
    industry: str | None
    strategy_labels: tuple[str, ...]
    business_model_tags: tuple[str, ...]
    legal_domicile: str | None
    regulatory_country: str | None
    operating_country: str | None
    primary_listing_country: str | None
    revenue_regions: tuple[str, ...]
    asset_regions: tuple[str, ...]
    accounting_standard: str | None
    reporting_currency: str | None
    trading_currency: str | None
    dealing_currency: str | None
    share_class_currency: str | None
    hedging_currency: str | None
    market_cap_eur: str | None
    cap_bucket: str | None
    liquidity_bucket: str | None
    bond_type: str | None
    issuer_sector: str | None
    issuer_type: str | None
    seniority: str | None
    secured_status: str | None
    coupon_type: str | None
    rating_bucket: str | None
    maturity_bucket: str | None
    duration_bucket: str | None
    fund_structure: str | None
    management_style: str | None
    mandate: str | None
    benchmark: str | None
    distribution_policy: str | None
    fee_tier: str | None
    dealing_liquidity_class: str | None
    special_structures: tuple[str, ...]
    classification_status: str
    classification_confidence: float
    field_confidence: Mapping[str, float]
    fallback_path: tuple[str, ...]
    alternatives: Mapping[str, tuple[str, ...]]
    evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    override_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    effective_at: str
    decision_time: str
    schema_version: int
    version_id: str
    score_invalidation_token: str
    invalidated_score_keys: tuple[str, ...]
    dependent_scores_invalidated: bool
    sector_adapter_allowed: bool
    warnings: tuple[str, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class ClassificationAccuracy:
    correct: int
    total: int
    accuracy: float | None
    mismatches: tuple[str, ...]
    execution_allowed: bool = False


def resolve_instrument_context(
    evidence: Iterable[ClassificationEvidence],
    overrides: Iterable[ClassificationOverride] = (),
    *,
    effective_at: str | datetime | None = None,
    decision_time: str | datetime | None = None,
    min_leaf_confidence: float = DEFAULT_LEAF_CONFIDENCE,
) -> InstrumentContextV2:
    """Resolve one instrument from point-in-time evidence and overrides."""

    threshold = _confidence(min_leaf_confidence, "min_leaf_confidence")
    items = tuple(_normalise_evidence(item) for item in evidence)
    decisions = tuple(_normalise_override(item) for item in overrides)
    instrument_ids = {item.instrument_id for item in (*items, *decisions)}
    if len(instrument_ids) != 1:
        raise ClassificationSchemaError("classification resolution requires exactly one instrument_id")
    instrument_id = next(iter(instrument_ids))
    now = datetime.now(timezone.utc)
    effective_cutoff = _cutoff(effective_at) or now
    decision_cutoff = _cutoff(decision_time) or now

    eligible = tuple(
        item
        for item in items
        if _eligible(
            valid_from=item.valid_from,
            valid_to=item.valid_to,
            available_at=item.available_at,
            effective_at=effective_cutoff,
            decision_time=decision_cutoff,
        )
    )
    excluded = tuple(item for item in items if item not in eligible)
    grouped: dict[str, list[ClassificationEvidence]] = {}
    for item in eligible:
        grouped.setdefault(item.field, []).append(item)

    values: dict[str, str | None] = {}
    multi_values: dict[str, tuple[str, ...]] = {}
    confidences: dict[str, float] = {}
    alternatives: dict[str, tuple[str, ...]] = {}
    selected_ids: list[str] = []
    warnings: list[str] = []
    conflict_fields: set[str] = set()
    for field_name, candidates in sorted(grouped.items()):
        if field_name in _MULTI_FIELDS:
            selected, confidence, candidate_ids, retained = _select_multi(candidates)
            multi_values[field_name] = selected
            confidences[field_name] = confidence
            selected_ids.extend(candidate_ids)
            if retained:
                alternatives[field_name] = retained
            continue
        selected, confidence, candidate_ids, retained, conflicted = _select_scalar(candidates)
        values[field_name] = selected
        confidences[field_name] = confidence
        selected_ids.extend(candidate_ids)
        if retained:
            alternatives[field_name] = retained
        if conflicted:
            conflict_fields.add(field_name)
            warnings.append(f"conflicting_{field_name}_evidence")

    applicable_overrides = tuple(
        item
        for item in decisions
        if _eligible(
            valid_from=item.valid_from,
            valid_to=item.valid_to,
            available_at=item.available_at,
            effective_at=effective_cutoff,
            decision_time=decision_cutoff,
        )
    )
    applied_overrides: list[ClassificationOverride] = []
    for field_name in sorted({item.field for item in applicable_overrides}):
        candidates = tuple(item for item in applicable_overrides if item.field == field_name)
        selected, conflicted = _select_override(candidates)
        if conflicted or selected is None:
            conflict_fields.add(field_name)
            alternatives[field_name] = tuple(sorted({item.value for item in candidates}))
            values[field_name] = None
            multi_values.pop(field_name, None)
            warnings.append(f"conflicting_{field_name}_overrides")
            continue
        applied_overrides.append(selected)
        conflict_fields.discard(field_name)
        if field_name in _MULTI_FIELDS:
            multi_values[field_name] = (selected.value,)
        else:
            values[field_name] = selected.value
        confidences[field_name] = 1.0

    fallback: list[str] = []
    instrument_type = _canonical_instrument_type(values.get("instrument_type"))
    if values.get("instrument_type") and instrument_type is None:
        warnings.append("unsupported_instrument_type")
        fallback.append("instrument_type->unresolved")
    asset_class = _canonical_asset_class(values.get("asset_class"))
    if values.get("asset_class") and asset_class is None:
        warnings.append("unsupported_asset_class")
        fallback.append("asset_class->unresolved")
    if asset_class is None and instrument_type == "stock":
        asset_class = "equity"
        confidences["asset_class"] = confidences.get("instrument_type", 0.0)
        fallback.append("asset_class<-stock_rule")
    elif asset_class is None and instrument_type == "bond":
        asset_class = "fixed_income"
        confidences["asset_class"] = confidences.get("instrument_type", 0.0)
        fallback.append("asset_class<-bond_rule")
    elif asset_class is None and instrument_type in {"etf", "ordinary_fund"} and values.get("bond_type"):
        asset_class = "fixed_income"
        confidences["asset_class"] = min(
            confidences.get("instrument_type", 0.0),
            confidences.get("bond_type", 0.0),
        )
        fallback.append("asset_class<-bond_look_through_rule")

    sector = values.get("sector")
    industry = values.get("industry")
    if sector is not None and confidences.get("sector", 0.0) < threshold:
        alternatives.setdefault("sector", (sector,))
        sector = None
        industry = None
        fallback.append("sector->unresolved_low_confidence")
        warnings.append("sector_confidence_below_threshold")
    elif industry is not None and confidences.get("industry", 0.0) < threshold:
        alternatives.setdefault("industry", (industry,))
        industry = None
        fallback.append("industry->sector_low_confidence")
        warnings.append("industry_confidence_below_threshold")
    if sector is None and industry is not None:
        alternatives.setdefault("industry", (industry,))
        industry = None
        fallback.append("industry->unresolved_without_sector")

    essential_confidence = tuple(
        confidences.get(field_name, 0.0)
        for field_name in ("instrument_type", "asset_class")
        if (instrument_type if field_name == "instrument_type" else asset_class) is not None
    )
    overall_confidence = min(essential_confidence, default=0.0)
    unresolved_core = instrument_type is None or asset_class is None or bool(
        {"instrument_type", "asset_class"}.intersection(conflict_fields)
    )
    status = "unresolved" if unresolved_core else ("partial" if fallback or conflict_fields else "resolved")
    if not eligible:
        warnings.append("classification_evidence_unavailable_at_cutoff")

    override_ids = tuple(_override_key(item) for item in applied_overrides)
    invalidated_keys = tuple(
        sorted(
            {
                key
                for item in applied_overrides
                for key in (item.dependent_score_keys or (f"classification:{instrument_id}:*",))
            }
        )
    )
    source_ids = tuple(sorted({item.source_id for item in eligible}))
    context_payload = {
        "instrument_id": instrument_id,
        "selected_evidence_ids": sorted(set(selected_ids)),
        "override_ids": override_ids,
        "values": values,
        "multi_values": multi_values,
        "instrument_type": instrument_type,
        "asset_class": asset_class,
        "sector": sector,
        "industry": industry,
        "confidence": confidences,
        "fallback": fallback,
        "effective_at": _display_cutoff(effective_at),
        "decision_time": _display_cutoff(decision_time),
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
    }
    version_id = _hash(context_payload)
    score_token = _hash(
        {
            "instrument_id": instrument_id,
            "classification_version": version_id,
            "invalidated_score_keys": invalidated_keys,
        }
    )
    sector_allowed = bool(sector) and confidences.get("sector", 0.0) >= threshold and "sector" not in conflict_fields
    return InstrumentContextV2(
        instrument_id=instrument_id,
        entity_id=values.get("entity_id"),
        share_class_id=values.get("share_class_id"),
        listing_or_quotation_id=values.get("listing_or_quotation_id"),
        instrument_type=instrument_type,
        asset_class=asset_class,
        sector=sector,
        industry=industry,
        strategy_labels=multi_values.get("strategy_label", ()),
        business_model_tags=multi_values.get("business_model_tag", ()),
        legal_domicile=values.get("legal_domicile"),
        regulatory_country=values.get("regulatory_country"),
        operating_country=values.get("operating_country"),
        primary_listing_country=values.get("primary_listing_country"),
        revenue_regions=multi_values.get("revenue_region", ()),
        asset_regions=multi_values.get("asset_region", ()),
        accounting_standard=values.get("accounting_standard"),
        reporting_currency=values.get("reporting_currency"),
        trading_currency=values.get("trading_currency"),
        dealing_currency=values.get("dealing_currency"),
        share_class_currency=values.get("share_class_currency"),
        hedging_currency=values.get("hedging_currency"),
        market_cap_eur=values.get("market_cap_eur"),
        cap_bucket=values.get("cap_bucket"),
        liquidity_bucket=values.get("liquidity_bucket"),
        bond_type=values.get("bond_type"),
        issuer_sector=values.get("issuer_sector"),
        issuer_type=values.get("issuer_type"),
        seniority=values.get("seniority"),
        secured_status=values.get("secured_status"),
        coupon_type=values.get("coupon_type"),
        rating_bucket=values.get("rating_bucket"),
        maturity_bucket=values.get("maturity_bucket"),
        duration_bucket=values.get("duration_bucket"),
        fund_structure=values.get("fund_structure"),
        management_style=values.get("management_style"),
        mandate=values.get("mandate"),
        benchmark=values.get("benchmark"),
        distribution_policy=values.get("distribution_policy"),
        fee_tier=values.get("fee_tier"),
        dealing_liquidity_class=values.get("dealing_liquidity_class"),
        special_structures=multi_values.get("special_structure", ()),
        classification_status=status,
        classification_confidence=overall_confidence,
        field_confidence=dict(sorted(confidences.items())),
        fallback_path=tuple(fallback),
        alternatives=dict(sorted(alternatives.items())),
        evidence_ids=tuple(sorted(set(selected_ids))),
        excluded_evidence_ids=tuple(sorted(item.evidence_id for item in excluded)),
        override_ids=override_ids,
        source_ids=source_ids,
        effective_at=_display_cutoff(effective_at),
        decision_time=_display_cutoff(decision_time),
        schema_version=CLASSIFICATION_SCHEMA_VERSION,
        version_id=version_id,
        score_invalidation_token=score_token,
        invalidated_score_keys=invalidated_keys,
        dependent_scores_invalidated=bool(applied_overrides),
        sector_adapter_allowed=sector_allowed,
        warnings=tuple(dict.fromkeys(warnings)),
        execution_allowed=False,
    )


def sector_adapter_route(
    context: InstrumentContextV2,
    *,
    min_confidence: float = DEFAULT_LEAF_CONFIDENCE,
) -> AdapterRoute:
    """Return a deterministic sector-adapter route, or a controlled block."""

    threshold = _confidence(min_confidence, "min_confidence")
    confidence = float(context.field_confidence.get("sector", 0.0))
    if context.sector is None:
        reason = (
            "SECTOR_CONFIDENCE_BELOW_THRESHOLD"
            if "sector_confidence_below_threshold" in context.warnings
            else "SECTOR_CLASSIFICATION_UNAVAILABLE"
        )
    elif confidence < threshold or not context.sector_adapter_allowed:
        reason = "SECTOR_CONFIDENCE_BELOW_THRESHOLD"
    else:
        return AdapterRoute(
            allowed=True,
            adapter_id=f"sector:{context.sector}",
            reason_code="SECTOR_ADAPTER_ALLOWED",
            confidence=confidence,
            context_version=context.version_id,
        )
    return AdapterRoute(
        allowed=False,
        adapter_id=None,
        reason_code=reason,
        confidence=confidence,
        context_version=context.version_id,
    )


def measure_classification_accuracy(
    expected: Mapping[str, Mapping[str, object]],
    actual: Mapping[str, InstrumentContextV2],
) -> ClassificationAccuracy:
    """Measure exact field accuracy on a labelled fixture corpus."""

    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        raise TypeError("expected and actual classifications must be mappings")
    correct = 0
    total = 0
    mismatches: list[str] = []
    for instrument_id, labels in sorted(expected.items()):
        context = actual.get(instrument_id)
        if context is None:
            for field_name in labels:
                total += 1
                mismatches.append(f"{instrument_id}.{field_name}: missing context")
            continue
        for field_name, expected_value in sorted(labels.items()):
            if not hasattr(context, field_name):
                raise ValueError(f"unknown InstrumentContextV2 label field: {field_name}")
            total += 1
            observed = getattr(context, field_name)
            if _comparable(observed) == _comparable(expected_value):
                correct += 1
            else:
                mismatches.append(
                    f"{instrument_id}.{field_name}: expected {expected_value!r}, observed {observed!r}"
                )
    return ClassificationAccuracy(
        correct=correct,
        total=total,
        accuracy=(correct / total) if total else None,
        mismatches=tuple(mismatches),
    )


class ClassificationStore:
    """Append-only local repository for classification evidence and overrides."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        try:
            self._store = TransactionalStore(self.root)
            self._ensure_schema()
        except (StorageSchemaError, sqlite3.DatabaseError, OSError) as exc:
            raise ClassificationSchemaError(f"classification storage is unavailable: {exc}") from exc
        except Exception:
            if hasattr(self, "_store"):
                self._store.close()
            raise

    def __enter__(self) -> ClassificationStore:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._store.close()

    def append_evidence(self, evidence: Iterable[ClassificationEvidence]) -> tuple[str, ...]:
        items = tuple(_normalise_evidence(item) for item in evidence)
        records = tuple((_EVIDENCE_TYPE, _evidence_key(item), _evidence_payload(item)) for item in items)
        try:
            self._store.put_many(records, immutable=True)
        except (StorageRevisionConflict, sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise ClassificationSchemaError(f"classification evidence rejected: {exc}") from exc
        return tuple(record_id for _, record_id, _ in records)

    def append_overrides(self, overrides: Iterable[ClassificationOverride]) -> tuple[str, ...]:
        items = tuple(_normalise_override(item) for item in overrides)
        records = tuple((_OVERRIDE_TYPE, _override_key(item), _override_payload(item)) for item in items)
        try:
            self._store.put_many(records, immutable=True)
        except (StorageRevisionConflict, sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise ClassificationSchemaError(f"classification override rejected: {exc}") from exc
        return tuple(record_id for _, record_id, _ in records)

    def classify(
        self,
        instrument_id: str,
        *,
        effective_at: str | datetime | None = None,
        decision_time: str | datetime | None = None,
        min_leaf_confidence: float = DEFAULT_LEAF_CONFIDENCE,
    ) -> InstrumentContextV2:
        canonical_id = str(instrument_id).strip()
        if not canonical_id:
            raise ValueError("instrument_id must be non-empty")
        evidence = tuple(item for item in self._load_evidence() if item.instrument_id == canonical_id)
        overrides = tuple(item for item in self._load_overrides() if item.instrument_id == canonical_id)
        if not evidence and not overrides:
            raise KeyError(f"classification evidence unavailable for {canonical_id}")
        return resolve_instrument_context(
            evidence,
            overrides,
            effective_at=effective_at,
            decision_time=decision_time,
            min_leaf_confidence=min_leaf_confidence,
        )

    def projection(
        self,
        instrument_id: str,
        *,
        effective_at: str | datetime | None = None,
        decision_time: str | datetime | None = None,
        min_leaf_confidence: float = DEFAULT_LEAF_CONFIDENCE,
    ) -> dict[str, object]:
        context = self.classify(
            instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
            min_leaf_confidence=min_leaf_confidence,
        )
        route = sector_adapter_route(context, min_confidence=min_leaf_confidence)
        return {
            "status": "available" if context.classification_status != "unresolved" else "unresolved",
            "classification": asdict(context),
            "sector_adapter_route": asdict(route),
            "execution_allowed": False,
        }

    def _ensure_schema(self) -> None:
        expected = {
            "schema_version": CLASSIFICATION_SCHEMA_VERSION,
            "contract": CLASSIFICATION_CONTRACT,
        }
        try:
            marker = self._store.get(_META_TYPE, _META_ID)
            if marker is None:
                self._store.put_many(((_META_TYPE, _META_ID, expected),), immutable=True)
                marker = self._store.get(_META_TYPE, _META_ID)
            if marker is None or marker.payload != expected:
                raise ClassificationSchemaError("classification schema marker is unsupported or corrupt")
            for record in self._store.list(_EVIDENCE_TYPE):
                _evidence_from_payload(record.payload)
            for record in self._store.list(_OVERRIDE_TYPE):
                _override_from_payload(record.payload)
        except ClassificationSchemaError:
            raise
        except (StorageRevisionConflict, sqlite3.DatabaseError, KeyError, TypeError, ValueError) as exc:
            raise ClassificationSchemaError(f"classification store is corrupt: {exc}") from exc

    def _load_evidence(self) -> tuple[ClassificationEvidence, ...]:
        try:
            return tuple(_evidence_from_payload(item.payload) for item in self._store.list(_EVIDENCE_TYPE))
        except (sqlite3.DatabaseError, KeyError, TypeError, ValueError) as exc:
            raise ClassificationSchemaError(f"classification evidence store is corrupt: {exc}") from exc

    def _load_overrides(self) -> tuple[ClassificationOverride, ...]:
        try:
            return tuple(_override_from_payload(item.payload) for item in self._store.list(_OVERRIDE_TYPE))
        except (sqlite3.DatabaseError, KeyError, TypeError, ValueError) as exc:
            raise ClassificationSchemaError(f"classification override store is corrupt: {exc}") from exc


def classification_store_exists(root: Path) -> bool:
    """Read-only marker check; a presentation read must not create storage."""

    path = storage_layout(root).transactional_path
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transactional_records'"
            ).fetchone()
            if table is None:
                return False
            marker = connection.execute(
                "SELECT 1 FROM transactional_records WHERE entity_type = ? AND entity_id = ? AND deleted_at IS NULL",
                (_META_TYPE, _META_ID),
            ).fetchone()
            return marker is not None
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ClassificationSchemaError(f"classification store is unreadable: {exc}") from exc


def _normalise_evidence(item: ClassificationEvidence) -> ClassificationEvidence:
    if not isinstance(item, ClassificationEvidence):
        raise ClassificationSchemaError("classification evidence must use ClassificationEvidence")
    evidence_id = _required(item.evidence_id, "evidence_id")
    instrument_id = _required(item.instrument_id, "instrument_id")
    field_name = _field(item.field)
    value = _required(item.value, "value")
    source = _required(item.source, "source")
    source_id = _required(item.source_id, "source_id")
    try:
        authority = item.authority if isinstance(item.authority, SourceAuthority) else SourceAuthority(str(item.authority))
    except ValueError as exc:
        raise ClassificationSchemaError(f"unknown classification authority: {item.authority!r}") from exc
    confidence = _confidence(item.confidence, "confidence")
    checksum = _checksum(item.source_checksum, "source_checksum")
    if authority is SourceAuthority.MODEL and not checksum:
        raise ClassificationSchemaError("model-assisted classification requires a cited source_checksum")
    valid_from = _optional_timestamp(item.valid_from, "valid_from")
    valid_to = _optional_timestamp(item.valid_to, "valid_to")
    available_at = _optional_timestamp(item.available_at, "available_at")
    _validate_interval(valid_from, valid_to)
    alternatives = tuple(dict.fromkeys(_required(value, "alternative") for value in item.alternatives))
    return ClassificationEvidence(
        evidence_id=evidence_id,
        instrument_id=instrument_id,
        field=field_name,
        value=value,
        source=source,
        authority=authority,
        source_id=source_id,
        confidence=confidence,
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at,
        revision=_positive_revision(item.revision),
        source_checksum=checksum,
        alternatives=alternatives,
    )


def _normalise_override(item: ClassificationOverride) -> ClassificationOverride:
    if not isinstance(item, ClassificationOverride):
        raise ClassificationSchemaError("classification overrides must use ClassificationOverride")
    valid_from = _timestamp(item.valid_from, "valid_from")
    valid_to = _optional_timestamp(item.valid_to, "valid_to")
    available_at = _timestamp(item.available_at, "available_at")
    _validate_interval(valid_from, valid_to)
    instrument_id = _required(item.instrument_id, "instrument_id")
    dependencies = tuple(
        dict.fromkeys(_required(value, "dependent_score_key") for value in item.dependent_score_keys)
    )
    return ClassificationOverride(
        override_id=_required(item.override_id, "override_id"),
        instrument_id=instrument_id,
        field=_field(item.field),
        value=_required(item.value, "value"),
        reason=_required(item.reason, "reason"),
        reviewer=_required(item.reviewer, "reviewer"),
        valid_from=valid_from,
        available_at=available_at,
        valid_to=valid_to,
        revision=_positive_revision(item.revision),
        dependent_score_keys=dependencies,
        source_checksum=_checksum(item.source_checksum, "source_checksum"),
    )


def _field(value: object) -> str:
    field_name = str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")
    if not field_name:
        raise ClassificationSchemaError("classification field must be non-empty")
    if field_name in _PROPRIETARY_FIELDS:
        raise ClassificationSchemaError("proprietary GICS/ICB taxonomy redistribution is unsupported")
    if field_name not in _SUPPORTED_FIELDS:
        raise ClassificationSchemaError(f"unsupported classification field: {field_name}")
    return field_name


def _select_scalar(
    candidates: Iterable[ClassificationEvidence],
) -> tuple[str | None, float, tuple[str, ...], tuple[str, ...], bool]:
    items = tuple(candidates)
    ranked = sorted(items, key=_evidence_rank, reverse=True)
    top = ranked[0]
    top_rank = _evidence_rank(top)
    tied = tuple(item for item in ranked if _evidence_rank(item) == top_rank)
    tied_values = {item.value for item in tied}
    retained = tuple(
        sorted(
            {
                value
                for item in items
                for value in (item.value, *item.alternatives)
                if value and value != top.value
            }
        )
    )
    if len(tied_values) > 1:
        return None, top.confidence, tuple(sorted(item.evidence_id for item in tied)), retained, True
    return top.value, top.confidence, (top.evidence_id,), retained, False


def _select_multi(
    candidates: Iterable[ClassificationEvidence],
) -> tuple[tuple[str, ...], float, tuple[str, ...], tuple[str, ...]]:
    items = tuple(candidates)
    highest_authority = max(item.authority.rank for item in items)
    authoritative = tuple(item for item in items if item.authority.rank == highest_authority)
    per_value: dict[str, ClassificationEvidence] = {}
    for item in authoritative:
        previous = per_value.get(item.value)
        if previous is None or _evidence_rank(item) > _evidence_rank(previous):
            per_value[item.value] = item
    values = tuple(sorted(per_value))
    selected = tuple(per_value[value] for value in values)
    retained = tuple(
        sorted(
            {
                value
                for item in items
                for value in (item.value, *item.alternatives)
                if value and value not in per_value
            }
        )
    )
    return values, min((item.confidence for item in selected), default=0.0), tuple(
        sorted(item.evidence_id for item in selected)
    ), retained


def _select_override(
    candidates: tuple[ClassificationOverride, ...],
) -> tuple[ClassificationOverride | None, bool]:
    ranked = sorted(candidates, key=_override_rank, reverse=True)
    top_rank = _override_rank(ranked[0])
    tied = tuple(item for item in ranked if _override_rank(item) == top_rank)
    if len({item.value for item in tied}) > 1:
        return None, True
    return sorted(tied, key=lambda item: item.override_id)[0], False


def _evidence_rank(item: ClassificationEvidence) -> tuple[int, float, int, str]:
    return item.authority.rank, item.confidence, item.revision, item.available_at or ""


def _override_rank(item: ClassificationOverride) -> tuple[int, str]:
    return item.revision, item.available_at


def _eligible(
    *,
    valid_from: str | None,
    valid_to: str | None,
    available_at: str | None,
    effective_at: datetime | None,
    decision_time: datetime | None,
) -> bool:
    # Evidence without an availability timestamp cannot be used in a
    # point-in-time decision, including the latest projection.
    if available_at is None:
        return False
    available = _as_datetime(available_at)
    if decision_time is not None and available > decision_time:
        return False
    if effective_at is not None:
        if valid_from is not None and _as_datetime(valid_from) > effective_at:
            return False
        if valid_to is not None and _as_datetime(valid_to) <= effective_at:
            return False
    return True


def _canonical_instrument_type(value: str | None) -> str | None:
    return _INSTRUMENT_TYPE_ALIASES.get(
        str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    )


def _canonical_asset_class(value: str | None) -> str | None:
    return _ASSET_CLASS_ALIASES.get(str(value or "").strip().casefold().replace("-", "_"))


def _evidence_payload(item: ClassificationEvidence) -> dict[str, Any]:
    payload = asdict(item)
    payload["authority"] = item.authority.value
    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "contract": CLASSIFICATION_CONTRACT,
        "evidence": payload,
    }


def _override_payload(item: ClassificationOverride) -> dict[str, Any]:
    return {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "contract": CLASSIFICATION_CONTRACT,
        "override": asdict(item),
    }


def _evidence_from_payload(payload: Mapping[str, Any]) -> ClassificationEvidence:
    body = _payload_body(payload, "evidence")
    return _normalise_evidence(ClassificationEvidence(**body))


def _override_from_payload(payload: Mapping[str, Any]) -> ClassificationOverride:
    body = _payload_body(payload, "override")
    return _normalise_override(ClassificationOverride(**body))


def _payload_body(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ClassificationSchemaError("classification payload is not a mapping")
    try:
        version = int(payload["schema_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ClassificationSchemaError("classification schema version is missing") from exc
    if version > CLASSIFICATION_SCHEMA_VERSION:
        raise ClassificationSchemaError(f"classification schema {version} is newer than supported")
    if version != CLASSIFICATION_SCHEMA_VERSION or payload.get("contract") != CLASSIFICATION_CONTRACT:
        raise ClassificationSchemaError("classification record contract is unsupported")
    body = payload.get(key)
    if not isinstance(body, Mapping):
        raise ClassificationSchemaError(f"classification record is missing {key}")
    return dict(body)


def _evidence_key(item: ClassificationEvidence) -> str:
    return _hash(
        {
            "evidence_id": item.evidence_id,
            "instrument_id": item.instrument_id,
            "field": item.field,
            "revision": item.revision,
        }
    )


def _override_key(item: ClassificationOverride) -> str:
    return _hash(
        {
            "override_id": item.override_id,
            "instrument_id": item.instrument_id,
            "field": item.field,
            "revision": item.revision,
        }
    )


def _hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ClassificationSchemaError(f"classification {label} must be non-empty")
    return text


def _positive_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ClassificationSchemaError("classification revision must be a positive integer")
    return value


def _confidence(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ClassificationSchemaError(f"classification {label} must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ClassificationSchemaError(f"classification {label} must be between 0 and 1")
    return result


def _checksum(value: object, label: str) -> str:
    checksum = str(value or "").strip().lower()
    if checksum and (len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum)):
        raise ClassificationSchemaError(f"classification {label} must be a SHA-256 hex digest")
    return checksum


def _timestamp(value: object, label: str) -> str:
    text = _required(value, label)
    _as_datetime(text)
    return text


def _optional_timestamp(value: object, label: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return _timestamp(value, label)


def _as_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClassificationSchemaError(f"invalid classification timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ClassificationSchemaError("classification timestamps require an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _cutoff(value: str | datetime | None) -> datetime | None:
    return None if value is None else _as_datetime(value)


def _display_cutoff(value: str | datetime | None) -> str:
    if value is None:
        return "latest"
    return _as_datetime(value).isoformat().replace("+00:00", "Z")


def _validate_interval(valid_from: str | None, valid_to: str | None) -> None:
    if valid_from is not None and valid_to is not None and _as_datetime(valid_to) <= _as_datetime(valid_from):
        raise ClassificationSchemaError("classification valid_to must be later than valid_from")


def _comparable(value: object) -> object:
    if isinstance(value, (tuple, list, set)):
        return tuple(sorted(str(item) for item in value))
    return value


__all__ = [
    "AdapterRoute",
    "ClassificationAccuracy",
    "ClassificationEvidence",
    "ClassificationOverride",
    "ClassificationSchemaError",
    "ClassificationStore",
    "InstrumentContextV2",
    "classification_store_exists",
    "measure_classification_accuracy",
    "resolve_instrument_context",
    "sector_adapter_route",
]
