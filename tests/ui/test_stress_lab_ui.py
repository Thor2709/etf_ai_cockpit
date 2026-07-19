from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages import stress_lab
from etf_cockpit.app.router import PAGES, workspace_for_route
from etf_cockpit.core.config import load_config


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(root) -> str:
    return "\n".join(str(item.value) for item in _walk(root) if isinstance(item, ft.Text))


def _state():
    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame({"etf_id": ["AAA"], "current_weight": [1.0], "asset_class": ["equity"]}),
        prices=pd.DataFrame(),
        latest_features=pd.DataFrame(),
    )
    return SimpleNamespace(snapshot=snapshot)


def test_stress_lab_exposes_stable_controls_route_and_disabled_authority() -> None:
    root = stress_lab.stress_lab_page(None, _state())
    keys = {str(control.key) for control in _walk(root) if getattr(control, "key", None)}

    assert {"stress-lab.scenario-id", "stress-lab.run", "stress-lab.save", "stress-lab.load", "stress-lab.reverse"} <= keys
    assert PAGES["/stress-lab"] == ("Stress Lab", stress_lab.stress_lab_page)
    assert workspace_for_route("/stress-lab") == "Portfolio"
    assert "execution_allowed=false" in _text(root)
    assert "Probability" in _text(root)
    assert "Instrument contributions" in _text(root)
    assert "residual" in _text(root)
