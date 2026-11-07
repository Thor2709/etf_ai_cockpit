"""MCP tier and profile policy.

Open defaults: an omitted tier list enables read only; an omitted profile is core.
The full profile is available only when explicitly selected at launch.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Iterable


class Tier(StrEnum):
    READ = "read"
    READ_JOB = "read_job"
    RESEARCH = "research"
    EDIT = "edit"
    PAPER = "paper"


KNOWN_TIERS = frozenset(item.value for item in Tier)
KNOWN_PROFILES = frozenset({"core", "full"})
WRITE_TIERS = frozenset({Tier.RESEARCH.value, Tier.EDIT.value, Tier.PAPER.value})

CORE_PROFILE_TOOLS = frozenset(
    {
        "cockpit_status",
        "job_status",
        "scores_ranked",
        "score_explain",
        "instrument_detail",
        "compare_instruments",
        "etf_look_through",
        "etf_overlap",
        "forecast_get",
        "data_health",
        "gates_status",
        "what_changed",
        "portfolio_overview",
        "paper_bots_status",
        "paper_portfolio",
        "instrument_lookup",
        "research_findings",
        "research_record_findings",
        "paper_order_preview",
        "paper_order_place",
    }
)


def normalise_tier(value: str | Tier) -> str:
    text = str(value).strip().lower().replace("-", "_")
    if text not in KNOWN_TIERS:
        raise ValueError(f"unknown MCP tier: {value!r}")
    return text


def parse_tiers(values: str | Iterable[str | Tier] | None = None) -> frozenset[str]:
    """Parse a launch tier list; the conservative default is read-only."""

    if values is None:
        return frozenset({Tier.READ.value})
    if isinstance(values, str):
        raw = values.split(",")
    else:
        raw = list(values)
    tiers = frozenset(normalise_tier(value) for value in raw if str(value).strip())
    if not tiers:
        raise ValueError("at least one MCP tier must be enabled")
    return tiers


def normalise_profile(profile: str | None) -> str:
    value = (profile or "core").strip().lower()
    if value not in KNOWN_PROFILES:
        raise ValueError(f"unknown MCP profile: {profile!r}")
    return value


def profile_allows(name: str, profile: str, declared: frozenset[str] | None = None) -> bool:
    if profile == "core":
        return name in CORE_PROFILE_TOOLS and (declared is None or profile in declared)
    return declared is None or profile in declared
