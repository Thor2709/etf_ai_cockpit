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


@pytest.mark.parametrize("band", ["0.02", "0.5"])
def test_policy_rejects_hysteresis_band_not_below_uncertainty_hurdle(
    tmp_path, band: str
) -> None:
    default = opportunity_module._DEFAULT_CONFIG.read_text(encoding="utf-8")
    assert "hysteresis_band: 0.002" in default
    path = tmp_path / "decision_opportunity_bad_band.yaml"
    path.write_text(
        default.replace("hysteresis_band: 0.002", f"hysteresis_band: {band}"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hysteresis_band"):
        opportunity_module.load_opportunity_policy(path)


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


@pytest.mark.parametrize("bad_state", [["CANDIDATE_BUY"], {}, None, 7])
def test_malformed_prior_state_fails_closed_without_aborting_the_cohort(
    available_vwce_registry: CanonicalBenchmarkRegistry,
    bad_state: object,
) -> None:
    evidence = _absolute_evidence(
        available_vwce_registry,
        forecast_return=0.0525,
        previous_state="CANDIDATE_BUY",
    )
    previous = evidence["previous_decision"]
    assert isinstance(previous, dict)
    previous["state"] = bad_state

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


def _held_position(held: bool) -> dict[str, object]:
    position: dict[str, object] = {
        "status": "available",
        "held": held,
        "currency": "EUR",
        "friction_unit": "decimal_fraction",
        "effective_at": DECISION_TIME,
        "known_at": DECISION_TIME,
        "source_hash": "e" * 64,
    }
    if held:
        position.update({"cost_basis": 100.0, "mark_price": 101.0, "friction": 0.001})
    return position


def test_prior_hold_no_trade_hysteresis_applies_only_to_held_positions(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    def build(held: bool) -> object:
        evidence = _absolute_evidence(
            available_vwce_registry,
            forecast_return=0.0525,
            previous_state="HOLD_NO_TRADE",
            position=_held_position(held),
        )
        return _build([_candidate("ACME", 1.0, evidence=evidence)])["ACME"]

    held = build(True)
    unheld = build(False)

    assert held.decision_state == "HOLD_NO_TRADE"
    assert unheld.decision_state == "CANDIDATE_BUY"
    assert unheld.decision_reason_code == "NET_EXCESS_CLEARS_COST_AND_UNCERTAINTY_HURDLE"


def test_candidate_with_insufficient_status_cannot_be_a_candidate_buy(
    available_vwce_registry: CanonicalBenchmarkRegistry,
) -> None:
    candidate = _candidate(
        "MISSING", 1.0, evidence=_absolute_evidence(available_vwce_registry)
    )
    candidate["underwriting_domains"] = (
        DomainSlot("Underwriting", "INSUFFICIENT_EVIDENCE", None, None, 0.0, 0.0, "MISSING"),
        DomainSlot("Valuation", "AVAILABLE", 1.0, 1.0, 1.0, 0.8, "AVAILABLE"),
    )

    result = _build([candidate])["MISSING"]

    assert result.status == "Insufficient Evidence"
    assert result.decision_state == "SOURCE_UNAVAILABLE"
    assert result.decision_reason_code == "RELATIVE_EVIDENCE_INSUFFICIENT"


def test_bridge_evidence_reaches_the_six_states_through_the_decision_shadow(
    available_vwce_registry: CanonicalBenchmarkRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import dataclasses
    import json
    import math
    import os

    import pandas as pd

    from etf_cockpit.analysis.decision import shadow_run
    from etf_cockpit.application import absolute_merit
    from etf_cockpit.core.config import load_config
    from etf_cockpit.portfolio.costs import estimated_cost_bps

    config = load_config()
    sessions = pd.bdate_range("2026-01-01", periods=160)
    decision = sessions[-1].date()
    realised = 60 * math.log1p(0.001)  # every 60-session outcome of the synthetic prices
    cost = {name: estimated_cost_bps(config, name, 10_000.0) / 1e4 for name in ("VWCE", "UCG")}
    hold = 0.03 - cost["VWCE"] + cost["UCG"] + 0.0185  # net excess 0.0185: inside the band below the hurdle
    forecasts = {"VWCE": 0.03, "LYP6": 0.10, "SPYK": 0.04, "SXRJ_EMU_SMALL": 0.10, "EXX1": 0.10, "MSFT": 0.10, "UCG": hold}
    prices, history, distributions = [], [], {}
    for name, forecast in forecasts.items():
        prices.append(pd.DataFrame({"etf_id": name, "date": sessions, "close": 100 * 1.001 ** pd.RangeIndex(160),
                                    "adjusted_close": 100 * 1.001 ** pd.RangeIndex(160)}))
        miss = [name == "SXRJ_EMU_SMALL" or k % 5 == 0 for k in range(99)]  # ~80% band coverage, or none
        history.append(pd.DataFrame({
            "etf_id": name, "model_name": "baseline", "model_id": "model-A", "model_version": "v1", "target_id": "target-1",
            "prediction_id": [f"{name}-{k}" for k in range(99)], "fold_id": "wf-01", "out_of_fold": True,
            "forecast_date": sessions[:99], "created_at": sessions[:99] + pd.Timedelta(hours=9), "horizon_days": 60,
            "expected_return": realised, "q50_return": realised, "status": "ok", "model_allowed_in_score": True,
            "q10_return": [realised + (0.1 if m else -0.05) for m in miss], "q90_return": [realised + (0.2 if m else 0.05) for m in miss],
        }))
        q50 = math.log1p(forecast)
        distributions[name] = {"status": "available", "model_name": "baseline", "model_id": "model-A", "model_version": "v1",
                               "target_id": "target-1", "horizon_days": 60, "q10_return": q50 - 0.05, "q50_return": q50,
                               "q90_return": q50 + 0.05, "forecast_date": sessions[-2].isoformat()}
    prices, history = pd.concat(prices, ignore_index=True), pd.concat(history, ignore_index=True)
    anchor = dataclasses.replace(available_vwce_registry.benchmarks[0], known_at=sessions[100].isoformat() + "Z", source_hashes=("0" * 64,))
    anchor = dataclasses.replace(anchor, source_hashes=(absolute_merit.vwce_anchor_series_hash(prices, anchor),))
    monkeypatch.setattr(opportunity_module, "load_canonical_benchmark_registry", lambda: CanonicalBenchmarkRegistry(benchmarks=(anchor,)))
    prior = tmp_path / "decision_opportunity_prior.json"
    prior.write_text(json.dumps({
        "decision_time": f"{sessions[-2].date()}T23:59:59Z", "config_hashes": shadow_run._config_hashes(),
        "results": [{"instrument": "UCG", "decision_state": "HOLD_NO_TRADE", "absolute_horizon": "60_sessions"}],
    }), encoding="utf-8")
    published = (sessions[-1] + pd.Timedelta(hours=1)).tz_localize("UTC").timestamp()  # written before the cut-off
    os.utime(prior, (published, published))
    holdings = pd.DataFrame({"as_of_date": [sessions[-2].date()], "etf_id": ["UCG"], "units": [0.0]})
    positions = absolute_merit.positions_from_holdings(holdings, list(forecasts), decision_time=decision)
    stamp = f"{decision}T00:00:00Z"
    positions["UCG"] = {"status": "available", "held": True, "currency": "EUR", "friction_unit": "decimal_fraction",
                        "cost_basis": 100.0, "mark_price": 101.0, "friction": 0.001,
                        "effective_at": stamp, "known_at": stamp, "source_hash": "e" * 64}

    merit = absolute_merit.build_absolute_merit(
        distributions, history, prices, config=config, decision_time=decision,
        prior=absolute_merit.latest_prior_decision(tmp_path, decision), positions=positions,
    )
    vetoed = (SimpleNamespace(status="BLOCKED", passed=False, reason_code="ECONOMIC_RISK_GATE"),)
    candidates = [{**_candidate(name, float(rank), gate_results=vetoed if name == "EXX1" else ()), "score_authority": ScoreAuthorityFlags()}
                  for rank, name in enumerate(forecasts) if name != "VWCE"]
    path = shadow_run.run_decision_shadow(config, [], decision_time=decision, output_directory=tmp_path,
                                          candidates=candidates, absolute_merit=merit)

    results = {row["instrument"]: row for row in json.loads(path.read_text(encoding="utf-8"))["results"]}
    assert {name: row["decision_state"] for name, row in results.items()} == {
        "LYP6": "CANDIDATE_BUY", "SPYK": "POSITIVE_BUT_INSUFFICIENT_MARGIN", "SXRJ_EMU_SMALL": "RETURN_NOT_CALIBRATED",
        "EXX1": "ECONOMIC_RISK_VETO", "MSFT": "SOURCE_UNAVAILABLE", "UCG": "HOLD_NO_TRADE"}
    assert results["MSFT"]["decision_reason_code"] == "FX_CONVERSION_UNAVAILABLE"  # a USD forecast without fx evidence
    assert merit["UCG"]["absolute_merit_evidence"]["previous_decision"]["state"] == "HOLD_NO_TRADE"


def test_positions_from_holdings_use_only_snapshots_known_by_the_decision() -> None:
    from datetime import date

    import pandas as pd

    from etf_cockpit.application.absolute_merit import positions_from_holdings

    holdings = pd.DataFrame({"as_of_date": [date(2026, 9, 1), date(2026, 10, 15)], "etf_id": ["AAA", "AAA"], "units": [5.0, 0.0]})
    # The newest snapshot is after the decision: it must not leak, and the earlier valid evidence must stay.
    assert positions_from_holdings(holdings, ["AAA"], decision_time=date(2026, 9, 30))["AAA"]["held"] is True
    assert positions_from_holdings(holdings, ["AAA"], decision_time=date(2026, 10, 15))["AAA"]["held"] is False
    # No snapshot by the decision: unavailable, not the later snapshot.
    assert positions_from_holdings(holdings, ["AAA"], decision_time=date(2026, 8, 31)) == {}
    # A snapshot imported after the decision is not known yet.
    imported = holdings.assign(known_at=["2026-09-02T00:00:00Z", "2026-10-16T00:00:00Z"])
    assert positions_from_holdings(imported.iloc[[1]], ["AAA"], decision_time=date(2026, 10, 15)) == {}
