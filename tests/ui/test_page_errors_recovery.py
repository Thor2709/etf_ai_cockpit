from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.errors_recovery import errors_recovery_page
from etf_cockpit.core.errors import ErrorCategory, ErrorStore


def _texts(control: object) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(control, "controls", ()) or ():
        values.extend(_texts(child))
    body = getattr(control, "body", None)
    if body is not None:
        values.extend(_texts(body))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_texts(content))
    return values


def _state(tmp_path, *, with_error: bool):
    store = ErrorStore(tmp_path / "errors.jsonl")
    if with_error:
        store.append(action_id="refresh", category=ErrorCategory.NETWORK, user_message="Provider timed out", retryable=True)
    return SimpleNamespace(
        error_store=store,
        snapshot=SimpleNamespace(forecasts=[{"forecast_date": date(2026, 9, 22)}], data_report=SimpleNamespace(as_of_date=date(2026, 9, 21))),
        application_api=None,
        current_activity=None,
        recent_activity=[],
        last_message="",
    )


def test_renders_with_sample_data(tmp_path) -> None:
    result = errors_recovery_page(SimpleNamespace(), _state(tmp_path, with_error=True))
    text = "\n".join(_texts(result))
    assert isinstance(result, PageView)
    assert all(title in text for title in ("Recent errors", "Recovery status", "Recovery policy", "Activity log"))
    assert "Traceback" not in text


def test_empty_data_shows_unavailable(tmp_path) -> None:
    result = errors_recovery_page(SimpleNamespace(), _state(tmp_path, with_error=False))
    text = _texts(result)
    assert isinstance(result, PageView)
    assert any("Unavailable" in value or "No controlled errors" in value or "No activity" in value for value in text)
    assert "0" not in text
