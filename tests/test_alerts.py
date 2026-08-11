from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from etf_cockpit.data.alerts import (
    ALERT_ENTITY_TYPE,
    AlertBlockPolicy,
    AlertConfidence,
    AlertRevisionConflict,
    AlertSeverity,
    AlertStatus,
    AlertStore,
    AlertType,
    IncidentDomain,
    build_alert,
    evaluate_alerts_as_of,
)
from etf_cockpit.application.alerts import (
    AlertTriggerObservation,
    generate_local_alert,
    read_local_alerts,
)
from etf_cockpit.data.local_storage import TransactionalStore


NOW = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


def _alert(alert_type: AlertType, *, subject_id: str = "VWCE", suffix: str = "1", **kwargs):
    return build_alert(
        alert_type,
        subject_id=subject_id,
        title=f"{alert_type.value} alert",
        message=kwargs.pop("message", "Review local evidence."),
        severity=kwargs.pop("severity", AlertSeverity.WARNING),
        confidence=kwargs.pop("confidence", AlertConfidence.HIGH),
        occurred_at=kwargs.pop("occurred_at", NOW),
        available_at=kwargs.pop("available_at", NOW),
        dedupe_key=f"{alert_type.value}:{subject_id}:{suffix}",
        **kwargs,
    )


@pytest.mark.parametrize(
    ("alert_type", "domain"),
    [
        (AlertType.MATERIAL_SCORE_CHANGE, IncidentDomain.GENERAL),
        (AlertType.RANK_CHANGE, IncidentDomain.GENERAL),
        (AlertType.NEWS_CONFLICT, IncidentDomain.GENERAL),
        (AlertType.STALE_DATA, IncidentDomain.GENERAL),
        (AlertType.MODEL_FORECAST_FAILURE, IncidentDomain.MODEL),
        (AlertType.REVIEW_DATE_ARRIVED, IncidentDomain.GENERAL),
        (AlertType.RISK_LIMIT_BREACHED, IncidentDomain.PORTFOLIO),
        (AlertType.TARGET_DRIFT_EXCEEDED, IncidentDomain.PORTFOLIO),
    ],
)
def test_all_accepted_alert_types_are_typed_and_non_executable(alert_type, domain) -> None:
    alert = _alert(alert_type)
    assert alert.alert_type is alert_type
    assert alert.incident_domain is domain
    assert alert.severity is AlertSeverity.WARNING
    assert alert.confidence is AlertConfidence.HIGH
    assert alert.execution_allowed is False
    assert alert.is_blocked() is False


def test_strict_malformed_input_is_rejected() -> None:
    alert = _alert(AlertType.STALE_DATA)
    payload = alert.to_dict()
    with pytest.raises(ValueError, match="unknown alert fields"):
        alert.from_dict({**payload, "unexpected": True})
    with pytest.raises(ValueError, match="missing alert fields"):
        alert.from_dict({key: value for key, value in payload.items() if key != "confidence"})
    with pytest.raises(ValueError, match="timezone"):
        build_alert(
            AlertType.STALE_DATA,
            subject_id="VWCE",
            title="Bad",
            message="Bad",
            severity="info",
            confidence="low",
            occurred_at="2026-08-01T12:00:00",
            available_at="2026-08-01T12:00:00+00:00",
            dedupe_key="bad-timezone",
        )
    with pytest.raises(ValueError, match="execution_allowed"):
        alert.from_dict({**payload, "execution_allowed": True})
    with pytest.raises(ValueError, match="incident domain"):
        build_alert(
            AlertType.MODEL_FORECAST_FAILURE,
            subject_id="VWCE",
            title="Bad domain",
            message="Bad domain",
            severity="warning",
            confidence="medium",
            occurred_at=NOW,
            available_at=NOW,
            dedupe_key="bad-domain",
            incident_domain=IncidentDomain.ORDER,
        )


def test_deterministic_dedupe_survives_reopen(tmp_path) -> None:
    alert = _alert(AlertType.RANK_CHANGE, suffix="same-event")
    with AlertStore(tmp_path) as store:
        first = store.create(alert)
        duplicate = store.create(_alert(AlertType.RANK_CHANGE, suffix="same-event", message="Different wording"))
        assert duplicate.alert_id == first.alert_id
        assert duplicate.revision == first.revision == 1
        assert len(store.list()) == 1
    with AlertStore(tmp_path) as reopened:
        assert reopened.get(alert.alert_id).alert.to_dict() == first.alert.to_dict()


