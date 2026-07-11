from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import AppConfig


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
