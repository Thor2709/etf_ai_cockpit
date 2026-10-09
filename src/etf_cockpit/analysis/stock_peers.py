"""Automatic peer selection for normal stocks (pure): sector/industry, region and size band.

A candidate's similarity is the sum of the configured weights for each matching trait; candidates
below ``peers.min_score`` are not peers. The instrument is never its own peer. User-picked peers
are stored separately (``data/stock_peers``) and always override the automatic list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PeerProfile:
    instrument_id: str
    name: str
    sector: str = ""
    industry: str = ""
    region: str = ""
    market_cap_eur_bn: float | None = None


@dataclass(frozen=True)
class PeerPick:
    instrument_id: str
    name: str
    score: int
    reasons: tuple[str, ...]
    origin: str  # auto | user


def size_band(market_cap_eur_bn: float | None, edges: Sequence[float]) -> int | None:
    if market_cap_eur_bn is None:
        return None
    return sum(1 for edge in edges if market_cap_eur_bn >= edge)


def _same(left: str, right: str) -> bool:
    return bool(left) and bool(right) and left.strip().casefold() == right.strip().casefold()


def auto_peers(target: PeerProfile, candidates: Sequence[PeerProfile], config: Mapping[str, object]) -> list[PeerPick]:
    cfg = config.get("peers", {}) if isinstance(config.get("peers"), Mapping) else {}
    weights = cfg.get("weights", {"industry": 3, "sector": 2, "region": 1, "size_band": 1})  # type: ignore[union-attr]
    edges = list(cfg.get("size_bands_market_cap_eur_bn", [2, 10, 50]))  # type: ignore[union-attr]
    minimum = int(cfg.get("min_score", 2))  # type: ignore[union-attr]
    limit = int(cfg.get("max_auto", 8))  # type: ignore[union-attr]
    own_band = size_band(target.market_cap_eur_bn, edges)
    picks: list[PeerPick] = []
    for candidate in candidates:
        if candidate.instrument_id == target.instrument_id:
            continue
        score = 0
        reasons = []
        if _same(target.industry, candidate.industry):
            score += int(weights["industry"])
            reasons.append(f"same industry ({candidate.industry})")
        if _same(target.sector, candidate.sector):
            score += int(weights["sector"])
            reasons.append(f"same sector ({candidate.sector})")
        classified = score > 0  # region and size only rank peers: a peer must share the industry or the sector
        if _same(target.region, candidate.region):
            score += int(weights["region"])
            reasons.append(f"same region ({candidate.region})")
        band = size_band(candidate.market_cap_eur_bn, edges)
        if own_band is not None and band is not None and band == own_band:
            score += int(weights["size_band"])
            reasons.append("same size band")
        if classified and score >= minimum:
            picks.append(PeerPick(candidate.instrument_id, candidate.name, score, tuple(reasons), "auto"))
    picks.sort(key=lambda item: (-item.score, item.instrument_id))
    return picks[:limit]


def effective_peers(auto: Sequence[PeerPick], user_ids: Sequence[str], names: Mapping[str, str], self_id: str) -> list[PeerPick]:
    """User-picked peers first (always kept, never the instrument itself), then automatic ones."""

    picks: list[PeerPick] = []
    seen = {self_id}
    for peer_id in user_ids:
        if peer_id in seen:
            continue
        seen.add(peer_id)
        picks.append(PeerPick(peer_id, names.get(peer_id, peer_id), 99, ("picked by you",), "user"))
    for pick in auto:
        if pick.instrument_id not in seen:
            seen.add(pick.instrument_id)
            picks.append(pick)
    return picks
