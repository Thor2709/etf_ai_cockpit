from __future__ import annotations

import inspect
from types import SimpleNamespace

import flet as ft
import pytest

from etf_cockpit.app.pages import training_centre
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS


def _walk(control: object):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def test_training_centre_route_and_acceptance_surface_are_registered() -> None:
    assert PAGES["/training-centre"][0] == "Training Centre"
    assert any("/training-centre" in routes for _, routes in WORKSPACE_GROUPS)
    assert hasattr(training_centre, "render_optimisation_history")
    source = inspect.getsource(training_centre)
    for label in ("Run list", "Live metrics", "Model comparison", "Final reports and replay", "Synthetic Scenario Builder", "Validation Designer", "Bounded optimisation", "Retain trial evidence", "return_series", "parameters", "validation_scores", "discarded_reason", "fold boundaries", "data_hash", "code_hash", "researcher_decision", "promotion=", "retained_text.value", "deflated_sharpe", "probability_of_backtest_overfitting", "false_discovery_rate", "final_test_used_for_selection", "synthetic=true", "promotion_eligible=false", "execution_allowed=false", "approval"):
        assert label in source


def test_synthetic_scenario_button_regenerates_and_shows_controlled_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[str] = []
    rendered = training_centre._synthetic_panel(SimpleNamespace(update=lambda: updates.append("updated")))
    button = next(item for item in _walk(rendered) if getattr(item, "key", None) == "training-centre.synthetic-scenario")
    assert button.on_click.__name__ == "generate_synthetic_scenario"

    button.on_click(SimpleNamespace(control=button))
    assert updates == ["updated"]
    assert any(isinstance(item, ft.Text) and "price rows" in str(item.value) for item in _walk(rendered))

    def fail_generation(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("controlled synthetic failure")

    monkeypatch.setattr(training_centre.SyntheticScenarioGenerator, "generate", fail_generation)
    button.on_click(SimpleNamespace(control=button))
    visible = " ".join(str(item.value) for item in _walk(rendered) if isinstance(item, ft.Text))
    assert updates == ["updated", "updated"]
    assert "Synthetic scenario unavailable" in visible
    assert "Controlled failure: RuntimeError: controlled synthetic failure" in visible
