from __future__ import annotations

from etf_cockpit.core.config import AppConfig


def estimated_cost_bps(config: AppConfig, etf_id: str) -> float:
    per_etf = config.costs.per_etf.get(etf_id, {})
    spread = per_etf.get("spread_bps", config.costs.cost_model.default_spread_bps)
    slippage = per_etf.get("slippage_bps", config.costs.cost_model.default_slippage_bps)
    fx = config.costs.cost_model.fx_conversion_bps
    return float(spread + slippage + fx)


def estimated_trade_cost_eur(config: AppConfig, etf_id: str, trade_value_eur: float) -> float:
    bps_cost = abs(trade_value_eur) * estimated_cost_bps(config, etf_id) / 10_000
    return float(bps_cost + config.costs.cost_model.default_commission_eur)
