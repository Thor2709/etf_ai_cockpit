"""Comparison page: view-model rules and rendered cards (FINAL_UI_SPEC 6.5)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from etf_cockpit.app.pages import _p3_common as common
from etf_cockpit.app.pages.comparison import comparison_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.ui_views import comparison as view


def _walk(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(c, "value", "") or "") for c in _walk(control))


def _prices(days: int = 520) -> pd.DataFrame:
    dates = pd.bdate_range("2024-06-01", periods=days)
    rows = []
    for name, drift in (("AAA", 0.0006), ("BBB", 0.0003)):
        close = 100 * np.exp(np.cumsum(drift + 0.004 * np.sin(np.arange(days) / 5.0)))
        rows.append(pd.DataFrame({"etf_id": name, "date": dates, "close": close, "adjusted_close": close}))
    return pd.concat(rows, ignore_index=True)


def test_price_index_rebases_both_instruments_to_100_on_the_first_shared_date() -> None:
    series = view.price_index(_prices(), "AAA", "BBB", "1Y")
    assert series.reason is None and series.a[0] == 100.0 and series.b[0] == 100.0
    assert series.end_gap is not None and abs(series.end_gap - (series.a[-1] - series.b[-1])) < 1e-9


def test_missing_prices_give_a_reason_never_zero() -> None:
    series = view.price_index(_prices(), "AAA", "ZZZ", "1Y")
    assert series.a == [] and "ZZZ" in (series.reason or "")
    assert view.monthly_gap({}, "AAA", "BBB", "1Y").values == []
    assert "two stored score runs" in (view.score_history({}, "AAA", "BBB", "1Y").reason or "")


def test_monthly_gap_is_a_minus_b_in_percentage_points_inside_the_range() -> None:
    gap = view.monthly_gap(_prices(), "AAA", "BBB", "1Y")
    assert gap.reason is None and 10 <= len(gap.values) <= 12 and len(gap.labels) == len(gap.values)
    three = view.monthly_gap(_prices(), "AAA", "BBB", "3M")
    assert len(three.values) <= 3


def test_risk_band_follows_the_friction_score() -> None:
    assert [view.risk_band(v) for v in (None, 8.0, 5.0, 2.0)] == [None, "Low", "Medium", "High"]


def _state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def test_page_renders_the_four_reference_cards_with_segments() -> None:
    page = SimpleNamespace(width=1920, height=1200, update=lambda: None)
    result = comparison_page(page, _state())
    text = _text(result.body)
    for title in ("Comparison workspace", "Price, indexed to 100", "Score components", "Rolling return gap", "Aligned evidence"):
        assert title.casefold() in text.casefold()
    assert result.chrome.title == "Comparison"
    assert [list(group.items) for group in result.chrome.segment_groups] == [["Price", "Score", "Risk"], ["1M", "3M", "1Y", "5Y"]]
    keys = {getattr(c, "key", None) for c in _walk(result.body)}
    assert {"comparison.left", "comparison.right", "comparison.save-workspace", "comparison.export-csv", "comparison.table"} <= keys


def test_metric_segment_switches_the_hero_card_in_place_and_score_history_may_be_unavailable() -> None:
    page = SimpleNamespace(width=1920, height=1200, update=lambda: None)
    result = comparison_page(page, _state())
    result.chrome.segment_groups[0].on_change("Risk")
    assert "Drawdown" in _text(result.body)
    result.chrome.segment_groups[0].on_change("Score")
    text = _text(result.body)
    assert "Score history" in text and "Traceback" not in text


def test_empty_scores_show_an_empty_state_not_zeros(monkeypatch) -> None:
    monkeypatch.setattr(common, "scores_for", lambda _state: [])
    result = comparison_page(SimpleNamespace(width=1920, height=1200, update=lambda: None), _state())
    assert "Comparison unavailable" in _text(result.body)
