from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class ClusterRow:
    instrument_id: str
    cluster_id: str
    cluster_label: str
    average_peer_correlation: float | None
    theme: str | None
    crowding_warning: str
    sample_size: int


@dataclass(frozen=True)
class ClusterReport:
    rows: tuple[ClusterRow, ...]
    as_of: str | None
    window: int


def build_correlation_clusters(prices: pd.DataFrame, metadata: Mapping[str, str] | None = None, *, window: int = 120) -> ClusterReport:
    if prices.empty:
        return ClusterReport((), None, window)
    frame = prices.tail(window).apply(pd.to_numeric, errors="coerce")
    returns = frame.pct_change(fill_method=None).dropna(how="all")
    corr = returns.corr(min_periods=max(20, min(60, len(returns))))
    rows: list[ClusterRow] = []
    for instrument_id in corr.columns:
        peers = corr[instrument_id].drop(labels=[instrument_id], errors="ignore").dropna()
        average = None if peers.empty else float(peers.mean())
        warning = "high_correlation_cluster" if average is not None and average >= 0.80 else "no_crowding_warning"
        rows.append(ClusterRow(str(instrument_id), "high" if warning.startswith("high") else "mixed", "High correlation" if warning.startswith("high") else "Mixed", average, None if metadata is None else metadata.get(str(instrument_id)), warning, int(len(returns))))
    return ClusterReport(tuple(rows), str(prices.index.max()) if len(prices.index) else None, window)
