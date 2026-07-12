"""Deterministic, fail-closed instrument identity resolution.

The resolver is deliberately small: claims are immutable observations and the
highest-authority claim is selected only as a canonical view.  Every rejected
or ambiguous value remains in :class:`IdentityConflict` for audit and manual
review; no source is silently discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping

from etf_cockpit.data.contracts import SourceAuthority


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


_SPECIAL_FIELDS = frozenset({"ticker", "isin", "exchange", "mic", "currency", "share_class", "listing"})


def resolve_identity(claims: Iterable[IdentityClaim]) -> IdentityResolution:
    """Resolve one instrument's claims deterministically.

    Authority is the primary ordering key, followed by source ID, source name
    and normalised value.  Empty source IDs are retained but force manual
    review, as do explicit manual overrides and any conflicting identity
    values.
    """

    items = tuple(_coerce_claim(item) for item in claims)
    if not items:
        raise ValueError("identity resolution requires at least one claim")
    instrument_ids = {item.instrument_id.strip() for item in items}
    if len(instrument_ids) != 1 or not next(iter(instrument_ids), ""):
        raise ValueError("identity claims must belong to one non-empty instrument")
    instrument_id = next(iter(instrument_ids))

    by_field: dict[str, list[IdentityClaim]] = {}
    for claim in items:
        field = _canonical_field(claim.field)
        if not field:
            continue
        by_field.setdefault(field, []).append(claim)

    selected: dict[str, IdentityClaim] = {}
    conflicts: list[IdentityConflict] = []
    for field in sorted(by_field):
        field_claims = by_field[field]
        ordered = sorted(field_claims, key=_claim_sort_key)
        chosen = ordered[0]
        selected[field] = chosen
        values = tuple(sorted({_normalise_value(field, claim.value) for claim in field_claims if _normalise_value(field, claim.value)}))
        if len(values) > 1:
            source_ids = tuple(sorted({claim.source_id.strip() or "unknown" for claim in field_claims}))
            conflict_id = _conflict_id(instrument_id, field, values, source_ids)
            reason = _identity_conflict_reason(field, chosen, values, field_claims)
            conflicts.append(
                IdentityConflict(
                    instrument_id=instrument_id,
                    field=field,
                    values=values,
                    source_ids=source_ids,
                    canonical_value=_normalise_value(field, chosen.value),
                    requires_manual_review=True,
                    reason=reason,
                    conflict_id=conflict_id,
                    canonical_source_id=chosen.source_id.strip(),
                )
            )

    warnings: list[str] = []
    if any(not item.source_id.strip() for item in items):
        warnings.append("missing_source_id")
    if any(item.manual_override or item.source.casefold() in {"manual_override", "override"} for item in items):
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
        warnings.append(f"{conflict.field}_conflict_requires_manual_review")
    if conflicts:
        warnings.append("source_conflict_requires_manual_review")

    provider_symbols = _provider_symbols(items)
    required_fields_present = all(_optional(selected.get(field), field=field) for field in ("ticker", "isin"))
    requires_review = bool(conflicts or warnings or not required_fields_present)
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
    return IdentityResolution(
        identity=identity,
        conflicts=tuple(conflicts),
        claims=items,
        requires_manual_review=requires_review,
        warnings=tuple(identity.warnings),
    )


def _coerce_claim(claim: IdentityClaim) -> IdentityClaim:
    if not isinstance(claim, IdentityClaim):
        raise TypeError("identity claims must be IdentityClaim instances")
    try:
        authority = claim.authority if isinstance(claim.authority, SourceAuthority) else SourceAuthority(str(claim.authority).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unknown identity authority: {claim.authority!r}") from exc
    return IdentityClaim(
        instrument_id=str(claim.instrument_id).strip(),
        field=str(claim.field).strip(),
        value=str(claim.value or "").strip(),
        source=str(claim.source or "").strip(),
        authority=authority,
        source_id=str(claim.source_id or "").strip(),
        as_of=claim.as_of,
        manual_override=bool(claim.manual_override),
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


def _claim_sort_key(claim: IdentityClaim) -> tuple[int, str, str, str, str]:
    return (
        -_authority_rank(claim.authority),
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


def _conflict_id(instrument_id: str, field: str, values: tuple[str, ...], source_ids: tuple[str, ...]) -> str:
    import hashlib

    payload = "|".join((instrument_id, field, *values, *source_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _unique(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
