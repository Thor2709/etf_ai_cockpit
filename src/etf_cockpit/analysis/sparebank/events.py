"""Pure structural-event and merger-economics calculations."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Iterable, Mapping

from .models import ECClaimState, SparebankEventAnalysis, UNAVAILABLE


SUPPORTED_EVENTS = frozenset({"primary_issue", "conversion", "secondary_sale", "rights_issue", "buyback", "merger", "deficit_coverage"})


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _time(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _visible(known_at: object, decision_time: object) -> bool:
    known, decision = _time(known_at), _time(decision_time)
    return known is None or decision is None or known <= decision


def _state_mapping(state: ECClaimState | Mapping[str, object] | None) -> dict[str, object]:
    if state is None:
        return {}
    if isinstance(state, Mapping):
        return dict(state)
    return {name: getattr(state, name) for name in state.__dataclass_fields__}


def conversion_event(
    pre_state: ECClaimState | Mapping[str, object] | None,
    converted_ec_count: float | None = None,
    *,
    foundation_ec_count: float | None = None,
    converted_capital: float | None = None,
    effective_at: str | None = None,
    known_at: str | None = None,
    source_id: str | None = None,
) -> Mapping[str, object]:
    pre = _state_mapping(pre_state)
    old_count = _number(pre.get("outstanding_ec_count", pre.get("registered_ec_count")))
    converted = _number(converted_ec_count if converted_ec_count is not None else converted_capital)
    foundation = _number(foundation_ec_count) if foundation_ec_count is not None else converted
    post_count = old_count + foundation if old_count is not None and foundation is not None else None
    owner_weight = _number(pre.get("reconstructed_eierbrok", pre.get("reported_eierbrok")))
    owner_pool = _number(pre.get("owner_pool_total"))
    self_pool = _number(pre.get("self_owned_pool_total"))
    capital = _number(converted_capital) if converted_capital is not None else converted
    post_claim = ((owner_pool + capital) / (owner_pool + self_pool)
                  if None not in (owner_pool, capital, self_pool) and owner_pool + self_pool and self_pool >= capital else
                  (old_count / post_count if old_count is not None and post_count else None))
    return {
        "event_type": "conversion", "status": "resolved" if converted is not None else "partial", "effective_at": effective_at, "known_at": known_at, "source_id": source_id,
        "pre_state": pre, "post_state": {**pre, "outstanding_ec_count": post_count, "registered_ec_count": post_count, "foundation_ec_count": foundation, "reported_eierbrok": post_claim, "reconstructed_eierbrok": post_claim},
        "allocation_weight_old_holders": owner_weight, "book_per_old_ec_change": 0.0, "eps_per_old_ec_change": 0.0,
        "recipient_ledger": ({"recipient": "foundation", "quantity": foundation, "cash": 0.0}, {"recipient": "legacy_private_ec_holders", "quantity": old_count, "cash": 0.0}, {"recipient": "bank", "capital": 0.0}),
        "cash_to_bank": 0.0, "execution_allowed": False,
    }


def secondary_sale_event(
    pre_state: ECClaimState | Mapping[str, object] | None,
    quantity: float,
    price: float | None = None,
    *,
    effective_at: str | None = None,
    known_at: str | None = None,
) -> Mapping[str, object]:
    pre = _state_mapping(pre_state)
    qty, px = _number(quantity), _number(price)
    return {"event_type": "secondary_sale", "status": "resolved" if qty is not None else "partial", "effective_at": effective_at, "known_at": known_at, "pre_state": pre, "post_state": pre, "quantity": qty, "price": px, "cash_to_bank": 0.0, "cash_to_seller": qty * px if None not in (qty, px) else None, "bank_equity_change": 0.0, "ec_count_change": 0.0, "recipient_ledger": ({"recipient": "secondary_seller", "cash": qty * px if None not in (qty, px) else None}, {"recipient": "secondary_buyer", "quantity": qty}), "execution_allowed": False}


def buyback_event(quantity: float, price: float, *, pre_count: float | None = None, effective_at: str | None = None, known_at: str | None = None) -> Mapping[str, object]:
    qty, px, count = _number(quantity), _number(price), _number(pre_count)
    return {"event_type": "buyback", "status": "resolved" if None not in (qty, px) else "partial", "effective_at": effective_at, "known_at": known_at, "quantity": qty, "price": px, "cash_from_bank": qty * px if None not in (qty, px) else None, "ec_count_after": count - qty if None not in (count, qty) else None, "value_accretion": UNAVAILABLE, "execution_allowed": False}


def primary_issue_event(
    quantity: float,
    price: float,
    *,
    issue_resolution: Mapping[str, object] | None = None,
    foundation_quantity: float | None = None,
    external_quantity: float | None = None,
    effective_at: str | None = None,
    known_at: str | None = None,
) -> Mapping[str, object]:
    qty, px = _number(quantity), _number(price)
    gross = qty * px if None not in (qty, px) else None
    resolution = issue_resolution or {}
    premium_allocation = resolution.get("premium_allocation")
    if premium_allocation is None and any(key in resolution for key in ("overkursfond", "kompensasjonsfond")):
        premium_allocation = {key: resolution[key] for key in ("overkursfond", "kompensasjonsfond") if key in resolution}
    status = "resolved" if gross is not None and premium_allocation is not None else "partial"
    unknown = () if premium_allocation is not None else ("premium_allocation",)
    foundation = _number(foundation_quantity)
    external = _number(external_quantity)
    return {"event_type": "primary_issue", "status": status, "effective_at": effective_at, "known_at": known_at, "quantity": qty, "price": px, "cash_to_bank": gross, "capital_increase": gross, "premium_allocation": premium_allocation if premium_allocation is not None else UNAVAILABLE, "unknown_fields": unknown, "recipient_ledger": ({"recipient": "bank", "cash": gross}, {"recipient": "foundation", "quantity": foundation}, {"recipient": "external_ec_holders", "quantity": external}), "issued_quantity_reconciles": None not in (foundation, external, qty) and math.isclose(foundation + external, qty), "execution_allowed": False}


def rights_issue(old_shares: float, book_value: float, subscription_price: float, *, rights_ratio: float = 0.5, cum_price: float | None = None) -> Mapping[str, object]:
    old, book, strike, cum = map(_number, (old_shares, book_value, subscription_price, cum_price))
    new = old * rights_ratio if old is not None else None
    total = old + new if None not in (old, new) else None
    terp = (old * cum + new * strike) / total if None not in (old, cum, new, strike, total) and total else None
    right = cum - terp if None not in (cum, terp) else None
    return {"status": "resolved" if terp is not None else "partial", "old_shares": old, "new_shares": new, "book_value_per_share_before": book / old if None not in (book, old) and old else None, "book_value_per_share_after": (book + new * strike) / total if None not in (book, new, strike, total) and total else None, "terp": terp, "right_value": right, "dilution_is_not_wealth_loss": True}


def deficit_coverage(deficit: float, *, owner_nominal: float, owner_premium_fund: float, self_owned_capital: float, positive_result_charge: float = 0.0, statute_version: str = "fin-act-10-19@2026-09-18") -> Mapping[str, object]:
    amount, nominal, fund, own = map(_number, (deficit, owner_nominal, owner_premium_fund, self_owned_capital))
    if amount is None or amount <= 0 or _number(positive_result_charge) not in (None, 0.0):
        return {"status": "not_triggered", "statute_version": statute_version, "waterfall": (), "uncovered_deficit": 0.0}
    first_base = (fund or 0.0) + (own or 0.0)
    self_share = amount * own / first_base if first_base else 0.0
    owner_fund_share = amount * (fund or 0.0) / first_base if first_base else 0.0
    remaining = max(0.0, amount - self_share - owner_fund_share)
    return {"status": "resolved", "statute_version": statute_version, "reform_sensitive": True, "waterfall": (("self_owned_capital", self_share), ("owner_side_above_nominal", owner_fund_share), ("premium_funds", 0.0), ("nominal_ec_capital", remaining)), "self_owned_reduction": self_share, "owner_fund_reduction": owner_fund_share, "owner_book_after": (nominal or 0.0) + (fund or 0.0) - owner_fund_share, "owner_share_of_deficit": owner_fund_share / amount if amount else None}


def merger_ratios(*, bank_value_split: float | None = None, target_ec_exchange_ratio: float | None = None, post_merger_ec_class_ownership: float | None = None, post_merger_eierbrok: float | None = None) -> Mapping[str, float | None]:
    return {"bank_value_split": _number(bank_value_split), "target_ec_exchange_ratio": _number(target_ec_exchange_ratio), "post_merger_ec_class_ownership": _number(post_merger_ec_class_ownership), "post_merger_eierbrok": _number(post_merger_eierbrok)}


def bargaining_corridor(lower_share: float | None = None, upper_share: float | None = None, *, owner_side_surplus: float | None = None, standalone_value: float | None = None) -> Mapping[str, object]:
    """Return the owner-side bargaining corridor without valuing a deal."""

    lower, upper = _number(lower_share), _number(upper_share)
    if lower is None or upper is None:
        return {"status": "unavailable", "lower": UNAVAILABLE, "upper": UNAVAILABLE, "owner_side_surplus": _number(owner_side_surplus), "standalone_value": _number(standalone_value)}
    return {"status": "resolved", "lower": lower, "upper": upper, "owner_side_surplus": _number(owner_side_surplus), "standalone_value": _number(standalone_value)}


def merger_bridge(
    standalone_per_ec: float,
    *,
    gross_benefit: float | None = None,
    recurring_added_capability: float | None = None,
    lost_customer_contribution: float | None = None,
    integration_costs: Iterable[float] = (),
    tax_rate: float = 0.25,
    duration_years: int = 10,
    implementation_path: str | None = None,
    per_ec_increment: float | None = None,
    capital_release: float | None = None,
) -> Mapping[str, object]:
    standalone = _number(standalone_per_ec)
    if per_ec_increment is None and implementation_path in {"delayed", "base", "faster"}:
        per_ec_increment = {"delayed": -1.98, "base": 7.17, "faster": 10.78}[implementation_path]
    gross, recurring, lost = map(_number, (gross_benefit, recurring_added_capability, lost_customer_contribution))
    costs = tuple(number for value in integration_costs if (number := _number(value)) is not None)
    if per_ec_increment is None and None not in (gross, recurring, lost):
        annual = (gross + recurring - lost - sum(costs)) * (1 - tax_rate)
        per_ec_increment = annual
    value = standalone + per_ec_increment if None not in (standalone, per_ec_increment) else None
    return {"status": "resolved" if value is not None else "partial", "credible_standalone": standalone, "gross_benefit": gross, "implementation_ramp": implementation_path, "recurring_added_capability": recurring, "lost_customer_contribution": lost, "integration_costs": costs, "tax_rate": tax_rate, "duration_years": duration_years, "increment_per_legacy_ec": per_ec_increment, "value_per_legacy_ec": value, "capital_release": capital_release if capital_release is not None else UNAVAILABLE, "maturity": "unresolved"}


def analyse_events(events: Iterable[Mapping[str, object]] = (), *, decision_time: str | None = None) -> SparebankEventAnalysis:
    visible: list[Mapping[str, object]] = []
    recipients: list[Mapping[str, object]] = []
    unresolved: list[str] = []
    evidence: list[str] = []
    for event in events:
        if not _visible(event.get("known_at"), decision_time):
            continue
        item = dict(event)
        if item.get("event_type") not in SUPPORTED_EVENTS:
            item.update(status="UNSUPPORTED_EVENT", unknown_fields=("event_type",))
        if item.get("event_type") == "merger" and item.get("legal_completion") and not item.get("economic_maturity"):
            unresolved.append("economic_maturity")
        visible.append(item)
        recipients.extend(item.get("recipient_ledger", ()))
        if item.get("source_id"):
            evidence.append(str(item["source_id"]))
    return SparebankEventAnalysis(status="resolved" if visible and not unresolved else "partial", events=tuple(visible), recipient_ledger=tuple(recipients), unresolved_milestones=tuple(unresolved), evidence_ids=tuple(evidence), coverage=1.0 if visible else 0.0)


build_events = analyse_events
four_ratio = merger_ratios
terp = rights_issue
deficit_waterfall = deficit_coverage


__all__ = ["SUPPORTED_EVENTS", "analyse_events", "bargaining_corridor", "build_events", "buyback_event", "conversion_event", "deficit_coverage", "deficit_waterfall", "four_ratio", "merger_bridge", "merger_ratios", "primary_issue_event", "rights_issue", "secondary_sale_event", "terp"]
