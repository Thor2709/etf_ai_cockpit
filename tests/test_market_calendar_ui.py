from __future__ import annotations

from collections.abc import Iterable

import flet as ft

from etf_cockpit.app.pages.instrument_detail import _render_evidence_section
from etf_cockpit.application.market_clock import build_market_clock_diagnostics
from etf_cockpit.services import build_snapshot


def _identity_projection(
    *, mic: str = "XNYS", timezone: str = "America/New_York"
) -> dict[str, object]:
    return {
        "status": "available",
        "instrument_id": "SEC-1",
        "identity_decision_id": "identity-decision-1",
        "identity_decision_time": "2024-11-27T20:00:00Z",
        "identity_effective_at": "2024-01-01T00:00:00Z",
        "identity_conflict_ids": [],
        "identity_objects": [
            {
                "object_type": "listing",
                "object_id": f"listing:{mic}",
                "parent_object_id": "SEC-1",
                "relationship": "listed_as",
                "fields": {"mic": mic, "calendar_id": mic, "timezone": timezone},
                "source_ids": ["iso-mic:test", "exchange-calendar:test"],
            }
        ],
        "identity_history": [
            {
                "object_type": "listing",
                "object_id": f"listing:{mic}",
                "field": "mic",
                "value": mic,
                "source_id": "iso-mic:test",
                "valid_from": "2024-01-01T00:00:00Z",
                "valid_to": None,
                "available_at": "2024-01-02T00:00:00Z",
                "revision": 1,
                "event_type": "observation",
            }
        ],
        "execution_allowed": False,
    }


def _walk(control: object) -> Iterable[object]:
    yield control
    for attribute in ("content", "controls"):
        child = getattr(control, attribute, None)
        if isinstance(child, list):
            for item in child:
                yield from _walk(item)
        elif isinstance(child, ft.Control):
            yield from _walk(child)


def test_application_facade_exposes_certified_advisory_market_clock() -> None:
    result = build_market_clock_diagnostics(
        _identity_projection(),
        decision_time="2024-11-29T17:30:00Z",
        observed_at="2024-11-27T21:00:00Z",
    )

    assert result["status"] == "available"
    assert result["certification"] == "certified"
    assert result["mic"] == "XNYS"
    assert result["timezone"] == "America/New_York"
    assert result["phase"] == "open"
    assert result["early_close"] is True
    assert result["staleness"]["expected_sessions_elapsed"] == 0  # type: ignore[index]
    assert result["execution_allowed"] is False
    assert result["advisory_only"] is True
    assert result["settlement_calendar"]["status"] == "unavailable"  # type: ignore[index]


def test_application_facade_exposes_only_declared_settlement_calendar() -> None:
    projection = _identity_projection()
    listing = projection["identity_objects"][0]  # type: ignore[index]
    listing["fields"].update(  # type: ignore[union-attr]
        {
            "settlement_calendar_id": "XNYS",
            "settlement_timezone": "America/New_York",
            "settlement_calendar_evidence_id": "settlement:XNYS",
        }
    )
    result = build_market_clock_diagnostics(
        projection,
        decision_time="2024-11-29T17:30:00Z",
    )
    assert result["settlement_calendar"]["status"] == "available"  # type: ignore[index]
    assert result["settlement_calendar"]["calendar_id"] == "XNYS"  # type: ignore[index]


def test_application_facade_keeps_uncertified_identity_explicitly_unavailable() -> None:
    conflicted = _identity_projection()
    conflicted["identity_conflict_ids"] = ["conflict-1"]

    result = build_market_clock_diagnostics(
        conflicted,
        decision_time="2024-11-29T17:30:00Z",
    )

    assert result["status"] == "unavailable"
    assert result["phase"] == "unknown"
    assert result["execution_allowed"] is False
    assert "conflicted" in str(result["message"])


def test_instrument_market_clock_panel_has_acceptance_key_and_authority_warning() -> (
    None
):
    diagnostics = build_market_clock_diagnostics(
        _identity_projection(),
        decision_time="2024-11-29T17:30:00Z",
    )
    control = _render_evidence_section(
        "Market clock and session",
        diagnostics,
        subtitle="Advisory only; execution_allowed=false.",
        key="instrument-detail.market-clock",
    )

    keys = {getattr(item, "key", None) for item in _walk(control)}
    text = " ".join(str(getattr(item, "value", "")) for item in _walk(control))
    assert "instrument-detail.market-clock" in keys
    assert "execution_allowed" in text
    assert "America/New_York" in text


def test_instrument_selector_queries_identity_at_snapshot_point_in_time(
    monkeypatch,
) -> None:
    from etf_cockpit.app.selectors import instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    captured: dict[str, object] = {}

    def projection(
        selected: str,
        _path=None,
        *,
        storage_root=None,
        effective_at=None,
        decision_time=None,
    ) -> dict[str, object]:
        captured.update(
            {
                "instrument_id": selected,
                "effective_at": effective_at,
                "decision_time": decision_time,
            }
        )
        value = _identity_projection()
        value["instrument_id"] = selected
        value["identity_effective_at"] = effective_at
        value["identity_decision_time"] = decision_time
        return value

    monkeypatch.setattr(selector, "load_identity_projection", projection)
    model = selector.build_instrument_detail(snapshot, instrument_id)

    assert captured["instrument_id"] == instrument_id
    assert captured["effective_at"] == captured["decision_time"]
    assert str(captured["decision_time"]).endswith("Z")
    assert model.sections["market_clock"]["certification"] == "certified"
