from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.cyclical_sector_adapters import (
    CycleHistoryEvidence,
    CyclicalMetricEvidence,
    build_cyclical_projection,
    cyclical_adapter_definitions,
    cyclical_source_digest,
    verify_cyclical_projection,
)
from etf_cockpit.analysis.decision.domains import DomainReference
from etf_cockpit.analysis.decision.stock import compose_stock_decision
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry, PeerObservation
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.signals import simple_scores as scores
from etf_cockpit.signals.simple_scores import _stock_fundamental_components


DECISION_TIME = "2025-02-28T00:00:00Z"
INSTRUMENT = "SYNTH-ENERGY"


def _context(instrument_id: str = INSTRUMENT, model: str = "energy", decision_time: str = DECISION_TIME):
    fields = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": model,
        "industry": model,
        "business_model_tag": model,
        "operating_country": "AU",
        "reporting_currency": "AUD",
    }
    rows = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument_id}:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            source="synthetic gap fixture",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"synthetic:{field}",
            confidence=0.99,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in fields.items()
    )
    return resolve_instrument_context(
        rows,
        instrument_id=instrument_id,
        effective_at="2024-12-31T00:00:00Z",
        decision_time=decision_time,
    )


def _history(count: int = 2):
    cycles = (
        ("2010-01-01T00:00:00Z", "2013-12-31T00:00:00Z"),
        ("2015-01-01T00:00:00Z", "2019-12-31T00:00:00Z"),
    )
    return tuple(
        CycleHistoryEvidence(
            cycle_id=f"cycle-{index}",
            phase="completed_cycle",
            start_at=start,
            end_at=end,
            known_at="2025-02-01T00:00:00Z",
            source_id=f"synthetic:cycle-{index}",
            source_authority=SourceAuthority.ISSUER,
        )
        for index, (start, end) in enumerate(cycles[:count])
    )


def _metric(name: str, value: float | None, unit: str, model: str = "energy"):
    return CyclicalMetricEvidence(
        metric=name,
        value=value,
        unit=unit,
        period="through-cycle" if name == "normalised_margin" else "TTM-2024",
        reporting_standard="IFRS",
        jurisdiction="AU",
        business_model=model,
        source_id=f"synthetic:{name}",
        source_authority=SourceAuthority.ISSUER,
        as_of="2024-12-31T00:00:00Z",
        known_at="2025-02-15T00:00:00Z",
        normalisation_cycle_ids=("cycle-0", "cycle-1") if name == "normalised_margin" else (),
    )


def _projection(*, history_count: int = 2, model: str = "energy", omit=(), overrides=None, history=None, decision_time: str = DECISION_TIME):
    evidence = (
        _metric("spot_cycle_margin", 0.40, "ratio"),
        _metric("normalised_margin", 0.10, "ratio"),
        _metric("enterprise_value", 500.0, "currency:AUD"),
        _metric("revenue", 100.0, "currency:AUD"),
        # The peak-year multiple would be 12.5x; the adapter must calculate 50x from normalised earnings.
        _metric("cycle_adjusted_ev_to_earnings", 12.5, "multiple"),
    )
    scenarios = {
        "commodity_price": {"shock_rate": -0.2, "exposed_amount": 50.0, "portfolio_base": 100.0},
        "input_cost": {"shock_rate": 0.1, "exposed_amount": 50.0, "portfolio_base": 100.0},
        "demand_rate": {"shock_rate": 0.15, "exposed_amount": 50.0, "portfolio_base": 100.0},
    }
    evidence = tuple(
        replace((overrides or {}).get(row.metric, row), business_model=model)
        for row in evidence if row.metric not in omit
    )
    return build_cyclical_projection(
        _context(model=model, decision_time=decision_time),
        evidence,
        cycle_history=_history(history_count) if history is None else history,
        registry=AdapterRegistry(cyclical_adapter_definitions()),
        decision_time=decision_time,
        scenarios=scenarios,
    )


