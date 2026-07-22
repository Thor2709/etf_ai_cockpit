from __future__ import annotations

from collections.abc import Iterable

import flet as ft

from etf_cockpit.app.pages.instrument_detail import _render_evidence_section
from etf_cockpit.application.market_clock import build_market_clock_diagnostics


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
    assert result["staleness"]["expected_sessions_elapsed"] == 1  # type: ignore[index]
    assert result["execution_allowed"] is False
    assert result["advisory_only"] is True


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
