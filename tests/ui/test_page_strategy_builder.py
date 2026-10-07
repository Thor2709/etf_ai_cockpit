from __future__ import annotations

from types import SimpleNamespace

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