def test_snooze_dismiss_and_expiry_are_durable(tmp_path) -> None:
    clock = [NOW]
    expiring = _alert(AlertType.REVIEW_DATE_ARRIVED, expires_at=NOW.replace(hour=14))
    snoozed = _alert(AlertType.STALE_DATA, subject_id="EUNL", suffix="snooze")
    with AlertStore(tmp_path, clock=lambda: clock[0]) as store:
        created_expiring = store.create(expiring)
        created_snoozed = store.create(snoozed)
        snoozed_record = store.snooze(
            snoozed.alert_id,
            NOW.replace(hour=13),
            expected_revision=created_snoozed.revision,
        )
        assert snoozed_record.status is AlertStatus.SNOOZED
        dismissed = store.dismiss(expiring.alert_id, expected_revision=created_expiring.revision)
        assert dismissed.status is AlertStatus.DISMISSED
    with AlertStore(tmp_path, clock=lambda: clock[0]) as reopened:
        assert reopened.get(snoozed.alert_id).status is AlertStatus.SNOOZED
        assert reopened.get(expiring.alert_id).status is AlertStatus.DISMISSED
        expiring2 = _alert(AlertType.REVIEW_DATE_ARRIVED, subject_id="EUNL", suffix="expiry", expires_at=NOW.replace(hour=14))
        reopened.create(expiring2)
        clock[0] = NOW.replace(hour=15)
        assert reopened.get(expiring2.alert_id).status is AlertStatus.EXPIRED
    with AlertStore(tmp_path, clock=lambda: clock[0]) as final_store:
        assert final_store.get(expiring2.alert_id).status is AlertStatus.EXPIRED


def test_stale_revision_is_rejected(tmp_path) -> None:
    alert = _alert(AlertType.RISK_LIMIT_BREACHED)
    with AlertStore(tmp_path, clock=lambda: NOW) as first, AlertStore(tmp_path, clock=lambda: NOW) as second:
        created = first.create(alert)
        second.create(alert)
        first.snooze(alert.alert_id, NOW.replace(hour=13), expected_revision=created.revision)
        with pytest.raises(AlertRevisionConflict):
            second.dismiss(alert.alert_id, expected_revision=created.revision)


def test_only_explicit_policy_can_block() -> None:
    alert = _alert(AlertType.RISK_LIMIT_BREACHED, severity=AlertSeverity.CRITICAL)
    assert alert.is_blocked() is False
    policy = AlertBlockPolicy(policy_id="portfolio-risk-v1", alert_types=frozenset({AlertType.RISK_LIMIT_BREACHED}))
    assert alert.is_blocked(policy) is True
    assert _alert(AlertType.TARGET_DRIFT_EXCEEDED).is_blocked(policy) is False


def test_historical_evaluation_excludes_future_available_evidence() -> None:
    available = _alert(AlertType.MATERIAL_SCORE_CHANGE, suffix="available", available_at=NOW.replace(hour=13))
    future = _alert(AlertType.RANK_CHANGE, suffix="future", available_at=NOW.replace(hour=14))
    assert [item.alert_type for item in evaluate_alerts_as_of([future, available], NOW.replace(hour=13, minute=30))] == [AlertType.MATERIAL_SCORE_CHANGE]
    assert evaluate_alerts_as_of([future], NOW.replace(hour=13)) == ()


@pytest.mark.parametrize(
    ("alert_type", "trigger_value"),
    [
        (AlertType.MATERIAL_SCORE_CHANGE, 1.25),
        (AlertType.RANK_CHANGE, 5),
        (AlertType.NEWS_CONFLICT, True),
        (AlertType.STALE_DATA, 2.0),
        (AlertType.MODEL_FORECAST_FAILURE, True),
        (AlertType.REVIEW_DATE_ARRIVED, NOW.date()),
        (AlertType.RISK_LIMIT_BREACHED, 1.0),
        (AlertType.TARGET_DRIFT_EXCEEDED, 0.05),
    ],
)
def test_typed_trigger_generation_persists_each_accepted_alert(tmp_path, alert_type, trigger_value) -> None:
    observation = AlertTriggerObservation(
        alert_type=alert_type,
        subject_id="VWCE",
        occurred_at=NOW,
        available_at=NOW,
        dedupe_key=f"generated:{alert_type.value}",
        trigger_value=trigger_value,
        evidence={"source_revision": "source-1"},
    )
    record = generate_local_alert(tmp_path, observation)
    assert record is not None
    assert record.alert.alert_type is alert_type
    assert record.alert.evidence["generation"] == "issue-0033-local-thresholds-v1"
    assert record.alert.evidence["source_revision"] == "source-1"
    with AlertStore(tmp_path) as store:
        assert store.get(record.alert_id).revision == 1


