from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.strategy_builder import strategy_builder_page


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _texts(control) -> list[str]:
    return [
        str(getattr(item, "value", "") or getattr(item, "text", ""))
        for item in _walk(control)
    ]


def test_renders_with_sample_data() -> None:
    state = SimpleNamespace(
        snapshot=SimpleNamespace(
            signals=[{"instrument_id": "ETF-1", "asset_type": "etf", "trend": 0.2}]
        )
    )
    page = strategy_builder_page(None, state)
    text = " ".join(_texts(page.body))

    assert isinstance(page, PageView)
    assert page.chrome.title == "Strategy Builder"
    for title in (
        "Strategy templates",
        "Template detail · ETF dual momentum",
        "Matches per template",
        "Stage coverage",
    ):
        assert title in text
    assert "Traceback" not in text


def test_empty_data_shows_unavailable() -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(signals=[]))
    page = strategy_builder_page(None, state)
    text = " ".join(_texts(page.body))

    assert "Unavailable" in text
    assert "Traceback" not in text
    for control in _walk(page.body):
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "DataTable":
            assert all(
                str(getattr(item, "value", "")) != "0"
                for item in _walk(control)
            )


def test_strategy_cards_have_controls_with_bounded_layout() -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(signals=[]))
    page = strategy_builder_page(None, state)
    cards = {
        control.data["title"]: control
        for control in _walk(page.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "GlassCard"
    }
    templates = cards["Strategy templates"]
    coverage = cards["Stage coverage"]
    template_controls = list(_walk(templates))
    coverage_controls = list(_walk(coverage))

    assert templates.expand is False
    assert coverage.expand is False
    assert any(
        isinstance(control, ft.Container)
        and isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "Toggle"
        for control in template_controls
    )
    assert any(
        isinstance(control, ft.Container)
        and control.width == 28
        and control.height == 28
        for control in coverage_controls
    )
    for control in (templates, coverage):
        descendants = list(_walk(control))
        assert not any(isinstance(item, ft.ListView) for item in descendants)
        assert not any(
            isinstance(item, ft.Column)
            and item.scroll == ft.ScrollMode.AUTO
            and item.expand
            for item in descendants
        )
