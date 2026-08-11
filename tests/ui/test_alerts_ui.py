from __future__ import annotations

from etf_cockpit.app.pages import dashboard, instrument_detail
from etf_cockpit.application.alerts import AlertReadback
from etf_cockpit.data.alerts import AlertRevisionConflict, AlertStore, AlertType, build_alert


def _text_values(control) -> list[str]:
    values = []
    value = getattr(control, "value", None)
    if value is not None:
        values.append(str(value))
    for child in getattr(control, "controls", []) or []:
        values.extend(_text_values(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    return values


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_dashboard_digest_and_activity_log_read_local_alerts(tmp_path, monkeypatch) -> None:
    alert = build_alert(
        AlertType.STALE_DATA,
        subject_id="VWCE",
        title="Data is stale",
        message="Review the latest local price vintage.",
        severity="warning",
        confidence="high",
        occurred_at="2026-08-01T12:00:00+00:00",
        available_at="2026-08-01T12:00:00+00:00",
        dedupe_key="ui-stale",
    )
    with AlertStore(tmp_path) as store:
        store.create(alert)
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    state = type("State", (), {"last_message": "Ready", "recent_activity": [], "current_activity": None})()
    rendered = "\n".join(_text_values(dashboard._alerts_digest(None, state)))
    history = "\n".join(_text_values(dashboard._activity_panel(state, page=None)))
    assert "Alerts & review reminders" in rendered
    assert "severity=warning" in rendered
    assert "confidence=high" in rendered
    assert "execution_allowed=false" in rendered
    assert "Alert history" in history
    assert "Data is stale" in history


def test_dashboard_dismiss_and_fixed_snooze_callbacks_use_expected_revision(tmp_path, monkeypatch) -> None:
    alert = build_alert(
        AlertType.STALE_DATA,
        subject_id="VWCE",
        title="Data is stale",
        message="Review local evidence.",
        severity="warning",
        confidence="high",
        occurred_at="2026-08-01T12:00:00+00:00",
        available_at="2026-08-01T12:00:00+00:00",
        dedupe_key="ui-callbacks",
    )
    with AlertStore(tmp_path) as store:
        record = store.create(alert)
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    calls: list[tuple[str, str, int]] = []
    monkeypatch.setattr(
        dashboard,
        "dismiss_local_alert",
        lambda _root, alert_id, *, expected_revision: calls.append(("dismiss", alert_id, expected_revision)),
    )
    snooze_until = []
    monkeypatch.setattr(
        dashboard,
        "snooze_local_alert",
        lambda _root, alert_id, until, *, expected_revision: (calls.append(("snooze", alert_id, expected_revision)), snooze_until.append(until)),
    )
    monkeypatch.setattr(dashboard, "_rebuild", lambda _page, _state: None)
    state = type("State", (), {"last_message": "Ready", "recent_activity": [], "current_activity": None})()
    controls = list(_walk(dashboard._alerts_digest(None, state)))
    buttons = {getattr(item, "key", ""): item for item in controls if getattr(item, "key", None)}
    buttons[f"alert.dismiss.{alert.alert_id}"].on_click(None)
    buttons[f"alert.snooze.{alert.alert_id}"].on_click(None)
    assert calls == [("dismiss", alert.alert_id, record.revision), ("snooze", alert.alert_id, record.revision)]
    assert snooze_until[0].tzinfo is not None
    assert state.last_message == "Alert snoozed locally for one day."
    monkeypatch.setattr(dashboard, "dismiss_local_alert", lambda *_args, **_kwargs: (_ for _ in ()).throw(AlertRevisionConflict("stale")))
    dashboard._dismiss_alert(None, state, record)
    assert state.last_message == "Alert changed elsewhere; refresh required."
    monkeypatch.setattr(dashboard, "snooze_local_alert", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")))
    dashboard._snooze_alert(None, state, record)
    assert state.last_message == "Alert snooze unavailable; manual review required."


def test_alert_ui_distinguishes_unavailable_from_healthy_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    state = type("State", (), {"last_message": "Ready", "recent_activity": [], "current_activity": None})()
    monkeypatch.setattr(dashboard, "read_local_alerts", lambda *_args, **_kwargs: AlertReadback("unavailable"))
    unavailable = "\n".join(_text_values(dashboard._alerts_digest(None, state)))
    assert "Alerts unavailable" in unavailable
    assert "manual review" in unavailable.lower()
    assert "No active local alerts" not in unavailable
    monkeypatch.setattr(dashboard, "read_local_alerts", lambda *_args, **_kwargs: AlertReadback("available"))
    empty = "\n".join(_text_values(dashboard._alerts_digest(None, state)))
    assert "No active local alerts" in empty


def test_instrument_detail_renders_unavailable_alert_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(instrument_detail, "ROOT", tmp_path)
    monkeypatch.setattr(instrument_detail, "read_local_alerts", lambda *_args, **_kwargs: AlertReadback("unavailable"))
    rendered = "\n".join(_text_values(instrument_detail._instrument_alerts_panel("VWCE")))
    assert "Alerts unavailable" in rendered
    assert "manual review" in rendered.lower()
    assert "No local alerts" not in rendered


def test_instrument_detail_alert_readback_is_scoped_and_non_executable(tmp_path, monkeypatch) -> None:
    alert = build_alert(
        AlertType.MODEL_FORECAST_FAILURE,
        subject_id="VWCE",
        title="Forecast unavailable",
        message="The optional model failed locally.",
        severity="critical",
        confidence="medium",
        occurred_at="2026-08-01T12:00:00+00:00",
        available_at="2026-08-01T12:00:00+00:00",
        dedupe_key="ui-model-failure",
    )
    with AlertStore(tmp_path) as store:
        store.create(alert)
    monkeypatch.setattr(instrument_detail, "ROOT", tmp_path)
    rendered = "\n".join(_text_values(instrument_detail._instrument_alerts_panel("VWCE")))
    assert "Alerts & review reminders" in rendered
    assert "model_forecast_failure" in rendered
    assert "severity=critical" in rendered
    assert "execution_allowed=false" in rendered
