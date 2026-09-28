"""Pure routing and owner-claim calculations for Norwegian ECs."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from numbers import Real
from typing import Iterable, Mapping

from .models import (
    CONTRACT_ID,
    ECClaimPath,
    ECClaimState,
    SparebankAnalysis,
    SparebankRoutingResult,
)


_OWNER_FACTS = ("ec_capital", "overkursfond", "utjevningsfond")
_SELF_FACTS = ("sparebankens_fond", "gavefond", "kompensasjonsfond")
_REQUIRED_ROUTING_EC_TOKENS = {"equity_certificate", "certificate", "ec", "egenkapitalbevis"}
_NO_TOKENS = {"no", "norway", "norge", "norwegian"}
_SAVINGS_BANK_TOKENS = {
    "savings_bank",
    "savings-bank",
    "savings bank",
    "sparebank",
    "sparebanker",
    "savingsbank",
}


def routing(evidence: object) -> SparebankRoutingResult:
    """Route only with explicit jurisdiction, legal form and EC class evidence."""

    values = _as_mapping(evidence)
    jurisdiction_values = _evidence_values(values, "jurisdiction", "operating_country", "regulatory_country", "legal_domicile")
    legal_values = _evidence_values(values, "legal_form", "legal_entity_form", "issuer_type")
    instrument_values = _evidence_values(
        values,
        "instrument_subtype",
        "capital_class",
        "share_class",
        "instrument_type",
    )
    jurisdiction = jurisdiction_values[0] if jurisdiction_values else None
    legal_form = legal_values[0] if legal_values else None
    instrument = instrument_values[0] if instrument_values else None
    if not jurisdiction:
        no_reason = "JURISDICTION_EVIDENCE_MISSING"
    elif len({_normal(item) for item in jurisdiction_values}) > 1:
        no_reason = "JURISDICTION_EVIDENCE_CONFLICT"
    elif _normal(jurisdiction) not in {_normal(item) for item in _NO_TOKENS}:
        no_reason = "JURISDICTION_NOT_NORWEGIAN"
    else:
        no_reason = ""
    if not legal_form:
        form_reason = "LEGAL_FORM_EVIDENCE_MISSING"
    elif len({_normal(item) for item in legal_values}) > 1:
        form_reason = "LEGAL_FORM_EVIDENCE_CONFLICT"
    elif not _is_savings_bank(legal_form):
        form_reason = "LEGAL_FORM_NOT_SAVINGS_BANK"
    else:
        form_reason = ""
    if not instrument:
        class_reason = "EC_CLASS_EVIDENCE_MISSING"
    elif len({_normal(item) for item in instrument_values}) > 1:
        class_reason = "EC_CLASS_EVIDENCE_CONFLICT"
    elif not _is_ec(instrument):
        class_reason = "INSTRUMENT_NOT_EQUITY_CERTIFICATE"
    else:
        class_reason = ""
    reasons = tuple(item for item in (no_reason, form_reason, class_reason) if item)
    canonical = {
        "jurisdiction": jurisdiction,
        "legal_form": legal_form,
        "instrument_subtype": instrument,
    }
    return SparebankRoutingResult(
        applies=not reasons,
        suite_id=CONTRACT_ID if not reasons else None,
        reason_codes=reasons or ("SPAREBANK_EC_ROUTE_ALLOWED",),
        evidence=canonical,
    )


def reconstruct_eierbrok(
    owner_pools: Mapping[str, object] | Iterable[object] | None,
    self_owned_pools: Mapping[str, object] | Iterable[object] | None,
) -> float | None:
    """Reconstruct eierbrøk from the two ownership pools, never accounting equity."""

    owner = _pool_total(owner_pools)
    self_owned = _pool_total(self_owned_pools)
    if owner is None or self_owned is None or owner < 0 or self_owned < 0:
        return None
    denominator = owner + self_owned
    if denominator <= 0:
        return None
    return owner / denominator


def build_claim_state(
    evidence: object,
    *,
    decision_time: str | datetime | None = None,
) -> ECClaimState:
    """Build a dated immutable claim state from selected EC fact evidence."""

    values = _facts_mapping(evidence)
    outer = _as_mapping(evidence)
    known_candidates = [_text(_first(outer, "known_at")), _text(_first(values, "known_at"))]
    known_candidates.extend(
        _text(item.get("known_at"))
        for item in values.values()
        if isinstance(item, Mapping) and item.get("known_at")
    )
    known_candidates = [item for item in known_candidates if item]
    known_at = max(known_candidates, key=_parse_time) if known_candidates else None
    effective_at = _text(_first(outer, "effective_at", "period"))
    source_id = _text(_first(outer, "source_url", "source_id", "source", "filing_version", "sha256"))
    revision_id = _text(_first(outer, "filing_version", "sha256", "revision_id", "revision"))
    instrument_id = _text(_first(outer, "instrument_id"))
    bank_entity = _text(_first(outer, "bank_entity", "entity_id", "orgnr"))
    listing_id = _text(_first(outer, "listing_id", "ticker", "instrument_id"))
    reasons: list[str] = []
    if decision_time is not None and known_at and _parse_time(known_at) > _parse_time(decision_time):
        reasons.append("CLAIM_KNOWN_AFTER_DECISION_TIME")
        values = {}

    owner_pools = _available_pool_values(values, _OWNER_FACTS)
    self_owned_pools = _available_pool_values(values, _SELF_FACTS)
    missing_pool_components = _missing_pool_components(values)
    owner_total = _pool_total(owner_pools) if not any(name in missing_pool_components for name in _OWNER_FACTS) else None
    self_total = _pool_total(self_owned_pools) if not any(name in missing_pool_components for name in _SELF_FACTS) else None
    reconstructed = reconstruct_eierbrok(owner_pools, self_owned_pools) if not missing_pool_components else None
    reported = _fact_number(values, "eierbrok")
    difference = abs(reconstructed - reported) if reconstructed is not None and reported is not None else None
    if difference is not None and difference > 0.005:
        reasons.append("REPORTED_RECONSTRUCTED_EIERBROK_DIFFER" )

    registered = _fact_number(values, "registered_ec_count")
    outstanding = _fact_number(values, "outstanding_ec_count")
    treasury = _fact_number(values, "treasury_ec_count")
    weighted = _fact_number(values, "weighted_average_ec_count")
    period_end = _fact_number(values, "period_end_ec_count")
    owner_book = _fact_number(values, "owner_attributable_book")
    owner_earnings = _fact_number(values, "ec_attributable_result")
    foundation_count = _fact_number(values, "foundation_ec_count")
    foundation_holdings = _fact_value(values, "major_foundation_holdings")
    voting_share = _fact_number(values, "voting_share")
    accounting_equity = _fact_number(values, "accounting_equity")
    count_reasons = _count_reconciliation_reasons(registered, outstanding, treasury, foundation_count)
    if missing_pool_components:
        reasons.append("POOL_COMPONENT_EVIDENCE_MISSING")
    reasons.extend(count_reasons)
    if known_at is None or (source_id is None and revision_id is None):
        reasons.append("CLAIM_REVISION_IDENTITY_MISSING")
    provenance = _provenance(values, outer)
    field_provenance = {
        name: ("observed" if _fact_value(values, name) is not None else "unavailable")
        for name in (
            *_OWNER_FACTS,
            *_SELF_FACTS,
            "eierbrok",
            "registered_ec_count",
            "outstanding_ec_count",
            "treasury_ec_count",
            "weighted_average_ec_count",
            "ec_attributable_result",
            "major_foundation_holdings",
        )
    }
    if reconstructed is not None:
        field_provenance["reconstructed_eierbrok"] = "reconstructed"
    unavailable = tuple(dict.fromkeys(
        (*missing_pool_components, *(name for name, value in (
            ("eierbrok", reconstructed),
            ("period_end_ec_count", period_end),
            ("weighted_average_ec_count", weighted),
            ("owner_attributable_book", owner_book),
            ("owner_attributable_earnings", owner_earnings),
        ) if value is None))
    ))
    resolved = reconstructed is not None and not any(
        reason in {
            "CLAIM_KNOWN_AFTER_DECISION_TIME",
            "REPORTED_RECONSTRUCTED_EIERBROK_DIFFER",
            "POOL_COMPONENT_EVIDENCE_MISSING",
            "CLAIM_REVISION_IDENTITY_MISSING",
            "EC_COUNT_RECONCILIATION_CONTRADICTION",
        }
        for reason in reasons
    )
    if "CLAIM_KNOWN_AFTER_DECISION_TIME" in reasons:
        status = "stale"
    elif "REPORTED_RECONSTRUCTED_EIERBROK_DIFFER" in reasons:
        status = "ambiguous"
    elif count_reasons:
        status = "ambiguous"
    elif resolved:
        status = "resolved"
    else:
        status = "partial"
    observed_fields = sum(value is not None for value in (reconstructed, reported, period_end, weighted, owner_book, owner_earnings))
    coverage = observed_fields / 6.0
    return ECClaimState(
        effective_at=effective_at,
        known_at=known_at,
        source_id=source_id,
        revision_id=revision_id,
        instrument_id=instrument_id,
        bank_entity=bank_entity,
        listing_id=listing_id,
        owner_pools=owner_pools,
        self_owned_pools=self_owned_pools,
        owner_pool_total=owner_total,
        self_owned_pool_total=self_total,
        reported_eierbrok=reported,
        reconstructed_eierbrok=reconstructed,
        eierbrok_difference=difference,
        registered_ec_count=registered,
        outstanding_ec_count=outstanding,
        treasury_ec_count=treasury,
        period_end_ec_count=period_end,
        weighted_average_ec_count=weighted,
        owner_attributable_book=owner_book,
        owner_attributable_earnings=owner_earnings,
        foundation_ec_count=foundation_count,
        foundation_holdings=foundation_holdings,
        voting_share=voting_share,
        venue=_text(_first(values, "venue", "listing_venue")),
        accounting_equity=accounting_equity,
        claim_status=status,
        provenance=provenance,
        field_provenance=field_provenance,
        unavailable_fields=unavailable,
        coverage=coverage,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def build_claim_path(
    claim_state: ECClaimState,
    payouts: Iterable[Mapping[str, object]] = (),
) -> ECClaimPath:
    """Apply each side's payout ratio independently (book equation 2.2)."""

    owner = claim_state.owner_pool_total
    self_owned = claim_state.self_owned_pool_total
    if owner is None or self_owned is None:
        return ECClaimPath(reason_codes=("CLAIM_POOL_EVIDENCE_MISSING",))
    payouts = tuple(payouts)
    if not payouts:
        return ECClaimPath(reason_codes=("PAYOUT_EVIDENCE_MISSING",))
    points: list[Mapping[str, object]] = []
    for index, payout in enumerate(payouts, start=1):
        owner_ratio = _ratio(payout, "owner_payout_ratio", "owner_payout")
        self_ratio = _ratio(payout, "self_owned_payout_ratio", "self_owned_payout")
        if owner_ratio is None or self_ratio is None:
            return ECClaimPath(periods=tuple(points), reason_codes=("PAYOUT_RATIO_EVIDENCE_MISSING",))
        total_earnings = _number(payout, "profit", "earnings", "net_profit")
        if total_earnings is None:
            return ECClaimPath(periods=tuple(points), reason_codes=("PROFIT_EVIDENCE_MISSING",))
        denominator_before = owner + self_owned
        current = owner / denominator_before if denominator_before > 0 else None
        if current is None:
            return ECClaimPath(periods=tuple(points), reason_codes=("CLAIM_POOL_EVIDENCE_MISSING",))
        owner_earnings = total_earnings * current
        self_earnings = total_earnings - owner_earnings
        owner_distribution = owner_earnings * owner_ratio
        self_distribution = self_earnings * self_ratio
        owner += owner_earnings - owner_distribution
        self_owned += self_earnings - self_distribution
        denominator = owner + self_owned
        points.append(
            {
                "period": payout.get("period", index),
                "owner_pool": owner,
                "self_owned_pool": self_owned,
                "eierbrok": owner / denominator if denominator > 0 else None,
                "owner_payout_ratio": owner_ratio,
                "self_owned_payout_ratio": self_ratio,
                "profit": total_earnings,
                "owner_profit_share": owner_earnings,
                "self_owned_profit_share": self_earnings,
                "owner_distribution": owner_distribution,
                "self_owned_distribution": self_distribution,
            }
        )
    return ECClaimPath(periods=tuple(points))


