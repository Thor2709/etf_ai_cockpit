"""Summary layouts must respond without rebuilding their route or evidence."""
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.pages import screener, signals


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
    monkeypatch.setattr(signals, "build_simple_instrument_scores", scores)
    monkeypatch.setattr(signals, "simple_score_grouped_sections", lambda *args, **kwargs: ft.Text("Evidence rows"))
    state = SimpleNamespace(snapshot=SimpleNamespace(config=SimpleNamespace(ui=SimpleNamespace(window_width=1280)),
        data_report=SimpleNamespace(as_of_date="2026-07-01"), signals=[], forecasts=pd.DataFrame(), prices=pd.DataFrame(),
        benchmark_reference_decision_time=None), evidence_mode="simple", current_activity=None, last_message="Ready")
    field = ft.TextField(value="session filter")
    builds = []
    def builder(page, state):
        builds.append(route)
        content = signals.signals_page(page, state) if route == "/signals" else screener._summary(pd.DataFrame({"id": [1, 2, 3]}), 2, 1, "Local evidence", "#00FFFF")
        return ft.Column([field, content])
    monkeypatch.setitem(router.PAGES, route, ("Summary", builder))
    updates = []
    page = SimpleNamespace(width=1280, update=lambda: updates.append(True), views=[])
    view = router.build_shell(page, state, route)
    page.views.append(view)
    expected_titles = {"Strong evidence", "Positive evidence", "Watch/mixed", "Manual review", "Forecast source"} if route == "/signals" else {"Canonical instruments", "Complete five-section", "Score eligible"}
    summary = next(control for control in _walk(view) if isinstance(control, ft.ResponsiveRow) and len(control.controls) == len(expected_titles)
                   and all(isinstance(card, ft.Container) for card in control.controls))
    cards = tuple(summary.controls)
    text = {control.value for control in _walk(summary) if isinstance(control, ft.Text)}
    assert expected_titles <= text
    assert ({"0", "No forecast file loaded"} if route == "/signals" else {"3", "2", "1", "Local evidence"}) <= text
    assert all(card.col["xs"] == 12 and card.col["sm"] == 6 for card in cards)
    assert all(card.col["xl" if route == "/signals" else "lg"] < 12 for card in cards)
    for width in (390, 1280, 390):
        router.relayout_shell(page, state, width)
        assert page.views[0] is view and tuple(summary.controls) == cards
        assert field.value == "session filter"
        assert builds == [route]
    assert len(updates) == 3
    assert calls == (["scores"] if route == "/signals" else [])
