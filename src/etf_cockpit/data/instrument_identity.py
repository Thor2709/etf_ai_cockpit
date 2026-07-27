"""Deterministic, fail-closed instrument identity resolution.

The resolver is deliberately small: claims are immutable observations and the
highest-authority claim is selected only as a canonical view.  Every rejected
or ambiguous value remains in :class:`IdentityConflict` for audit and manual
review; no source is silently discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping, cast

from etf_cockpit.data.contracts import SourceAuthority


class IdentityResolutionError(ValueError):
    """Raised when identity evidence cannot be resolved without inventing facts."""


class AmbiguousIdentityAvailabilityError(IdentityResolutionError):
    """Raised when a point-in-time identity claim lacks availability evidence."""


@dataclass(frozen=True)
class IdentityClaim:
    instrument_id: str
    field: str
    value: str
    source: str
    authority: SourceAuthority
    source_id: str = ""
    as_of: str | None = None
    manual_override: bool = False
    object_type: str = "instrument"
    object_id: str = ""
    parent_object_id: str | None = None
    relationship: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    available_at: str | None = None
    revision: int = 1
    event_type: str = "observation"
    retrieved_at: str | None = None


@dataclass(frozen=True)
class IdentityReviewDecision:
    conflict_id: str
    selected_source_id: str
    reviewer: str
    reviewed_at: str
    reason: str
    revision: int = 1

    @property
    def decision_id(self) -> str:
        payload = {
            "conflict_id": self.conflict_id,
            "selected_source_id": self.selected_source_id,
            "reviewer": self.reviewer,
            "reviewed_at": _timestamp(self.reviewed_at, "reviewed_at", require_timezone=True),
            "reason": self.reason,
            "revision": self.revision,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdentityConflict:
    instrument_id: str
    field: str
    values: tuple[str, ...]
    source_ids: tuple[str, ...]
    canonical_value: str
    requires_manual_review: bool
    reason: str = ""
    conflict_id: str = ""
    canonical_source_id: str = ""
    object_type: str = "instrument"
    object_id: str = ""
    reason_code: str = "identity_value_conflict"
    resolution_status: str = "manual_review"
    review_decision_id: str = ""


@dataclass(frozen=True)
class IdentityHistoryEntry:
    object_type: str
    object_id: str
    field: str
    value: str
    source_id: str
    valid_from: str | None
    valid_to: str | None
    available_at: str | None
    revision: int
    event_type: str
    retrieved_at: str | None = None


@dataclass(frozen=True)
class IdentityObject:
    object_type: str
    object_id: str
    parent_object_id: str | None
    relationship: str | None
    fields: Mapping[str, str]
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalIdentity:
    # The first fields are retained in their historical order.  A number of
    # parser callers construct this object positionally, so new identity
    # dimensions intentionally have defaults at the end.
    instrument_id: str
    name: str
    isin: str | None
    isin_status: str
    ticker: str
    exchange: str | None
    currency: str | None
    asset_type: str
    provider_symbols: Mapping[str, str]
    confidence: str
    warnings: tuple[str, ...]
    cik: str | None = None
    mic: str | None = None
    share_class: str | None = None
    issuer: str | None = None
    listing: str | None = None


@dataclass(frozen=True)
class IdentityResolution:
    identity: CanonicalIdentity
    conflicts: tuple[IdentityConflict, ...]
    claims: tuple[IdentityClaim, ...] = ()
    requires_manual_review: bool = False
    warnings: tuple[str, ...] = ()
    objects: tuple[IdentityObject, ...] = ()
    history: tuple[IdentityHistoryEntry, ...] = ()
    effective_at: str | None = None
    decision_time: str | None = None
    decision_id: str = ""
    resolution_state: str = "manual_review"
    execution_allowed: bool = False
    excluded_claims: tuple[IdentityClaim, ...] = ()
    decision_schema_version: int = 2


_SPECIAL_FIELDS = frozenset({"ticker", "isin", "exchange", "mic", "currency", "share_class", "listing"})


def resolve_identity(
    claims: Iterable[IdentityClaim],
    *,
    effective_at: str | datetime | None = None,
    decision_time: str | datetime | None = None,
    review_decisions: Iterable[IdentityReviewDecision] = (),
    decision_schema_version: int = 2,
) -> IdentityResolution:
    """Resolve one instrument's claims deterministically.

    Authority is the primary ordering key, followed by source ID, source name
    and normalised value.  Empty source IDs are retained but force manual
    review, as do explicit manual overrides and any conflicting identity
    values.
    """

    if decision_schema_version not in {1, 2}:
        raise IdentityResolutionError(
            f"unsupported identity decision schema version: {decision_schema_version}"
        )
    items = tuple(_coerce_claim(item) for item in claims)
    if not items:
        raise ValueError("identity resolution requires at least one claim")
    instrument_ids = {item.instrument_id.strip() for item in items}
    if len(instrument_ids) != 1 or not next(iter(instrument_ids), ""):
        raise ValueError("identity claims must belong to one non-empty instrument")
    instrument_id = next(iter(instrument_ids))

    effective_timestamp, decision_timestamp = _resolution_times(effective_at, decision_time)
    eligible = _eligible_claims(
        items,
        effective_at=effective_timestamp,
        decision_time=decision_timestamp,
    )
    if not eligible:
        raise IdentityResolutionError("no identity claims are available at the requested decision and effective times")
    known_items, excluded_items = _known_identity_claims(items, decision_timestamp)

    reviews = _identity_review_map(tuple(review_decisions), decision_timestamp)
    used_reviews: set[str] = set()
    by_field: dict[tuple[str, str, str], list[IdentityClaim]] = {}
    for claim in eligible:
        field = _canonical_field(claim.field)
        if not field:
            continue
        by_field.setdefault((claim.object_type, claim.object_id, field), []).append(claim)

    selected_by_object: dict[tuple[str, str], dict[str, IdentityClaim]] = {}
    conflicts: list[IdentityConflict] = []
    for object_type, object_id, field in sorted(by_field):
        field_claims = by_field[(object_type, object_id, field)]
        ordered = sorted(field_claims, key=_claim_sort_key)
        chosen = ordered[0]
        values = tuple(sorted({_normalise_value(field, claim.value) for claim in field_claims if _normalise_value(field, claim.value)}))
        if len(values) > 1:
            source_ids = tuple(sorted({claim.source_id.strip() or "unknown" for claim in field_claims}))
            conflict_id = _conflict_id(instrument_id, field, values, source_ids, object_type=object_type, object_id=object_id)
            review = reviews.get(conflict_id)
            if review is not None:
                matching = [claim for claim in field_claims if claim.source_id == review.selected_source_id]
                if not matching:
                    raise IdentityResolutionError("identity review selected source is not a retained candidate")
                chosen = sorted(matching, key=_claim_sort_key)[0]
                used_reviews.add(conflict_id)
            reason = _identity_conflict_reason(field, chosen, values, field_claims)
            conflicts.append(
                IdentityConflict(
                    instrument_id=instrument_id,
                    field=field,
                    values=values,
                    source_ids=source_ids,
                    canonical_value=_normalise_value(field, chosen.value),
                    requires_manual_review=review is None,
                    reason=reason,
                    conflict_id=conflict_id,
                    canonical_source_id=chosen.source_id.strip(),
                    object_type=object_type,
                    object_id=object_id,
                    reason_code="identity_value_conflict" if review is None else "identity_value_conflict_reviewed",
                    resolution_status="manual_review" if review is None else "reviewed",
                    review_decision_id="" if review is None else review.decision_id,
                )
            )
        selected_by_object.setdefault((object_type, object_id), {})[field] = chosen

    unknown_reviews = set(reviews).difference(used_reviews)
    if unknown_reviews:
        raise IdentityResolutionError(f"identity review references unknown conflict: {sorted(unknown_reviews)[0]}")

    objects = tuple(
        IdentityObject(
            object_type=object_type,
            object_id=object_id,
            parent_object_id=_single_context_value(eligible, object_type, object_id, "parent_object_id"),
            relationship=_single_context_value(eligible, object_type, object_id, "relationship"),
            fields={field: _normalise_value(field, claim.value) for field, claim in sorted(fields.items())},
            source_ids=tuple(sorted({claim.source_id or "unknown" for claim in eligible if claim.object_type == object_type and claim.object_id == object_id})),
        )
        for (object_type, object_id), fields in sorted(selected_by_object.items())
    )
    selected = _legacy_selected_fields(selected_by_object, instrument_id)

    warnings: list[str] = []
    if any(not item.source_id.strip() for item in eligible):
        warnings.append("missing_source_id")
    if any(item.manual_override or item.source.casefold() in {"manual_override", "override"} for item in eligible):
        warnings.append("manual_override_requires_review")
    isin = _optional(selected.get("isin"), field="isin")
    isin_status = _isin_status(isin)
    exchange = _optional(selected.get("exchange"), field="exchange")
    if isin_status != "verified":
        warnings.append("isin_needs_verification")
    if not exchange:
        warnings.extend(("missing_exchange", "exchange_needs_verification"))
    elif exchange.casefold() in {"unknown", "needs_verification", "n/a", "na", "null"}:
        warnings.append("exchange_needs_verification")
    if not _optional(selected.get("ticker"), field="ticker"):
        warnings.append("missing_ticker")
    for conflict in conflicts:
        suffix = "requires_manual_review" if conflict.requires_manual_review else "reviewed"
        warnings.append(f"{conflict.field}_conflict_{suffix}")
    if any(conflict.requires_manual_review for conflict in conflicts):
        warnings.append("source_conflict_requires_manual_review")

    provider_symbols = _provider_symbols(eligible)
    required_fields_present = all(_optional(selected.get(field), field=field) for field in ("ticker", "isin"))
    requires_review = bool(any(conflict.requires_manual_review for conflict in conflicts) or any("requires_review" in warning or "needs_verification" in warning or warning.startswith("missing_") for warning in warnings) or not required_fields_present)
    confidence = "high" if required_fields_present and not requires_review else "manual_review"

    def value(field: str, default: str = "") -> str:
        claim = selected.get(field)
        return _normalise_value(field, claim.value) if claim is not None else default

    identity = CanonicalIdentity(
        instrument_id=instrument_id,
        name=value("name", instrument_id),
        isin=isin,
        isin_status=isin_status,
        ticker=value("ticker"),
        exchange=exchange,
        currency=_optional(selected.get("currency"), field="currency"),
        asset_type=value("asset_type", "unknown"),
        provider_symbols=provider_symbols,
        confidence=confidence,
        warnings=tuple(_unique(warnings)),
        cik=_optional(selected.get("cik"), field="cik"),
        mic=_optional(selected.get("mic"), field="mic"),
        share_class=_optional(selected.get("share_class"), field="share_class"),
        issuer=_optional(selected.get("issuer"), field="issuer"),
        listing=_optional(selected.get("listing"), field="listing"),
    )
    history = tuple(
        IdentityHistoryEntry(
            object_type=claim.object_type,
            object_id=claim.object_id,
            field=_canonical_field(claim.field),
            value=_normalise_value(_canonical_field(claim.field), claim.value),
            source_id=claim.source_id or "unknown",
            valid_from=claim.valid_from,
            valid_to=claim.valid_to,
            available_at=claim.available_at,
            revision=claim.revision,
            event_type=claim.event_type,
            retrieved_at=claim.retrieved_at,
        )
        for claim in sorted(known_items, key=_history_sort_key)
    )
    decision_id = _decision_id(
        instrument_id,
        effective_timestamp,
        decision_timestamp,
        eligible,
        conflicts,
        schema_version=decision_schema_version,
    )
    resolution_state = (
        "quarantined"
        if any(item.requires_manual_review for item in conflicts)
        else "manual_review"
        if requires_review
        else "reviewed"
        if conflicts
        else "resolved"
    )
    return IdentityResolution(
        identity=identity,
        conflicts=tuple(conflicts),
        claims=known_items,
        requires_manual_review=requires_review,
        warnings=tuple(identity.warnings),
        objects=objects,
        history=history,
        effective_at=effective_timestamp,
        decision_time=decision_timestamp,
        decision_id=decision_id,
        resolution_state=resolution_state,
        execution_allowed=False,
        excluded_claims=excluded_items,
        decision_schema_version=decision_schema_version,
    )


def _coerce_claim(claim: IdentityClaim) -> IdentityClaim:
    if not isinstance(claim, IdentityClaim):
        raise TypeError("identity claims must be IdentityClaim instances")
    try:
        authority = claim.authority if isinstance(claim.authority, SourceAuthority) else SourceAuthority(str(claim.authority).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unknown identity authority: {claim.authority!r}") from exc
    instrument_id = str(claim.instrument_id).strip()
    object_type = str(claim.object_type or "instrument").strip().lower()
    object_id = str(claim.object_id or instrument_id).strip()
    if not object_type or not object_id:
        raise IdentityResolutionError("identity object_type and object_id must be non-empty")
    try:
        revision = int(claim.revision)
    except (TypeError, ValueError) as exc:
        raise IdentityResolutionError("identity revision must be a positive integer") from exc
    if revision < 1:
        raise IdentityResolutionError("identity revision must be a positive integer")
    valid_from = _optional_timestamp(claim.valid_from, "valid_from")
    valid_to = _optional_timestamp(claim.valid_to, "valid_to")
    available_at = _optional_timestamp(claim.available_at, "available_at", require_timezone=True)
    retrieved_at = _optional_timestamp(
        claim.retrieved_at, "retrieved_at", require_timezone=True
    )
    if valid_from and valid_to and _as_datetime(valid_to) <= _as_datetime(valid_from):
        raise IdentityResolutionError("identity valid_to must be later than valid_from")
    return IdentityClaim(
        instrument_id=instrument_id,
        field=str(claim.field).strip(),
        value=str(claim.value or "").strip(),
        source=str(claim.source or "").strip(),
        authority=authority,
        source_id=str(claim.source_id or "").strip(),
        as_of=claim.as_of,
        manual_override=bool(claim.manual_override),
        object_type=object_type,
        object_id=object_id,
        parent_object_id=str(claim.parent_object_id).strip() if claim.parent_object_id else None,
        relationship=str(claim.relationship).strip().lower() if claim.relationship else None,
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at,
        revision=revision,
        event_type=str(claim.event_type or "observation").strip().lower(),
        retrieved_at=retrieved_at,
    )


def _canonical_field(field: str) -> str:
    aliases = {
        "symbol": "ticker",
        "isin_status": "isin",
        "mic_code": "mic",
        "shareclass": "share_class",
        "share-class": "share_class",
        "listing_id": "listing",
        "provider_symbol_map": "provider_symbol_map",
        "yahoo": "yahoo_symbol",
    }
    return aliases.get(field.strip().lower(), field.strip().lower())


def _claim_sort_key(claim: IdentityClaim) -> tuple[int, int, str, str, str, str]:
    return (
        -_authority_rank(claim.authority),
        -claim.revision,
        claim.source_id.strip() or "unknown",
        claim.source.casefold(),
        _normalise_value(_canonical_field(claim.field), claim.value).casefold(),
        claim.value,
    )


def _authority_rank(authority: SourceAuthority) -> int:
    return authority.rank if isinstance(authority, SourceAuthority) else SourceAuthority.VENDOR.rank


def _normalise_value(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if field in {"exchange", "mic", "currency"}:
        return text.upper()
    if field == "share_class":
        return " ".join(text.casefold().split())
    return text


def _optional(claim: IdentityClaim | None, *, field: str) -> str | None:
    if claim is None:
        return None
    value = _normalise_value(field, claim.value)
    return value or None


def _isin_status(value: str | None) -> str:
    if not value or value.casefold() in {"unknown", "needs_verification", "n/a", "na", "null"}:
        return "needs_verification"
    if len(value) == 12 and value[:2].isalpha() and value[2:].isalnum():
        return "verified"
    return "needs_verification"


def _provider_symbols(items: Iterable[IdentityClaim]) -> dict[str, str]:
    output: dict[str, str] = {}
    for claim in items:
        field = _canonical_field(claim.field)
        value = str(claim.value or "").strip()
        if not value:
            continue
        if field == "provider_symbol":
            provider = claim.source.casefold() or claim.source_id.split(":", 1)[0].casefold() or "unknown"
            output[provider] = value
        elif field.startswith("provider_") and field != "provider_symbol_map":
            output[field.removeprefix("provider_")] = value
        elif field == "yahoo_symbol":
            output.setdefault("yahoo", value)
        elif field == "provider_symbol_map":
            try:
                mapping = json.loads(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                mapping = {}
            if isinstance(mapping, Mapping):
                for provider, symbol in sorted(mapping.items(), key=lambda item: str(item[0])):
                    if str(symbol).strip():
                        output[str(provider).strip()] = str(symbol).strip()
    return dict(sorted(output.items()))


def _identity_conflict_reason(field: str, chosen: IdentityClaim, values: tuple[str, ...], claims: Iterable[IdentityClaim]) -> str:
    authorities = {claim.authority for claim in claims}
    selected = _normalise_value(field, chosen.value)
    if SourceAuthority.OFFICIAL in authorities or SourceAuthority.ISSUER in authorities:
        return f"{field} claims disagree ({', '.join(values)}); highest-authority value {selected!r} selected and all source claims retained for manual review."
    return f"{field} claims disagree ({', '.join(values)}); canonical value {selected!r} selected deterministically and manual review is required."


def _conflict_id(
    instrument_id: str,
    field: str,
    values: tuple[str, ...],
    source_ids: tuple[str, ...],
    *,
    object_type: str = "instrument",
    object_id: str = "",
) -> str:
    payload = "|".join((instrument_id, object_type, object_id or instrument_id, field, *values, *source_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _identity_review_map(
    decisions: tuple[IdentityReviewDecision, ...],
    decision_time: str | None,
) -> dict[str, IdentityReviewDecision]:
    output: dict[str, IdentityReviewDecision] = {}
    cutoff = _as_datetime(decision_time) if decision_time else None
    for decision in decisions:
        if not decision.conflict_id or not decision.selected_source_id or not decision.reviewer or not decision.reason:
            raise IdentityResolutionError("identity reviews require conflict, candidate, reviewer and reason")
        if decision.revision < 1:
            raise IdentityResolutionError("identity review revision must be positive")
        reviewed_at = _timestamp(decision.reviewed_at, "reviewed_at", require_timezone=True)
        if cutoff is not None and _as_datetime(reviewed_at) > cutoff:
            continue
        previous = output.get(decision.conflict_id)
        if previous is not None and decision.revision == previous.revision and decision != previous:
            raise IdentityResolutionError("identity reviews contain conflicting decisions at the same revision")
        if previous is None or decision.revision > previous.revision:
            output[decision.conflict_id] = decision
    return output


def _resolution_times(
    effective_at: str | datetime | None,
    decision_time: str | datetime | None,
) -> tuple[str | None, str | None]:
    if effective_at is None and decision_time is None:
        return None, None
    if decision_time is None:
        raise AmbiguousIdentityAvailabilityError("decision_time is required for point-in-time identity resolution")
    decision = _timestamp(decision_time, "decision_time", require_timezone=True)
    effective = _timestamp(effective_at or decision_time, "effective_at")
    return effective, decision


def _eligible_claims(
    items: tuple[IdentityClaim, ...],
    *,
    effective_at: str | None,
    decision_time: str | None,
) -> tuple[IdentityClaim, ...]:
    if decision_time is None:
        return items
    for claim in items:
        if claim.available_at is None:
            raise AmbiguousIdentityAvailabilityError(
                f"available_at is required for point-in-time identity claim {claim.source_id or 'unknown'}"
            )
        if claim.valid_from is None:
            raise IdentityResolutionError(
                f"valid_from is required for point-in-time identity claim {claim.source_id or 'unknown'}"
            )
    decision = _as_datetime(decision_time)
    effective = _as_datetime(effective_at or decision_time)
    candidates = [
        claim
        for claim in items
        if _as_datetime(claim.available_at or decision_time) <= decision
        and (
            claim.retrieved_at is None
            or _as_datetime(claim.retrieved_at) <= decision
        )
        and _as_datetime(claim.valid_from or effective_at or decision_time) <= effective
        and (claim.valid_to is None or effective < _as_datetime(claim.valid_to))
    ]
    latest: dict[tuple[str, str, str, str, str], IdentityClaim] = {}
    for claim in sorted(
        candidates,
        key=lambda item: (
            _as_datetime(item.available_at or decision_time),
            _as_datetime(item.retrieved_at or item.available_at or decision_time),
            item.revision,
            _claim_sort_key(item),
        ),
    ):
        key = (
            claim.instrument_id,
            claim.object_type,
            claim.object_id,
            _canonical_field(claim.field),
            claim.source_id or "unknown",
        )
        latest[key] = claim
    return tuple(sorted(latest.values(), key=_history_sort_key))


def _known_identity_claims(
    items: tuple[IdentityClaim, ...],
    decision_time: str | None,
) -> tuple[tuple[IdentityClaim, ...], tuple[IdentityClaim, ...]]:
    if decision_time is None:
        return tuple(sorted(items, key=_history_sort_key)), ()
    cutoff = _as_datetime(decision_time)
    known = tuple(
        item
        for item in items
        if item.available_at is not None
        and _as_datetime(item.available_at) <= cutoff
        and (item.retrieved_at is None or _as_datetime(item.retrieved_at) <= cutoff)
    )
    excluded = tuple(item for item in items if item not in known)
    return tuple(sorted(known, key=_history_sort_key)), tuple(sorted(excluded, key=_history_sort_key))


def _legacy_selected_fields(
    selected_by_object: Mapping[tuple[str, str], Mapping[str, IdentityClaim]],
    instrument_id: str,
) -> dict[str, IdentityClaim]:
    preferred = selected_by_object.get(("instrument", instrument_id)) or selected_by_object.get(("security", instrument_id))
    if preferred is not None:
        return dict(preferred)
    if len(selected_by_object) == 1:
        return dict(next(iter(selected_by_object.values())))
    # Preserve deterministic compatibility without treating separate listings
    # as contradictory claims for one flat object.
    output: dict[str, IdentityClaim] = {}
    for key in sorted(selected_by_object):
        for field, claim in sorted(selected_by_object[key].items()):
            output.setdefault(field, claim)
    return output


def _single_context_value(
    claims: Iterable[IdentityClaim],
    object_type: str,
    object_id: str,
    attribute: str,
) -> str | None:
    values = {
        str(getattr(claim, attribute)).strip()
        for claim in claims
        if claim.object_type == object_type and claim.object_id == object_id and getattr(claim, attribute)
    }
    if len(values) > 1:
        raise IdentityResolutionError(f"identity object {object_id} has conflicting {attribute} values")
    return next(iter(values), None)


def _history_sort_key(
    claim: IdentityClaim,
) -> tuple[str, str, str, str, int, str, str, str]:
    return (
        claim.object_type,
        claim.object_id,
        _canonical_field(claim.field),
        claim.valid_from or "",
        claim.revision,
        claim.available_at or "",
        claim.retrieved_at or "",
        claim.source_id or "unknown",
    )


def _decision_id(
    instrument_id: str,
    effective_at: str | None,
    decision_time: str | None,
    claims: Iterable[IdentityClaim],
    conflicts: Iterable[IdentityConflict],
    *,
    schema_version: int,
) -> str:
    claim_items = tuple(claims)
    claim_sort_key = _legacy_history_sort_key if schema_version == 1 else _history_sort_key
    ordered_claims = sorted(claim_items, key=claim_sort_key)
    payload = {
        "schema_version": schema_version,
        "instrument_id": instrument_id,
        "effective_at": effective_at or "latest",
        "decision_time": decision_time or "latest",
        "claims": [
            {
                "object_type": item.object_type,
                "object_id": item.object_id,
                "field": _canonical_field(item.field),
                "value": _normalise_value(_canonical_field(item.field), item.value),
                "source_id": item.source_id or "unknown",
                "revision": item.revision,
                "valid_from": item.valid_from,
                "valid_to": item.valid_to,
                "available_at": item.available_at,
            }
            for item in ordered_claims
        ],
        "conflicts": [
            {
                "conflict_id": item.conflict_id,
                "canonical_value": item.canonical_value,
                "canonical_source_id": item.canonical_source_id,
                "resolution_status": item.resolution_status,
                "review_decision_id": item.review_decision_id,
            }
            for item in sorted(conflicts, key=lambda value: value.conflict_id)
        ],
        "execution_allowed": False,
    }
    if schema_version == 2:
        claim_payloads = cast(list[dict[str, Any]], payload["claims"])
        for claim_payload, claim in zip(
            claim_payloads,
            ordered_claims,
            strict=True,
        ):
            claim_payload["retrieved_at"] = claim.retrieved_at
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _legacy_history_sort_key(
    claim: IdentityClaim,
) -> tuple[str, str, str, str, int, str, str]:
    return (
        claim.object_type,
        claim.object_id,
        _canonical_field(claim.field),
        claim.valid_from or "",
        claim.revision,
        claim.available_at or "",
        claim.source_id or "unknown",
    )


def _optional_timestamp(value: str | datetime | None, field: str, *, require_timezone: bool = False) -> str | None:
    return None if value is None else _timestamp(value, field, require_timezone=require_timezone)


def _timestamp(value: str | datetime, field: str, *, require_timezone: bool = False) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise IdentityResolutionError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        if require_timezone and "T" in str(value):
            raise AmbiguousIdentityAvailabilityError(f"{field} must include a timezone")
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _unique(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
