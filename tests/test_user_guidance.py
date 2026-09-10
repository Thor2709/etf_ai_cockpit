"""Focused contract tests for ISSUE-0043 page help content."""

from __future__ import annotations

from etf_cockpit.app.content.user_guidance import (
    PAGE_ROUTES,
    get_guidance_topics,
    get_topic_by_slug,
    page_help_available,
    search_guidance,
)
from etf_cockpit.app.router import PAGES
from etf_cockpit.governance.product_scope import load_glossary


def _all_text() -> str:
    return " ".join(
        f"{topic.title} {topic.summary} {topic.authority_notice} "
        + " ".join(f"{section.heading} {section.body}" for section in topic.sections)
        for topic in get_guidance_topics()
    ).casefold()


def test_guidance_covers_every_registered_page() -> None:
    assert set(PAGE_ROUTES) == set(PAGES)
    assert all(page_help_available(route) for route in PAGES)
    assert page_help_available("/instrument/IE00TEST")
    assert not page_help_available("/unknown-route")


def test_guidance_topics_are_well_formed_and_include_required_workflows() -> None:
    topics = get_guidance_topics()
    assert len(topics) >= 10
    required = {
        "evidence-interpretation",
        "optional-models",
        "backtest-paper-results",
        "payoff-profile-interpretation",
        "optional-provider-status",
    }
    assert required.issubset({topic.slug for topic in topics})
    for topic in topics:
        assert topic.title and topic.summary and topic.routes and topic.sections
        assert "research" in topic.authority_notice.casefold() or "no live trading" in topic.authority_notice.casefold()
        for route in topic.routes:
            assert route.startswith("/")
        for section in topic.sections:
            assert section.heading and section.body


def test_required_glossary_vocabulary_and_score_authority_explanations_present() -> None:
    policy = load_glossary().policy
    assert policy is not None
    glossary_text = " ".join(
        f"{entry.term} {entry.definition} {entry.authority_note or ''}" for entry in policy.entries
    )
    text = f"{_all_text()} {glossary_text}".casefold()
    for term in ("alpha", "beta", "drawdown", "pbo", "deflated sharpe", "mase", "calibration", "slippage", "edge-to-cost"):
        assert term in text
    for phrase in (
        "8-10",
        "6-7.9",
        "4-5.9",
        "0-3.9",
        "research_candidate",
        "watchlist",
        "hold_review",
        "avoid",
        "needs_evidence",
        "manual_review",
        "not_scoreable",
        "not_applicable",
        "constraints_blocked",
        "blocker",
        "authority_warning",
        "notice",
        "context_only",
        "evidence_only",
        "research_state",
        "portfolio_review",
        "user_record",
        "none",
        "N/A",
        "zero",
        "execution_allowed=false",
        "hard",
        "high",
        "medium",
        "low",
        "unknown",
        "official_regulator",
        "official_filing",
        "issuer_document",
        "vendor_unofficial",
        "model_advisory",
        "manual_context",
        "local_manual_adjusted_close",
        "local_manual_corporate_action",
    ):
        assert phrase.casefold() in text


def test_topic_lookup_and_search_are_deterministic() -> None:
    assert get_topic_by_slug("evidence-interpretation").slug == "evidence-interpretation"  # type: ignore[union-attr]
    assert get_topic_by_slug("missing") is None
    assert any(topic.slug == "optional-models" for topic in search_guidance("TimesFM"))
    assert any(topic.slug == "backtest-paper-results" for topic in search_guidance("DSR"))
    assert any(topic.slug == "payoff-profile-interpretation" for topic in search_guidance("payoff"))
    assert search_guidance("no-such-help-term") == []


def test_guidance_never_grants_execution_authority() -> None:
    text = _all_text()
    assert "execution_allowed=false" in text
    assert "live trading is enabled" not in text
    assert "automated broker execution" not in text
