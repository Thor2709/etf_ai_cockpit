from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages.stress_lab import stress_lab_page
from etf_cockpit.core.config import load_config


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    if getattr(control, "content", None) is not None:
        yield from _walk(control.content)


def _state():
    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame({"etf_id": ["AAA"], "current_weight": [1.0], "asset_class": ["equity"]}),
        prices=pd.DataFrame(),
        latest_features=pd.DataFrame(),
    )
    return SimpleNamespace(snapshot=snapshot)


def _text(view) -> str:
    return "\n".join(str(item.value) for item in _walk(view.body) if isinstance(item, ft.Text))


def test_renders_with_sample_data() -> None:
    view = stress_lab_page(None, _state())
    content = _text(view)
    assert view.__class__.__name__ == "PageView"
    assert all(title in content for title in ("Scenario assumptions", "Scenario result", "Instrument contributions", "Reverse stress", "Saved local scenarios"))
    assert "Traceback" not in content


def test_empty_data_shows_unavailable() -> None:
    view = stress_lab_page(None, _state())
    content = _text(view)
    assert "Unavailable" in content or "No scenario run yet" in content
    assert all(line != "0" for line in content.splitlines())
