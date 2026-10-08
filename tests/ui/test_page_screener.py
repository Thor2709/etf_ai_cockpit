from __future__ import annotations

from collections.abc import Iterator

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import screener
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control: object) -> Iterator[ft.Control]:
    if isinstance(control, PageView):
        yield from _walk(control.body)
        return
    if not isinstance(control, ft.Control):
        return
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _texts(control: object) -> list[str]:
    return [
        str(value)
        for item in _walk(control)
        if (value := getattr(item, "value", None)) is not None
    ]


@pytest.fixture(scope="module")
def _snapshot():
    snapshot = build_snapshot()
    return snapshot


def _state(snapshot) -> AppState:
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _stub_projections(monkeypatch) -> None:
    monkeypatch.setattr(
        screener,
        "load_top_n_selection",
        lambda **_kwargs: {"status": "unavailable", "reason": "saved selection evidence unavailable", "rows": []},
    )
    monkeypatch.setattr(
        screener,
        "load_fixed_income_screener",
        lambda **_kwargs: {"status": "unavailable", "reason_codes": [], "rows": []},
    )


def test_renders_with_sample_data(monkeypatch, _snapshot) -> None:
    _stub_projections(monkeypatch)
    monkeypatch.setattr(
        screener,
        "load_fundamental_evidence",
        lambda _path: pd.DataFrame(
            [
                {
                    "instrument_id": "MSFT",
                    "valuation": 7.0,
                    "profitability": 8.0,
                    "leverage": 5.0,
                    "growth": 9.0,
                    "shareholder_return": 6.0,
                    "eligibility": "eligible",
                    "source": "sec_edgar",
                    "as_of_date": "2026-07-10",
                }
            ]
        ),
    )

    view = screener.screener_page(None, _state(_snapshot))
    text = "\n".join(_texts(view))

    assert isinstance(view, PageView)
    assert view.chrome.title == "Fundamentals Screener"
    assert "Reproducible local screen" in text
    assert "Screen results" in text
    assert "Distribution of" in text
    assert "Quality vs. risk friction" in text
    assert "Top-N opportunity selection" in text
    assert "Exclusion funnel" in text
    assert "Winners" in text
    assert "Fixed-income expected returns" in text
    assert "Instrument fundamentals" in text
    assert "Traceback" not in text


def test_empty_data_shows_unavailable(monkeypatch, _snapshot) -> None:
    _stub_projections(monkeypatch)
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    monkeypatch.setattr(screener, "build_screen_rows", lambda _snapshot, _frame: pd.DataFrame())

    view = screener.screener_page(None, _state(_snapshot))
    text = _texts(view)

    assert any("Unavailable" in value or "unavailable" in value for value in text)
    assert not any(value == "0" for value in text)
    assert "No screen results" in "\n".join(text)


def test_local_screen_card_controls_have_bounded_layout(monkeypatch, _snapshot) -> None:
    _stub_projections(monkeypatch)
    monkeypatch.setattr(screener, "load_fundamental_evidence", lambda _path: pd.DataFrame())
    view = screener.screener_page(None, _state(_snapshot))
    card = next(
        control
        for control in _walk(view)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "GlassCard"
        and control.data.get("title") == "Reproducible local screen"
    )
    descendants = list(_walk(card))

    assert card.expand is False
    assert any(isinstance(control, ft.TextField) for control in descendants)
    assert any(isinstance(control, ft.Dropdown) for control in descendants)
    assert any(
        isinstance(control, ft.TextButton)
        and control.key == "screener.filter.clear"
        for control in descendants
    )
    assert not any(isinstance(control, ft.ListView) for control in descendants)
    assert not any(
        isinstance(control, ft.Column)
        and control.scroll == ft.ScrollMode.AUTO
        and control.expand
        for control in descendants
    )