def test_trigger_observation_rejects_wrong_typed_value_and_threshold_is_explicit() -> None:
    with pytest.raises(TypeError, match="integer trigger_value"):
        AlertTriggerObservation(
            alert_type=AlertType.RANK_CHANGE,
            subject_id="VWCE",
            occurred_at=NOW,
            available_at=NOW,
            dedupe_key="wrong-rank-type",
            trigger_value=True,
        )
    below = AlertTriggerObservation(
        alert_type=AlertType.STALE_DATA,
        subject_id="VWCE",
        occurred_at=NOW,
        available_at=NOW,
        dedupe_key="below-threshold",
        trigger_value=1.9,
    )
    assert generate_local_alert(Path("."), below) is None


def test_order_incident_rule_is_explicit_and_non_blocking_by_default(tmp_path) -> None:
    observation = AlertTriggerObservation(
        alert_type=AlertType.RISK_LIMIT_BREACHED,
        subject_id="order-preview-1",
        occurred_at=NOW,
        available_at=NOW,
        dedupe_key="order-risk-limit",
        trigger_value=1.1,
        incident_domain=IncidentDomain.ORDER,
    )
    record = generate_local_alert(tmp_path, observation)
    assert record is not None
    assert record.alert.incident_domain is IncidentDomain.ORDER
    assert record.alert.is_blocked() is False

    invalid = AlertTriggerObservation(
        alert_type=AlertType.TARGET_DRIFT_EXCEEDED,
        subject_id="order-preview-1",
        occurred_at=NOW,
        available_at=NOW,
        dedupe_key="invalid-order-drift",
        trigger_value=0.1,
        incident_domain=IncidentDomain.ORDER,
    )
    with pytest.raises(ValueError, match="incident domain"):
        generate_local_alert(tmp_path, invalid)


def test_snooze_transition_is_reconstructible_before_during_and_after_cutoff(tmp_path) -> None:
    alert = _alert(AlertType.STALE_DATA, suffix="replay")
    clock = [NOW.replace(hour=13)]
    with AlertStore(tmp_path, clock=lambda: clock[0]) as store:
        created = store.create(alert)
        snoozed = store.snooze(alert.alert_id, NOW.replace(hour=15), expected_revision=created.revision)
        assert evaluate_alerts_as_of([snoozed.alert], NOW.replace(hour=12, minute=30))[0].status is AlertStatus.ACTIVE
        assert evaluate_alerts_as_of([snoozed.alert], NOW.replace(hour=14))[0].status is AlertStatus.SNOOZED
        assert evaluate_alerts_as_of([snoozed.alert], NOW.replace(hour=16))[0].status is AlertStatus.ACTIVE
        clock[0] = NOW.replace(hour=14)
        dismissed = store.dismiss(alert.alert_id, expected_revision=snoozed.revision)
        assert evaluate_alerts_as_of([dismissed.alert], NOW.replace(hour=13, minute=30))[0].status is AlertStatus.SNOOZED
        assert evaluate_alerts_as_of([dismissed.alert], NOW.replace(hour=16))[0].status is AlertStatus.DISMISSED


def test_default_list_excludes_snoozed_until_cas_reactivation(tmp_path) -> None:
    clock = [NOW]
    alert = _alert(AlertType.RANK_CHANGE, suffix="list-status")
    with AlertStore(tmp_path, clock=lambda: clock[0]) as store:
        created = store.create(alert)
        store.snooze(alert.alert_id, NOW.replace(hour=13), expected_revision=created.revision)
        assert store.list() == ()
        assert store.list(include_inactive=True)[0].status is AlertStatus.SNOOZED
        clock[0] = NOW.replace(hour=14)
        assert store.list()[0].status is AlertStatus.ACTIVE


def test_block_policy_never_blocks_non_active_statuses() -> None:
    policy = AlertBlockPolicy(policy_id="risk-only", alert_types=frozenset({AlertType.RISK_LIMIT_BREACHED}))
    alert = _alert(AlertType.RISK_LIMIT_BREACHED)
    assert alert.is_blocked(policy)
    snoozed = replace(alert, status=AlertStatus.SNOOZED, snoozed_at=NOW, snoozed_until=NOW.replace(hour=13))
    dismissed = replace(alert, status=AlertStatus.DISMISSED, dismissed_at=NOW)
    expired = replace(alert, status=AlertStatus.EXPIRED)
    assert not snoozed.is_blocked(policy)
    assert not dismissed.is_blocked(policy)
    assert not expired.is_blocked(policy)


