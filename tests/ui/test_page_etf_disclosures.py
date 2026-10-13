from __future__ import annotations

from functools import lru_cache

import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import _l2_common, etf_disclosures
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
    rendered = etf_disclosures.etf_disclosures_page(None, _state())

    assert isinstance(rendered, PageView)
    text = "\r\n".join(_texts(rendered))
    assert all(
        title in text
        for title in (
            "ETF disclosure inventory",
            "ETF disclosure import",
            "Coverage by document type",
            "SFDR disclosure",
            "Disclosure evidence",
        )
    )
    assert "Traceback" not in text
    assert rendered.chrome.subtitle == "Factsheets, holdings, KIDs, SFDR, reports and methodology · advisory only"
    group = rendered.chrome.segment_groups[0]
    assert callable(group.on_change)
    group.on_change("Holdings")
    assert "Holdings import controls" in "\r\n".join(_texts(rendered))


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(_l2_common, "read_frame", lambda _path: pd.DataFrame())
    rendered = etf_disclosures.etf_disclosures_page(None, _state())

    assert isinstance(rendered, PageView)
    texts = _texts(rendered)
    assert any("Unavailable" in value or "No rows" in value for value in texts)
    cells = [
        str(getattr(item, "value", ""))
        for parent in _walk(rendered.body)
        if isinstance(getattr(parent, "data", None), dict)
        and parent.data.get("kit") == "DataTable"
        for item in _walk(parent)
    ]
    assert "0" not in cells
    assert all("Traceback" not in value for value in texts)


def test_disclosure_import_layout_is_bounded() -> None:
    rendered = etf_disclosures.etf_disclosures_page(None, _state())
    importer = next(
        control for control in _walk(rendered.body)
        if isinstance(getattr(control, "data", None), dict)
        and control.data.get("kit") == "GlassCard"
        and control.data.get("title") == "ETF disclosure import"
    )
    descendants = list(_walk(importer))
    ids = [id(control) for control in descendants]
    assert len(ids) == len(set(ids))
    assert any(control.__class__.__name__ == "TextField" for control in descendants)
    assert not getattr(importer, "expand", False)
    assert not any(control.__class__.__name__ == "ListView" for control in descendants)
