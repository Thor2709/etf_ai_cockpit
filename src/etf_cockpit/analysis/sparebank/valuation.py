"""Pure owner-consistent valuation and implementation calculations for ECs.

All functions are deliberately input-driven.  Missing market depth, rates or
scenario assumptions remain unavailable; this module never fetches data or
grants execution authority.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from etf_cockpit.core.values import finite_float_or_none as _num
from etf_cockpit.portfolio.costs import COST_MODEL_ID

from .models import ECClaimState, UNAVAILABLE


def _state(value: ECClaimState | Mapping[str, object]) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def owner_valuation(
    claim: ECClaimState | Mapping[str, object],
    *,
    price: float | None = None,
    count_convention: Mapping[str, str] | None = None,
    allow_partial: bool = False,
) -> dict[str, object]:
    """Value the claim with each available matched filing input."""

    state = _state(claim)
    resolved = state.get("claim_status") == "resolved"
    if not resolved and not allow_partial:
        return {"status": "unavailable", "reason_code": "OWNER_VALUATION_CLAIM_NOT_RESOLVED", "execution_allowed": False}
    supplied_conventions = state.get("count_conventions")
    conventions = dict(count_convention or (supplied_conventions if isinstance(supplied_conventions, Mapping) else {
        "book": "period_end_ec_count",
        "earnings": "weighted_average_ec_count",
    }))
    if conventions.get("book") != "period_end_ec_count" or conventions.get("earnings") != "weighted_average_ec_count":
        raise ValueError("owner book and earnings require their matched count conventions")
    book = _num(state.get("owner_attributable_book"))
    book_source = "owner_attributable_book"
    if book is None:
        book = _num(state.get("owner_pool_total"))
        book_source = "owner_pool_total"
    earnings = _num(state.get("owner_attributable_earnings"))
    period_count = _num(state.get("period_end_ec_count"))
    count_source = "period_end_ec_count"
    if period_count is None:
        period_count = _num(state.get("outstanding_ec_count"))
        count_source = "outstanding_ec_count"
    if period_count is None:
        registered = _num(state.get("registered_ec_count"))
        treasury = _num(state.get("treasury_ec_count"))
        if registered is not None:
            period_count = registered - treasury if treasury is not None else registered
            count_source = "registered_ec_count_less_treasury" if treasury is not None else "registered_ec_count"
    weighted_count = _num(state.get("weighted_average_ec_count"))
    if book is None or period_count is None or period_count <= 0:
        return {"status": "unavailable", "reason_code": "OWNER_VALUATION_EVIDENCE_MISSING", "execution_allowed": False}
    book_per_ec = book / period_count
    eps = earnings / weighted_count if earnings is not None and weighted_count is not None and weighted_count > 0 else None
    px = _num(price)
    if px is not None and px <= 0:
        px = None
    tangible_book = _num(state.get("owner_attributable_tangible_book", state.get("tangible_owner_book")))
    result: dict[str, object] = {
        "status": "resolved" if resolved and eps is not None else "partial", "owner_book_per_ec": book_per_ec, "owner_eps": eps,
        "owner_pb": None if px is None or book_per_ec <= 0 else px / book_per_ec,
        "owner_pe": None if px is None or eps is None or eps <= 0 else px / eps,
        "roe": earnings / book if earnings is not None and book else None,
        "rote": earnings / tangible_book if tangible_book else None,
        "count_conventions": conventions,
        "count_sources": {"book": book_source, "book_count": count_source, "earnings_count": "weighted_average_ec_count"},
        "execution_allowed": False,
    }
    return result


def stable_pb(r: float, k: float, g: float) -> dict[str, float]:
    """Return stable-model value/book and implied payout (book eq. 5.3)."""

    r, k, g = (_num(r), _num(k), _num(g))
    if None in (r, k, g):
        raise ValueError("r, k and g are required")
    if k <= g:
        raise ValueError("required return k must exceed growth g")
    if g < 0 or g > r:
        raise ValueError("growth must satisfy 0 <= g <= r")
    return {"pb": (r - g) / (k - g), "payout": 1.0 - g / r if r else 0.0, "r": r, "k": k, "g": g}


def stable_model(r: float, k: float, g: float) -> float:
    """Scalar compatibility wrapper for the stable P/B diagnostic."""

    return stable_pb(r, k, g)["pb"]


def dividend_valuation(
    book_value: float,
    returns: Iterable[float],
    payout: float,
    *,
    required_return: float,
    terminal_return: float | None = None,
    terminal_growth: float | None = None,
) -> dict[str, object]:
    """Dated dividend route under clean surplus, with an optional terminal value."""

    book, payout, k = _num(book_value), _num(payout), _num(required_return)
    years = tuple(_num(item) for item in returns)
    if book is None or payout is None or k is None or not years or any(item is None for item in years):
        return {"status": "unavailable", "reason_code": "DIVIDEND_INPUTS_MISSING"}
    if not 0 <= payout <= 1 or k <= 0:
        raise ValueError("payout must be in [0, 1] and required return positive")
    dividends: list[float] = []
    pv_dividends = 0.0
    for index, ret in enumerate(years, start=1):
        dividend = book * ret * payout
        dividends.append(dividend)
        pv_dividends += dividend / (1 + k) ** index
        book += book * ret * (1 - payout)
    terminal = None
    pv_terminal = 0.0
    if terminal_return is not None or terminal_growth is not None:
        tr, tg = _num(terminal_return), _num(terminal_growth)
        if None in (tr, tg) or k <= tg or tg < 0 or tg > tr:
            raise ValueError("terminal inputs require k > g and 0 <= g <= r")
        # Clean-surplus terminal payout is implied by the stated terminal
        # return and growth; it must not silently reuse an interim payout.
        terminal_payout = 1.0 - tg / tr if tr else 0.0
        terminal = book * tr * terminal_payout / (k - tg)
        pv_terminal = terminal / (1 + k) ** len(years)
    return {
        "status": "resolved", "value": pv_dividends + pv_terminal,
        "dividends": tuple(dividends), "pv_dividends": pv_dividends,
        "terminal_value": terminal, "pv_terminal": pv_terminal,
        "ending_book": book, "required_return": k,
    }


def residual_income_valuation(
    book_value: float,
    returns: Iterable[float],
    required_return: float,
    *,
    payout: float | None = None,
    terminal_return: float | None = None,
    terminal_growth: float | None = None,
) -> dict[str, object]:
    """Residual-income route using opening book and clean-surplus evolution."""

    book, k = _num(book_value), _num(required_return)
    years = tuple(_num(item) for item in returns)
    if book is None or k is None or not years or any(item is None for item in years):
        return {"status": "unavailable", "reason_code": "RESIDUAL_INPUTS_MISSING"}
    if k <= 0:
        raise ValueError("required return must be positive")
    initial = book
    payout_value = _num(payout)
    if payout_value is not None and not 0 <= payout_value <= 1:
        raise ValueError("payout must be in [0, 1]")
    pv = book
    residuals: list[float] = []
    for index, ret in enumerate(years, start=1):
        residual = book * (ret - k)
        residuals.append(residual)
        pv += residual / (1 + k) ** index
        book += book * ret * (1 - payout_value) if payout_value is not None else book * ret
    terminal = 0.0
    if terminal_return is not None or terminal_growth is not None:
        tr, tg = _num(terminal_return), _num(terminal_growth)
        if None in (tr, tg) or k <= tg or tg < 0 or tg > tr:
            raise ValueError("terminal inputs require k > g and 0 <= g <= r")
        terminal = book * (tr - k) / (k - tg) / (1 + k) ** len(years)
        pv += terminal
    return {"status": "resolved", "value": pv, "residual_income": tuple(residuals), "terminal_pv": terminal, "opening_book": initial, "ending_book": book}


def recovery_valuation(book_value: float, dividends: Iterable[float], terminal_value: float, *, required_return: float = 0.10) -> dict[str, object]:
    """Convenience route for a dated recovery table with explicit cash flows."""

    book, terminal, k = _num(book_value), _num(terminal_value), _num(required_return)
    values = tuple(_num(item) for item in dividends)
    if None in (book, terminal, k) or any(item is None for item in values) or k <= 0:
        return {"status": "unavailable", "reason_code": "RECOVERY_INPUTS_MISSING"}
    pv_dividends = sum(item / (1 + k) ** index for index, item in enumerate(values, 1))
    pv_terminal = terminal / (1 + k) ** len(values)
    return {"status": "resolved", "value": pv_dividends + pv_terminal, "pv_dividends": pv_dividends, "pv_terminal": pv_terminal, "dividends": values, "terminal_value": terminal}


def residual_income(*args, **kwargs) -> dict[str, object]:
    return residual_income_valuation(*args, **kwargs)


def implied_roe(price_to_book: float, required_return: float, growth: float) -> float:
    pb, k, g = _num(price_to_book), _num(required_return), _num(growth)
    if None in (pb, k, g) or pb <= 0 or k <= g:
        raise ValueError("positive P/B and k > g are required")
    return g + pb * (k - g)


def implied_required_return(price_to_book: float, sustainable_roe: float, growth: float) -> float:
    pb, r, g = _num(price_to_book), _num(sustainable_roe), _num(growth)
    if None in (pb, r, g) or pb <= 0:
        raise ValueError("positive P/B is required")
    return g + (r - g) / pb


def reverse_valuation(price_to_book: float, *, k: float | None = None, r: float | None = None, g: float) -> dict[str, float]:
    result: dict[str, float] = {"price_to_book": float(price_to_book), "g": float(g)}
    if k is not None:
        result["implied_r"] = implied_roe(price_to_book, k, g)
    if r is not None:
        result["implied_k"] = implied_required_return(price_to_book, r, g)
    if len(result) == 2:
        raise ValueError("k or r is required")
    return result


def capital_release(book_value: float, earnings: float, release: float, earnings_on_released_capital: float) -> dict[str, float]:
    book, profit, released, carry = map(_num, (book_value, earnings, release, earnings_on_released_capital))
    if None in (book, profit, released, carry) or released < 0:
        raise ValueError("capital release inputs are required")
    adjusted = profit - carry
    operating_value = book + released
    return {"release": released, "earnings_before": profit, "earnings_after": adjusted, "operating_value": operating_value, "operating_return": adjusted / operating_value if operating_value else 0.0}


def buyback_accretion(book_value: float, intrinsic_value: float, count: float, quantity: float, price: float) -> dict[str, object]:
    book, value, n, q, px = map(_num, (book_value, intrinsic_value, count, quantity, price))
    if None in (book, value, n, q, px) or n <= 0 or q <= 0 or q >= n:
        raise ValueError("valid pre-buyback book, value and counts are required")
    post_book_per_ec = (book - q * px) / (n - q)
    post_value_per_ec = (value - q * px) / (n - q)
    return {"book_per_ec_before": book / n, "book_per_ec_after": post_book_per_ec, "book_accretion": post_book_per_ec - book / n, "intrinsic_per_ec_before": value / n, "intrinsic_per_ec_after": post_value_per_ec, "intrinsic_accretion": post_value_per_ec - value / n if px < value / n else 0.0, "intrinsic_accretion_eligible": px < value / n, "execution_allowed": False}


def scenario_value(scenarios: Iterable[Mapping[str, object]] | None) -> dict[str, object]:
    if scenarios is None:
        return {"status": "unavailable", "reason_code": "SCENARIO_ASSUMPTIONS_MISSING", "scenarios": ()}
    rows = tuple(dict(item) for item in scenarios)
    if not rows:
        return {"status": "unavailable", "reason_code": "SCENARIO_ASSUMPTIONS_MISSING", "scenarios": ()}
    weighted = 0.0
    total_weight = 0.0
    for row in rows:
        weight, value = _num(row.get("weight")), _num(row.get("value"))
        if weight is None or value is None or weight < 0:
            raise ValueError("scenario weights and values must be explicit and non-negative")
        weighted += weight * value
        total_weight += weight
    if not math.isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("scenario weights must sum to one")
    return {"status": "resolved", "value": weighted, "scenarios": rows, "weight_semantics": "operator_supplied", "execution_allowed": False}


def price_implied_state_weight(price: float, reference_value: float, improvement_value: float) -> dict[str, object]:
    """Report eq. 7.4's conditional pricing weight, never as a probability."""

    px, reference, improved = map(_num, (price, reference_value, improvement_value))
    if None in (px, reference, improved) or improved == reference:
        return {"status": "unavailable", "reason_code": "STATE_VALUES_NOT_IDENTIFIABLE"}
    weight = (px - reference) / (improved - reference)
    return {"status": "resolved", "price_implied_weight": weight, "conditional_pricing_weight": True, "mis_specified": not 0 <= weight <= 1, "execution_allowed": False}


