from __future__ import annotations

import numpy as np
import pandas as pd

from etf_cockpit.core.config import AppConfig


def exposure_limit_report(config: AppConfig, allocation: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    limits = config.risks.portfolio_limits
    for _, row in allocation.iterrows():
        current = float(row.get("current_weight", 0.0) or 0.0)
        limit = min(float(row.get("max_weight", 1.0) or 1.0), limits.max_single_etf_weight)
        rows.append(_limit_row("etf", str(row["etf_id"]), current, limit))

    for column, limit, kind in [
        ("sector", limits.max_sector_weight, "sector"),
        ("region", limits.max_region_weight, "region"),
        ("theme", limits.max_theme_weight, "theme"),
    ]:
        if column not in allocation:
            continue
        grouped = allocation.groupby(column, dropna=False)["current_weight"].sum()
        for bucket, current in grouped.items():
            if pd.isna(bucket):
                continue
            rows.append(_limit_row(kind, str(bucket), float(current), float(limit)))

    for column, kind in [("currency", "currency"), ("asset_class", "asset_class")]:
        if column not in allocation:
            continue
        grouped = allocation.groupby(column, dropna=False)["current_weight"].sum()
        for bucket, current in grouped.items():
            if pd.isna(bucket):
                continue
            rows.append(_limit_row(kind, str(bucket), float(current), None))

    return pd.DataFrame(rows).sort_values(["status_rank", "risk_type", "current_weight"], ascending=[True, True, False])


def return_correlation_matrix(prices: pd.DataFrame, etf_ids: list[str] | None = None, *, window: int = 120) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    pivot = frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().dropna(how="all")
    columns = [column for column in (etf_ids or list(pivot.columns)) if column in pivot.columns]
    if not columns:
        return pd.DataFrame()
    pivot = pivot[columns].dropna()
    if len(pivot) < 3:
        return pd.DataFrame(index=columns, columns=columns, dtype=float)
    returns = np.log(pivot / pivot.shift(1)).dropna()
    if window > 0:
        returns = returns.tail(window)
    if returns.empty:
        return pd.DataFrame(index=columns, columns=columns, dtype=float)
    correlation = returns.corr().reindex(index=columns, columns=columns)
    for etf_id in columns:
        if etf_id in correlation.index and etf_id in correlation.columns:
            correlation.loc[etf_id, etf_id] = 1.0
    return correlation.fillna(0.0)


def drawdown_contribution(allocation: pd.DataFrame, latest_features: pd.DataFrame) -> pd.DataFrame:
    if allocation.empty:
        return pd.DataFrame(columns=["etf_id", "current_weight", "drawdown_current", "drawdown_contribution", "risk_share"])
    metrics = latest_features[["etf_id", "drawdown_current", "drawdown_60d_max", "vol_60d_ann"]].copy()
    merged = allocation.merge(metrics, on="etf_id", how="left")
    merged["drawdown_current"] = pd.to_numeric(merged["drawdown_current"], errors="coerce").fillna(0.0)
    merged["drawdown_60d_max"] = pd.to_numeric(merged["drawdown_60d_max"], errors="coerce").fillna(0.0)
    merged["vol_60d_ann"] = pd.to_numeric(merged["vol_60d_ann"], errors="coerce").fillna(0.0)
    merged["drawdown_contribution"] = merged["current_weight"].astype(float) * merged["drawdown_current"].astype(float)
    absolute = merged["drawdown_contribution"].abs()
    denominator = float(absolute.sum())
    merged["risk_share"] = absolute / denominator if denominator > 0 else 0.0
    columns = [
        "etf_id",
        "name",
        "current_weight",
        "drawdown_current",
        "drawdown_60d_max",
        "vol_60d_ann",
        "drawdown_contribution",
        "risk_share",
    ]
    return merged[columns].sort_values("risk_share", ascending=False).reset_index(drop=True)


def underlying_holdings_exposure(allocation: pd.DataFrame, etf_holdings: pd.DataFrame, dimension: str) -> pd.DataFrame:
    columns = [dimension, "current_weight", "target_weight"]
    if allocation.empty or etf_holdings.empty or dimension not in etf_holdings.columns:
        return pd.DataFrame(columns=columns)
    required = {"etf_id", "as_of_date", "weight", dimension}
    if not required.issubset(etf_holdings.columns):
        return pd.DataFrame(columns=columns)

    holdings = etf_holdings.copy()
    holdings["as_of_date"] = pd.to_datetime(holdings["as_of_date"], errors="coerce")
    holdings["weight"] = pd.to_numeric(holdings["weight"], errors="coerce")
    holdings = holdings.dropna(subset=["as_of_date", "weight", dimension])
    if holdings.empty:
        return pd.DataFrame(columns=columns)

    latest_dates = holdings.groupby("etf_id")["as_of_date"].transform("max")
    holdings = holdings[holdings["as_of_date"] == latest_dates]
    merged = holdings.merge(allocation[["etf_id", "current_weight", "target_weight"]], on="etf_id", how="inner")
    if merged.empty:
        return pd.DataFrame(columns=columns)

    merged["portfolio_current_weight"] = merged["weight"].astype(float) * merged["current_weight"].astype(float)
    merged["portfolio_target_weight"] = merged["weight"].astype(float) * merged["target_weight"].astype(float)
    grouped = (
        merged.groupby(dimension, dropna=False)[["portfolio_current_weight", "portfolio_target_weight"]]
        .sum()
        .reset_index()
        .rename(columns={"portfolio_current_weight": "current_weight", "portfolio_target_weight": "target_weight"})
    )
    grouped = grouped[grouped[dimension].astype(str).str.len() > 0]
    return grouped[columns].sort_values("current_weight", ascending=False).reset_index(drop=True)


def _limit_row(risk_type: str, bucket: str, current: float, limit: float | None) -> dict[str, object]:
    if limit is None:
        status = "info"
        status_rank = 3
        headroom = None
    else:
        headroom = limit - current
        if current > limit:
            status = "breach"
            status_rank = 0
        elif current > limit * 0.9:
            status = "watch"
            status_rank = 1
        else:
            status = "ok"
            status_rank = 2
    return {
        "risk_type": risk_type,
        "bucket": bucket,
        "current_weight": current,
        "limit": limit,
        "headroom": headroom,
        "status": status,
        "status_rank": status_rank,
    }
