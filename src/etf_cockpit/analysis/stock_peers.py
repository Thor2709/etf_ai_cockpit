"""Automatic peer selection for normal stocks (pure): sector/industry, region and size band.

A candidate's similarity is the sum of the configured weights for each matching trait; candidates
below ``peers.min_score`` are not peers. The instrument is never its own peer. User-picked peers
are stored separately (``data/stock_peers``) and always override the automatic list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from etf_cockpit.core.values import is_finite_number

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
    if not is_finite_number(market_cap_eur_bn) or market_cap_eur_bn < 0:
        return None
    return sum(1 for edge in edges if market_cap_eur_bn >= edge)


def _key(text: str) -> str | None:
    """The trait match rule as a lookup key: an empty trait never matches."""

    return text.strip().casefold() if text else None


def _same(left: str, right: str) -> bool:
    key = _key(left)
    return key is not None and key == _key(right)


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


COHORT_LEVELS = ("industry", "sector", "region", "universe")  # narrowest first; "universe" is the asset-class (all stocks) prior


def cohort_members(target: PeerProfile, candidates: Sequence[PeerProfile]) -> dict[str, tuple[str, ...]]:
    """Instrument ids per cohort level (industry -> sector -> region -> universe), the instrument itself never included.

    Levels are nested in preference order, not in membership: a region cohort is every same-region stock,
    whatever its sector. Empty traits never match (an unclassified stock has no industry/sector cohort).
    """

    index = PeerIndex(candidates)
    return {
        level: tuple(item.instrument_id for item in index.members(level, target) if item.instrument_id != target.instrument_id)
        for level in COHORT_LEVELS
    }


class PeerIndex:
    """Candidates bucketed once by industry, sector and region (the ``_same`` rule): peers and cohorts are looked up,
    not scanned from every candidate for every stock."""

    def __init__(self, candidates: Sequence[PeerProfile]) -> None:
        self.candidates = tuple(candidates)
        self._positions: dict[tuple[str, str] | None, list[int]] = {}  # never a None key: an empty trait has no bucket
        for position, candidate in enumerate(self.candidates):
            for level in COHORT_LEVELS:
                bucket = self.bucket(level, candidate)
                if bucket is not None:
                    self._positions.setdefault(bucket, []).append(position)

    @staticmethod
    def bucket(level: str, profile: PeerProfile) -> tuple[str, str] | None:
        """The bucket of ``profile`` at a cohort level; None for an empty trait. Every profile is in the universe bucket."""

        if level == "universe":
            return level, ""
        key = _key(getattr(profile, level, ""))
        return None if key is None else (level, key)

    def members(self, level: str, target: PeerProfile) -> list[PeerProfile]:
        """Candidates in the bucket of ``target`` at ``level``, in candidate order; the target itself is not removed."""

        return [self.candidates[position] for position in self._positions.get(self.bucket(level, target), ())]

    def classified(self, target: PeerProfile) -> list[PeerProfile]:
        """Candidates that share the industry or the sector, in candidate order: no other one can be an automatic peer."""

        positions = {*self._positions.get(self.bucket("industry", target), ()), *self._positions.get(self.bucket("sector", target), ())}
        return [self.candidates[position] for position in sorted(positions)]
