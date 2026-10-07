from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.stress_lab import stress_lab_page
from etf_cockpit.application.stress_lab import StressLabFacade
from etf_cockpit.core.config import load_config


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    if getattr(control, "content", None) is not None:
        yield from _walk(control.content)


def _state(*, empty: bool = False):
    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=(
            pd.DataFrame(columns=["etf_id", "current_weight", "asset_class"])
            if empty
            else pd.DataFrame({"etf_id": ["AAA"], "current_weight": [1.0], "asset_class": ["equity"]})
        ),
        prices=pd.DataFrame(),
        latest_features=pd.DataFrame(),
    )
    return SimpleNamespace(snapshot=snapshot)


def _text(view) -> str:
    return "\n".join(str(item.value) for item in _walk(view.body) if isinstance(item, ft.Text))


def test_renders_with_sample_data(monkeypatch) -> None:
    monkeypatch.setattr(StressLabFacade, "list_saved", lambda _self: ())
    view = stress_lab_page(None, _state())
    content = _text(view)
    assert isinstance(view, PageView)
    assert all(
        title in content
        for title in (
            "Scenario assumptions",
            "Scenario result",
            "Instrument contributions",
            "Reverse stress",
            "Saved local scenarios",
        )
    )
    assert "Traceback" not in content


def test_empty_data_shows_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(StressLabFacade, "list_saved", lambda _self: ())
    view = stress_lab_page(None, _state(empty=True))
    content = _text(view)
    assert isinstance(view, PageView)
    assert "Unavailable" in content or "No scenario run yet" in content
    for control in _walk(view.body):
        data = getattr(control, "data", None)
        if isinstance(data, dict) and data.get("kit") == "DataTable":
            assert all(str(value) != "0" for row in data.get("rows", ()) for value in row.values())
