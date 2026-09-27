from __future__ import annotations

import inspect
from datetime import date
from types import SimpleNamespace

from etf_cockpit.app.pages import errors_recovery
from etf_cockpit.app.pages.errors_recovery import errors_recovery_page
from etf_cockpit.core.errors import ErrorCategory, ErrorStore


def test_errors_recovery_page_contains_required_sections_and_safe_copy() -> None:
    source = inspect.getsource(errors_recovery)
    for label in ("Errors and recovery", "Developer detail", "Activity Log", "Recovery status", "Recovery policy", "Retry"):
        assert label in source
    assert "Technical detail is hidden outside developer mode." in source
    assert "previous clean data remains unchanged" in source or "previous clean data" in source


def test_errors_recovery_page_supports_activity_and_developer_detail() -> None:
    source = inspect.getsource(errors_recovery)
    assert "current_activity" in source
    assert "recent_activity" in source
    assert "ExpansionTile" in source
    assert "developer_mode_enabled" in source


def _text_values(control: object) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(control, "controls", ()) or ():
        values.extend(_text_values(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    title = getattr(control, "title", None)
    if title is not None:
        values.extend(_text_values(title))
    return values


def test_errors_recovery_page_renders_failure_activity_and_recovery_sections(tmp_path) -> None:
    store = ErrorStore(tmp_path / "errors.jsonl")
    retryable = store.append(action_id="refresh", category=ErrorCategory.NETWORK, user_message="Provider timed out", retryable=True)
    store.append(action_id="import", category=ErrorCategory.INVALID_INPUT, user_message="Malformed input", retryable=False)
    state = SimpleNamespace(
        error_store=store,
        snapshot=SimpleNamespace(forecasts=[{"forecast_date": date(2026, 9, 22)}], data_report=SimpleNamespace(as_of_date=date(2026, 9, 21))),
        application_api=None,
        current_activity=SimpleNamespace(label="Forecast", step="Writing", completed_units=1, total_units=2, message=""),
        recent_activity=[SimpleNamespace(started_at="2026-09-22T10:00:00Z", action_id="import", label="Import", status="failed", message="Malformed input", step="parse")],
        last_message="Ready",
    )
    rendered = errors_recovery_page(SimpleNamespace(), state)
    text = "\n".join(_text_values(rendered))
    assert retryable.error_id in text
    assert all(label in text for label in ("Recent errors", "Developer detail", "Activity Log", "Recovery status", "Recovery policy", "Provider outage"))
    assert "Malformed input" in text


def test_errors_recovery_page_shows_detail_only_in_developer_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETF_COCKPIT_DEVELOPER_MODE", "1")
    store = ErrorStore(tmp_path / "errors.jsonl")
    store.append(action_id="parse", category=ErrorCategory.PARSER_SCHEMA, user_message="Parser failed", detail="Traceback: boom", retryable=False)
    state = SimpleNamespace(error_store=store, snapshot=SimpleNamespace(), application_api=None, current_activity=None, recent_activity=[], last_message="")
    shown = "\n".join(_text_values(errors_recovery_page(SimpleNamespace(), state)))
    assert "Traceback: boom" in shown
    monkeypatch.delenv("ETF_COCKPIT_DEVELOPER_MODE")
    hidden = "\n".join(_text_values(errors_recovery_page(SimpleNamespace(), state)))
    assert "Traceback: boom" not in hidden
    assert "Technical detail is hidden outside developer mode." in hidden
