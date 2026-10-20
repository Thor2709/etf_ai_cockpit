from __future__ import annotations

from types import SimpleNamespace

import pytest

import etf_cockpit.analysis.decision.opportunity as opportunity_module
from etf_cockpit.analysis.decision.contracts import DomainSlot, ScoreAuthorityFlags
from etf_cockpit.analysis.decision.opportunity import build_opportunity_results
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkDefinition,
    CanonicalBenchmarkRegistry,
)


DECISION_TIME = "2026-09-30T23:59:59Z"
HORIZON = "20_sessions"
BENCHMARK_ID = "benchmark:ftse-all-world"


@pytest.fixture
def available_vwce_registry(monkeypatch: pytest.MonkeyPatch) -> CanonicalBenchmarkRegistry:
    benchmark = BenchmarkDefinition(
        benchmark_id=BENCHMARK_ID,
        version="1.0.0",
        hierarchy="asset",
        selector={"asset_class": "equity"},
        currency="EUR",
        minimum_horizon_years=0.01,
        maximum_horizon_years=50.0,
        effective_at="2020-01-01T00:00:00Z",
        known_at="2020-01-02T00:00:00Z",
        start_date="2020-01-01",
        end_date="2100-12-31",
        methodology="Test source-backed VWCE total-return reference.",
        constituents=("VWCE",),
        source_hashes=("a" * 64,),
        status="available",
        opportunity_anchor=True,
    )
    registry = CanonicalBenchmarkRegistry(benchmarks=(benchmark,))
    monkeypatch.setattr(
        opportunity_module, "load_canonical_benchmark_registry", lambda: registry
    )
    return registry


def _absolute_evidence(
    registry: CanonicalBenchmarkRegistry,
    *,
    forecast_return: float = 0.08,
    benchmark_return: float = 0.03,
    previous_state: str | None = None,
    position: dict[str, object] | None = None,
) -> dict[str, object]:
    benchmark = registry.benchmarks[0]
    evidence: dict[str, object] = {
        "forecast": {
            "status": "available",
            "calibration_status": "calibrated",
            "expected_total_return": forecast_return,
            "unit": "decimal_fraction",
            "uncertainty_margin": 0.002,
            "horizon": HORIZON,
            "currency": "EUR",
            "effective_at": DECISION_TIME,
            "known_at": DECISION_TIME,
            "source_hash": "b" * 64,
        },
        "benchmark_reference": {
            "status": "available",
            "instrument_id": "VWCE",
            "benchmark_id": benchmark.benchmark_id,
            "benchmark_version": benchmark.version,
            "benchmark_digest": benchmark.digest(),
            "total_return": benchmark_return,
            "unit": "decimal_fraction",
            "horizon": HORIZON,
            "currency": "EUR",
            "effective_at": DECISION_TIME,
            "known_at": DECISION_TIME,
            "source_hash": "a" * 64,
        },
        "cost_model": {
            "status": "available",
            "candidate_acquisition_cost": 0.001,
            "benchmark_acquisition_cost": 0.001,
            "unit": "decimal_fraction",
            "currency": "EUR",
            "horizon": HORIZON,
            "effective_at": DECISION_TIME,
            "known_at": DECISION_TIME,
            "source_hash": "d" * 64,
        },
    }
    if previous_state is not None:
        evidence["previous_decision"] = {
            "status": "available",
            "state": previous_state,
            "horizon": HORIZON,
            "instrument_id": "ACME",
            "config_hash": opportunity_module.load_opportunity_policy().checksum,
            "effective_at": DECISION_TIME,
            "known_at": DECISION_TIME,
            "source_hash": "f" * 64,
        }
    evidence["position"] = position or {
        "status": "available",
        "held": False,
        "currency": "EUR",
        "friction_unit": "decimal_fraction",
        "effective_at": DECISION_TIME,
        "known_at": DECISION_TIME,
        "source_hash": "e" * 64,
    }
    return evidence


