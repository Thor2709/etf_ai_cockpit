"""Summary layouts must respond without rebuilding their route or evidence."""
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.pages import screener, signals
from etf_cockpit.application import score_views


def _walk(node):
    yield node
    for child in getattr(node, "controls", []) or []:
        yield from _walk(child)
    if getattr(node, "content", None) is not None:
        yield from _walk(node.content)


@pytest.mark.parametrize("route", ["/signals", "/screener"])
def test_summary_cards_reflow_natively_and_keep_session(monkeypatch, route):
    context = SimpleNamespace(benchmark_data_id=None, projection=None, registry=None, identity=None, peer_member_ids=())
    monkeypatch.setattr(signals, "context_from_snapshot", lambda *args, **kwargs: context)
    calls = []
    def scores(*args, **kwargs):
        calls.append("scores")
        return []
    monkeypatch.setattr(score_views, "build_simple_instrument_scores", scores)
    monkeypatch.setattr(signals, "simple_score_grouped_sections", lambda *args, **kwargs: ft.Text("Evidence rows"))
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(screener, "build_screen_rows", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(
        screener,
        "load_fixed_income_screener",
        lambda **kwargs: {"status": "unavailable", "reason_codes": [], "rows": []},
    )
    state = SimpleNamespace(snapshot=SimpleNamespace(config=SimpleNamespace(ui=SimpleNamespace(window_width=1280)),
        data_report=SimpleNamespace(as_of_date="2026-07-01"), signals=[], forecasts=pd.DataFrame(), prices=pd.DataFrame(),
        benchmark_reference_decision_time=None), evidence_mode="simple", current_activity=None, last_message="Ready")
    field = ft.TextField(value="session filter")
    builds = []
    def builder(page, state):
        builds.append(route)
        content = signals.signals_page(page, state) if route == "/signals" else screener.screener_page(page, state)
        return ft.Column([field, content])
    monkeypatch.setitem(router.PAGES, route, ("Summary", builder))
    updates = []
    page = SimpleNamespace(width=1280, update=lambda: updates.append(True), views=[])
    view = router.build_shell(page, state, route)
    page.views.append(view)
    controls = list(_walk(view))

    def kit(name):
        return [c for c in controls if isinstance(getattr(c, "data", None), dict) and c.data.get("kit") == name]

    if route == "/signals":
        # Current design: a four-item KPI strip with truthful unavailable states, then a natively reflowing
        # score-table / detail row that collapses to full width on narrow windows.
        strip = kit("KpiStrip")
        assert len(strip) == 1
        assert strip[0].data["items"] == ["Strong evidence", "Positive evidence", "Watch/mixed", "Manual review"]
        shown = {c.value.casefold() for c in _walk(strip[0]) if isinstance(c, ft.Text)}
        assert {"canonical scores", "unavailable"} <= shown
        reflow = next(
            c for c in controls if isinstance(c, ft.ResponsiveRow) and len(c.controls) == 2
            and all(isinstance(card, ft.Container) and isinstance(card.col, dict) for card in c.controls)
        )
        assert [card.col["lg"] for card in reflow.controls] == [8, 4]
        cards = tuple(reflow.controls)
        summary = reflow
    else:
        # Current design: the saved-evidence summaries are KPI tiles in native responsive rows.
        expected = {"Expected return status", "Horizon", "Yield to worst", "Risk-adjusted return"}
        summary = next(
            c for c in controls if isinstance(c, ft.ResponsiveRow)
            and {getattr(card, "data", {}).get("label") for card in c.controls if isinstance(getattr(card, "data", None), dict)} == expected
        )
        cards = tuple(summary.controls)
        shown = {c.value.casefold() for c in _walk(summary) if isinstance(c, ft.Text)}
        assert {label.casefold() for label in expected} | {"unavailable"} <= shown
        assert all(card.col == {"xs": 12, "sm": 6, "lg": 3} for card in cards)
    assert all(card.col["xs"] == 12 for card in cards)
    assert all(card.col["lg"] < 12 for card in cards)
    for width in (390, 1280, 390):
        router.relayout_shell(page, state, width)
        assert page.views[0] is view and tuple(summary.controls) == cards
        assert field.value == "session filter"
        assert builds == [route]
    assert len(updates) == 3
    assert calls == (["scores"] if route == "/signals" else [])