def test_repeated_snooze_intervals_are_preserved_for_point_in_time_replay(tmp_path) -> None:
    alert = _alert(AlertType.STALE_DATA, suffix="repeated-snooze")
    clock = [NOW.replace(hour=13)]
    with AlertStore(tmp_path, clock=lambda: clock[0]) as store:
        created = store.create(alert)
        store.snooze(
            alert.alert_id,
            NOW.replace(hour=14),
            expected_revision=created.revision,
        )
        clock[0] = NOW.replace(hour=15)
        reactivated = store.get(alert.alert_id)
        assert reactivated.status is AlertStatus.ACTIVE
        clock[0] = NOW.replace(hour=16)
        second = store.snooze(
            alert.alert_id,
            NOW.replace(hour=18),
            expected_revision=reactivated.revision,
        )

        assert second.revision == 4
        assert len(second.alert.snooze_history) == 1
        assert evaluate_alerts_as_of([second.alert], NOW.replace(hour=13, minute=30))[0].status is AlertStatus.SNOOZED
        assert evaluate_alerts_as_of([second.alert], NOW.replace(hour=15))[0].status is AlertStatus.ACTIVE
        assert evaluate_alerts_as_of([second.alert], NOW.replace(hour=17))[0].status is AlertStatus.SNOOZED
        assert evaluate_alerts_as_of([second.alert], NOW.replace(hour=19))[0].status is AlertStatus.ACTIVE

    with AlertStore(tmp_path, clock=lambda: NOW.replace(hour=17)) as reopened:
        replayed = reopened.get(alert.alert_id)
        assert len(replayed.alert.snooze_history) == 1
        assert evaluate_alerts_as_of([replayed.alert], NOW.replace(hour=13, minute=30))[0].status is AlertStatus.SNOOZED


def test_current_list_and_readback_exclude_future_available_alerts(tmp_path) -> None:
    clock = [NOW.replace(hour=13)]
    future = _alert(
        AlertType.RANK_CHANGE,
        suffix="future-current",
        available_at=NOW.replace(hour=14),
    )
    with AlertStore(tmp_path, clock=lambda: clock[0]) as store:
        store.create(future)
        with pytest.raises(KeyError, match="not yet available"):
            store.get(future.alert_id)
        assert store.list() == ()
        assert store.list(include_inactive=True) == ()
        clock[0] = NOW.replace(hour=15)
        assert store.list()[0].alert_id == future.alert_id

    readback_root = tmp_path / "readback"
    future_readback = _alert(
        AlertType.RANK_CHANGE,
        suffix="future-readback",
        occurred_at="2099-01-01T00:00:00+00:00",
        available_at="2099-01-01T01:00:00+00:00",
    )
    with AlertStore(readback_root) as store:
        store.create(future_readback)
    readback = read_local_alerts(readback_root)
    assert readback.status == "available"
    assert readback.records == ()


def test_expiry_precedes_ended_snooze_in_one_read(tmp_path) -> None:
    clock = [NOW.replace(hour=13)]
    alert = _alert(
        AlertType.REVIEW_DATE_ARRIVED,
        suffix="expiry-before-reactivation",
        expires_at=NOW.replace(hour=14),
    )
    with AlertStore(tmp_path, clock=lambda: clock[0]) as store:
        created = store.create(alert)
        snoozed = store.snooze(
            alert.alert_id,
            NOW.replace(hour=13, minute=30),
            expected_revision=created.revision,
        )
        clock[0] = NOW.replace(hour=15)
        expired = store.get(alert.alert_id)
        assert expired.status is AlertStatus.EXPIRED
        assert expired.revision == snoozed.revision + 1
        assert store.get(alert.alert_id).revision == expired.revision


@pytest.mark.parametrize(
    "changes",
    [
        {
            "status": "snoozed",
            "snoozed_at": "2026-08-01T13:00:00+00:00",
            "snoozed_until": "2026-08-01T13:00:00+00:00",
        },
        {
            "status": "snoozed",
            "snoozed_at": "2026-08-01T11:00:00+00:00",
            "snoozed_until": "2026-08-01T13:00:00+00:00",
        },
        {
            "status": "dismissed",
            "dismissed_at": "2026-08-01T11:00:00+00:00",
        },
        {
            "snooze_history": [
                {
                    "snoozed_at": "2026-08-01T13:00:00+00:00",
                    "snoozed_until": "2026-08-01T13:00:00+00:00",
                }
            ]
        },
    ],
)
def test_malformed_lifecycle_timeline_is_rejected(changes) -> None:
    alert = _alert(AlertType.STALE_DATA, suffix="malformed-timeline")
    payload = alert.to_dict()
    with pytest.raises(ValueError):
        alert.from_dict({**payload, **changes})