def _candidate(
    instrument: str,
    rank_score: float,
    *,
    evidence: dict[str, object] | None = None,
    gate_results: tuple[object, ...] = (),
) -> dict[str, object]:
    domains = (
        DomainSlot("Underwriting", "AVAILABLE", rank_score, rank_score, 1.0, 0.8, "AVAILABLE"),
        DomainSlot("Valuation", "AVAILABLE", rank_score, rank_score, 1.0, 0.8, "AVAILABLE"),
    )
    assessment = SimpleNamespace(
        eligibility_results=(),
        gate_results=gate_results,
        drivers=(),
        source_vintage_hash=f"source:{instrument}",
    )
    candidate: dict[str, object] = {
        "instrument": instrument,
        "asset_type": "stock",
        "assessment": assessment,
        "underwriting_domains": domains,
        "valuation_domain": domains[1],
        "underwriting_z_score": rank_score,
        "valuation_z_score": rank_score,
        "critical_domains": ("Underwriting", "Valuation"),
        "score_authority": ScoreAuthorityFlags(forecast_calibrated=True),
        "absolute_merit_evidence": evidence,
    }
    return candidate


def _build(
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    return build_opportunity_results(candidates, decision_time=DECISION_TIME)


def test_candidates_below_vwce_never_buy_and_keep_relative_ranks(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    candidates = [
        _candidate(
            "LOW",
            -1.0,
            evidence=_absolute_evidence(
                available_vwce_registry, forecast_return=0.01, benchmark_return=0.05
            ),
        ),
        _candidate(
            "MID",
            0.0,
            evidence=_absolute_evidence(
                available_vwce_registry, forecast_return=0.02, benchmark_return=0.05
            ),
        ),
        _candidate(
            "TOP",
            1.0,
            evidence=_absolute_evidence(
                available_vwce_registry, forecast_return=0.03, benchmark_return=0.05
            ),
        ),
    ]

    results = _build(candidates)

    assert results["TOP"].decision_state == "AVOID_REDUCE"
    assert all(item.decision_state != "CANDIDATE_BUY" for item in results.values())
    assert results["TOP"].percentile == pytest.approx(83.3333333333)
    assert results["TOP"].universe_rank == 1
    assert results["TOP"].expected_net_excess_return is not None
    assert results["TOP"].expected_net_excess_return < 0.0


def test_missing_vwce_reference_is_source_unavailable() -> None:
    result = _build([_candidate("TOP", 1.0)])["TOP"]

    assert result.decision_state == "SOURCE_UNAVAILABLE"
    assert result.expected_net_excess_return is None
    assert result.decision_reason_code


def test_unvalidated_forecast_or_win_probability_cannot_create_a_buy(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    evidence = _absolute_evidence(available_vwce_registry, forecast_return=0.25)
    forecast = evidence["forecast"]
    assert isinstance(forecast, dict)
    forecast["calibration_status"] = "uncalibrated"
    forecast["win_probability"] = 0.95

    result = _build([_candidate("UNCALIBRATED", 1.0, evidence=evidence)])[
        "UNCALIBRATED"
    ]

    assert result.decision_state == "RETURN_NOT_CALIBRATED"
    assert result.expected_net_excess_return is None


def test_forecast_and_vwce_horizons_must_match(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    evidence = _absolute_evidence(available_vwce_registry)
    benchmark = evidence["benchmark_reference"]
    assert isinstance(benchmark, dict)
    benchmark["horizon"] = "1_year"

    result = _build([_candidate("MISMATCH", 1.0, evidence=evidence)])["MISMATCH"]

    assert result.decision_state == "SOURCE_UNAVAILABLE"
    assert result.expected_net_excess_return is None
    assert result.decision_reason_code == "FORECAST_HORIZON_MISMATCH"


def test_fx_conversion_costs_and_uncertainty_margin_are_in_net_excess(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    evidence = _absolute_evidence(
        available_vwce_registry, forecast_return=0.06, benchmark_return=0.03
    )
    forecast = evidence["forecast"]
    assert isinstance(forecast, dict)
    forecast["currency"] = "USD"
    evidence["fx_conversion"] = {
        "status": "available",
        "from_currency": "USD",
        "to_currency": "EUR",
        "return": 0.02,
        "return_convention": "eur_value_per_candidate_currency",
        "unit": "decimal_fraction",
        "horizon": HORIZON,
        "effective_at": DECISION_TIME,
        "known_at": DECISION_TIME,
        "source_hash": "f" * 64,
    }

    result = _build([_candidate("FX", 1.0, evidence=evidence)])["FX"]

    assert result.expected_net_excess_return == pytest.approx(0.0492)
    assert result.absolute_fx_return == pytest.approx(0.02)
    assert result.decision_state == "CANDIDATE_BUY"


@pytest.mark.parametrize("missing_record", ("fx_conversion", "cost_model"))
def test_missing_fx_or_acquisition_cost_evidence_fails_closed(
    available_vwce_registry: CanonicalBenchmarkRegistry,
    missing_record: str,
) -> None:
    evidence = _absolute_evidence(available_vwce_registry)
    if missing_record == "fx_conversion":
        forecast = evidence["forecast"]
        assert isinstance(forecast, dict)
        forecast["currency"] = "USD"
    else:
        evidence.pop("cost_model")

    result = _build([_candidate("MISSING-INPUT", 1.0, evidence=evidence)])["MISSING-INPUT"]

    assert result.decision_state == "SOURCE_UNAVAILABLE"
    assert result.expected_net_excess_return is None


def test_conflicting_vwce_reference_digest_fails_closed(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    evidence = _absolute_evidence(available_vwce_registry)
    benchmark = evidence["benchmark_reference"]
    assert isinstance(benchmark, dict)
    benchmark["benchmark_digest"] = "f" * 64

    result = _build([_candidate("CONFLICT", 1.0, evidence=evidence)])["CONFLICT"]

    assert result.decision_state == "SOURCE_UNAVAILABLE"
    assert result.decision_reason_code == "VWCE_TOTAL_RETURN_UNVERIFIED"


def test_risk_gate_veto_overrides_a_top_percentile_without_hiding_rank(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    candidates = [
        _candidate(
            "VETOED",
            2.0,
            evidence=_absolute_evidence(available_vwce_registry),
            gate_results=(
                SimpleNamespace(
                    status="BLOCKED", passed=False, reason_code="ECONOMIC_RISK_GATE"
                ),
            ),
        ),
        _candidate("PEER-1", 0.0, evidence=_absolute_evidence(available_vwce_registry)),
        _candidate("PEER-2", -1.0, evidence=_absolute_evidence(available_vwce_registry)),
    ]

    result = _build(candidates)["VETOED"]

    assert result.decision_state == "ECONOMIC_RISK_VETO"
    assert result.percentile == pytest.approx(83.3333333333)
    assert result.universe_rank == 1


def test_hysteresis_keeps_prior_buy_for_a_point_one_percentage_point_change(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    benchmark_return = 0.03
    uncertainty = 0.002
    initial_return = benchmark_return + uncertainty + 0.0205
    changed_return = benchmark_return + uncertainty + 0.0195
    first = _build(
        [
            _candidate(
                "ACME",
                1.0,
                evidence=_absolute_evidence(
                    available_vwce_registry,
                    forecast_return=initial_return,
                    benchmark_return=benchmark_return,
                ),
            )
        ]
    )["ACME"]
    changed = _build(
        [
            _candidate(
                "ACME",
                1.0,
                evidence=_absolute_evidence(
                    available_vwce_registry,
                    forecast_return=changed_return,
                    benchmark_return=benchmark_return,
                    previous_state=first.decision_state,
                ),
            )
        ]
    )["ACME"]

    assert first.decision_state == "CANDIDATE_BUY"
    assert changed.decision_state == "CANDIDATE_BUY"


def test_stale_prior_decision_does_not_silently_drive_hysteresis(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    evidence = _absolute_evidence(
        available_vwce_registry,
        forecast_return=0.0525,
        previous_state="CANDIDATE_BUY",
    )
    previous = evidence["previous_decision"]
    assert isinstance(previous, dict)
    previous["effective_at"] = "2026-09-01T00:00:00Z"
    previous["known_at"] = "2026-09-01T00:00:00Z"

    result = _build([_candidate("ACME", 1.0, evidence=evidence)])["ACME"]

    assert result.decision_state == "SOURCE_UNAVAILABLE"
    assert result.decision_reason_code == "PREVIOUS_DECISION_UNVERIFIED_OR_STALE"


def test_held_position_near_the_hurdle_maps_to_hold_no_trade(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    position = {
        "status": "available",
        "held": True,
        "cost_basis": 100.0,
        "mark_price": 101.0,
        "friction": 0.001,
        "currency": "EUR",
        "friction_unit": "decimal_fraction",
        "effective_at": DECISION_TIME,
        "known_at": DECISION_TIME,
        "source_hash": "e" * 64,
    }
    evidence = _absolute_evidence(
        available_vwce_registry,
        forecast_return=0.0525,
        benchmark_return=0.03,
        position=position,
    )

    result = _build([_candidate("HELD", 1.0, evidence=evidence)])["HELD"]

    assert result.decision_state == "HOLD_NO_TRADE"
    assert result.expected_net_excess_return == pytest.approx(0.0205)
