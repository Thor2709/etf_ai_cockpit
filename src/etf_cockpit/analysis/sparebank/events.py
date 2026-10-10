"""Pure structural-event and merger-economics calculations."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Iterable, Mapping

from etf_cockpit.core.values import all_finite_or_none, finite_float_or_none as _number

from .models import ECClaimState, SparebankEventAnalysis, UNAVAILABLE


SUPPORTED_EVENTS = frozenset({"primary_issue", "conversion", "secondary_sale", "rights_issue", "buyback", "merger", "deficit_coverage"})


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
    # A point-in-time decision cannot safely use an event whose knowledge
    # timestamp is absent or malformed.  Unknown knowledge is only acceptable
    # when the caller did not request a point-in-time view.
    return decision is None or (known is not None and known <= decision)


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
    source_id: str | None = None,
) -> Mapping[str, object]:
    pre = _state_mapping(pre_state)
    qty, px = _number(quantity), _number(price)
    return {"event_type": "secondary_sale", "status": "resolved" if qty is not None else "partial", "effective_at": effective_at, "known_at": known_at, "source_id": source_id, "pre_state": pre, "post_state": pre, "quantity": qty, "price": px, "cash_to_bank": 0.0, "cash_to_seller": qty * px if None not in (qty, px) else None, "bank_equity_change": 0.0, "ec_count_change": 0.0, "recipient_ledger": ({"recipient": "secondary_seller", "cash": qty * px if None not in (qty, px) else None}, {"recipient": "secondary_buyer", "quantity": qty}), "execution_allowed": False}


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
    source_id: str | None = None,
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
    return {"event_type": "primary_issue", "status": status, "effective_at": effective_at, "known_at": known_at, "source_id": source_id, "quantity": qty, "price": px, "cash_to_bank": gross, "capital_increase": gross, "premium_allocation": premium_allocation if premium_allocation is not None else UNAVAILABLE, "unknown_fields": unknown, "recipient_ledger": ({"recipient": "bank", "cash": gross}, {"recipient": "foundation", "quantity": foundation}, {"recipient": "external_ec_holders", "quantity": external}), "issued_quantity_reconciles": None not in (foundation, external, qty) and math.isclose(foundation + external, qty), "execution_allowed": False}


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
    own_pool, fund_pool, nominal_pool = max(own or 0.0, 0.0), max(fund or 0.0, 0.0), max(nominal or 0.0, 0.0)
    first_base = fund_pool + own_pool
    # Each tier absorbs at most its pool; the remainder carries to the next tier (decision D10).
    first_absorbed = min(amount, first_base)
    self_share = first_absorbed * own_pool / first_base if first_base else 0.0
    owner_fund_share = first_absorbed * fund_pool / first_base if first_base else 0.0
    carried = max(0.0, amount - first_absorbed)
    nominal_share = min(carried, nominal_pool)
    uncovered = max(0.0, carried - nominal_share)
    return {"status": "partial" if uncovered > 0 else "resolved", "unknown_fields": ("uncovered_deficit",) if uncovered > 0 else (), "statute_version": statute_version, "reform_sensitive": True, "waterfall": (("self_owned_capital", self_share), ("owner_side_above_nominal", owner_fund_share), ("premium_funds", 0.0), ("nominal_ec_capital", nominal_share)), "self_owned_reduction": self_share, "owner_fund_reduction": owner_fund_share, "nominal_reduction": nominal_share, "uncovered_deficit": uncovered, "owner_book_after": nominal_pool + fund_pool - owner_fund_share - nominal_share, "owner_share_of_deficit": owner_fund_share / amount if amount else None}


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
    tax_rate: float | None = None,
    duration_years: int | None = None,
    implementation_path: str | None = None,
    per_ec_increment: float | None = None,
    capital_release: float | None = None,
    implementation_ramp: Iterable[float] | float | None = None,
    allocation_weight: float | None = None,
    legacy_ec_count: float | None = None,
    discount_rate: float | None = None,
    **aliases: object,
) -> Mapping[str, object]:
    gross_benefit = gross_benefit if gross_benefit is not None else aliases.get("gross")
    recurring_added_capability = recurring_added_capability if recurring_added_capability is not None else aliases.get("recurring")
    lost_customer_contribution = lost_customer_contribution if lost_customer_contribution is not None else aliases.get("lost")
    if not integration_costs and aliases.get("costs") is not None:
        integration_costs = aliases["costs"]  # type: ignore[assignment]
    tax_rate = _number(tax_rate if tax_rate is not None else aliases.get("tax"))
    duration_years = duration_years if duration_years is not None else aliases.get("duration")
    implementation_ramp = implementation_ramp if implementation_ramp is not None else aliases.get("ramp")
    allocation_weight = allocation_weight if allocation_weight is not None else _number(aliases.get("allocation"))
    legacy_ec_count = legacy_ec_count if legacy_ec_count is not None else _number(aliases.get("legacy_count"))
    discount_rate = discount_rate if discount_rate is not None else _number(aliases.get("discount"))
    standalone = _number(standalone_per_ec)
    gross, recurring, lost = map(_number, (gross_benefit, recurring_added_capability, lost_customer_contribution))
    integration_costs = tuple(integration_costs)
    costs = all_finite_or_none(integration_costs)
    ramp: tuple[float, ...] | None
    if implementation_ramp is None:
        ramp = None
    elif isinstance(implementation_ramp, (int, float)):
        ramp = (_number(implementation_ramp),)
    else:
        ramp = tuple(_number(item) for item in implementation_ramp)
    if ramp is not None and any(item is None for item in ramp):
        ramp = None
    if costs is None or (tax_rate is not None and not 0 <= tax_rate < 1):
        return {"status": "unavailable", "reason_code": "INVALID_MERGER_INPUT", "credible_standalone": standalone, "integration_costs": integration_costs, "tax_rate": tax_rate, "maturity": "unresolved"}
    annual = None
    if None not in (gross, recurring, lost, tax_rate):
        annual = (gross + recurring - lost - sum(costs)) * (1 - tax_rate)
    allocated = annual
    if allocated is not None and allocation_weight is not None:
        weight = _number(allocation_weight)
        allocated = allocated * weight if weight is not None else None
    if allocated is not None and legacy_ec_count is not None:
        count = _number(legacy_ec_count)
        allocated = allocated / count if count not in (None, 0) else None
    if per_ec_increment is None and allocated is not None:
        per_ec_increment = allocated
    discounted = None
    if per_ec_increment is not None:
        if ramp:
            cashflows = tuple(per_ec_increment * factor for factor in ramp)
        else:
            years = int(duration_years) if isinstance(duration_years, int) and duration_years > 0 else 1
            cashflows = (per_ec_increment,) * years
        if discount_rate is not None:
            rate = _number(discount_rate)
            discounted = (sum(value / (1 + rate) ** index for index, value in enumerate(cashflows, 1))
                          if rate is not None and rate > -1 else None)
        else:
            discounted = sum(cashflows)
    value_increment = discounted if discount_rate is not None else per_ec_increment
    value = standalone + value_increment if None not in (standalone, value_increment) else None
    return {"status": "resolved" if value is not None else "partial", "credible_standalone": standalone, "gross_benefit": gross, "implementation_ramp": implementation_path if implementation_ramp is None else ramp, "ramp_factors": ramp, "gross_benefit_after_tax": annual, "taxed_increment_per_legacy_ec": annual, "allocated_increment": allocated, "allocated_increment_per_legacy_ec": allocated, "discounted_increment": discounted, "discounted_increment_per_legacy_ec": discounted, "recurring_added_capability": recurring, "lost_customer_contribution": lost, "integration_costs": costs, "tax_rate": tax_rate, "duration_years": duration_years, "allocation_weight": _number(allocation_weight), "legacy_ec_count": _number(legacy_ec_count), "discount_rate": _number(discount_rate), "increment_per_legacy_ec": per_ec_increment, "value_per_legacy_ec": value, "capital_release": capital_release if capital_release is not None else UNAVAILABLE, "maturity": "unresolved"}


def analyse_events(events: Iterable[Mapping[str, object]] = (), *, decision_time: str | None = None) -> SparebankEventAnalysis:
    visible: list[Mapping[str, object]] = []
    recipients: list[Mapping[str, object]] = []
    unresolved: list[str] = []
    evidence: list[str] = []
    for event in events:
        if not _visible(event.get("known_at"), decision_time):
            continue
        item = dict(event)
        event_type = item.get("event_type")
        if event_type == "conversion":
            item = dict(conversion_event(item.get("pre_state", item.get("state")), item.get("converted_ec_count", item.get("converted")), foundation_ec_count=item.get("foundation_ec_count", item.get("foundation_ec")), converted_capital=item.get("converted_capital"), effective_at=item.get("effective_at"), known_at=item.get("known_at"), source_id=item.get("source_id")))
        elif event_type == "primary_issue":
            item = dict(primary_issue_event(item.get("quantity"), item.get("price"), issue_resolution=item.get("issue_resolution"), foundation_quantity=item.get("foundation_quantity"), external_quantity=item.get("external_quantity"), effective_at=item.get("effective_at"), known_at=item.get("known_at"), source_id=item.get("source_id")))
        elif event_type == "secondary_sale":
            item = dict(secondary_sale_event(item.get("pre_state"), item.get("quantity"), item.get("price"), effective_at=item.get("effective_at"), known_at=item.get("known_at"), source_id=item.get("source_id")))
        elif event_type == "rights_issue":
            item = dict(rights_issue(item.get("old_shares"), item.get("book_value"), item.get("subscription_price"), rights_ratio=item.get("rights_ratio", 0.5), cum_price=item.get("cum_price")))
            item.update(event_type="rights_issue", known_at=event.get("known_at"), effective_at=event.get("effective_at"), source_id=event.get("source_id"))
        elif event_type == "deficit_coverage":
            item = dict(deficit_coverage(item.get("deficit"), owner_nominal=item.get("owner_nominal"), owner_premium_fund=item.get("owner_premium_fund", item.get("owner_fund")), self_owned_capital=item.get("self_owned_capital", item.get("self_owned")), positive_result_charge=item.get("positive_result_charge", 0.0)))
            item.update(event_type="deficit_coverage", known_at=event.get("known_at"), effective_at=event.get("effective_at"), source_id=event.get("source_id"))
        elif event_type == "merger":
            item = dict(merger_bridge(item.get("standalone_per_ec", item.get("standalone")), gross_benefit=item.get("gross_benefit"), recurring_added_capability=item.get("recurring_added_capability"), lost_customer_contribution=item.get("lost_customer_contribution"), integration_costs=item.get("integration_costs", ()), tax_rate=item.get("tax_rate"), duration_years=item.get("duration_years"), implementation_path=item.get("implementation_path"), per_ec_increment=item.get("per_ec_increment"), capital_release=item.get("capital_release"), implementation_ramp=item.get("implementation_ramp"), allocation_weight=item.get("allocation_weight"), legacy_ec_count=item.get("legacy_ec_count"), discount_rate=item.get("discount_rate")))
            item.update(event_type="merger", known_at=event.get("known_at"), effective_at=event.get("effective_at"), legal_completion=event.get("legal_completion"), economic_maturity=event.get("economic_maturity"), source_id=event.get("source_id"))
        if event_type not in SUPPORTED_EVENTS:
            item.update(status="UNSUPPORTED_EVENT", unknown_fields=("event_type",))
        if item.get("event_type") == "merger" and item.get("legal_completion") and not item.get("economic_maturity"):
            unresolved.append("economic_maturity")
        visible.append(item)
        recipients.extend(item.get("recipient_ledger", ()))
        if item.get("source_id"):
            evidence.append(str(item["source_id"]))
    complete = visible and not unresolved and all(item.get("status") == "resolved" for item in visible)
    return SparebankEventAnalysis(status="resolved" if complete else "partial", events=tuple(visible), recipient_ledger=tuple(recipients), unresolved_milestones=tuple(unresolved), evidence_ids=tuple(evidence), coverage=1.0 if visible else 0.0)


build_events = analyse_events
four_ratio = merger_ratios
terp = rights_issue
deficit_waterfall = deficit_coverage


__all__ = ["SUPPORTED_EVENTS", "analyse_events", "bargaining_corridor", "build_events", "buyback_event", "conversion_event", "deficit_coverage", "deficit_waterfall", "four_ratio", "merger_bridge", "merger_ratios", "primary_issue_event", "rights_issue", "secondary_sale_event", "terp"]
