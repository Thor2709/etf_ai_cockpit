from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

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


@dataclass(frozen=True)
class IdentityConflict:
    instrument_id: str
    field: str
    values: tuple[str, ...]
    source_ids: tuple[str, ...]
    canonical_value: str
    requires_manual_review: bool


@dataclass(frozen=True)
class CanonicalIdentity:
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


@dataclass(frozen=True)
class IdentityResolution:
    identity: CanonicalIdentity
    conflicts: tuple[IdentityConflict, ...]


def resolve_identity(claims: Iterable[IdentityClaim]) -> IdentityResolution:
    items = tuple(claims)
    if not items:
        raise ValueError("identity resolution requires at least one claim")
    instrument_id = items[0].instrument_id
    if any(item.instrument_id != instrument_id for item in items):
        raise ValueError("identity claims must belong to one instrument")
    by_field: dict[str, list[IdentityClaim]] = {}
    for claim in items:
        by_field.setdefault(claim.field, []).append(claim)
    selected: dict[str, IdentityClaim] = {}
    conflicts: list[IdentityConflict] = []
    for field, field_claims in by_field.items():
        ordered = sorted(field_claims, key=lambda claim: (-claim.authority.rank, claim.source_id, claim.source))
        chosen = ordered[0]
        selected[field] = chosen
        values = tuple(sorted({claim.value.strip() for claim in field_claims if claim.value.strip()}))
        if len(values) > 1:
            conflicts.append(
                IdentityConflict(
                    instrument_id=instrument_id,
                    field=field,
                    values=values,
                    source_ids=tuple(sorted({claim.source_id or claim.source for claim in field_claims})),
                    canonical_value=chosen.value,
                    requires_manual_review=True,
                )
            )
    isin = _optional(selected.get("isin"))
    isin_status = _isin_status(isin)
    warnings: list[str] = []
    if isin_status != "verified":
        warnings.append("isin_needs_verification")
    if conflicts:
        warnings.append("source_conflict_requires_manual_review")
    provider_symbols = {
        claim.field.removeprefix("provider_"): claim.value
        for claim in items
        if claim.field.startswith("provider_") and claim.value.strip()
    }
    if "yahoo_symbol" in selected:
        provider_symbols.setdefault("yahoo", selected["yahoo_symbol"].value)
    return IdentityResolution(
        identity=CanonicalIdentity(
            instrument_id=instrument_id,
            name=selected.get("name", IdentityClaim(instrument_id, "name", instrument_id, "", SourceAuthority.MANUAL)).value,
            isin=isin,
            isin_status=isin_status,
            ticker=selected.get("ticker", IdentityClaim(instrument_id, "ticker", "", "", SourceAuthority.MANUAL)).value,
            exchange=_optional(selected.get("exchange")),
            currency=_optional(selected.get("currency")),
            asset_type=selected.get("asset_type", IdentityClaim(instrument_id, "asset_type", "unknown", "", SourceAuthority.MANUAL)).value,
            provider_symbols=provider_symbols,
            confidence="high" if isin_status == "verified" and not conflicts else "manual_review",
            warnings=tuple(warnings),
        ),
        conflicts=tuple(conflicts),
    )


def _optional(claim: IdentityClaim | None) -> str | None:
    value = "" if claim is None else claim.value.strip()
    return value or None


def _isin_status(value: str | None) -> str:
    if not value or value.lower() in {"unknown", "needs_verification", "n/a"}:
        return "needs_verification"
    if len(value) == 12 and value[:2].isalpha() and value[2:].isalnum():
        return "verified"
    return "needs_verification"