def implementation_shortfall(*, reference_price: float, filled_quantity: float, fill_price: float, unfilled_quantity: float = 0.0, end_price: float | None = None, fees: float = 0.0) -> dict[str, object]:
    """Calculate shortfall only when a fill simulation supplies the inputs."""

    reference, filled, fill, unfilled, end, fee = map(_num, (reference_price, filled_quantity, fill_price, unfilled_quantity, end_price, fees))
    if None in (reference, filled, fill, unfilled, fee) or reference <= 0 or filled < 0 or unfilled < 0:
        return {"status": "unavailable", "reason_code": "FILL_SIMULATION_MISSING"}
    opportunity = unfilled * max(0.0, (end if end is not None else reference) - reference)
    implementation = filled * (fill - reference) + fee + opportunity
    return {"status": "resolved", "shortfall": implementation, "shortfall_pct": implementation / (reference * max(1.0, filled + unfilled)), "filled_quantity": filled, "unfilled_quantity": unfilled, "execution_allowed": False}


def decision_price(value: float, hurdle: float, *, years: float = 1.0, exit_cost: float = 0.0) -> float:
    value, hurdle, years, cost = map(_num, (value, hurdle, years, exit_cost))
    if None in (value, hurdle, years, cost) or hurdle <= -1 or years < 0 or not 0 <= cost < 1:
        raise ValueError("valid value, hurdle, years and exit cost are required")
    return value * (1 - cost) / (1 + hurdle) ** years


