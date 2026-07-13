from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from collections.abc import Sequence
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
    pair_sample_size: int = 0
    ranking_weight: float | None = None
    cluster_weight: float | None = None
    cluster_risk_contribution: float | None = None
    ranking_coverage: float | None = None
    top_ranked_concentration: float | None = None


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
    ranked_instrument_count: int = 0
    ranking_coverage: float | None = None
    top_ranked_concentration: float | None = None


def build_correlation_clusters(
    prices: pd.DataFrame,
    metadata: Mapping[str, Any] | None = None,
    *,
    window: int = 120,
    ranked_instruments: Sequence[str] | Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
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
    requested_ranking_count = _requested_ranking_count(ranked_instruments, weights)
    ranking, normalised_weights = _ranking_weights(instrument_ids, ranked_instruments, weights)
    ranked_set = set(ranking)
    ranking_coverage = None if not ranking or requested_ranking_count == 0 else round(len(ranked_set) / requested_ranking_count, 6)
    top_ranked_concentration = None
    if normalised_weights:
        top_ranked_concentration = round(
            max((sum(normalised_weights.get(member, 0.0) for member in group) for group in groups.values()), default=0.0),
            6,
        )
    risk_by_cluster = _cluster_risk_contributions(returns, groups, normalised_weights, min_pair_samples)
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
        selected_members = [member for member in members if member in normalised_weights]
        cluster_weight = None
        cluster_risk_contribution = None
        if normalised_weights:
            if selected_members:
                cluster_weight = round(sum(normalised_weights.get(member, 0.0) for member in selected_members), 6)
                cluster_risk_contribution = risk_by_cluster.get(cluster_id)
        cluster_label = "High correlation cluster" if len(members) > 1 else "Singleton / no correlated peer"
        if dominant_theme:
            cluster_label += f" ({dominant_theme})"
        for instrument_id in members:
            peers = corr[instrument_id].drop(labels=[instrument_id], errors="ignore").dropna()
            valid_peer_values = []
            pair_sample_counts: list[int] = []
            for peer in peers.index:
                pair_count = int(returns[[instrument_id, peer]].dropna().shape[0])
                if pair_count >= min_pair_samples:
                    valid_peer_values.append(float(peers.loc[peer]))
                    pair_sample_counts.append(pair_count)
            clean_sample_size = int(returns[instrument_id].notna().sum())
            average_peer = _safe_float(sum(valid_peer_values) / len(valid_peer_values)) if valid_peer_values else None
            row_warning = cluster_warning
            if average_peer is None and (clean_sample_size < min_pair_samples or not valid_peer_values):
                row_warning = "correlation_coverage_unavailable"
            pair_sample_size = min(pair_sample_counts, default=0)
            row_coverage = None if clean_sample_size == 0 else round(pair_sample_size / clean_sample_size, 6)
            item = labels.get(instrument_id, {})
            rows.append(
                ClusterRow(
                    instrument_id=instrument_id,
                    cluster_id=cluster_id,
                    cluster_label=cluster_label,
                    average_peer_correlation=average_peer,
                    theme=item.get("theme"),
                    crowding_warning=row_warning,
                    sample_size=clean_sample_size,
                    sector=item.get("sector"),
                    theme_warning=theme_warning,
                    members=members,
                    as_of=_as_of(frame.index),
                    pair_sample_size=pair_sample_size,
                    ranking_weight=normalised_weights.get(instrument_id) if normalised_weights else None,
                    cluster_weight=cluster_weight,
                    cluster_risk_contribution=cluster_risk_contribution,
                    ranking_coverage=row_coverage,
                    top_ranked_concentration=top_ranked_concentration,
                )
            )
    return ClusterReport(
        rows=tuple(rows),
        as_of=_as_of(frame.index),
        window=window,
        status="available",
        sample_size=int(len(returns)),
        reason="Correlation clusters computed from clean adjusted-price returns.",
        ranked_instrument_count=len(ranked_set),
        ranking_coverage=ranking_coverage,
        top_ranked_concentration=top_ranked_concentration,
    )


def _ranking_weights(
    instrument_ids: list[str],
    ranked_instruments: Sequence[str] | Mapping[str, float] | None,
    weights: Mapping[str, float] | None,
) -> tuple[list[str], dict[str, float]]:
    if isinstance(ranked_instruments, Mapping):
        ranking = [
            instrument_id
            for instrument_id, _ in sorted(
                ((str(key), _safe_float(value)) for key, value in ranked_instruments.items()),
                key=lambda item: (float("inf") if item[1] is None else item[1], item[0]),
            )
        ]
    elif ranked_instruments is not None:
        ranking = [str(value) for value in ranked_instruments]
    elif weights:
        ranking = [
            str(key)
            for key, value in sorted(
                weights.items(), key=lambda item: (-(_safe_float(item[1]) or 0.0), str(item[0]))
            )
        ]
    else:
        return [], {}
    ranking = list(dict.fromkeys(item for item in ranking if item in instrument_ids))
    if not ranking:
        return [], {}
    raw = {instrument_id: max(0.0, _safe_float((weights or {}).get(instrument_id)) or 0.0) for instrument_id in ranking}
    if not any(raw.values()):
        raw = {instrument_id: 1.0 for instrument_id in ranking}
    total = sum(raw.values())
    return ranking, {instrument_id: value / total for instrument_id, value in raw.items()}


def _requested_ranking_count(
    ranked_instruments: Sequence[str] | Mapping[str, float] | None,
    weights: Mapping[str, float] | None,
) -> int:
    if isinstance(ranked_instruments, Mapping):
        return len({str(key) for key in ranked_instruments})
    if ranked_instruments is not None:
        return len({str(value) for value in ranked_instruments})
    return len({str(key) for key in (weights or {})})


def _cluster_risk_contributions(
    returns: pd.DataFrame,
    groups: Mapping[str, list[str]],
    weights: Mapping[str, float],
    min_pair_samples: int,
) -> dict[str, float]:
    """Estimate covariance-adjusted cluster risk while retaining singleton weight.

    The multiplier compares each cluster's covariance variance with the variance
    implied by its weighted average constituent volatility.  A singleton has a
    multiplier of one, so its published contribution remains its selected
    portfolio weight rather than collapsing to zero because it has no peer.
    """

    if not weights:
        return {}
    selected = [instrument_id for instrument_id in weights if instrument_id in returns.columns]
    if not selected:
        return {}
    covariance = returns[selected].cov(min_periods=min_pair_samples).reindex(index=selected, columns=selected)
    variances = pd.to_numeric(pd.Series({instrument_id: covariance.loc[instrument_id, instrument_id] for instrument_id in selected}), errors="coerce")
    fallback_variances = returns[selected].var(skipna=True).reindex(selected)
    variances = variances.fillna(fallback_variances).fillna(0.0).clip(lower=0.0)
    covariance = covariance.fillna(0.0)
    for instrument_id in selected:
        covariance.loc[instrument_id, instrument_id] = float(variances.loc[instrument_id])

    raw_contributions: dict[str, float] = {}
    for members in groups.values():
        selected_members = [member for member in members if member in weights and member in covariance.columns]
        if not selected_members:
            continue
        cluster_id = "cluster_" + "_".join(sorted(members))
        cluster_weight = sum(float(weights[member]) for member in selected_members)
        if cluster_weight <= 0.0:
            continue
        vector = pd.Series({member: float(weights[member]) for member in selected_members})
        sub_covariance = covariance.loc[selected_members, selected_members]
        cluster_variance = float(vector.to_numpy() @ sub_covariance.to_numpy() @ vector.to_numpy())
        weighted_average_variance = sum(
            (float(weights[member]) / cluster_weight) * float(variances.loc[member])
            for member in selected_members
        )
        denominator = cluster_weight * cluster_weight * weighted_average_variance
        multiplier = cluster_variance / denominator if denominator > 0.0 else 1.0
        raw_contributions[cluster_id] = max(0.0, cluster_weight * multiplier)
    total = sum(raw_contributions.values())
    if total <= 0.0:
        return {}
    return {cluster_id: round(value / total, 6) for cluster_id, value in raw_contributions.items()}


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
