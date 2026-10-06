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
        columns = list(etf_ids or [])
        if not columns:
            return pd.DataFrame()
        pivot = pd.DataFrame(columns=columns, dtype=float)
    else:
        frame = prices.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        pivot = frame.pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().dropna(how="all")
        columns = list(etf_ids or list(pivot.columns))
    if not columns:
        return pd.DataFrame()
    missing_assets = [
        column
        for column in columns
        if column not in pivot.columns or int(pivot[column].notna().sum()) < 2
    ]
    excluded_assets = {
        str(asset_id): "requested_asset_price_history_unavailable"
        for asset_id in missing_assets
    }
    usable_columns = [column for column in columns if column not in missing_assets]
    if len(usable_columns) < 2:
        unavailable = pd.DataFrame(index=columns, columns=columns, dtype=float)
        unavailable.attrs.update(
            status="unavailable",
            reason_code="requested_asset_prices_unavailable",
            excluded_assets=excluded_assets,
        )
        return unavailable
    pivot = pivot[usable_columns].dropna()
    if len(pivot) < 3:
        result = pd.DataFrame(index=usable_columns, columns=usable_columns, dtype=float)
        result.attrs.update(status="unavailable", reason_code="shared_return_history_unavailable")
        if excluded_assets:
            result.attrs["excluded_assets"] = excluded_assets
        return result
    returns = np.log(pivot / pivot.shift(1)).dropna()
    if window > 0:
        returns = returns.tail(window)
    if returns.empty:
        result = pd.DataFrame(index=usable_columns, columns=usable_columns, dtype=float)
        result.attrs.update(status="unavailable", reason_code="shared_return_history_unavailable")
        if excluded_assets:
            result.attrs["excluded_assets"] = excluded_assets
        return result
    correlation = returns.corr().reindex(index=usable_columns, columns=usable_columns)
    values = correlation.to_numpy(float)
    if not np.isfinite(values).all():
        unavailable = pd.DataFrame(index=usable_columns, columns=usable_columns, dtype=float)
        unavailable.attrs.update(status="unavailable", reason_code="correlation_inputs_incomplete")
        if excluded_assets:
            unavailable.attrs["excluded_assets"] = excluded_assets
        return unavailable
    eigenvalues = np.linalg.eigvalsh((values + values.T) / 2.0)
    if float(eigenvalues.min()) < -1e-10:
        unavailable = pd.DataFrame(index=usable_columns, columns=usable_columns, dtype=float)
        unavailable.attrs.update(status="unavailable", reason_code="correlation_matrix_not_psd")
        if excluded_assets:
            unavailable.attrs["excluded_assets"] = excluded_assets
        return unavailable
    if excluded_assets:
        correlation.attrs.update(
            status="partial",
            reason_code="requested_asset_prices_unavailable",
            excluded_assets=excluded_assets,
        )
    else:
        correlation.attrs.update(status="available")
    return correlation


def drawdown_contribution(allocation: pd.DataFrame, latest_features: pd.DataFrame) -> pd.DataFrame:
    if allocation.empty:
        return pd.DataFrame(columns=["etf_id", "current_weight", "drawdown_current", "drawdown_contribution", "risk_share"])
    metrics = latest_features[["etf_id", "drawdown_current", "drawdown_60d_max", "vol_60d_ann"]].copy()
    merged = allocation.merge(metrics, on="etf_id", how="left")
    metric_columns = ["drawdown_current", "drawdown_60d_max", "vol_60d_ann"]
    for column in metric_columns:
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    if merged[metric_columns].isna().to_numpy().any() or not np.isfinite(merged[metric_columns].to_numpy(float)).all():
        merged["drawdown_contribution"] = np.nan
        merged["risk_share"] = np.nan
        result = merged[["etf_id", "name", "current_weight", *metric_columns, "drawdown_contribution", "risk_share"]].sort_values("risk_share", ascending=False).reset_index(drop=True)
        result.attrs.update(status="unavailable", reason_code="drawdown_or_volatility_unavailable")
        return result
    merged["drawdown_contribution"] = merged["current_weight"].astype(float) * merged["drawdown_current"].astype(float)
    absolute = merged["drawdown_contribution"].abs()
    denominator = float(absolute.sum())
    merged["risk_share"] = absolute / denominator if denominator > 0 else np.nan
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
    result = merged[columns].sort_values("risk_share", ascending=False).reset_index(drop=True)
    result.attrs.update(status="available" if denominator > 0 else "unavailable", reason_code=None if denominator > 0 else "zero_drawdown_contribution")
    return result


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