def expected_irr(price: float, cash_flows: Iterable[float], *, guess: float = 0.1) -> float | None:
    px = _num(price)
    flows = tuple(_num(item) for item in cash_flows)
    if px is None or px <= 0 or not flows or any(item is None for item in flows):
        return None
    def npv(rate: float) -> float:
        return -px + sum(item / (1 + rate) ** (index + 1) for index, item in enumerate(flows))
    low, high = -0.99, 10.0
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(100):
        mid = (low + high) / 2
        if npv(low) * npv(mid) <= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def days_to_trade(quantity: float, adv: float, participation: float) -> float | str:
    qty, volume, rate = map(_num, (quantity, adv, participation))
    if qty is None or volume is None or rate is None or qty < 0 or volume <= 0 or not 0 < rate <= 1:
        return UNAVAILABLE
    return qty / (volume * rate)


def executable_order(quantity: float, asks: Iterable[Mapping[str, object]] | None, *, fees: float = 0.0, limit_price: float | None = None, instrument_id: str = "sparebank-ec", config: object | None = None, order_value_eur: float | None = None) -> dict[str, object]:
    qty, fee = _num(quantity), _num(fees)
    if qty is None or qty <= 0 or fee is None or fee < 0:
        raise ValueError("quantity and non-negative fees are required")
    levels = tuple(asks or ())
    if levels:
        remaining, cost, filled = qty, 0.0, 0.0
        for row in levels:
            px, available = _num(row.get("price")), _num(row.get("quantity", row.get("size")))
            if px is None or available is None or available <= 0 or (limit_price is not None and px > limit_price):
                continue
            take = min(remaining, available)
            cost += take * px
            filled += take
            remaining -= take
            if remaining <= 0:
                break
        if filled <= 0:
            return {"status": "unavailable", "reason_code": "NO_EXECUTABLE_DEPTH", "filled_quantity": 0.0, "execution_allowed": False}
        return {"status": "resolved" if remaining <= 0 else "partial", "filled_quantity": filled, "unfilled_quantity": remaining, "vwap": cost / filled, "all_in_price": (cost + fee) / filled, "fees": fee, "execution_allowed": False, "shortfall": None}
    if config is not None and order_value_eur is not None:
        from etf_cockpit.portfolio.costs import estimate_execution_cost

        estimate = estimate_execution_cost(config, instrument_id, float(order_value_eur))
        return {"status": "unavailable", "reason_code": "DEPTH_UNAVAILABLE", "execution_cost_model": estimate.model_id, "estimate_kind": estimate.estimate_kind, "estimate": estimate.as_dict(), "execution_allowed": False}
    return {"status": "unavailable", "reason_code": "DEPTH_UNAVAILABLE", "filled_quantity": 0.0, "unfilled_quantity": qty, "execution_cost_model": COST_MODEL_ID, "estimate_kind": "labelled_estimate", "execution_allowed": False}


