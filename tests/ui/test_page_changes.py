"""What Changed: view-model rules and rendered cards (FINAL_UI_SPEC 6.8)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages import what_changed
from etf_cockpit.application.ui_views.changes import SEGMENT_ITEMS, ChangeRow, filter_rows, score_bars, signed, sorted_rows


def _walk(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(c, "value", "") or "") for c in _walk(control))


def _row(ident: str, delta: float | None, dims=frozenset({"score"})) -> ChangeRow:
    return ChangeRow(ident, delta, 1, ("Fresh", "ok"), ("Available", "ok"), "Unchanged", None, "Same", "Same", dims)


def _history() -> pd.DataFrame:
    rows = []
    for run, stamp, scores in (("a", "2026-09-30T17:30:00+00:00", [7.0, 5.0]), ("b", "2026-10-01T17:30:00+00:00", [7.5, 4.4])):
        for ident, score, rank in zip(("VWCE", "EIMI"), scores, (1, 2)):
            rows.append({"run_id": run, "run_completed_at": stamp, "instrument_id": ident, "final_combined_score_10": score,
                         "rank": rank, "final_action": "watchlist"})
    return pd.DataFrame(rows)


def test_sorting_filtering_and_signed_format() -> None:
    rows = sorted_rows([_row("A", 0.1), _row("B", -0.6), _row("C", None, frozenset())])
    assert [r.instrument_id for r in rows][:2] == ["B", "A"]
    assert [r.instrument_id for r in filter_rows(rows, query="", changed_only=True, segment="All dimensions")] == ["B", "A"]
    assert signed(-0.6, 1) == "−0.6" and signed(0.04, 1) == "0" and signed(None) == "—"
    assert SEGMENT_ITEMS[:5] == ("All dimensions", "Score", "Freshness", "Forecasts", "Portfolio")


def test_score_bars_cover_the_largest_changes() -> None:
    assert {b.instrument_id for b in score_bars([_row("A", 0.1), _row("B", -0.6)])} == {"A", "B"}


def test_page_renders_reference_cards(monkeypatch) -> None:
    monkeypatch.setattr(what_changed, "score_history_frame", _history)
    view = what_changed.what_changed_page(SimpleNamespace(width=1920, height=1200), SimpleNamespace())
    text = _text(view.body)
    for title in ("Changes by instrument", "Run lineage", "Score change by instrument", "Causal path: "):
        assert title in text
    assert view.chrome.title == "What Changed" and view.chrome.subtitle.startswith("Run ")


def test_no_comparable_runs_is_an_empty_state(monkeypatch) -> None:
    monkeypatch.setattr(what_changed, "score_history_frame", lambda: pd.DataFrame())
    view = what_changed.what_changed_page(SimpleNamespace(width=1920, height=1200), SimpleNamespace())
    assert view.chrome.subtitle == "No comparable runs yet"
    assert "No score runs with valid timezone-aware completion times are available to compare." in _text(view.body)


def test_medium_window_keeps_every_card(monkeypatch) -> None:
    monkeypatch.setattr(what_changed, "score_history_frame", _history)
    view = what_changed.what_changed_page(SimpleNamespace(width=1100, height=900), SimpleNamespace())
    assert "Run lineage" in _text(view.body)
