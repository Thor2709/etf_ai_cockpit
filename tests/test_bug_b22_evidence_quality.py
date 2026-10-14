"""Issue #931: optional forecasts must not promote deterministic evidence."""

from dataclasses import replace

import pytest

from etf_cockpit.signals.simple_scores import (
    SimpleInstrumentScore,
    SimpleScoreComponent,
    _evidence_quality_score,
    combine_component_scores,
    final_label_from_scores,
    simple_scoreboard_frame,
)


def _component(key, value, role="evidence"):
    return SimpleScoreComponent(
        key, key, value, None if value is None else value / 5 - 1,
        "N/A" if value is None else "OK", "", "", "",
        score_role=role, as_of_date="2026-06-29", freshness_status="ok",
    )


def _components(model_count):
    return [
        _component("data_quality", 8.0, "evidence_quality"),
        _component("momentum", 8.2),
        _component("trend", 8.2),
        _component("risk", 7.0, "risk_friction"),
        _component("etf_exposure", 8.2),
        *[
            _component(key, 10.0 if index < model_count else None, "model_confirmation")
            for index, key in enumerate(("baseline", "timesfm", "toto"))
        ],
    ]


def _decision(components):
    _, score = combine_component_scores(components, {"momentum": 1.0})
    quality = _evidence_quality_score(components, warnings=[], asset_type="ETF")
    return score, quality, final_label_from_scores(score, quality, 7.0, warnings=[])


def test_b22_n001_model_availability_never_changes_quality_or_label():
    outcomes = [_decision(_components(count)) for count in (0, 1, 3)]
    assert outcomes[0] == outcomes[1] == outcomes[2]


def test_b122_n001_zero_weight_timesfm_toto_do_not_confirm_quality():
    base = _components(1)
    optional = [replace(c, score_10=10.0, raw_score=1.0, status="OK")
                if c.key in {"timesfm", "toto"} else c for c in base]
    assert _decision(base) == _decision(optional)


def _instrument(components):
    score, quality, (label, action, decision) = _decision(components)
    return SimpleInstrumentScore(
        "candidate:ABC", "ABC", "secondary_etf", "ETF", "ABC", "ABC.DE",
        "2026-06-29", 100.0, score, decision, "", components, [],
        evidence_score_10=score, evidence_quality_10=quality,
        risk_friction_10=7.0, final_label=label, final_action=action,
    )


@pytest.mark.parametrize("count,status", [(0, "unavailable"), (1, "partial"), (3, "available")])
def test_model_readiness_is_reported_separately(count, status):
    score = _instrument(_components(count))
    readiness = score.model_readiness
    assert readiness["status"] == status
    assert readiness["available_models"] == ["baseline", "timesfm", "toto"][:count]
    assert readiness["reason"]
    frame = simple_scoreboard_frame([score])
    assert frame.loc[0, "model_readiness"] == readiness
    assert not frame.loc[0, "execution_allowed"]


@pytest.mark.parametrize("change", [
    {"status": "N/A"}, {"freshness_status": "stale"},
    {"freshness_status": "unknown"}, {"conflict_id": "conflict"},
    {"as_of_date": None}, {"score_10": float("nan")},
])
def test_unverifiable_model_is_unavailable_with_reason(change):
    components = _components(1)
    components = [replace(c, **change) if c.key == "baseline" else c for c in components]
    readiness = _instrument(components).model_readiness
    assert readiness["status"] == "unavailable"
    assert readiness["available_models"] == []
    assert readiness["reason"]


@pytest.mark.parametrize("change", [
    {"score_10": None, "raw_score": None}, {"status": "N/A"},
    {"freshness_status": "stale"}, {"conflict_id": "conflict"},
    {"as_of_date": None}, {"score_10": float("nan")},
    {"raw_score": float("nan")}, {"raw_score": float("inf")},
    {"raw_score": 2.0}, {"freshness_status": "unrecognized"},
])
def test_unverifiable_data_quality_cannot_promote_label(change):
    components = [replace(c, **change) if c.key == "data_quality" else c
                  for c in _components(3)]
    _, quality, label = _decision(components)
    assert quality is None
    assert label == ("manual_review", "manual_review", "Manual Review")


def test_models_alone_cannot_supply_deterministic_quality():
    components = [c for c in _components(3) if c.score_role != "evidence"
                  and c.score_role != "risk_friction"]
    assert _evidence_quality_score(components, warnings=[], asset_type="ETF") is None


def test_invalid_label_inputs_fail_closed():
    for values in ((float("nan"), 8.0, 7.0), (8.2, float("inf"), 7.0), (8.2, 8.0, -1.0)):
        assert final_label_from_scores(*values, warnings=[]) == (
            "manual_review", "manual_review", "Manual Review"
        )
