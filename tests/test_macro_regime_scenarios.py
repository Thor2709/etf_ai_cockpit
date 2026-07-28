from __future__ import annotations

from dataclasses import asdict, replace
import copy

import pytest

from etf_cockpit.analysis.macro_regime_scenarios import (
    MacroAuthority,
    MacroEvidence,
    MacroScenarioError,
    MacroScenarioLink,
    build_macro_scenario_context,
    macro_scenario_hash,
    macro_scenario_payload,
    verify_macro_scenario_context,
)


NOW = "2026-07-28T00:00:00Z"
SHA = "a" * 64


def _evidence(**changes: object) -> MacroEvidence:
    base = MacroEvidence(
        evidence_id="cpi-v0",
        driver="inflation",
        series_id="US-CPI",
        country="US",
        currency="USD",
        unit="index_points",
        value=312.5,
        observation_time="2026-05-31T23:59:59Z",
        effective_time="2026-05-01T00:00:00Z",
        available_at="2026-06-12T12:30:00Z",
        revision=0,
        source_id="official-cpi.csv",
        source_sha256=SHA,
        authority=MacroAuthority.OFFICIAL_PUBLIC_FILE,
    )
    return replace(base, **changes)


def _link(**changes: object) -> MacroScenarioLink:
    base = MacroScenarioLink(
        link_id="inflation-base",
        scenario="inflation pressure",
        driver="inflation",
        series_id="US-CPI",
        country="US",
        currency="USD",
        unit="index_points",
        horizon_days=90,
        rationale="User links CPI evidence to the declared portfolio context.",
    )
    return replace(base, **changes)


def _build(evidence=(), links=(_link(),), **changes: object):
    options = {
        "decision_time": NOW,
        "portfolio_currency": "USD",
        "horizon_days": 90,
    }
    options.update(changes)
    return build_macro_scenario_context(evidence, links, **options)


def test_latest_revision_available_at_cutoff_is_selected_without_future_leakage() -> None:
    old = _evidence()
    revision = _evidence(
        evidence_id="cpi-v1",
        value=313.0,
        revision=1,
        available_at="2026-07-01T00:00:00Z",
    )
    future = _evidence(
        evidence_id="cpi-v2",
        value=314.0,
        revision=2,
        available_at="2026-07-29T00:00:00Z",
    )
    row = _build((future, old, revision)).rows[0]
    assert row.status == "available"
    assert row.evidence_id == "cpi-v1"
    assert row.value == 313.0
    assert row.revision == 1
    assert "cpi-v2" not in row.candidate_evidence_ids


def test_latest_period_precedes_revision_number_when_selecting_vintage() -> None:
    old_high_revision = _evidence(
        evidence_id="old-revision-9",
        value=300.0,
        observation_time="2026-04-30T23:59:59Z",
        effective_time="2026-04-01T00:00:00Z",
        available_at="2026-07-01T00:00:00Z",
        revision=9,
    )
    new_initial_release = _evidence(
        evidence_id="new-revision-0",
        value=312.5,
        revision=0,
    )
    row = _build((old_high_revision, new_initial_release)).rows[0]
    assert row.evidence_id == "new-revision-0"
    assert row.revision == 0
    assert row.candidate_evidence_ids == ("new-revision-0", "old-revision-9")


def test_observation_and_availability_are_separate_and_timezone_boundary_is_utc() -> None:
    known_at_boundary = _evidence(
        observation_time="2026-07-27T19:00:00-04:00",
        effective_time="2026-07-27T19:00:00-04:00",
        available_at="2026-07-28T10:00:00+10:00",
    )
    row = _build((known_at_boundary,)).rows[0]
    assert row.status == "available"
    assert row.observation_time == "2026-07-27T23:00:00Z"
    assert row.available_at == NOW


@pytest.mark.parametrize(
    ("link", "reason"),
    [
        (_link(currency="EUR"), "portfolio_currency_mismatch"),
        (_link(horizon_days=30), "horizon_mismatch"),
        (_link(unit="percent"), "evidence_context_mismatch"),
    ],
)
def test_currency_horizon_and_unit_mismatch_are_explicit(
    link: MacroScenarioLink, reason: str
) -> None:
    row = _build((_evidence(),), (link,)).rows[0]
    assert row.status == "unavailable"
    assert reason in row.reason_codes
    assert row.value is None


def test_missing_driver_and_same_revision_conflict_fail_closed_preserving_candidates() -> None:
    missing = _build((), (_link(series_id="MISSING"),)).rows[0]
    assert missing.reason_codes == ("driver_evidence_absent",)

    conflict = _evidence(evidence_id="cpi-conflict", value=999.0)
    row = _build((_evidence(), conflict)).rows[0]
    assert row.status == "unavailable"
    assert row.reason_codes == ("same_revision_conflict",)
    assert row.candidate_evidence_ids == ("cpi-conflict", "cpi-v0")


def test_stale_and_explicit_assumed_time_reduce_confidence_without_wall_clock() -> None:
    fresh = _build((_evidence(),)).rows[0]
    stale = _build(
        (
            _evidence(
                observation_time="2024-01-01T00:00:00Z",
                effective_time="2024-01-01T00:00:00Z",
                limitations=("assumed_time",),
            ),
        )
    ).rows[0]
    assert stale.confidence < fresh.confidence
    assert {"stale_observation", "assumed_time"} <= set(stale.reason_codes)
    assert _build((_evidence(),)).rows[0].confidence == fresh.confidence


