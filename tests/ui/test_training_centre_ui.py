from __future__ import annotations

import inspect

from etf_cockpit.app.pages import training_centre
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS


def test_training_centre_route_and_acceptance_surface_are_registered() -> None:
    assert PAGES["/training-centre"][0] == "Training Centre"
    assert any("/training-centre" in routes for _, routes in WORKSPACE_GROUPS)
    source = inspect.getsource(training_centre)
    for label in ("Run list", "Live metrics", "Model comparison", "Final reports and replay", "Synthetic Scenario Builder", "Validation Designer", "final_test_used_for_selection", "synthetic=true", "promotion_eligible=false", "execution_allowed=false", "approval"):
        assert label in source
