from __future__ import annotations

import inspect

from etf_cockpit.app.pages import feature_catalogue
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS


def test_feature_catalogue_is_registered_and_exposes_safe_training_contract() -> None:
    assert PAGES["/feature-catalogue"][0] == "Feature Catalogue"
    assert any("/feature-catalogue" in routes for _, routes in WORKSPACE_GROUPS)
    source = inspect.getsource(feature_catalogue)
    for label in (
        "Feature definitions",
        "Training data preview",
        "Targets and leakage controls",
        "execution_allowed=false",
        "offline, paper and disabled live-inference",
    ):
        assert label in source