def valuation(claim: ECClaimState | Mapping[str, object], *, price: float | None = None, assumptions: Mapping[str, object] | None = None) -> dict[str, object]:
    """Build the explicit valuation section used by the suite entry point."""

    standalone = owner_valuation(claim, price=price, allow_partial=True)
    if standalone.get("status") not in {"resolved", "partial"}:
        return {"status": "unavailable", "standalone": standalone, "reverse": {"status": "unavailable"}, "execution_allowed": False}
    assumptions = assumptions or {}
    if not isinstance(assumptions, Mapping):
        return {"status": "unavailable", "standalone": standalone, "reason_code": "VALUATION_ASSUMPTIONS_INVALID", "execution_allowed": False}
    reverse = None
    if "price_to_book" in assumptions and "k" in assumptions and "g" in assumptions:
        reverse = reverse_valuation(float(assumptions["price_to_book"]), k=float(assumptions["k"]), g=float(assumptions["g"]))
    elif "price_to_book" in assumptions and "r" in assumptions and "g" in assumptions:
        reverse = reverse_valuation(float(assumptions["price_to_book"]), r=float(assumptions["r"]), g=float(assumptions["g"]))
    else:
        reverse = {"status": "unavailable", "reason_code": "REVERSE_INPUTS_MISSING"}
    scenarios = scenario_value(assumptions.get("scenarios")) if "scenarios" in assumptions else {"status": "unavailable", "reason_code": "SCENARIO_ASSUMPTIONS_MISSING", "scenarios": ()}

    recovery_inputs = assumptions.get("recovery")
    if isinstance(recovery_inputs, Mapping) and "required_return" in recovery_inputs:
        recovery = recovery_valuation(
            recovery_inputs.get("book_value"), recovery_inputs.get("dividends", ()), recovery_inputs.get("terminal_value"),
            required_return=recovery_inputs.get("required_return"),
        )
    else:
        recovery = {"status": "unavailable", "reason_code": "RECOVERY_INPUTS_MISSING"}

    four_state_inputs = assumptions.get("four_state")
    if isinstance(four_state_inputs, Mapping):
        weights = four_state_inputs.get("weights")
        values = four_state_inputs.get("values")
        rows = (
            tuple({"name": str(index), "weight": weight, "value": value} for index, (weight, value) in enumerate(zip(weights, values, strict=True)))
            if isinstance(weights, (list, tuple)) and isinstance(values, (list, tuple)) and len(weights) == len(values)
            else four_state_inputs.get("scenarios")
        )
        four_state = scenario_value(rows)
        four_state["state_count"] = len(rows) if isinstance(rows, (list, tuple)) else 0
    else:
        four_state = {"status": "unavailable", "reason_code": "FOUR_STATE_ASSUMPTIONS_MISSING", "scenarios": ()}

    marketability_inputs = assumptions.get("marketability")
    if marketability_inputs is None and isinstance(four_state_inputs, Mapping):
        marketability_inputs = {
            "with_marketability": four_state_inputs.get("with_marketability"),
            "without_marketability": four_state_inputs.get("without_marketability"),
        }
    if isinstance(marketability_inputs, Mapping):
        with_value = _num(marketability_inputs.get("with_marketability"))
        without_value = _num(marketability_inputs.get("without_marketability"))
        marketability = dict(marketability_inputs)
        marketability.update(
            status="resolved" if None not in (with_value, without_value) else "partial",
            with_marketability=with_value,
            without_marketability=without_value,
            reason_code=None if None not in (with_value, without_value) else "MARKETABILITY_VALUES_MISSING",
        )
    else:
        marketability = {"status": "unavailable", "reason_code": "MARKETABILITY_ASSUMPTIONS_MISSING"}

    capital_policy_inputs = assumptions.get("capital_policy")
    if isinstance(capital_policy_inputs, Mapping):
        try:
            capital_policy = capital_release(
                capital_policy_inputs["book_value"], capital_policy_inputs["earnings"],
                capital_policy_inputs["release"], capital_policy_inputs["earnings_on_released_capital"],
            )
            capital_policy["status"] = "resolved"
        except (KeyError, TypeError, ValueError):
            capital_policy = {"status": "unavailable", "reason_code": "CAPITAL_POLICY_INPUTS_MISSING"}
    else:
        capital_policy = {"status": "unavailable", "reason_code": "CAPITAL_POLICY_ASSUMPTIONS_MISSING"}

    irr_inputs = assumptions.get("irr") or assumptions.get("irr_assumptions")
    if isinstance(irr_inputs, Mapping):
        irr = expected_irr(irr_inputs.get("price", price), irr_inputs.get("cash_flows", ()))
        irr_section = {"status": "resolved" if irr is not None else "unavailable", "irr": irr}
    else:
        irr_section = {"status": "unavailable", "irr": None, "reason_code": "IRR_INPUTS_MISSING"}

    decision_inputs = assumptions.get("decision_price") or assumptions.get("decision_price_assumptions")
    if isinstance(decision_inputs, Mapping):
        try:
            decision = decision_price(decision_inputs["value"], decision_inputs["hurdle"], years=decision_inputs.get("years", 1.0), exit_cost=decision_inputs.get("exit_cost", 0.0))
            decision_section = {"status": "resolved", "price": decision, "hurdle": decision_inputs["hurdle"], "years": decision_inputs.get("years", 1.0), "exit_cost": decision_inputs.get("exit_cost", 0.0)}
        except (KeyError, TypeError, ValueError):
            decision_section = {"status": "unavailable", "reason_code": "DECISION_PRICE_INPUTS_MISSING"}
    else:
        decision_section = {"status": "unavailable", "reason_code": "DECISION_PRICE_INPUTS_MISSING"}

    implementation_inputs = assumptions.get("implementation") or assumptions.get("implementation_shortfall")
    if isinstance(implementation_inputs, Mapping):
        implementation = implementation_shortfall(**implementation_inputs)
    else:
        implementation = {"status": "unavailable", "reason_code": "IMPLEMENTATION_INPUTS_MISSING", "execution_allowed": False}
    resolved = any(section.get("status") == "resolved" for section in (recovery, four_state, marketability, capital_policy, irr_section, decision_section))
    return {
        "status": "resolved" if resolved else "partial", "standalone": standalone, "reverse": reverse,
        "scenarios": scenarios, "recovery": recovery, "four_state": four_state,
        "marketability": marketability, "capital_policy": capital_policy, "irr": irr_section,
        "decision_price": decision_section, "implementation": implementation,
        "timestamp": assumptions.get("timestamp", assumptions.get("valuation_timestamp", assumptions.get("as_of", UNAVAILABLE))),
        "currency": assumptions.get("currency", assumptions.get("output_currency", UNAVAILABLE)),
        "quantity": _num(assumptions.get("quantity", assumptions.get("position_quantity"))) if ("quantity" in assumptions or "position_quantity" in assumptions) else None,
        "implementation_shortfall": implementation,
        "execution_allowed": False,
    }


calculate_valuation = valuation
owner_consistent_valuation = owner_valuation
stable_price_to_book = stable_pb
implied_r = implied_roe
implied_k = implied_required_return
order_size = executable_order
calculate_stable_pb = stable_pb
calculate_dividend_value = dividend_valuation
calculate_residual_income = residual_income_valuation
implied_sustainable_roe = implied_roe
calculate_days_to_trade = days_to_trade
calculate_order_size = executable_order


__all__ = [
    "buyback_accretion", "calculate_days_to_trade", "calculate_dividend_value", "calculate_order_size", "calculate_residual_income", "calculate_stable_pb", "calculate_valuation", "capital_release", "days_to_trade", "decision_price", "dividend_valuation", "expected_irr", "executable_order", "implementation_shortfall", "implied_k", "implied_r", "implied_required_return", "implied_roe", "implied_sustainable_roe", "order_size", "owner_consistent_valuation", "owner_valuation", "price_implied_state_weight", "recovery_valuation", "residual_income", "residual_income_valuation", "reverse_valuation", "scenario_value", "stable_model", "stable_pb", "stable_price_to_book", "valuation",
]