def test_canonical_order_hash_tamper_and_nested_authority_rejection() -> None:
    rate_evidence = _evidence(
        evidence_id="rate",
        driver="rates",
        series_id="US-POLICY",
        unit="percent",
        value=4.25,
    )
    rate_link = _link(
        link_id="rates",
        scenario="rate pressure",
        driver="rates",
        series_id="US-POLICY",
        unit="percent",
    )
    first = _build((_evidence(), rate_evidence), (rate_link, _link()))
    second = _build((rate_evidence, _evidence()), (_link(), rate_link))
    assert first == second
    assert macro_scenario_hash(first) == first.context_hash
    assert verify_macro_scenario_context(first)["execution_allowed"] is False

    tampered = macro_scenario_payload(first)
    tampered["portfolio_currency"] = "EUR"
    with pytest.raises(MacroScenarioError, match="verification"):
        verify_macro_scenario_context(tampered)

    unsafe = macro_scenario_payload(first)
    unsafe["rows"][0]["execution_allowed"] = True  # type: ignore[index]
    unsafe["context_hash"] = macro_scenario_hash(unsafe)
    with pytest.raises(MacroScenarioError, match="verification"):
        verify_macro_scenario_context(unsafe)


def test_verifier_rejects_rehashed_malformed_nested_and_inconsistent_payloads() -> None:
    rate_evidence = _evidence(
        evidence_id="rate",
        driver="rates",
        series_id="US-POLICY",
        unit="percent",
        value=4.25,
    )
    rate_link = _link(
        link_id="rates",
        scenario="rate pressure",
        driver="rates",
        series_id="US-POLICY",
        unit="percent",
    )
    context = _build((_evidence(), rate_evidence), (_link(), rate_link))

    def rejected(mutator) -> None:
        payload = copy.deepcopy(macro_scenario_payload(context))
        mutator(payload)
        payload["context_hash"] = macro_scenario_hash(payload)
        with pytest.raises(MacroScenarioError, match="verification"):
            verify_macro_scenario_context(payload)

    rejected(lambda payload: payload.__setitem__("rows", "BUY NOW"))
    rejected(lambda payload: payload["rows"][0].__setitem__("horizon_days", True))
    rejected(lambda payload: payload["rows"][0].__setitem__("unexpected", "field"))
    rejected(lambda payload: payload["rows"][0].pop("unit"))
    rejected(lambda payload: payload.__setitem__("rows", tuple(reversed(payload["rows"]))))
    rejected(lambda payload: payload.__setitem__("status", "unavailable"))
    rejected(lambda payload: payload.__setitem__("limitations", ("invented_reason",)))
    rejected(lambda payload: payload["rows"][0].__setitem__("reason_codes", ("unknown",)))
    rejected(lambda payload: payload["rows"][0].__setitem__("currency", "EUR"))
    rejected(lambda payload: payload["rows"][0].__setitem__("confidence", 0.123))

    for nonfinite in (float("nan"), float("inf")):
        nonfinite_payload = copy.deepcopy(macro_scenario_payload(context))
        nonfinite_payload["rows"][0]["value"] = nonfinite
        with pytest.raises(MacroScenarioError, match="canonical JSON"):
            macro_scenario_hash(nonfinite_payload)


def test_all_unavailable_and_legitimate_zero_negative_values() -> None:
    unavailable = _build((), (_link(),))
    assert unavailable.status == "unavailable"
    zero = _build((_evidence(value=0.0),)).rows[0]
    negative = _build((_evidence(value=-0.5),)).rows[0]
    assert zero.status == negative.status == "available"
    assert zero.value == 0.0
    assert negative.value == -0.5


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (_evidence(source_sha256="bad"), "source_checksum_invalid"),
        (_evidence(available_at="2026-07-29T00:00:00Z"), "future_availability"),
        (_evidence(available_at="2026-05-01T00:00:00Z"), "availability_precedes_observation"),
        (_evidence(available_at="2026-06-12T12:30:00"), "timestamp_invalid_or_ambiguous"),
        (_evidence(execution_allowed=True), "evidence_authority_invalid"),
    ],
)
def test_invalid_lineage_is_explicitly_unavailable(
    evidence: MacroEvidence, reason: str
) -> None:
    row = _build((evidence,)).rows[0]
    assert row.status == "unavailable"
    assert reason in row.reason_codes


def test_authority_flags_and_serialization_are_context_only() -> None:
    context = _build(
        (
            _evidence(
                authority=MacroAuthority.LOCAL_USER_IMPORT,
                source_id="user-owned-import.csv",
            ),
        )
    )
    payload = asdict(context)
    row = context.rows[0]
    assert row.authority == "local_user_import"
    assert row.confidence < 1.0
    assert payload["context_only"] is True
    assert payload["score_eligible"] is False
    assert payload["forecast_authority"] is False
    assert payload["execution_allowed"] is False
    assert row.context_only is True
    assert row.score_eligible is row.forecast_authority is row.execution_allowed is False
