from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.data_models import data_models_page


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _page(snapshot: object) -> PageView:
    return data_models_page(None, SimpleNamespace(snapshot=snapshot))


def _text(page: PageView) -> list[str]:
    return [str(item.value) for item in _walk(page.body) if isinstance(item, ft.Text)]


def test_renders_with_sample_data() -> None:
    snapshot = SimpleNamespace(
        model_status={"reasons": True, "timesfm": False, "toto": False},
        model_inventory=(),
        prices=pd.DataFrame({"etf_id": ["ETF-A"], "date": ["2026-01-02"]}),
    )
    rendered = _page(snapshot)
    values = _text(rendered)
    assert isinstance(rendered, PageView)
    for title in (
        "Model availability",
        "Latest local price data",
        "Data coverage and model monitoring",
        "Unified plugin capability status",
        "Forecast artefacts",
        "Derived evidence artefacts",
        "Market regime",
        "Forecast calibration",
        "Strategy templates",
        "Candidate reports",
        "Dataset provenance",
        "Reference data",
        "Manual thesis and news notes",
        "Validation findings",
    ):
        assert title in values
    assert not any("Traceback" in value for value in values)


def test_empty_data_shows_unavailable() -> None:
    rendered = _page(SimpleNamespace(model_status={}, model_inventory=(), prices=pd.DataFrame()))
    values = _text(rendered)
    assert "Unavailable" in " ".join(values)
    assert not any(value.strip() == "0" for value in values)
