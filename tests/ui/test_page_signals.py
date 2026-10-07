from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import signals
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
    page = signals.signals_page(
        None,
        SimpleNamespace(snapshot=build_snapshot()),
    )
    text = _text(page)

    assert isinstance(page, PageView)
    assert page.chrome.title == "Scores"
    assert len(page.chrome.segment_groups) == 2
    for title in (
        "All stock and ETF scores",
        "Score details",
        "Score vs. evidence confidence",
        "Operational evidence",
    ):
        assert title in text
    assert "STRONG EVIDENCE" in text
    assert "POSITIVE EVIDENCE" in text
    assert "WATCH/MIXED" in text
    assert "MANUAL REVIEW" in text
    assert "Traceback" not in text


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(signals, "build_simple_instrument_scores", lambda *args, **kwargs: [])
    snapshot = SimpleNamespace(
        config=SimpleNamespace(),
        signals=(),
        forecasts=pd.DataFrame(),
        prices=pd.DataFrame(),
        benchmark_reference_decision_time=None,
    )
    page = signals.signals_page(None, SimpleNamespace(snapshot=snapshot))
    text = _text(page)

    assert "Unavailable" in text
    assert "No canonical score rows are available" in text
    assert "Traceback" not in text
    for control in _walk(page):
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "DataTable":
            assert all(
                str(getattr(item, "value", "") or "") != "0"
                for item in _walk(control)
            )
