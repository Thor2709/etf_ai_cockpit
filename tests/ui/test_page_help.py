"""Help & Glossary: view model and rendered views (FINAL_UI_SPEC 6.9)."""

from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app.pages.help_glossary import PAGE_HELP, help_glossary_page
from etf_cockpit.application.scope_facade import load_glossary
from etf_cockpit.application.ui_views.help import build_terms, filter_terms, find_term, short_gloss
from etf_cockpit.core.navigation import ROUTE_TITLES


def _walk(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(c, "value", "") or "") for c in _walk(control))


def _terms():
    loaded = load_glossary()
    return build_terms(loaded.policy.entries if loaded.policy else (), PAGE_HELP, dict(ROUTE_TITLES))


def test_gloss_is_a_short_use_boundary_phrase() -> None:
    assert short_gloss("Context only; it does not bypass gates") == "Context only"
    assert all(len(t.gloss) <= 28 for t in _terms())


def test_reference_terms_lead_the_list_and_search_filters() -> None:
    terms = _terms()
    assert [t.term for t in terms[:3]] == ["Score", "Evidence quality", "Execution authority"]
    assert find_term(terms, "score") is not None
    assert [t.term.casefold() for t in filter_terms(terms, "drawdown")][:1] == ["drawdown"]


def test_glossary_view_has_four_reference_cards() -> None:
    view = help_glossary_page(None, SimpleNamespace(previous_route="/"))
    text = _text(view.body)
    for title in ("Glossary", "Selected definition", "About this page", "Terms and use boundaries"):
        assert title in text
    assert "Legal terms status" not in text  # the legal status belongs to the Boundaries view


def test_segments_switch_views_in_place() -> None:
    view = help_glossary_page(None, SimpleNamespace(previous_route="/"))
    switch = view.chrome.segment_groups[0].on_change
    switch("This page")
    assert "Back to " in _text(view.body)
    switch("Boundaries")
    assert "Authority boundaries" in _text(view.body) and "Legal terms status" in _text(view.body)
