from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import macro_factors
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


@lru_cache(maxsize=1)
def _state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _walk(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None and content is not control:
        yield from _walk(content)


def _texts(view: PageView) -> list[str]:
    return [
        str(getattr(item, "value", "") or getattr(item, "text", ""))
        for item in _walk(view.body)
    ]


def test_renders_with_sample_data() -> None:
    rendered = macro_factors.macro_factors_page(None, _state())

    assert isinstance(rendered, PageView)
    text = "\r\n".join(_texts(rendered))
    assert all(
        title in text
        for title in (
            "Regime and proxy context",
            "Macro series",
            "Risk-free curves and lawful benchmarks",
            "Latest local observations",
            "Rates and inflation",
            "Scenario-linked macro evidence",
        )
    )
    assert "Traceback" not in text
    rendered.chrome.segment_groups[0].on_change("Scenarios")
    rendered.chrome.segment_groups[1].on_change("5Y")
    assert "View: Scenarios · Horizon: 5Y" in "\r\n".join(_texts(rendered))


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        macro_factors,
        "build_macro_context_binding",
        lambda *_args, **_kwargs: SimpleNamespace(
            summary={"status": "unavailable", "reason": "No local macro snapshot."},
            observations=(),
            curve_coverage={"status": "unavailable"},
            context={
                "regime": {},
                "breadth": {},
                "volatility": {},
                "inflation_rates": {"rows": [], "reason": "No local rates series."},
                "proxy_rows": [],
            },
            scenario={"rows": [], "limitations": []},
            error="",
            decision_time=None,
        ),
    )
    rendered = macro_factors.macro_factors_page(None, _state())

    assert isinstance(rendered, PageView)
    texts = _texts(rendered)
    assert any("Unavailable" in value or "No data" in value for value in texts)
    cells = [
        str(getattr(item, "value", ""))
        for parent in _walk(rendered.body)
        if isinstance(getattr(parent, "data", None), dict)
        and parent.data.get("kit") == "DataTable"
        for item in _walk(parent)
    ]
    assert "0" not in cells
    assert all("Traceback" not in value for value in texts)
