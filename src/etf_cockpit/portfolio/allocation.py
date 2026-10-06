from __future__ import annotations

import pandas as pd

from etf_cockpit.core.config import AppConfig


def target_frame(config: AppConfig) -> pd.DataFrame:
    rows = []
    universe = config.universe.by_id()
    for etf_id, position in config.targets.positions.items():
        etf = universe.get(etf_id)
        rows.append(
            {
                "etf_id": etf_id,
                "name": etf.name if etf else etf_id,
                "target_weight": position.target_weight,
                "soft_band": position.soft_band,
                "hard_band": position.hard_band,
                "role": etf.role if etf else "unknown",
                "asset_class": etf.asset_class if etf else "unknown",
                "region": etf.region if etf else None,
                "sector": etf.sector if etf else None,
                "theme": etf.theme if etf else None,
                "currency": etf.currency if etf else "EUR",
                "max_weight": etf.max_weight if etf else 1.0,
            }
        )
    return pd.DataFrame(rows)


def allocation_frame(config: AppConfig, holdings: pd.DataFrame) -> pd.DataFrame:
    targets = target_frame(config)
    merged = targets.merge(holdings, on="etf_id", how="left")
    merged["current_weight"] = merged["current_weight"].fillna(0.0)
    merged["market_value_eur"] = merged["market_value_eur"].fillna(0.0)
    merged["drift"] = merged["current_weight"] - merged["target_weight"]
    merged["drift_status"] = "inside"
    merged.loc[merged["drift"] > merged["soft_band"], "drift_status"] = "over_soft"
    merged.loc[merged["drift"] < -merged["soft_band"], "drift_status"] = "under_soft"
    merged.loc[merged["drift"] > merged["hard_band"], "drift_status"] = "over_hard"
    merged.loc[merged["drift"] < -merged["hard_band"], "drift_status"] = "under_hard"
    return merged


def exposure_summary(allocation: pd.DataFrame, column: str) -> pd.DataFrame:
    if allocation.empty or column not in allocation:
        return pd.DataFrame(columns=[column, "current_weight", "target_weight"])
    return (
        allocation.groupby(column, dropna=False)[["current_weight", "target_weight"]]
        .sum()
        .sort_values("current_weight", ascending=False)
        .reset_index()
    )
