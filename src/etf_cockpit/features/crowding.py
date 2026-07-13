from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

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
    sector: str | None = None
    theme_warning: str = "no_theme_concentration_warning"
    members: tuple[str, ...] = ()
    as_of: str | None = None
    source_dataset: str = "adjusted_price_returns"
    execution_allowed: bool = False


@dataclass(frozen=True)
class ClusterReport:
    rows: tuple[ClusterRow, ...]
    as_of: str | None
    window: int
    status: str = "unavailable"
    sample_size: int = 0
    source_dataset: str = "adjusted_price_returns"
    reason: str = "Correlation clusters unavailable."
    execution_allowed: bool = False


def build_correlation_clusters(
    prices: pd.DataFrame,
    metadata: Mapping[str, Any] | None = None,
    *,
    window: int = 120,
) -> ClusterReport:
    """Build deterministic connected correlation clusters from adjusted prices.

    The function accepts both the canonical long price panel and a wide test or
    research frame. Missing values are never fabricated; pairwise correlations
    are only used when each pair has enough clean return observations.
    """

    if window < 2:
        return _unavailable(window, "Correlation window must contain at least two price observations.")
    frame = _price_frame(prices)
    if frame.empty:
        return _unavailable(window, "No clean adjusted-price observations are available.")
    frame = frame.sort_index().tail(window)
    returns = frame.pct_change(fill_method=None)
    min_pair_samples = max(20, min(60, window - 1))
    corr = returns.corr(min_periods=min_pair_samples)
    if corr.empty or len(returns) < min_pair_samples or corr.dropna(how="all").shape[1] < 2:
        return _unavailable(window, f"Fewer than {min_pair_samples} clean return observations are available.", as_of=_as_of(frame.index))

    instrument_ids = [str(value) for value in corr.columns]
    parent = {instrument_id: instrument_id for instrument_id in instrument_ids}
    for left_index, left in enumerate(instrument_ids):
        for right in instrument_ids[left_index + 1 :]:
            value = _safe_float(corr.loc[left, right])
            if value is not None and value >= 0.80:
                _union(parent, left, right)

    groups: dict[str, list[str]] = {}
    for instrument_id in instrument_ids:
        groups.setdefault(_find(parent, instrument_id), []).append(instrument_id)
    labels = _normalise_metadata(metadata or {})
    rows: list[ClusterRow] = []
    for members in sorted(groups.values(), key=lambda values: values[0]):
        members = tuple(sorted(members))
        cluster_id = "cluster_" + "_".join(members)
        metadata_rows = [labels.get(member, {}) for member in members]
        theme_counts = _counts(metadata_row.get("theme") for metadata_row in metadata_rows)
        dominant_theme = _dominant(theme_counts, len(members))
        theme_warning = "theme_concentration_warning" if dominant_theme else "no_theme_concentration_warning"
        cluster_warning = "high_correlation_cluster_warning" if len(members) > 1 else "no_cluster_warning"
        if cluster_warning == "no_cluster_warning" and dominant_theme:
            cluster_warning = theme_warning
        cluster_label = "High correlation cluster" if len(members) > 1 else "Singleton / no correlated peer"
        if dominant_theme:
            cluster_label += f" ({dominant_theme})"
        for instrument_id in members:
            peers = corr[instrument_id].drop(labels=[instrument_id], errors="ignore").dropna()
            average_peer = _safe_float(peers.mean()) if not peers.empty else None
            item = labels.get(instrument_id, {})
            rows.append(
                ClusterRow(
                    instrument_id=instrument_id,
                    cluster_id=cluster_id,
                    cluster_label=cluster_label,
                    average_peer_correlation=average_peer,
                    theme=item.get("theme"),
                    crowding_warning=cluster_warning,
                    sample_size=int(len(returns)),
                    sector=item.get("sector"),
                    theme_warning=theme_warning,
                    members=members,
                    as_of=_as_of(frame.index),
                )
            )
    return ClusterReport(
        rows=tuple(rows),
        as_of=_as_of(frame.index),
        window=window,
        status="available",
        sample_size=int(len(returns)),
        reason="Correlation clusters computed from clean adjusted-price returns.",
    )


def _price_frame(prices: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return pd.DataFrame()
    if {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        clean = prices.copy()
        clean["date"] = pd.to_datetime(clean["date"], errors="coerce")
        clean["adjusted_close"] = pd.to_numeric(clean["adjusted_close"], errors="coerce")
        clean = clean.dropna(subset=["date", "adjusted_close", "etf_id"])
        if clean.empty:
            return pd.DataFrame()
        return clean.pivot_table(index="date", columns="etf_id", values="adjusted_close", aggfunc="last").sort_index()
    clean = prices.copy()
    clean.index = pd.to_datetime(clean.index, errors="coerce")
    clean = clean.loc[clean.index.notna()]
    for column in clean.columns:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    return clean.dropna(axis=1, how="all")


def _normalise_metadata(metadata: Mapping[str, Any]) -> dict[str, dict[str, str | None]]:
    output: dict[str, dict[str, str | None]] = {}
    for instrument_id, value in metadata.items():
        if isinstance(value, Mapping):
            sector = _text(value.get("sector"))
            theme = _text(value.get("theme"))
        else:
            # A scalar metadata value is retained as a configured theme label;
            # no company-name or model-based inference is attempted.
            sector = None
            theme = _text(value)
        output[str(instrument_id)] = {"sector": sector, "theme": theme}
    return output


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _dominant(counts: dict[str, int], total: int) -> str | None:
    if not counts or total < 2:
        return None
    value, count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return value if count >= 2 and count / total >= 0.5 else None


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _as_of(index: pd.Index) -> str | None:
    if len(index) == 0:
        return None
    value = pd.to_datetime(index, errors="coerce").max()
    return None if pd.isna(value) else value.date().isoformat()


def _find(parent: dict[str, str], value: str) -> str:
    while parent[value] != value:
        parent[value] = parent[parent[value]]
        value = parent[value]
    return value


def _union(parent: dict[str, str], left: str, right: str) -> None:
    left_root, right_root = _find(parent, left), _find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def _unavailable(window: int, reason: str, *, as_of: str | None = None) -> ClusterReport:
    return ClusterReport((), as_of, window, "unavailable", 0, reason=reason)
