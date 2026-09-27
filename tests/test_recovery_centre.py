from __future__ import annotations

from types import SimpleNamespace
from datetime import date

from etf_cockpit.application.recovery_centre import RECOVERY_POLICIES, build_recovery_read_model


def test_recovery_read_model_marks_missing_publication_sources_unavailable() -> None:
    state = SimpleNamespace(snapshot=SimpleNamespace(), application_api=None)
    model = build_recovery_read_model(state)
    assert model.forecasts_last_known_good == "unavailable"
    assert model.data_last_known_good == "unavailable"
    assert model.jobs == ()
    assert all("unavailable" in reason.lower() or "no " in reason.lower() for reason in model.unavailable_reasons)


def test_recovery_read_model_uses_explicit_last_known_good_fields_only() -> None:
    state = SimpleNamespace(
        snapshot=SimpleNamespace(last_successful_forecast_at="2026-09-27T10:00:00Z", last_successful_data_at="2026-09-27T09:00:00Z"),
        application_api=None,
    )
    model = build_recovery_read_model(state)
    assert model.forecasts_last_known_good == "2026-09-27T10:00:00Z"
    assert model.data_last_known_good == "2026-09-27T09:00:00Z"


def test_recovery_read_model_uses_snapshot_forecast_and_data_as_of_values() -> None:
    state = SimpleNamespace(
        snapshot=SimpleNamespace(
            forecasts=[{"forecast_date": date(2026, 9, 22)}, {"forecast_date": date(2026, 9, 20)}],
            data_report=SimpleNamespace(as_of_date=date(2026, 9, 21)),
        ),
        application_api=None,
    )
    model = build_recovery_read_model(state)
    assert model.forecasts_last_known_good == "2026-09-22"
    assert model.data_last_known_good == "2026-09-21"


def test_recovery_policy_is_static_and_covers_required_failures() -> None:
    assert {card.title for card in RECOVERY_POLICIES} == {
        "Provider outage", "Failed import", "Failed model or forecast run", "Corrupt local store", "Interrupted job",
    }
    assert all(card.symptom and card.guarantee and card.steps for card in RECOVERY_POLICIES)


def test_recovery_read_model_reports_unreadable_job_store_as_unavailable() -> None:
    api = SimpleNamespace(
        jobs_store_status=lambda: (False, "OSError: the local job store could not be read"),
        get_jobs=lambda: SimpleNamespace(items=()),
    )
    model = build_recovery_read_model(SimpleNamespace(snapshot=SimpleNamespace(), application_api=api))
    assert model.jobs == ()
    assert any("job store is unavailable" in reason for reason in model.unavailable_reasons)


def test_recovery_read_model_lists_active_jobs_from_readable_store() -> None:
    api = SimpleNamespace(
        jobs_store_status=lambda: (True, None),
        get_jobs=lambda: SimpleNamespace(items=(SimpleNamespace(label="Refresh", status="running"), SimpleNamespace(label="Old", status="completed"))),
    )
    model = build_recovery_read_model(SimpleNamespace(snapshot=SimpleNamespace(), application_api=api))
    assert model.jobs == ("Refresh: running",)
