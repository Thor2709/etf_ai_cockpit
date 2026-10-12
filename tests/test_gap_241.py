from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.analysis.cyclical_sector_adapters import (
    CycleHistoryEvidence,
    CyclicalMetricEvidence,
    build_cyclical_projection,
    cyclical_adapter_definitions,
)
from etf_cockpit.analysis.decision.domains import DomainReference
from etf_cockpit.analysis.decision.stock import compose_stock_decision
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry, PeerObservation
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.signals.simple_scores import _stock_fundamental_components


DECISION_TIME = "2025-02-28T00:00:00Z"
INSTRUMENT = "SYNTH-ENERGY"


def _context(instrument_id: str = INSTRUMENT):
    fields = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": "energy",
        "industry": "integrated energy",
        "business_model_tag": "energy",
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
        decision_time=DECISION_TIME,
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


def _metric(name: str, value: float | None, unit: str):
    return CyclicalMetricEvidence(
        metric=name,
        value=value,
        unit=unit,
        period="through-cycle" if name == "normalised_margin" else "TTM-2024",
        reporting_standard="IFRS",
        jurisdiction="AU",
        business_model="energy",
        source_id=f"synthetic:{name}",
        source_authority=SourceAuthority.ISSUER,
        as_of="2024-12-31T00:00:00Z",
        known_at="2025-02-15T00:00:00Z",
        normalisation_cycle_ids=("cycle-0", "cycle-1") if name == "normalised_margin" else (),
    )


def _projection(*, history_count: int = 2):
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
    return build_cyclical_projection(
        _context(),
        evidence,
        cycle_history=_history(history_count),
        registry=AdapterRegistry(cyclical_adapter_definitions()),
        decision_time=DECISION_TIME,
        scenarios=scenarios,
    )


def test_peak_year_earnings_do_not_make_cyclical_look_cheap():
    projection = _projection()
    multiple = next(row for row in projection.metrics if row.metric == "cycle_adjusted_ev_to_earnings")
    check = next(row for row in projection.checks if row.check == "cycle_adjusted_ev_to_earnings")

    assert multiple.value == 50.0
    assert "normalised_margin" in multiple.basis
    assert "cycle-0,cycle-1" in multiple.basis
    assert check.status == "failed"


def test_synthetic_energy_stock_scores_consume_adapter_basis_end_to_end():
    projection = _projection()
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
            context=_context(f"reference-energy-{index}"),
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
        _context(),
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


def test_insufficient_cycle_history_makes_sector_scores_unavailable_with_reason():
    projection = _projection(history_count=1)
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


def test_non_cyclical_stock_components_keep_the_existing_values():
    evidence = SimpleNamespace(
        components={
            "stock_value": SimpleNamespace(score_10=7.5, why="generic value basis", source_id="sec_edgar:fundamentals", as_of="2025-02-15", freshness="ok"),
            "stock_quality": SimpleNamespace(score_10=6.5, why="generic quality basis", source_id="sec_edgar:fundamentals", as_of="2025-02-15", freshness="ok"),
            "analyst_revision": SimpleNamespace(score_10=None, why="not disclosed", source_id="sec_edgar:fundamentals", as_of="2025-02-15", freshness="ok"),
        }
    )
    components = _stock_fundamental_components(evidence)

    assert [(row.key, row.score_10) for row in components[:2]] == [
        ("stock_value", 7.5),
        ("stock_quality", 6.5),
    ]
