from __future__ import annotations

from functools import lru_cache

import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages import _l2_common, filings
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
    rendered = filings.filings_page(None, _state())

    assert isinstance(rendered, PageView)
    text = "\n".join(_texts(rendered))
    assert all(
        title in text
        for title in (
            "Official filing import",
            "Filings inventory",
            "Jurisdiction coverage",
            "Filing evidence",
        )
    )
    assert "Traceback" not in text


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(_l2_common, "read_frame", lambda _path: pd.DataFrame())
    rendered = filings.filings_page(None, _state())

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
