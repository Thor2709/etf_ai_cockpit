from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import catalogue
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


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
    rendered = catalogue.catalogue_page(None, _state())

    assert isinstance(rendered, PageView)
    text = "\n".join(_texts(rendered))
    assert all(
        title in text
        for title in (
            "Registered datasets",
            "Instrument provenance explorer",
            "Lineage graph",
            "Lineage and schema checks",
        )
    )
    group = rendered.chrome.segment_groups[0]
    group.on_change("Snapshots")
    assert "Immutable snapshots" in "\n".join(_texts(rendered))
    assert "Traceback" not in "\n".join(_texts(rendered))


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    class EmptyCatalogue:
        datasets = ()
        snapshots = ()
        lineage = ()

        def __init__(self, _root):
            pass

        def summary(self):
            return {"status": "unavailable"}

        def validate(self):
            return {"status": "unavailable", "errors": []}

        def provenance_for(self, _instrument):
            return {"snapshot_ids": [], "dataset_ids": []}

    monkeypatch.setattr(catalogue, "DataCatalogue", EmptyCatalogue)
    rendered = catalogue.catalogue_page(
        None,
        SimpleNamespace(selected_etf=""),
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
