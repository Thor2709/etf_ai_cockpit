from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import flet as ft
from etf_cockpit.app.pages.help_glossary import PAGE_HELP, help_glossary_page
from etf_cockpit.app.router import PAGES, build_shell
from etf_cockpit.app.state import AppState
from etf_cockpit.governance.product_scope import load_glossary
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text_content(control) -> str:
    return "\n".join(
        item if isinstance(item, str) else str(getattr(item, "value", "") or getattr(item, "text", ""))
        for item in _walk(control)
    )


def test_help_glossary_explains_authority_and_unavailable_states() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    view = help_glossary_page(None, state)
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(view))
    assert "Authority" in text
    assert "Manual review" in text
    assert "Unavailable" in text


def test_help_glossary_retains_hash_target_for_keyboard_navigation() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {"route": "/help#manual_review"})()
    text = "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(help_glossary_page(page, state)))
    assert "Selected definition" in text


def test_help_route_renders_through_shared_shell() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = cast(ft.Page, SimpleNamespace(route="/help", width=1440))

    text = _text_content(build_shell(page, state, "/help"))

    assert "Help and glossary" in text
    assert "User guide: docs/user/USER_GUIDE.md" in text
    assert "N/A denotes unavailable" in text


def test_every_registered_route_has_page_specific_help() -> None:
    assert set(PAGE_HELP) == set(PAGES)
    assert all(len(description) >= 40 for description in PAGE_HELP.values())

    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = cast(ft.Page, SimpleNamespace(route="/signals", width=1440))
    view = build_shell(page, state, "/signals")
    text = _text_content(view)

    assert PAGE_HELP["/signals"] in text
    assert "Help & Glossary" in text


def test_glossary_covers_scores_authority_and_required_user_terms() -> None:
    result = load_glossary()
    assert result.policy is not None
    terms = {entry.term.casefold() for entry in result.policy.entries}

    assert {
        "alpha",
        "beta",
        "drawdown",
        "pbo",
        "dsr",
        "deflated sharpe",
        "mase",
        "calibration",
        "slippage",
        "edge-to-cost",
        "n/a versus zero",
        "attractiveness score",
        "expected-return score",
        "risk/implementation score",
        "research",
        "shadow proposal",
        "paper",
        "broker read-only",
        "draft order",
        "capped automatic",
        "disabled",
    } <= terms


def test_user_guide_covers_required_methodology_and_operational_topics() -> None:
    guide = Path(__file__).parents[2] / "docs" / "user" / "USER_GUIDE.md"
    text = guide.read_text(encoding="utf-8").casefold()

    for section in (
        "how to read scores",
        "models and model cards",
        "etf and sector-specific evidence",
        "data sources and licences",
        "authority, paper use and live capability",
        "incidents and recovery",
        "reproducibility",
    ):
        assert section in text
    assert "execution_allowed=false" in text
