"""Task-based help content for every registered cockpit page.

This module is deliberately a content contract, not a second router.  Page
builders can remain independently testable while the help route exposes the
same stable route vocabulary and its safety boundaries in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class GuidanceSection:
    heading: str
    body: str


@dataclass(frozen=True)
class GuidanceTopic:
    slug: str
    title: str
    summary: str
    routes: tuple[str, ...]
    sections: tuple[GuidanceSection, ...]
    authority_notice: str = "Research and education only. No live trading or broker order execution."


PAGE_ROUTES: tuple[str, ...] = (
    "/",
    "/portfolio",
    "/portfolio-optimiser",
    "/signals",
    "/screener",
    "/comparison",
    "/stock-research",
    "/risk",
    "/stress-lab",
    "/etf",
    "/backtests",
    "/chatgpt",
    "/providers",
    "/evidence",
    "/filings",
    "/etf-disclosures",
    "/news-context",
    "/data-models",
    "/forecasts",
    "/training-centre",
    "/feature-catalogue",
    "/catalogue",
    "/macro",
    "/settings",
    "/diagnostics",
    "/errors",
    "/data-health",
    "/universe",
    "/onboarding",
    "/what-changed",
    "/instrument",
    "/import-export",
    "/system-map",
    "/help",
    "/decision-journal",
    "/forward-evidence",
    "/jobs",
    "/operations",
    "/release-readiness",
    "/roadmap",
)


_SAFE_BOUNDARY = (
    "This is descriptive research context. It cannot create authority, change a gate, "
    "transmit an order, or enable execution (execution_allowed=false)."
)


_GUIDANCE_TOPICS: tuple[GuidanceTopic, ...] = (
    GuidanceTopic(
        slug="evidence-interpretation",
        title="Understanding Scores, Authority, and N/A",
        summary="How to read the 0–10 evidence scores, score components, authority states, and unavailable N/A values.",
        routes=(
            "/",
            "/portfolio",
            "/portfolio-optimiser",
            "/signals",
            "/screener",
            "/comparison",
            "/stock-research",
            "/risk",
            "/stress-lab",
            "/etf",
            "/instrument",
            "/backtests",
        ),
        sections=(
            GuidanceSection(
                "Score scale and decision labels",
                "Every numeric score is normalised to 0-10: 8-10 is strong positive evidence; 6-7.9 is positive or watchlist evidence; 4-5.9 is mixed or hold evidence; 0-3.9 is weak or negative evidence. A score is a descriptive aggregation of its eligible components, not a forecast or instruction. Final labels such as research candidate, watchlist, hold review, avoid, needs evidence, manual review, and not scoreable are governed by evidence gates; they never mean buy or sell authority.",
            ),
            GuidanceSection(
                "What each score measures",
                "Momentum measures recent multi-month price strength; trend checks medium and long moving-average direction; relative strength compares the instrument with its configured peer set; risk measures volatility and drawdown; liquidity/cost estimates whether spread, slippage, and commission could overwhelm the signal; ETF exposure measures concentration and diversification; stock value uses available valuation evidence; stock quality summarises available quality evidence; analyst revision is low-authority estimate or revision context. Evidence confidence reflects data quality, while expected return, attractiveness, risk/implementation, and portfolio fit are separate derived context fields. Calibration and backtest trust describe model evidence, not execution permission.",
            ),
            GuidanceSection(
                "Authority levels and states",
                "Component authority is hard, high, medium, low, or unknown. Hard means a mandatory evidence-quality gate; high, medium, and low describe decreasing evidential weight; unknown means the authority could not be established. Source authority is shown separately: official_regulator and official_filing are regulator or filed records; issuer_document is issuer-published evidence; vendor_unofficial is third-party vendor evidence; model_advisory is model output; manual_context and community are context-only user or community material; local_manual_adjusted_close and local_manual_corporate_action are explicitly entered local paper-ledger evidence. These labels describe provenance and reliability, never permission. Public research states are research_candidate, watchlist, hold_review, avoid, needs_evidence, manual_review, and not_scoreable. Portfolio-review states are not_applicable, maintain_review, increase_exposure_review, reduce_exposure_review, exit_thesis_review, and constraints_blocked. Gate severities are blocker (stops the next transition), authority_warning (visible caution that can require review), and notice (non-blocking information). Capability authorities such as context_only, evidence_only, research_state, portfolio_review, user_record, and none describe the permitted use of an artifact; authority stages such as research, shadow_proposal, paper, broker_read_only, draft_order, capped_automatic, and disabled are lifecycle vocabulary only. The cockpit's effective execution authority is always none.",
            ),
            GuidanceSection(
                "N/A, unavailable, and zero",
                "N/A means unavailable or inapplicable: for example, a missing disclosure, conflicted source, stale observation, or insufficient history. Unavailable is an explicit state that requires more evidence or manual review. Zero is an observed numeric value and is not interchangeable with N/A. Missing data is never silently zero-filled, imputed, or treated as a passing score. "+_SAFE_BOUNDARY,
            ),
        ),
    ),
    GuidanceTopic(
        slug="local-data-startup",
        title="Starting with Local and Sample Data",
        summary="Explore the cockpit using bundled sample data, local caches, and onboarding.",
        routes=("/onboarding", "/settings", "/universe", "/catalogue", "/data-health"),
        sections=(
            GuidanceSection(
                "First-run setup",
                "Use /onboarding to inspect local runtime settings, sample ETF holdings, benchmark definitions, and historical quotes. Sample data supports exploration without external provider keys.",
            ),
            GuidanceSection(
                "Local storage and offline guarantees",
                "Analytics, snapshots, and parquet datasets remain under the project runtime directory. Provider data that is not configured is reported as unavailable; it is not invented.",
            ),
        ),
    ),
    GuidanceTopic(
        slug="research-navigation",
        title="Navigating Research and Exploration",
        summary="Find ETFs, compare instruments, inspect changes, and review source evidence.",
        routes=("/signals", "/screener", "/comparison", "/stock-research", "/universe", "/what-changed", "/etf", "/instrument"),
        sections=(
            GuidanceSection(
                "Discovery workflows",
                "Use /signals for quantitative screening flags, /screener for multidimensional filters, and /comparison for pair-wise profiles. /etf and /instrument provide instrument facts and component evidence.",
            ),
            GuidanceSection(
                "Inspecting changes and provenance",
                "Use /what-changed after a refresh to inspect score deltas, lineage, and anomalies. Source dates, freshness, conflicts, and limitations remain visible for review.",
            ),
        ),
    ),
    GuidanceTopic(
        slug="optional-models",
        title="Optional Models and Deterministic Baselines",
        summary="Understand optional forecasting models and why baseline behavior remains available.",
        routes=("/data-models", "/forecasts", "/training-centre", "/feature-catalogue", "/macro"),
        sections=(
            GuidanceSection(
                "Baselines and promotion",
                "The cockpit works with deterministic time-series baselines. Optional TimesFM or Toto packages and weights are disabled-safe. Promotion requires walk-forward validation, purging/embargo leakage checks, calibration evidence, and PBO review.",
            ),
            GuidanceSection(
                "Model authority",
                "Model output is advisory context. It cannot override a data-quality gate, create a score authority state, or become an order. Wide uncertainty intervals indicate weak or dispersed evidence.",
            ),
        ),
    ),
    GuidanceTopic(
        slug="payoff-profile-interpretation",
        title="Payoff-Profile and Risk/Reward Asymmetry Interpretation",
        summary="Interpret descriptive payoff profiles, tail risks, sample limits, and N/A observations without predictive bias.",
        routes=("/risk", "/stress-lab", "/help"),
        sections=(
            GuidanceSection(
                "Descriptive Payoff Asymmetry",
                "Payoff profiles describe empirical skewness, upside capture, and downside deviation across historical observation windows. They illustrate non-linear return distributions without implying future predictability.",
            ),
            GuidanceSection(
                "Tail risk and sample limits",
                "Stress scenarios expose asymmetric drawdowns under historical factor shocks. When history is insufficient or quotes are missing, the profile is explicitly unavailable or insufficient_history rather than extrapolated.",
            ),
            GuidanceSection(
                "Non-predictive classification",
                "Labels such as convex, concave, or positively skewed describe historical distributions only. They are not investment advice or order-generation signals. "+_SAFE_BOUNDARY,
            ),
        ),
    ),
    GuidanceTopic(
        slug="optional-provider-status",
        title="Optional Provider Status and Capability Probes",
        summary="Understand disabled-by-default providers, offline probes, and configured versus verified entitlement.",
        routes=("/settings", "/providers", "/help"),
        sections=(
            GuidanceSection(
                "Offline and disabled-by-default behavior",
                "Optional providers such as FRED and RSS remain disabled by default. In offline mode, capability probes report adapter availability without initiating network traffic.",
            ),
            GuidanceSection(
                "Configuration is not entitlement",
                "An API key or feed URL is not proof of verified entitlement. The cockpit distinguishes configured, probing, entitled, unknown, and unavailable states; an unverified provider cannot promote evidence.",
            ),
            GuidanceSection(
                "No authority escalation",
                "Provider context cannot alter core scores, bypass fail-closed evidence gates, or grant execution authority. "+_SAFE_BOUNDARY,
            ),
        ),
    ),
    GuidanceTopic(
        slug="backtest-paper-results",
        title="Backtest and Paper Results",
        summary="Read simulations, friction assumptions, and forward paper evidence within the execution boundary.",
        routes=("/backtests", "/operations", "/forward-evidence", "/jobs"),
        sections=(
            GuidanceSection(
                "Simulation diagnostics",
                "Review DSR, maximum drawdown, turnover, MASE where forecast errors are evaluated, and edge-to-cost ratios. Slippage is a modeled difference between an assumed decision price and an observed fill proxy; it is not a guaranteed fill.",
            ),
            GuidanceSection(
                "Forward evidence and operations",
                "Paper allocations, job activity, and operational records are replayable research evidence. They do not connect to a broker or place a real order. "+_SAFE_BOUNDARY,
            ),
        ),
    ),
    GuidanceTopic(
        slug="data-licences-terms",
        title="Data Licences, Sources, and Audit Export",
        summary="Understand provenance, redistribution limits, and audit bundle generation.",
        routes=("/chatgpt", "/evidence", "/filings", "/etf-disclosures", "/news-context", "/providers", "/help"),
        sections=(
            GuidanceSection(
                "Terms and provenance",
                "configs/legal_terms_registry.yaml records source identifiers, attribution rules, cache permissions, and redistribution restrictions. Audit bundles retain provenance and legal notices; restricted source data is not silently redistributed.",
            ),
            GuidanceSection(
                "Source authority",
                "Official regulator or issuer documents may provide stronger evidence than vendor, model, news, or manually supplied context. Source authority remains bounded by freshness, point-in-time validity, completeness, and conflict checks.",
            ),
        ),
    ),
    GuidanceTopic(
        slug="troubleshooting-reproducibility",
        title="Diagnostics, Recovery, and Reproducible Runs",
        summary="Diagnose local health, inspect failures, and preserve reproducibility.",
        routes=("/diagnostics", "/errors", "/import-export", "/system-map", "/release-readiness"),
        sections=(
            GuidanceSection(
                "System health and recovery",
                "Use /diagnostics for resource and cache status, /errors for fail-closed warnings and recovery runbooks, and /import-export for local data movement. /system-map and /release-readiness show bounded architecture and evidence readiness.",
            ),
            GuidanceSection(
                "Reproducibility",
                "Deterministic seeds, local inputs, version metadata, and audit manifests help reproduce a run. A failed or incomplete check is reported explicitly and does not become a positive result.",
            ),
        ),
    ),
    GuidanceTopic(
        slug="decision-and-programme-records",
        title="Decision Records and Programme Context",
        summary="Keep human decisions, roadmap context, and research notes separate from calculated evidence.",
        routes=("/decision-journal", "/roadmap", "/help"),
        sections=(
            GuidanceSection(
                "Human records",
                "Decision journal notes and programme maps record user context and planned work. They are user records, not source-linked score evidence and not automated authority.",
            ),
            GuidanceSection(
                "Review discipline",
                "Keep assumptions, uncertainty, and reasons for manual review visible. A human can accept or reject a research hypothesis, but the application remains non-executable.",
            ),
        ),
    ),
)


def _normalise_route(route: str) -> str:
    value = str(route or "/").strip().split("?", 1)[0].split("#", 1)[0] or "/"
    if value.startswith("/instrument/"):
        return "/instrument"
    return value


def get_guidance_topics() -> Sequence[GuidanceTopic]:
    """Return all task-based guidance topics in stable display order."""

    return _GUIDANCE_TOPICS


def get_topic_by_slug(slug: str) -> GuidanceTopic | None:
    """Look up a guidance topic by its stable slug."""

    normalized = str(slug or "").strip().casefold()
    return next((topic for topic in _GUIDANCE_TOPICS if topic.slug == normalized), None)


def get_page_guidance(route: str) -> tuple[GuidanceTopic, ...]:
    """Return the guidance topics that cover a registered page route.

    Dynamic instrument routes are normalised to the registered ``/instrument``
    page. Unknown routes return an empty tuple so callers can render an
    explicit unavailable state instead of inventing help text.
    """

    normalized = _normalise_route(route)
    return tuple(topic for topic in _GUIDANCE_TOPICS if normalized in topic.routes)


def page_help_available(route: str) -> bool:
    """Return whether a route has at least one explicit guidance topic."""

    return bool(get_page_guidance(route))


def search_guidance(query: str) -> list[GuidanceTopic]:
    """Filter topics by title, summary, slug, routes, or section text."""

    needle = str(query or "").strip().casefold()
    if not needle:
        return list(_GUIDANCE_TOPICS)
    return [
        topic
        for topic in _GUIDANCE_TOPICS
        if needle in topic.slug.casefold()
        or needle in topic.title.casefold()
        or needle in topic.summary.casefold()
        or any(needle in route.casefold() for route in topic.routes)
        or any(needle in section.heading.casefold() or needle in section.body.casefold() for section in topic.sections)
    ]


__all__ = [
    "GuidanceSection",
    "GuidanceTopic",
    "PAGE_ROUTES",
    "get_guidance_topics",
    "get_page_guidance",
    "get_topic_by_slug",
    "page_help_available",
    "search_guidance",
]