def owner_per_ec_figures(
    claim_state: ECClaimState,
    *,
    price: float | None = None,
) -> Mapping[str, object]:
    """Return owner-consistent values with explicit count conventions."""

    if claim_state.claim_status != "resolved":
        return {
            "owner_book_per_ec": None,
            "owner_eps": None,
            "owner_pb": None,
            "owner_pe": None,
            "reason": "OWNER_VALUATION_CLAIM_NOT_RESOLVED",
            "count_conventions": {
                "owner_book_per_ec": "period_end_ec_count",
                "owner_eps": "weighted_average_ec_count",
                "owner_pb": "period_end_ec_count",
                "owner_pe": "weighted_average_ec_count",
            },
        }
    book = _divide(claim_state.owner_attributable_book, claim_state.period_end_ec_count)
    eps = _divide(claim_state.owner_attributable_earnings, claim_state.weighted_average_ec_count)
    result: dict[str, object] = {
        "owner_book_per_ec": book,
        "owner_eps": eps,
        "owner_pb": _divide(price, book),
        "owner_pe": _divide(price, eps),
        "count_conventions": {
            "owner_book_per_ec": "period_end_ec_count",
            "owner_eps": "weighted_average_ec_count",
            "owner_pb": "period_end_ec_count",
            "owner_pe": "weighted_average_ec_count",
        },
    }
    return result


