from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import AppConfig


def target_weights(config: AppConfig, columns: list[str]) -> pd.Series:
    raw = pd.Series({etf_id: position.target_weight for etf_id, position in config.targets.positions.items()})
    weights = raw.reindex(columns).fillna(0.0)
    total = weights.sum()
    return weights / total if total > 0 else pd.Series(1 / len(columns), index=columns)


def equal_weights(columns: list[str]) -> pd.Series:
    return pd.Series(1 / len(columns), index=columns)


def momentum_weights(price_history: pd.DataFrame, columns: list[str]) -> pd.Series:
    if len(price_history) < 181:
        return equal_weights(columns)
    mom = 0.4 * (price_history.iloc[-1] / price_history.iloc[-60] - 1)
    mom += 0.4 * (price_history.iloc[-1] / price_history.iloc[-120] - 1)
    mom += 0.2 * (price_history.iloc[-1] / price_history.iloc[-180] - 1)
    ranked = mom.sort_values(ascending=False)
    keep = ranked.head(max(1, len(columns) // 2)).index
    weights = pd.Series(0.0, index=columns)
    weights.loc[keep] = 1 / len(keep)
    return weights


def trend_weights(config: AppConfig, price_history: pd.DataFrame, columns: list[str]) -> pd.Series:
    base = target_weights(config, columns)
    if len(price_history) < 200:
        return base
    sma = price_history.tail(200).mean()
    active = price_history.iloc[-1] > sma
    weights = base.where(active, 0.0)
    total = weights.sum()
    return weights / total if total > 0 else pd.Series(0.0, index=columns)