def test_corrupted_timeline_payload_fails_closed_in_store_and_readback(tmp_path) -> None:
    alert = _alert(AlertType.STALE_DATA, suffix="corrupted-timeline")
    with AlertStore(tmp_path) as store:
        created = store.create(alert)
    payload = alert.to_dict()
    payload["snooze_history"] = [
        {
            "snoozed_at": "2026-08-01T13:00:00+00:00",
            "snoozed_until": "2026-08-01T13:00:00+00:00",
        }
    ]
    with TransactionalStore(tmp_path) as store:
        store.put(
            ALERT_ENTITY_TYPE,
            alert.alert_id,
            payload,
            expected_revision=created.revision,
        )

    with AlertStore(tmp_path) as store:
        with pytest.raises(ValueError, match="snoozed_at must be before snoozed_until"):
            store.list(include_inactive=True)
    readback = read_local_alerts(tmp_path, include_inactive=True)
    assert readback.status == "unavailable"
    assert readback.records == ()


def test_current_read_reconciles_active_status_with_live_snooze_interval(tmp_path) -> None:
    alert = _alert(AlertType.STALE_DATA, suffix="active-live-snooze")
    with AlertStore(tmp_path) as store:
        created = store.create(alert)
    payload = alert.to_dict()
    payload.update(
        {
            "status": "active",
            "snoozed_at": "2026-08-01T13:00:00+00:00",
            "snoozed_until": "2099-01-01T00:00:00+00:00",
        }
    )
    with TransactionalStore(tmp_path) as store:
        store.put(
            ALERT_ENTITY_TYPE,
            alert.alert_id,
            payload,
            expected_revision=created.revision,
        )

    with AlertStore(tmp_path) as store:
        assert store.list() == ()
        reconciled = store.list(include_inactive=True)[0]
        assert reconciled.status is AlertStatus.SNOOZED
    readback = read_local_alerts(tmp_path)
    assert readback.status == "available"
    assert readback.records == ()


def test_dismiss_uses_one_cutoff_when_expiry_falls_between_clock_reads(tmp_path) -> None:
    alert = _alert(
        AlertType.REVIEW_DATE_ARRIVED,
        suffix="dismiss-expiry-cutoff",
        expires_at=NOW.replace(hour=13, minute=30),
    )
    clock_values = iter((NOW.replace(hour=13), NOW.replace(hour=14)))
    with AlertStore(tmp_path, clock=lambda: next(clock_values)) as store:
        created = store.create(alert)
        dismissed = store.dismiss(alert.alert_id, expected_revision=created.revision)

    assert dismissed.status is AlertStatus.DISMISSED
    assert dismissed.alert.dismissed_at == NOW.replace(hour=13)
    assert evaluate_alerts_as_of((dismissed.alert,), NOW.replace(hour=14))[0].status is AlertStatus.DISMISSED


def test_historical_projection_hides_future_snooze_metadata() -> None:
    alert = replace(
        _alert(AlertType.STALE_DATA, suffix="future-snooze-metadata"),
        status=AlertStatus.SNOOZED,
        snoozed_at=NOW.replace(hour=13),
        snoozed_until=NOW.replace(hour=18),
    )

    projected = evaluate_alerts_as_of((alert,), NOW.replace(hour=12))[0]

    assert projected.status is AlertStatus.ACTIVE
    assert projected.snoozed_at is None
    assert projected.snoozed_until is None
    assert projected.snooze_history == ()


def test_resnooze_replaces_live_interval_at_operation_cutoff(tmp_path) -> None:
    clock = [NOW.replace(hour=13)]
    alert = _alert(AlertType.STALE_DATA, suffix="replace-live-snooze")
    with AlertStore(tmp_path, clock=lambda: clock[0]) as store:
        created = store.create(alert)
        first = store.snooze(
            alert.alert_id,
            NOW.replace(hour=18),
            expected_revision=created.revision,
        )
        clock[0] = NOW.replace(hour=14)
        replaced = store.snooze(
            alert.alert_id,
            NOW.replace(hour=16),
            expected_revision=first.revision,
        )

    assert replaced.alert.snooze_history[0].snoozed_until == NOW.replace(hour=14)
    assert evaluate_alerts_as_of((replaced.alert,), NOW.replace(hour=15))[0].status is AlertStatus.SNOOZED
    assert evaluate_alerts_as_of((replaced.alert,), NOW.replace(hour=17))[0].status is AlertStatus.ACTIVE
