"""Portfolio Sandbox page: view-model rules and rendered cards (FINAL_UI_SPEC 6.4)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd

from etf_cockpit.app.pages.portfolio import portfolio_page
from etf_cockpit.application.ui_views import portfolio as view
from etf_cockpit.core.config import load_config
from tests.ui._p4_helpers import all_text, card_titles, walk


def _state(holdings: pd.DataFrame | None = None, prices: pd.DataFrame | None = None) -> SimpleNamespace:
    if holdings is None:
        holdings = pd.DataFrame(
            [
                {"etf_id": "VWCE", "current_weight": 0.5, "market_value_eur": 50_000.0, "as_of_date": "2026-07-18", "known_at": "2026-07-18T12:00:00Z"},
                {"etf_id": "LYP6", "current_weight": 0.3, "market_value_eur": 30_000.0, "as_of_date": "2026-07-18", "known_at": "2026-07-18T12:00:00Z"},
            ]
        )
    snapshot = SimpleNamespace(
        config=load_config(), holdings=holdings, prices=prices if prices is not None else pd.DataFrame(),
        universe_revision="u-1", data_report=SimpleNamespace(as_of_date="2026-07-18"),
    )
    return SimpleNamespace(snapshot=snapshot, last_message="Ready")


def test_series_stats_and_concentration_are_descriptive_and_never_zero_filled() -> None:
    stats = view.series_stats([100.0, 110.0, 99.0, 105.0])
    assert round(stats.range_return, 4) == 0.05 and round(stats.max_drawdown, 4) == -0.1
    assert view.series_stats([100.0]).range_return is None and view.series_stats([None, None]).reason
    assert view.herfindahl([0.5, 0.5]) == 0.5 and view.herfindahl([]) is None
    assert [view.hhi_band(v) for v in (None, 0.1, 0.2, 0.4)] == [None, "low", "moderate", "high"]


def test_window_return_ignores_prices_after_the_as_of_date() -> None:
    days = pd.bdate_range("2025-01-01", periods=400)
    prices = pd.DataFrame({"etf_id": "AAA", "date": days, "adjusted_close": np.linspace(100, 200, 400)})
    early = view.window_return(prices, "AAA", "1M", days[300].date())
    late = view.window_return(prices, "AAA", "1M", days[-1].date())
    assert early is not None and late is not None and early != late
    assert view.window_return(prices, "AAA", "1Y", date(2025, 2, 1)) is None  # not enough history: unavailable, not zero
    assert view.window_return(prices, "ZZZ", "1M", None) is None


def test_risk_insight_names_the_largest_gaps() -> None:
    lines = [view.HoldingLine("A", "A", 0.4, 1.0, None, 0.6), view.HoldingLine("B", "B", 0.6, 1.0, None, 0.4)]
    assert view.risk_insight(lines) == "A adds 20.0 pts more risk than its weight; B adds 20.0 pts less."
    assert view.risk_insight(lines[:1]) is None


def test_page_renders_reference_cards_views_and_segments() -> None:
    result = portfolio_page(SimpleNamespace(width=1920, height=1200, update=lambda: None), _state())
    titles = card_titles(result.body)
    for title in (
        "Account snapshot", "Portfolio value vs. benchmark", "Holdings", "Risk contribution vs. weight", "Risk profile & guardrails",
        "Goals, alerts & what-if", "Candidate weights", "Candidate result", "Portfolio forecast", "Projected cash flows",
        "Fixed-income portfolio fit", "Fixed-income maturity and income ladder", "Existing service evidence",
        "Optimiser comparisons and baselines", "Monthly decision template",
    ):
        assert title in titles
    assert result.chrome.title == "Portfolio Sandbox"
    assert [list(g.items) for g in result.chrome.segment_groups] == [["Holdings", "Policy", "Candidates"], ["1M", "3M", "1Y", "Custom"]]
    assert "execution_allowed=false" in all_text(result.body)


def test_view_segment_switches_row_b_in_place() -> None:
    result = portfolio_page(SimpleNamespace(width=1920, height=1200, update=lambda: None), _state())
    containers = [c for c in walk(result.body) if getattr(c, "visible", True) is False]
    assert containers  # Policy and Candidates start hidden
    result.chrome.segment_groups[0].on_change("Candidates")
    result.chrome.segment_groups[1].on_change("3M")


def test_empty_holdings_show_unavailable_states_not_zeros() -> None:
    state = _state(pd.DataFrame(columns=["etf_id", "current_weight", "market_value_eur"]))
    result = portfolio_page(SimpleNamespace(width=1100, height=900, update=lambda: None), state)
    text = all_text(result.body)
    assert "No holdings" in text or "No holdings are available" in text
    assert "No saved daily valuations" in text or "Return unavailable" in text
    assert "HHI 0.00" not in text
