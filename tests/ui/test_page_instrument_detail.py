from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    if isinstance(control, PageView):
        control = control.body
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return " ".join(
        str(getattr(item, "value", "") or getattr(item, "text", "") or "")
        for item in _walk(control)
    )


def test_renders_with_sample_data() -> None:
    snapshot = build_snapshot()
    selected = snapshot.config.ui.default_etf
    page = instrument_detail_page(
        None,
        SimpleNamespace(snapshot=snapshot, selected_etf=selected),
    )
    text = _text(page)

    assert isinstance(page, PageView)
    assert page.chrome.title.startswith("Instrument Detail · ")
    for title in (
        "Identity and provenance",
        "Price history",
        "Evidence score",
        "Expected-return range",
        "Alerts & review reminders",
        "Feature drivers",
        "Crowding and attribution",
        "Alpha, beta and correlation",
        "Opportunity",
        "Peer cohort and adapter lineage",
        "Classification context",
        "ETF Structure & Documents",
        "ETF disclosure evidence",
        "ETF holdings and exposure",
        "ETF direct overlap",
        "ETF Liquidity",
        "ETF order-preview capacity meter",
        "ETF Economics",
        "Market clock and session",
        "Risk and feature evidence",
        "Factor risk",
        "Forecast evidence",
        "Model cards",
        "Backtest trust",
        "Operational evidence",
        "Evidence Score",
        "News/macro contradictions",
        "Score history",
        "Score-component metric history",
        "Point-in-time vintage history",
        "What changed since the last run",
        "Paper-trade history",
        "Decision journal",
        "LLM thesis diary",
        "News & context",
        "Event calendar",
    ):
        assert title in text
    assert "Traceback" not in text


def test_empty_data_shows_unavailable() -> None:
    snapshot = SimpleNamespace(
        config=SimpleNamespace(
            ui=SimpleNamespace(default_etf=""),
            universe=SimpleNamespace(etfs=()),
        ),
        signals=(),
    )
    page = instrument_detail_page(
        None,
        SimpleNamespace(snapshot=snapshot, selected_etf=""),
    )
    text = _text(page)

    assert "Unavailable" in text
    assert "No forecast fan" in text
    assert "Traceback" not in text
    for control in _walk(page):
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "DataTable":
            assert all(
                str(getattr(item, "value", "") or "") != "0"
                for item in _walk(control)
            )
