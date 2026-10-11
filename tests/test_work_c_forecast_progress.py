from types import SimpleNamespace

from etf_cockpit.app.pages import forecast_lab
from tests.test_work_c_backtest_menus import walk


def test_forecast_unknown_progress_and_cancelled_status_are_renderable():
    activity = SimpleNamespace(label=forecast_lab.FORECAST_RUN_LABEL, status="running", step="Starting",
                               completed_units=0, total_units=None, message="Cancelled by user")
    state = SimpleNamespace(current_activity=activity, recent_activity=[activity])
    for total in (None, 0, 10):
        activity.total_units = total
        text = [getattr(c, "value", None) for c in walk(forecast_lab._run_status(state))]
        assert "Forecast run in progress: " + activity.label in text
        assert ("—" if not total else "0") in text
    activity.status = "cancelled"
    assert "cancelled" in forecast_lab._run_status(state).value
    assert "in progress" not in forecast_lab._run_status(state).value