def analyse_sparebank_ec(
    evidence: object,
    *,
    decision_time: str | datetime | None = None,
    price: float | None = None,
    payouts: Iterable[Mapping[str, object]] = (),
    bank_metrics: Iterable[object] = (),
    bank_economics_evidence: Mapping[str, object] | None = None,
    events: Iterable[Mapping[str, object]] = (),
) -> SparebankAnalysis:
    """Canonical pure entry point for the versioned Sparebank EC suite."""

    routed = routing(evidence)
    claim = build_claim_state(evidence, decision_time=decision_time)
    path = build_claim_path(claim, payouts)
    figures = owner_per_ec_figures(claim, price=price)
    reasons = list(routed.reason_codes)
    reasons.extend(claim.reason_codes)
    if figures.get("reason"):
        reasons.append(str(figures["reason"]))
    generic_status = "inapplicable" if routed.applies and claim.claim_status != "resolved" else "not_applicable"
    generic_reason = (
        f"sparebank_ec_claim_{claim.claim_status}" if generic_status == "inapplicable" else None
    )
    if generic_reason:
        reasons.append("GENERIC_BANK_VALUATION_INAPPLICABLE")
    from .bank_economics import build_bank_economics
    from .events import analyse_events
    bank_economics = build_bank_economics(bank_economics_evidence, bank_metrics=bank_metrics)
    event_analysis = analyse_events(events, decision_time=decision_time if isinstance(decision_time, str) else None)
    return SparebankAnalysis(
        contract=CONTRACT_ID,
        routing=routed,
        claim_state=claim,
        claim_path=path,
        coverage=claim.coverage,
        reason_codes=tuple(dict.fromkeys(reasons)),
        provenance=claim.provenance,
        owner_book_per_ec=figures["owner_book_per_ec"],
        owner_eps=figures["owner_eps"],
        owner_pb=figures["owner_pb"],
        owner_pe=figures["owner_pe"],
        count_conventions=figures["count_conventions"],
        generic_valuation_status=generic_status,
        generic_valuation_reason=generic_reason,
        bank_economics=bank_economics,
        events=event_analysis,
    )


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    result: dict[str, object] = {}
    for name in ("jurisdiction", "operating_country", "regulatory_country", "legal_domicile", "legal_form", "issuer_type", "instrument_subtype", "instrument_type", "capital_class", "share_class"):
        if hasattr(value, name):
            result[name] = getattr(value, name)
    if hasattr(value, "special_structures"):
        result["special_structures"] = getattr(value, "special_structures")
    if hasattr(value, "business_model_tags"):
        result["business_model_tags"] = getattr(value, "business_model_tags")
    return result


