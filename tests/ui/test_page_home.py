"""Home (Simple Scores): view-model rules and rendered cards (FINAL_UI_SPEC 6.1)."""

from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app.pages import dashboard
from etf_cockpit.app.pages._p1_common import make_layout
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.ui_views.home import (
    CheckRow,
    HomeView,
    ScoreRow,
    evidence_tag,
    filter_tier,
    risk_band,
    score_bands,
    sort_rows,
)


def _walk(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(c, "value", "") or "") for c in _walk(control))


ROWS = (
    ScoreRow(1, "VWCE", "Vanguard FTSE All-World", "Primary", 7.2, "Strong", "ok", "Low", 2, 3, 1),
    ScoreRow(2, "ASML", "ASML Holding", "Secondary", 6.1, "Good", "ok", "High", 3, 7, 4),
    ScoreRow(3, "SPAR1", "Sparebank 1 SR-Bank", "Sparebanken", 2.4, "Weak", "bad", None, -1, 6, 7),
)
CHECKS = (CheckRow("ok", "Data health is Clean", "As of 01 Oct 2026", "OK", "ok", "/data-health", 3),)


def _body(view: HomeView, width: int = 1920):
    page = SimpleNamespace(width=width, height=1200, route="/")
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    return dashboard._home_body(page, state, view, [], make_layout(page), "All", "Score")


def test_mapping_rules_follow_the_spec() -> None:
    assert evidence_tag("watchlist") == ("Watchlist", "ok")
    assert evidence_tag("anything", blocked=True) == ("Blocked", "bad")
    assert risk_band(7.0) == "Low" and risk_band(4.0) == "Medium" and risk_band(3.9) == "High"
    assert risk_band(None) is None  # missing is never a band
    assert score_bands(ROWS) == (1, 0, 0, 0, 1, 1)


def test_tier_filter_and_sort_modes() -> None:
    assert [r.instrument_id for r in filter_tier(ROWS, "Secondary")] == ["ASML"]
    assert [r.instrument_id for r in sort_rows(ROWS, "Change")] == ["ASML", "VWCE", "SPAR1"]
    assert [r.instrument_id for r in sort_rows(ROWS, "Rank")] == ["VWCE", "ASML", "SPAR1"]


def test_reference_cards_are_present_with_data() -> None:
    text = _text(_body(HomeView(CHECKS, ROWS, "Clean", 3, 3, 100.0, ("Toto 2.0",))))
    for title in ("What matters today", "Scores", "Biggest score & rank changes", "Score distribution", "Evidence state"):
        assert title in text
    assert "+ Toto 2.0 (exp.)" in text


def test_empty_universe_shows_empty_state_not_zeros() -> None:
    text = _text(_body(HomeView((), (), "Unavailable", 0, 0, None, ())))
    assert "No instruments yet" in text and "Set up a local watchlist to start." in text
    assert "No previous run to compare" in text
    assert "No instruments to assess" in text  # data quality is unavailable, never 0%


def test_medium_and_narrow_windows_render_every_card() -> None:
    view = HomeView(CHECKS, ROWS, "Clean", 3, 3, 100.0, ())
    for width in (1100, 1000):
        assert "Evidence state" in _text(_body(view, width=width))