@pytest.mark.parametrize("model", ("energy", "materials", "industrials"))
def test_peak_year_earnings_do_not_make_cyclical_look_cheap(model):
    projection = _projection(model=model)
    multiple = next(row for row in projection.metrics if row.metric == "cycle_adjusted_ev_to_earnings")
    check = next(row for row in projection.checks if row.check == "cycle_adjusted_ev_to_earnings")

    assert multiple.value == 50.0
    assert "normalised_margin" in multiple.basis
    assert "cycle-0,cycle-1" in multiple.basis
    assert check.status == "failed"
    replay = verify_cyclical_projection(
        projection, expected_source_digest=cyclical_source_digest(projection.source_payload)
    )
    assert replay["result_hash"] == projection.result_hash


def _candidate_components(monkeypatch, projection=None, *, sector="energy"):
    monkeypatch.setattr(scores, "_etf_exposure_lookup", lambda: {})
    report = pd.DataFrame([{
        "instrument_id": INSTRUMENT, "asset_type": "STOCK", "instrument_type": "stock",
        "sector": sector, "latest_date": "2025-02-28", "latest_price": 50.0,
        "value_score_10": 7.5, "quality_score_10": 6.5,
    }])
    result = scores.build_candidate_simple_scores(
        report, pd.DataFrame(), decision_date=date(2025, 2, 28),
        cyclical_projections={INSTRUMENT: projection} if projection is not None else None,
    )
    assert len(result) == 1 and result[0].display_id == INSTRUMENT
    return {row.key: row for row in result[0].components}


@pytest.mark.parametrize("model", ("energy", "materials", "industrials"))
def test_synthetic_energy_stock_scores_consume_adapter_basis_end_to_end(monkeypatch, model):
    projection = _projection(model=model)
    components = _stock_fundamental_components(
        None,
        cyclical_projection=projection,
        instrument_id=INSTRUMENT,
        decision_time=DECISION_TIME,
    )
    value = next(row for row in components if row.key == "stock_value")
    quality = next(row for row in components if row.key == "stock_quality")

    assert value.score_10 == 2.0
    assert "50.00x" in value.why
    assert "cycle-0,cycle-1" in value.why
    assert quality.score_10 == 4.0
    assert "normalised margin is 10.0%" in quality.why
    public = _candidate_components(monkeypatch, projection, sector=model)
    assert public["stock_value"].score_10 == value.score_10
    assert public["stock_quality"].score_10 == quality.score_10
    assert public["stock_value"].score_eligible and public["stock_quality"].score_eligible
    assert public["stock_value"].source_id == f"sector:{model}"
    assert "normalised_margin" in public["stock_value"].why

    references = {
        domain: tuple(
            DomainReference(f"reference-{index}", z, DECISION_TIME, DECISION_TIME)
            for index, z in enumerate((-1.0, 0.0, 1.0))
        )
        for domain in ("profitability_economic_returns", "valuation")
    }
    peers = tuple(
        PeerObservation(
            instrument_id=f"reference-energy-{index}",
            context=_context(f"reference-energy-{index}", model),
            metric=metric_id,
            value=value,
            weight=1.0,
            effective_at="2024-12-31T00:00:00Z",
            known_at="2025-02-15T00:00:00Z",
        )
        for metric_id, values in (
            ("cyclical_normalised_margin", (0.08, 0.10, 0.12)),
            ("cyclical_cycle_adjusted_ev_to_earnings", (30.0, 50.0, 70.0)),
        )
        for index, value in enumerate(values)
    )
    decision = compose_stock_decision(
        INSTRUMENT,
        _context(model=model),
        DECISION_TIME,
        {},
        cyclical_projection=projection,
        peer_observations=peers,
        domain_reference_z=references,
    )
    assert decision["route"] == "cyclical_sector_adapter"
    assert decision["route_status"] == "available"
    assert any(
        driver.metric_id == "cyclical_cycle_adjusted_ev_to_earnings" and driver.raw_value == 50.0
        for driver in decision["valuation_drivers"]
    )
    basis = decision["underwriting_input_evidence"]["cyclical_normalised_margin"]["basis"]
    assert "cycle-0,cycle-1" in basis
    assert decision["underwriting_input_evidence"]["cyclical_normalised_margin"]["value"] == 0.10
    quality_driver = next(driver for driver in decision["underwriting"].drivers if driver.metric_id == "cyclical_normalised_margin")
    assert quality_driver.raw_value == 0.10
    # The existing registry deliberately withholds peer-rank authority.
    assert quality_driver.reason_code == "RANK_AUTHORITY_NOT_GRANTED"
    value_driver = next(driver for driver in decision["valuation_drivers"] if driver.metric_id == "cyclical_cycle_adjusted_ev_to_earnings")
    assert value_driver.raw_value == 50.0 and value_driver.reason_code == "RANK_AUTHORITY_NOT_GRANTED"
    assert decision["execution_allowed"] is False