def _facts_mapping(value: object) -> Mapping[str, object]:
    outer = _as_mapping(value)
    facts = outer.get("facts")
    return facts if isinstance(facts, Mapping) else outer


def _first(values: Mapping[str, object], *names: str) -> object | None:
    for name in names:
        value = values.get(name)
        if value is not None and str(value).strip():
            return value
    return None


def _evidence_values(values: Mapping[str, object], *names: str) -> list[object]:
    result: list[object] = []
    for name in names:
        value = values.get(name)
        if isinstance(value, (tuple, list, set)):
            result.extend(item for item in value if item is not None and str(item).strip())
        elif value is not None and str(value).strip():
            result.append(value)
    return result


def _matching_label(values: Mapping[str, object], wanted: str) -> object | None:
    for key in ("special_structures", "business_model_tags", "capital_classes"):
        candidates = values.get(key)
        if isinstance(candidates, (tuple, list, set)):
            for candidate in candidates:
                if _normal(candidate) == _normal(wanted):
                    return candidate
    return None


def _fact_value(values: Mapping[str, object], name: str) -> object | None:
    item = values.get(name)
    if isinstance(item, Mapping):
        if item.get("available") is False:
            return None
        return item.get("value")
    return item


def _fact_number(values: Mapping[str, object], name: str) -> float | None:
    value = _fact_value(values, name)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _available_pool_values(values: Mapping[str, object], names: Iterable[str]) -> dict[str, float]:
    return {name: number for name in names if (number := _fact_number(values, name)) is not None}


