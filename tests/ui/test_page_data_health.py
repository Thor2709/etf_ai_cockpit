from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import data_health
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot
from etf_cockpit.application.ui_facade import DataHealthReport


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _state() -> AppState:
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


def _texts(page_view: PageView) -> list[str]:
    return [
        str(getattr(control, "value", "") or getattr(control, "text", ""))
        for control in _walk(page_view.body)
    ]


def test_renders_with_sample_data() -> None:
    page = SimpleNamespace(route="/data-health", update=lambda: None)
    rendered = data_health.data_health_page(page, _state())

    assert isinstance(rendered, PageView)
    titles = {
        control.data.get("title")
        for control in _walk(rendered.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "GlassCard"
    }
    assert {
        "Dataset inventory",
        "Datasets by status",
        "Freshness by dataset",
        "Anomaly rules and quarantine",
        "Bulk source cache",
    } <= titles
    assert all("Traceback" not in value for value in _texts(rendered))


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        data_health,
        "build_data_health",
        lambda *_args, **_kwargs: DataHealthReport("", "", ()),
    )
    monkeypatch.setattr(data_health, "bulk_cache_health", lambda _root: {})
    monkeypatch.setattr(
        data_health.AnomalyLedger,
        "summary",
        lambda *_args, **_kwargs: {
            "status": "unavailable",
            "reason": "No anomaly data is available.",
        },
    )
    rendered = data_health.data_health_page(
        SimpleNamespace(route="/data-health", update=lambda: None),
        _state(),
    )

    assert isinstance(rendered, PageView)
    texts = _texts(rendered)
    assert any("Unavailable" in value or "No data" in value for value in texts)
    table_cells = [
        str(getattr(control, "value", ""))
        for parent in _walk(rendered.body)
        if isinstance(getattr(parent, "data", None), dict)
        and parent.data.get("kit") == "DataTable"
        for control in _walk(parent)
    ]
    assert "0" not in table_cells
    assert all("Traceback" not in value for value in texts)