@pytest.mark.parametrize("history_count", (0, 1))
def test_insufficient_cycle_history_makes_sector_scores_unavailable_with_reason(monkeypatch, history_count):
    projection = _projection(history_count=history_count)
    components = _stock_fundamental_components(
        None,
        cyclical_projection=projection,
        instrument_id=INSTRUMENT,
        decision_time=DECISION_TIME,
    )

    assert all(row.score_10 is None for row in components[:2])
    assert all("insufficient" in row.why for row in components[:2])
    rows = {row.metric: row for row in projection.metrics}
    assert rows["normalised_margin"].status == "unavailable"
    assert rows["cycle_adjusted_ev_to_earnings"].status == "unavailable"
    public = _candidate_components(monkeypatch, projection)
    assert all(public[key].score_10 is None and not public[key].score_eligible for key in ("stock_value", "stock_quality"))
    for model in ("energy", "materials", "industrials"):
        missing = _candidate_components(monkeypatch, sector=model)
        assert all(missing[key].score_10 is None and "history" in missing[key].why for key in ("stock_value", "stock_quality"))
        configured = _stock_fundamental_components(None, sector=model)
        assert all(row.score_10 is None and "history" in row.why for row in configured[:2])
    decision = compose_stock_decision(INSTRUMENT, _context(), DECISION_TIME, {}, cyclical_projection=projection)
    assert decision["route_status"] == "unavailable" and decision["route_reason"]
    assert decision["valuation_z_score"] is None


def test_non_cyclical_stock_components_keep_the_existing_values(monkeypatch):
    evidence = SimpleNamespace(
        components={
            "stock_value": SimpleNamespace(score_10=7.5, why="generic value basis", source_id="sec_edgar:fundamentals", as_of="2025-02-15", freshness="ok"),
            "stock_quality": SimpleNamespace(score_10=6.5, why="generic quality basis", source_id="sec_edgar:fundamentals", as_of="2025-02-15", freshness="ok"),
            "analyst_revision": SimpleNamespace(score_10=None, why="not disclosed", source_id="sec_edgar:fundamentals", as_of="2025-02-15", freshness="ok"),
        }
    )
    components = _stock_fundamental_components(evidence, sector="technology")

    assert [(row.key, row.score_10) for row in components[:2]] == [
        ("stock_value", 7.5),
        ("stock_quality", 6.5),
    ]
    public = _candidate_components(monkeypatch, sector="technology")
    assert public["stock_value"].score_10 == 7.5
    assert public["stock_quality"].score_10 == 6.5
    decision = compose_stock_decision(INSTRUMENT, _context(model="technology"), DECISION_TIME, {})
    assert decision["route"] == "generic_stock"


@pytest.mark.parametrize("omit", (("enterprise_value",), ("revenue",), ("normalised_margin",)))
def test_reported_peak_multiple_cannot_bypass_missing_through_cycle_inputs(monkeypatch, omit):
    projection = _projection(omit=omit)
    public = _candidate_components(monkeypatch, projection)
    assert public["stock_value"].score_10 is None and not public["stock_value"].score_eligible
    decision = compose_stock_decision(INSTRUMENT, _context(), DECISION_TIME, {}, cyclical_projection=projection)
    assert decision["route_status"] == "unavailable"
    assert decision["valuation_z_score"] is None
    assert not any(driver.raw_value == 12.5 for driver in decision["valuation_drivers"])
    if "normalised_margin" not in omit:
        multiple = next(row for row in projection.metrics if row.metric == "cycle_adjusted_ev_to_earnings")
        assert multiple.status == "unavailable" and multiple.value is None
        assert "basis_unverified" in multiple.basis