def _missing_pool_components(values: Mapping[str, object]) -> tuple[str, ...]:
    missing: list[str] = []
    for name in (*_OWNER_FACTS, *_SELF_FACTS):
        if name in values and _fact_number(values, name) is None:
            missing.append(name)
    return tuple(missing)


def _count_reconciliation_reasons(
    registered: float | None,
    outstanding: float | None,
    treasury: float | None,
    foundation: float | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if any(value is not None and value < 0 for value in (registered, outstanding, treasury, foundation)):
        reasons.append("EC_COUNT_RECONCILIATION_CONTRADICTION")
    if registered is not None and treasury is not None and treasury > registered:
        reasons.append("EC_COUNT_RECONCILIATION_CONTRADICTION")
    if registered is not None and treasury is not None and outstanding is not None:
        if not math.isclose(outstanding, registered - treasury, rel_tol=0.0, abs_tol=1e-9):
            reasons.append("EC_COUNT_RECONCILIATION_CONTRADICTION")
    if outstanding is not None and foundation is not None and foundation > outstanding:
        reasons.append("EC_COUNT_RECONCILIATION_CONTRADICTION")
    return tuple(dict.fromkeys(reasons))


def _pool_total(value: Mapping[str, object] | Iterable[object] | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Mapping):
        numbers = []
        for item in value.values():
            try:
                number = float(item)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number):
                return None
            numbers.append(number)
    else:
        numbers = []
        for item in value:
            try:
                number = float(item)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number):
                return None
            numbers.append(number)
    return sum(numbers) if numbers else None


def _provenance(values: Mapping[str, object], outer: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, item in values.items():
        if isinstance(item, Mapping):
            source = item.get("source_locator") or item.get("source_url") or item.get("filing_version")
            if source:
                result[name] = str(source)
    for name in ("source_url", "sha256", "filing_version"):
        if outer.get(name):
            result[name] = str(outer[name])
    return result


def _ratio(values: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = values.get(name)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and 0.0 <= number <= 1.0:
            return number
    return None


def _number(values: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        try:
            number = float(values.get(name))
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _normal(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", " ").replace("-", " ")


def _is_ec(value: object) -> bool:
    normalized = _normal(value)
    return normalized in {_normal(item) for item in _REQUIRED_ROUTING_EC_TOKENS} or "equity certificate" in normalized or "egenkapitalbevis" in normalized


def _is_savings_bank(value: object) -> bool:
    normalized = _normal(value)
    return normalized in {_normal(item) for item in _SAVINGS_BANK_TOKENS} or "savings bank" in normalized or normalized == "sparebank"


def _text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "analyse_sparebank_ec",
    "build_claim_path",
    "build_claim_state",
    "owner_per_ec_figures",
    "reconstruct_eierbrok",
    "routing",
]
