from __future__ import annotations

import inspect

from etf_cockpit.app.pages import forecast_lab
from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS


def test_forecast_lab_workspace_is_registered_and_safe() -> None:
    assert PAGES["/forecasts"][0] == "Forecast Lab"
    assert any("/forecasts" in routes for _, routes in WORKSPACE_GROUPS)
    source = inspect.getsource(forecast_lab)
    for label in (
        "Experiment runs",
        "Model comparison",
        "Model cards",
        "Walk-forward protocol",
        "shadow_only",
        "execution_allowed=false",
        "Run forecasting models",
    ):
        assert label in source