@pytest.mark.parametrize("changed", (
    {"known_at": "2025-02-20T00:00:00Z"},
    {"end_at": "2025-01-01T00:00:00Z"},
    {"score_cutoff": "2025-02-28T00:00:00+01:00"},
))
def test_normalised_basis_cannot_use_history_after_its_evidence_cutoff(monkeypatch, changed):
    if "score_cutoff" in changed:
        projection = _projection()
        components = _stock_fundamental_components(
            None, cyclical_projection=projection, instrument_id=INSTRUMENT,
            decision_time=changed["score_cutoff"],
        )
        assert all(row.score_10 is None and "cutoff" in row.why for row in components[:2])
        equivalent = _stock_fundamental_components(
            None, cyclical_projection=projection, instrument_id=INSTRUMENT,
            decision_time="2025-02-28T01:00:00+01:00",
        )
        assert equivalent[0].score_10 == 2.0 and equivalent[1].score_10 == 4.0
        return
    history = list(_history())
    history[-1] = replace(history[-1], **changed)
    projection = _projection(history=history)
    rows = {row.metric: row for row in projection.metrics}
    assert rows["normalised_margin"].status == "unavailable"
    assert rows["cycle_adjusted_ev_to_earnings"].status == "unavailable"
    assert "unlinked_cycle_history" in rows["normalised_margin"].basis
    public = _candidate_components(monkeypatch, projection)
    assert public["stock_value"].score_10 is None and public["stock_quality"].score_10 is None


@pytest.mark.parametrize("label", ("Energy", "Basic Materials", "Capital Goods", "Industrial", "oil & gas"))
def test_classified_cyclical_without_projection_is_unavailable_not_generic(label):
    evidence = SimpleNamespace(
        components={
            key: SimpleNamespace(score_10=7.5, why="generic peak-year basis", source_id="sec_edgar:fundamentals", as_of="2025-02-15", freshness="ok")
            for key in ("stock_value", "stock_quality", "analyst_revision")
        }
    )
    components = _stock_fundamental_components(evidence, sector=label)
    assert all(row.score_10 is None and not row.score_eligible and "unavailable" in row.why for row in components[:2])


def test_percent_margin_is_canonicalised_to_a_fraction_before_valuation_and_scoring():
    overrides = {"normalised_margin": replace(_metric("normalised_margin", 10.0, "percent"))}
    projection = _projection(overrides=overrides)
    rows = {row.metric: row for row in projection.metrics}
    assert rows["normalised_margin"].value == pytest.approx(0.10) and rows["normalised_margin"].unit == "ratio"
    assert rows["cycle_adjusted_ev_to_earnings"].value == pytest.approx(50.0)
    components = _stock_fundamental_components(
        None, cyclical_projection=projection, instrument_id=INSTRUMENT, decision_time=DECISION_TIME
    )
    assert components[0].score_10 == 2.0 and components[1].score_10 == 4.0


@pytest.mark.parametrize("omit", (("revenue",), ("enterprise_value",), ("normalised_margin",)))
def test_reported_multiple_without_own_through_cycle_linkage_is_unavailable(omit):
    projection = _projection(omit=omit)
    multiple = next(row for row in projection.metrics if row.metric == "cycle_adjusted_ev_to_earnings")
    assert multiple.status == "unavailable" and multiple.value is None
    assert multiple.normalisation_cycle_ids == ()
    assert "basis_unverified" in multiple.basis


def test_projection_built_later_the_same_day_cannot_score_an_earlier_cutoff():
    projection = _projection(decision_time="2025-02-28T18:00:00Z")
    kwargs = dict(cyclical_projection=projection, instrument_id=INSTRUMENT)
    for early in ("2025-02-28", date(2025, 2, 28), "2025-02-28T09:00:00Z"):
        components = _stock_fundamental_components(None, decision_time=early, **kwargs)
        assert all(row.score_10 is None and "cutoff" in row.why for row in components[:2])
    same = _stock_fundamental_components(None, decision_time="2025-02-28T18:00:00Z", **kwargs)
    assert same[0].score_10 == 2.0 and same[1].score_10 == 4.0
    midnight = _stock_fundamental_components(
        None, cyclical_projection=_projection(), instrument_id=INSTRUMENT, decision_time=date(2025, 2, 28)
    )
    assert midnight[0].score_10 == 2.0
