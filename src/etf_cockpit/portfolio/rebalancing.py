from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import pandas as pd

from etf_cockpit.core.config import AppConfig
from etf_cockpit.portfolio.costs import estimate_execution_cost


REBALANCING_MODEL_VERSION = "portfolio-rebalancing.v1"
REBALANCE_TOLERANCE = 0.000_001


@dataclass(frozen=True)
class RebalanceConstraints:
    """Explicit, local-only constraints for an advisory rebalance proposal."""

    cash_buffer_weight: float = 0.0
    settlement_buffer_eur: float = 0.0
    min_trade_eur: float = 0.0
    lot_size: float = 1.0
    allow_fractional_lots: bool = False
    restricted_positions: tuple[str, ...] = ()
    tax_rate: float | None = None
    tax_jurisdiction: str | None = None

    def __post_init__(self) -> None:
        for name in ("cash_buffer_weight", "settlement_buffer_eur", "min_trade_eur", "tax_rate"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
                raise ValueError(f"{name} must be finite and non-negative")
        if float(self.cash_buffer_weight) > 1:
            raise ValueError("cash_buffer_weight must be no more than 100%")
        if not math.isfinite(float(self.lot_size)) or float(self.lot_size) <= 0:
            raise ValueError("lot_size must be finite and greater than zero")
        if self.tax_rate is not None and float(self.tax_rate) > 1:
            raise ValueError("tax_rate must be no more than 100%")


@dataclass(frozen=True)
class RebalanceTrade:
    instrument_id: str
    current_weight: float
    target_weight: float
    proposed_weight: float
    trade_value_eur: float
    quantity: float | None
    price_eur: float | None
    action: str
    status: str
    estimated_cost_eur: float
    estimated_tax_eur: float
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class RebalanceAlternative:
    name: str
    trades: tuple[RebalanceTrade, ...]
    tracking_error_proxy: float
    estimated_cost_eur: float
    trade_count: int
    cash_weight: float
    feasible: bool
    rationale: str


@dataclass(frozen=True)
class RebalanceReport:
    model_version: str
    trades: tuple[RebalanceTrade, ...]
    alternatives: dict[str, RebalanceAlternative]
    assumptions: dict[str, object]
    warnings: tuple[str, ...]
    portfolio_value_eur: float
    cash_weight: float
    tax_status: str
    tax_jurisdiction: str
    feasible: bool
    execution_allowed: bool = False


def target_weight_drift(current_weight: float, target_weight: float) -> float:
    return round(current_weight - target_weight, 12)


def rebalance_score(current_weight: float, target_weight: float, hard_band: float) -> float:
    if hard_band <= 0:
        return 0.0
    # Positive means underweight and therefore add pressure.
    return round(max(-1.0, min(1.0, (target_weight - current_weight) / hard_band)), 12)


def proposed_new_weight(
    current_weight: float,
    target_weight: float,
    action: str,
    max_trade_fraction: float,
    forecast_vol: float | None = None,
    target_vol: float = 0.16,
) -> float | None:
    if action not in {"buy", "add", "trim", "sell"}:
        return None
    if action == "sell":
        return 0.0
    if action in {"buy", "add"}:
        base_change = max(0.0, (target_weight - current_weight) * 0.5)
        change = min(base_change, max_trade_fraction)
    else:
        base_change = max(0.0, (current_weight - target_weight) * 0.5)
        change = -min(base_change, max_trade_fraction)
    if forecast_vol and forecast_vol > 0:
        change *= min(1.0, target_vol / forecast_vol)
    return max(0.0, current_weight + change)


def suggested_trade_value(portfolio_value_eur: float, current_weight: float, new_weight: float | None) -> float | None:
    if new_weight is None:
        return None
    return float((new_weight - current_weight) * portfolio_value_eur)


def target_weight_series(config: AppConfig) -> pd.Series:
    return pd.Series({etf_id: position.target_weight for etf_id, position in config.targets.positions.items()})


def build_rebalance_report(
    config: AppConfig,
    holdings: pd.DataFrame,
    target_weights: Mapping[str, object],
    *,
    target_cash_weight: object = 0.0,
    portfolio_value_eur: object | None = None,
    constraints: RebalanceConstraints | None = None,
    tax_lots: pd.DataFrame | None = None,
) -> RebalanceReport:
    """Build a deterministic, non-executable rebalance report.

    The report turns current weights into advisory trades only. It never
    creates an order, writes a fill or enables broker authority. Missing
    prices, tax lots and microstructure inputs remain visible as assumptions
    or warnings rather than being silently inferred.
    """

    limits = constraints or RebalanceConstraints()
    target_cash = _finite_non_negative(target_cash_weight, "target_cash_weight")
    if target_cash > 1:
        raise ValueError("target_cash_weight must be no more than 100%")
    targets = _clean_targets(target_weights)
    enabled = {str(item.id) for item in getattr(config.universe, "etfs", ()) if bool(getattr(item, "enabled", False))}
    unknown = sorted(set(targets) - enabled)
    if unknown:
        raise ValueError(f"unknown or disabled target instrument: {', '.join(unknown)}")
    if not math.isclose(sum(targets.values()) + target_cash, 1.0, abs_tol=REBALANCE_TOLERANCE):
        raise ValueError("target weights plus cash must equal 100%")

    current, values = _current_holdings(holdings)
    value = _portfolio_value(values, portfolio_value_eur)
    current_cash = max(0.0, 1.0 - sum(item["weight"] for item in current.values()))
    full = _alternative(
        "full",
        config,
        current,
        targets,
        value,
        current_cash,
        target_cash,
        limits,
        tax_lots,
        scale=1.0,
    )
    partial = _alternative(
        "partial",
        config,
        current,
        targets,
        value,
        current_cash,
        target_cash,
        limits,
        tax_lots,
        scale=0.5,
    )
    deferred = _alternative(
        "deferred",
        config,
        current,
        targets,
        value,
        current_cash,
        target_cash,
        limits,
        tax_lots,
        scale=0.0,
        forced_status="deferred",
    )
    no_trade = _alternative(
        "no_trade",
        config,
        current,
        targets,
        value,
        current_cash,
        target_cash,
        limits,
        tax_lots,
        scale=0.0,
        forced_status="no_trade",
    )
    warnings: list[str] = []
    if any(item.price_eur is None and abs(item.trade_value_eur) > REBALANCE_TOLERANCE for item in full.trades):
        warnings.append("price_unavailable_lot_rounding_not_applied")
    if any(item.status == "deferred_bond_terms_unavailable" for item in full.trades):
        warnings.append("bond_face_terms_unavailable")
    if any(item.status == "deferred_bond_quantity_unavailable" for item in full.trades):
        warnings.append("bond_position_quantity_unavailable")
    if tax_lots is None or tax_lots.empty:
        warnings.append("tax_lots_unavailable")
    tax_lot_gains_unavailable = any(
        item.status == "deferred_tax_lot_gains_unavailable"
        for alternative in (full, partial, deferred, no_trade)
        for item in alternative.trades
    )
    if tax_lot_gains_unavailable:
        warnings.append("tax_lot_gains_unavailable")
    if limits.restricted_positions:
        warnings.append("restricted_positions_are_not_traded")
    if not full.feasible:
        warnings.append("full_alternative_exceeds_cash_or_settlement_buffer")
    tax_status = "unavailable" if tax_lot_gains_unavailable or not limits.tax_jurisdiction else "informational_only"
    jurisdiction = str(limits.tax_jurisdiction or "not_provided")
    assumptions: dict[str, object] = {
        "cash_buffer_weight": round(float(limits.cash_buffer_weight), 8),
        "settlement_buffer_eur": round(float(limits.settlement_buffer_eur), 8),
        "min_trade_eur": round(float(limits.min_trade_eur), 8),
        "lot_policy": "fractional_lots" if limits.allow_fractional_lots else "integer_lots",
        "lot_size": round(float(limits.lot_size), 8),
        "bond_face_policy": "minimum_denomination_and_increment",
        "cost_model": "configured local execution-cost estimate",
        "tax_model": tax_status,
        "tax_jurisdiction": jurisdiction,
    }
    return RebalanceReport(
        model_version=REBALANCING_MODEL_VERSION,
        trades=full.trades,
        alternatives={item.name: item for item in (full, partial, deferred, no_trade)},
        assumptions=assumptions,
        warnings=tuple(dict.fromkeys(warnings)),
        portfolio_value_eur=round(value, 8),
        cash_weight=full.cash_weight,
        tax_status=tax_status,
        tax_jurisdiction=jurisdiction,
        feasible=full.feasible,
    )


def _alternative(
    name: str,
    config: AppConfig,
    current: dict[str, dict[str, object]],
    targets: dict[str, float],
    portfolio_value: float,
    current_cash: float,
    target_cash: float,
    constraints: RebalanceConstraints,
    tax_lots: pd.DataFrame | None,
    *,
    scale: float,
    forced_status: str | None = None,
) -> RebalanceAlternative:
    rows: list[RebalanceTrade] = []
    instrument_ids = sorted(set(current) | set(targets))
    for instrument_id in instrument_ids:
        state = current.get(instrument_id, {"weight": 0.0, "value": 0.0, "quantity": None, "price": None})
        current_weight = float(state["weight"] or 0.0)
        target_weight = float(targets.get(instrument_id, 0.0))
        desired_value = (target_weight - current_weight) * portfolio_value * scale
        action = "buy" if desired_value > REBALANCE_TOLERANCE else "sell" if desired_value < -REBALANCE_TOLERANCE else "hold"
        status = forced_status or "proposed"
        if action == "hold":
            status = forced_status or "no_change"
        elif instrument_id in set(constraints.restricted_positions):
            desired_value, status = 0.0, "restricted"
        elif abs(desired_value) < float(constraints.min_trade_eur):
            desired_value, status = 0.0, "deferred_below_minimum"
        bond_face_terms = _requires_bond_face_terms(state)
        minimum_denomination = _positive_or_none(state.get("minimum_denomination"))
        denomination_increment = _positive_or_none(state.get("denomination_increment"))
        if action != "hold" and bond_face_terms and status == "proposed":
            if bool(state.get("bond_terms_conflict")) or minimum_denomination is None or denomination_increment is None:
                desired_value, status = 0.0, "deferred_bond_terms_unavailable"
            elif desired_value < 0 and state.get("quantity") is None:
                desired_value, status = 0.0, "deferred_bond_quantity_unavailable"
        price = _positive_or_none(state.get("price"))
        quantity = _lot_quantity(
            desired_value,
            price,
            _positive_or_none(state.get("quantity")),
            constraints,
            minimum_denomination=minimum_denomination if bond_face_terms else None,
            denomination_increment=denomination_increment if bond_face_terms else None,
        )
        requested_value = desired_value
        assumptions = ["research_estimate_only", f"status={status}"]
        if bond_face_terms and minimum_denomination is not None and denomination_increment is not None:
            assumptions.extend((
                f"minimum_denomination={minimum_denomination:g}",
                f"denomination_increment={denomination_increment:g}",
            ))
        if status == "deferred_bond_terms_unavailable":
            assumptions.append("bond_face_terms_unavailable")
        if status == "deferred_bond_quantity_unavailable":
            assumptions.append("bond_position_quantity_unavailable")
        if price is None and abs(desired_value) > REBALANCE_TOLERANCE:
            assumptions.append("price_unavailable")
        if price is not None and quantity is not None:
            desired_value = math.copysign(abs(quantity) * price, desired_value)
        if price is not None and abs(requested_value) > REBALANCE_TOLERANCE and quantity == 0:
            status = "deferred_below_lot"
            desired_value = 0.0
        tax = _tax_estimate(tax_lots, instrument_id, desired_value, constraints)
        if tax is None:
            # The sale is deferred, so zero tax here is the cost of no trade, not an estimate of unknown gains.
            desired_value = 0.0
            quantity = 0.0 if quantity is not None else None
            action = "hold"
            status = "deferred_tax_lot_gains_unavailable"
            assumptions.append("tax_lot_gains_unavailable")
            tax = 0.0
        cost = estimate_execution_cost(config, instrument_id, abs(desired_value))
        rows.append(
            RebalanceTrade(
                instrument_id=instrument_id,
                current_weight=round(current_weight, 10),
                target_weight=round(target_weight, 10),
                proposed_weight=round(current_weight + desired_value / portfolio_value, 10),
                trade_value_eur=round(desired_value, 8),
                quantity=None if quantity is None else round(quantity, 8),
                price_eur=None if price is None else round(price, 8),
                action=action if desired_value else "hold",
                status=status,
                estimated_cost_eur=round(cost.total_cost_eur, 8),
                estimated_tax_eur=round(tax, 8),
                assumptions=tuple(assumptions),
            )
        )

    rows = _fit_cash(rows, current, current_cash, target_cash, portfolio_value, constraints, config, tax_lots)
    final_cash = current_cash - (
        sum(item.trade_value_eur + item.estimated_cost_eur + item.estimated_tax_eur for item in rows)
        / portfolio_value
    )
    tracking_error = sum(abs(item.target_weight - item.proposed_weight) for item in rows) + abs(target_cash - final_cash)
    cost_total = sum(item.estimated_cost_eur + item.estimated_tax_eur for item in rows)
    cash_required = target_cash + float(constraints.cash_buffer_weight) + float(constraints.settlement_buffer_eur) / portfolio_value
    return RebalanceAlternative(
        name=name,
        trades=tuple(rows),
        tracking_error_proxy=round(tracking_error, 10),
        estimated_cost_eur=round(cost_total, 8),
        trade_count=sum(abs(item.trade_value_eur) > REBALANCE_TOLERANCE for item in rows),
        cash_weight=round(final_cash, 10),
        feasible=final_cash + REBALANCE_TOLERANCE >= cash_required,
        rationale={"full": "Largest feasible local target-tracking alternative", "partial": "Half-sized turnover alternative", "deferred": "All proposed trades deferred for later review", "no_trade": "Hold current positions and cash"}[name],
    )


def _fit_cash(rows: list[RebalanceTrade], current: dict[str, dict[str, object]], current_cash: float, target_cash: float, portfolio_value: float, constraints: RebalanceConstraints, config: AppConfig, tax_lots: pd.DataFrame | None) -> list[RebalanceTrade]:
    available = (current_cash - target_cash - float(constraints.cash_buffer_weight)) * portfolio_value - float(constraints.settlement_buffer_eur)
    buys = sum(item.trade_value_eur + item.estimated_cost_eur + item.estimated_tax_eur for item in rows if item.trade_value_eur > 0)
    sells = sum(-item.trade_value_eur - item.estimated_cost_eur - item.estimated_tax_eur for item in rows if item.trade_value_eur < 0)
    cash_budget = max(0.0, available + sells)
    if buys <= cash_budget or buys <= 0:
        return rows
    ratio = max(0.0, min(1.0, cash_budget / buys))
    adjusted: list[RebalanceTrade] = []
    for item in rows:
        if item.trade_value_eur <= 0:
            adjusted.append(item)
            continue
        value = item.trade_value_eur * ratio
        state = current.get(item.instrument_id, {})
        bond_face_terms = _requires_bond_face_terms(state)
        quantity = _lot_quantity(
            value,
            item.price_eur,
            _positive_or_none(state.get("quantity")),
            constraints,
            minimum_denomination=_positive_or_none(state.get("minimum_denomination")) if bond_face_terms else None,
            denomination_increment=_positive_or_none(state.get("denomination_increment")) if bond_face_terms else None,
        )
        if item.price_eur is not None and quantity is not None:
            value = quantity * item.price_eur
        cost = estimate_execution_cost(config, item.instrument_id, abs(value))
        tax = _tax_estimate(tax_lots, item.instrument_id, value, constraints)
        adjusted.append(RebalanceTrade(**{**item.__dict__, "trade_value_eur": round(value, 8), "proposed_weight": round(item.current_weight + value / portfolio_value, 10), "quantity": None if quantity is None else round(quantity, 8), "estimated_cost_eur": round(cost.total_cost_eur, 8), "estimated_tax_eur": round(tax, 8), "status": item.status if value else "deferred_cash_buffer"}))

    while True:
        adjusted_buys = sum(
            item.trade_value_eur + item.estimated_cost_eur + item.estimated_tax_eur
            for item in adjusted
            if item.trade_value_eur > 0
        )
        if adjusted_buys <= cash_budget:
            return adjusted

        shortfall = adjusted_buys - cash_budget
        candidates: list[tuple[float, float, int, float, float | None, float | None]] = []
        for index, item in enumerate(adjusted):
            if item.trade_value_eur <= 0:
                continue
            state = current.get(item.instrument_id, {})
            bond_face_terms = _requires_bond_face_terms(state)
            denomination_increment = _positive_or_none(state.get("denomination_increment")) if bond_face_terms else None
            lot_step = denomination_increment or float(constraints.lot_size)
            step_value = item.price_eur * lot_step if item.price_eur is not None and item.quantity is not None else 0.0
            minimum_denomination = _positive_or_none(state.get("minimum_denomination")) if bond_face_terms else None
            candidates.append((step_value, item.trade_value_eur, index, lot_step, minimum_denomination, item.price_eur))
        if not candidates:
            return adjusted

        step_value, _, index, lot_step, minimum_denomination, price = min(candidates)
        item = adjusted[index]
        if price is not None and item.quantity is not None and step_value > 0:
            available_lots = max(0, math.floor(abs(item.quantity) / lot_step + 1e-10))
            lots_to_remove = max(1, math.ceil(shortfall / step_value - 1e-12))
            remaining_quantity = max(0, available_lots - lots_to_remove) * lot_step
            if minimum_denomination is not None and remaining_quantity + REBALANCE_TOLERANCE < minimum_denomination:
                remaining_quantity = 0.0
            quantity = math.copysign(remaining_quantity, item.trade_value_eur)
            value = remaining_quantity * price
        else:
            reduction = max(shortfall, 0.000_000_01)
            value = round(max(0.0, item.trade_value_eur - reduction), 8)
            if value >= item.trade_value_eur:
                value = max(0.0, item.trade_value_eur - 0.000_000_01)
            state = current.get(item.instrument_id, {})
            bond_face_terms = _requires_bond_face_terms(state)
            quantity = _lot_quantity(
                value,
                item.price_eur,
                _positive_or_none(state.get("quantity")),
                constraints,
                minimum_denomination=_positive_or_none(state.get("minimum_denomination")) if bond_face_terms else None,
                denomination_increment=_positive_or_none(state.get("denomination_increment")) if bond_face_terms else None,
            )
            if item.price_eur is not None and quantity is not None:
                value = quantity * item.price_eur

        cost = estimate_execution_cost(config, item.instrument_id, abs(value))
        tax = _tax_estimate(tax_lots, item.instrument_id, value, constraints)
        adjusted[index] = RebalanceTrade(
            **{
                **item.__dict__,
                "trade_value_eur": round(value, 8),
                "proposed_weight": round(item.current_weight + value / portfolio_value, 10),
                "quantity": None if quantity is None else round(quantity, 8),
                "estimated_cost_eur": round(cost.total_cost_eur, 8),
                "estimated_tax_eur": round(tax, 8),
                "status": item.status if value else "deferred_cash_buffer",
            }
        )


def _clean_targets(targets: Mapping[str, object]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for raw_id, raw_weight in targets.items():
        identifier = str(raw_id).strip()
        weight = _finite_non_negative(raw_weight, f"target weight for {identifier}")
        if not identifier or weight > 1:
            raise ValueError(f"invalid target weight for {identifier or '<blank>'}")
        if weight:
            cleaned[identifier] = weight
    return cleaned


def _current_holdings(holdings: pd.DataFrame) -> tuple[dict[str, dict[str, object]], dict[str, float]]:
    current: dict[str, dict[str, object]] = {}
    values: dict[str, float] = {}
    for _, row in holdings.iterrows():
        identifier = str(row.get("etf_id", row.get("instrument_id", ""))).strip()
        if not identifier:
            continue
        weight = _finite_non_negative(row.get("current_weight", 0.0), "current_weight")
        market_value = _finite_non_negative(row.get("market_value_eur", 0.0), "market_value_eur")
        state = current.setdefault(
            identifier,
            {
                "weight": 0.0,
                "value": 0.0,
                "quantity": None,
                "price": None,
                "asset_type": "",
                "minimum_denomination": None,
                "denomination_increment": None,
                "bond_terms_conflict": False,
            },
        )
        state["weight"] = float(state["weight"] or 0.0) + weight
        state["value"] = float(state["value"] or 0.0) + market_value
        quantity = _positive_or_none(row.get("quantity", row.get("shares")))
        price = _positive_or_none(row.get("price_eur", row.get("price")))
        if quantity is not None:
            state["quantity"] = float(state["quantity"] or 0.0) + quantity
        if price is not None:
            state["price"] = price
        raw_asset_type = row.get("asset_type", row.get("security_type", ""))
        asset_type = "" if raw_asset_type is None or pd.isna(raw_asset_type) else str(raw_asset_type).strip().casefold()
        existing_asset_type = str(state.get("asset_type") or "")
        if asset_type and existing_asset_type and asset_type != existing_asset_type:
            state["asset_type"] = "mixed"
            state["bond_terms_conflict"] = True
        elif asset_type:
            state["asset_type"] = asset_type
        for field in ("minimum_denomination", "denomination_increment"):
            term = _positive_or_none(row.get(field))
            existing_term = _positive_or_none(state.get(field))
            if term is not None and existing_term is not None and not math.isclose(term, existing_term, rel_tol=0.0, abs_tol=REBALANCE_TOLERANCE):
                state["bond_terms_conflict"] = True
            elif term is not None:
                state[field] = term
        minimum = _positive_or_none(state.get("minimum_denomination"))
        increment = _positive_or_none(state.get("denomination_increment"))
        if minimum is not None and increment is not None:
            units = minimum / increment
            if minimum < increment or not math.isclose(units, round(units), rel_tol=0.0, abs_tol=REBALANCE_TOLERANCE):
                state["bond_terms_conflict"] = True
        values[identifier] = values.get(identifier, 0.0) + market_value
    return current, values


def _portfolio_value(values: dict[str, float], supplied: object | None) -> float:
    value = sum(values.values()) if supplied is None else _finite_non_negative(supplied, "portfolio_value_eur")
    if value <= 0:
        raise ValueError("portfolio_value_eur must be greater than zero")
    return value


def _lot_quantity(
    value: float,
    price: float | None,
    current_quantity: float | None,
    constraints: RebalanceConstraints,
    *,
    minimum_denomination: float | None = None,
    denomination_increment: float | None = None,
) -> float | None:
    if price is None or abs(value) <= REBALANCE_TOLERANCE:
        return None if price is None else 0.0
    raw = abs(value) / price
    if minimum_denomination is not None or denomination_increment is not None:
        if minimum_denomination is None or denomination_increment is None or minimum_denomination <= 0 or denomination_increment <= 0:
            return math.copysign(0.0, value)
        units = raw / denomination_increment
        if value > 0:
            quantity = math.floor(units + 1e-10) * denomination_increment
        else:
            quantity = math.ceil(units - 1e-10) * denomination_increment
        if quantity + REBALANCE_TOLERANCE < minimum_denomination:
            quantity = 0.0
        if value < 0 and current_quantity is not None:
            current_units = round(current_quantity / denomination_increment)
            current_is_valid = math.isclose(
                current_quantity,
                current_units * denomination_increment,
                rel_tol=0.0,
                abs_tol=REBALANCE_TOLERANCE,
            )
            if not current_is_valid:
                quantity = 0.0
            else:
                quantity = min(quantity, current_quantity)
                remainder = current_quantity - quantity
                if quantity > 0 and REBALANCE_TOLERANCE < remainder < minimum_denomination - REBALANCE_TOLERANCE:
                    quantity = current_quantity
    else:
        lot = float(constraints.lot_size)
        if constraints.allow_fractional_lots:
            quantity = round(raw / lot) * lot
        elif value > 0:
            quantity = math.floor(raw / lot) * lot
        else:
            quantity = math.ceil(raw / lot) * lot
    if denomination_increment is None and value < 0 and current_quantity is not None:
        quantity = min(quantity, current_quantity)
    return math.copysign(quantity, value)


def _requires_bond_face_terms(state: Mapping[str, object]) -> bool:
    asset_type = str(state.get("asset_type") or "").strip().casefold()
    return (
        "bond" in asset_type
        or bool(state.get("bond_terms_conflict"))
        or state.get("minimum_denomination") is not None
        or state.get("denomination_increment") is not None
    )


def _tax_estimate(tax_lots: pd.DataFrame | None, instrument_id: str, trade_value: float, constraints: RebalanceConstraints) -> float | None:
    if constraints.tax_rate is None or trade_value >= 0:
        return 0.0
    if tax_lots is None or tax_lots.empty:
        return None
    identifier_column = "instrument_id" if "instrument_id" in tax_lots.columns else "etf_id" if "etf_id" in tax_lots.columns else None
    if identifier_column is None:
        return None
    matches = tax_lots.loc[tax_lots[identifier_column].astype(str) == instrument_id]
    if matches.empty or "unrealised_gain_eur" not in matches.columns:
        return None
    gains = pd.to_numeric(matches["unrealised_gain_eur"], errors="coerce")
    if gains.isna().any():
        return None
    lot_value = pd.to_numeric(matches.get("market_value_eur", pd.Series(0.0, index=matches.index)), errors="coerce").fillna(0.0)
    covered_fraction = min(1.0, abs(trade_value) / float(lot_value.sum())) if float(lot_value.sum()) > 0 else 1.0
    return max(0.0, float(gains.sum())) * covered_fraction * float(constraints.tax_rate)


def _finite_non_negative(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite and non-negative") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return number


def _positive_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


__all__ = [
    "REBALANCE_TOLERANCE",
    "REBALANCING_MODEL_VERSION",
    "RebalanceAlternative",
    "RebalanceConstraints",
    "RebalanceReport",
    "RebalanceTrade",
    "build_rebalance_report",
    "proposed_new_weight",
    "rebalance_score",
    "suggested_trade_value",
    "target_weight_drift",
    "target_weight_series",
]
