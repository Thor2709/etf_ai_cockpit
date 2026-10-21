"""#980 Bughunt C/D: stress testing and factor exposure (native RED tests; each names its register ID)."""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application import stress_lab
from etf_cockpit.application.portfolio_sandbox import analyse_portfolio_candidate, build_portfolio_candidate
from etf_cockpit.portfolio.factor_risk import (
    build_factor_exposures,
    build_factor_risk_report,
)
from etf_cockpit.portfolio.stress_testing import (
    StressScenario,
    reverse_stress,
    run_stress_scenario,
)
from test_factor_risk import _fixture as _factor_fixture
from test_portfolio_sandbox import _snapshot


def _usd_equity(**extra: object) -> pd.DataFrame:
    return pd.DataFrame([{"instrument_id": "USEQ", "weight": 1.0, "asset_class": "equity", "currency": "USD", **extra}])


# --- D109-N001 ---------------------------------------------------------------------------------

def test_d109_n001_fx_shock_applies_to_unhedged_foreign_currency_equity() -> None:
    result = run_stress_scenario(StressScenario("fx", "FX -20%", {"fx": -0.20}), _usd_equity(), notional=100_000)

    assert result.status == "available"
    assert result.total_pnl == pytest.approx(-20_000.0)
    assert {row["factor"]: row["pnl"] for row in result.factor_contributions}["fx"] == pytest.approx(-20_000.0)


def test_d109_n001_fx_shock_skips_base_currency_and_hedged_exposure() -> None:
    scenario = StressScenario("fx", "FX -20%", {"fx": -0.20, "equity": -0.10})
    base = run_stress_scenario(scenario, _usd_equity().assign(currency="EUR"), notional=100_000)
    hedged = run_stress_scenario(scenario, _usd_equity(currency_hedged=True), notional=100_000)
    partly = run_stress_scenario(scenario, _usd_equity(hedge_ratio=0.5), notional=100_000)

    assert base.total_pnl == pytest.approx(-10_000.0)
    assert hedged.total_pnl == pytest.approx(-10_000.0)
    assert partly.total_pnl == pytest.approx(-20_000.0)


# --- D109-N002 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("shocks", [{"rates": 0.01}, {"credit": -0.03}, {"commodity": -0.2}])
def test_d109_n002_zero_applicable_components_is_unavailable_not_zero_available(shocks: dict[str, float]) -> None:
    allocation = pd.DataFrame([{"instrument_id": "EQ", "weight": 1.0, "asset_class": "equity", "currency": "EUR"}])

    result = run_stress_scenario(StressScenario("na", "Not applicable", shocks), allocation, notional=100_000)

    assert result.status == "unavailable"
    assert result.total_pnl is None
    assert result.coverage["status"] == "unavailable"
    assert result.coverage["covered_instruments"] == 0
    assert result.coverage["missing_instruments"] == ["EQ"]


def test_d109_n002_mixed_applicability_is_partial_with_per_holding_coverage() -> None:
    allocation = pd.DataFrame(
        [
            {"instrument_id": "EQ", "weight": 0.5, "asset_class": "equity"},
            {"instrument_id": "BOND", "weight": 0.5, "asset_class": "bond"},
        ]
    )

    result = run_stress_scenario(StressScenario("rate", "Rates", {"rates": -0.02}), allocation, notional=100_000)

    assert result.status == "partial"
    assert result.coverage["missing_instruments"] == ["EQ"]
    assert result.total_pnl == pytest.approx(-1_000.0)


def test_d109_n002_explicit_zero_shock_on_applicable_holding_stays_available() -> None:
    allocation = pd.DataFrame([{"instrument_id": "EQ", "weight": 1.0, "asset_class": "equity"}])

    result = run_stress_scenario(StressScenario("zero", "Zero", {"equity": 0.0}), allocation, notional=100_000)

    assert result.status == "available"
    assert result.total_pnl == pytest.approx(0.0)


# --- D109-N003 ---------------------------------------------------------------------------------

def test_d109_n003_factor_contributions_reconcile_with_instrument_total() -> None:
    allocation = pd.DataFrame([{"instrument_id": "EQ", "weight": 1.0, "asset_class": "equity"}])
    exposures = pd.DataFrame([{"instrument_id": "EQ", "factor": "equity", "exposure": 0.5}])

    result = run_stress_scenario(
        StressScenario("eq", "Equity -10%", {"equity": -0.10}), allocation, factor_exposures=exposures, notional=100_000
    )

    assert result.total_pnl == pytest.approx(-15_000.0)
    assert sum(float(row["pnl"]) for row in result.factor_contributions) == pytest.approx(result.total_pnl)
    by_factor = {row["factor"]: row["pnl"] for row in result.factor_contributions}
    assert by_factor["residual"] == pytest.approx(0.0)
    instrument = result.instrument_contributions[0]
    assert sum(instrument["factor_components"].values()) == pytest.approx(instrument["shock"])


# --- D109-N004 ---------------------------------------------------------------------------------

def test_d109_n004_missing_price_is_not_bridged_in_stress_returns() -> None:
    prices = pd.DataFrame(
        [
            {"etf_id": "A", "date": "2026-01-01", "adjusted_close": 100.0},
            {"etf_id": "A", "date": "2026-01-02", "adjusted_close": np.nan},
            {"etf_id": "A", "date": "2026-01-03", "adjusted_close": 121.0},
        ]
    )

    returns = stress_lab._adjusted_returns(prices)
    assert returns is not None
    jan3 = returns[returns["date"].eq(pd.Timestamp("2026-01-03"))]
    assert jan3["adjusted_return"].isna().all()  # never the bridged +21%

    allocation = pd.DataFrame([{"instrument_id": "A", "weight": 1.0}])
    result = run_stress_scenario(
        StressScenario("hist", "Historical", {"equity": -0.1}, historical_date="2026-01-03"),
        allocation,
        historical_returns=returns,
        notional=100_000,
    )
    assert result.status == "unavailable"
    assert result.total_pnl is None


def test_d109_n004_complete_prices_still_give_the_daily_return() -> None:
    prices = pd.DataFrame(
        [{"etf_id": "A", "date": f"2026-01-0{day}", "adjusted_close": price} for day, price in ((1, 100.0), (2, 110.0), (3, 121.0))]
    )
    returns = stress_lab._adjusted_returns(prices)
    jan3 = returns[returns["date"].eq(pd.Timestamp("2026-01-03"))]
    assert float(jan3["adjusted_return"].iloc[0]) == pytest.approx(0.10)


# --- D013-N003 / N004 / N005 (portfolio sandbox) ---------------------------------------------------

def _priced_snapshot(**scenarios: object):
    snapshot = _snapshot()
    snapshot.prices = pd.DataFrame(
        [
            {"date": f"2026-07-{day:02d}", "etf_id": instrument_id, "adjusted_close": base * (1.0 + (0.01 if day % 2 else -0.005)) ** day}
            for day in range(1, 20)
            for instrument_id, base in (("VWCE", 100.0), ("LYP6", 80.0))
        ]
    )
    for name, value in scenarios.items():
        setattr(snapshot, name, value)
    return snapshot


def _candidate(snapshot):
    return build_portfolio_candidate(
        snapshot, name="Core", analysis_notional_eur=100_000, target_weights={"VWCE": 0.6, "LYP6": 0.3}, cash_weight=0.1
    )


def test_d013_n003_historical_stress_receives_historical_returns() -> None:
    scenario = StressScenario("hist", "Historical", {"equity": -0.5}, historical_date="2026-07-10")
    snapshot = _priced_snapshot(stress_scenarios=[scenario])

    analysis = analyse_portfolio_candidate(snapshot, _candidate(snapshot))

    result = analysis.service_evidence["scenarios"]["results"][0]
    assert result["status"] in {"available", "partial"}
    assert {row["source"] for row in result["instrument_contributions"]} == {"historical_adjusted_return"}


def test_d013_n004_aggregate_scenario_status_is_the_worst_component() -> None:
    good = StressScenario("good", "Equity", {"equity": -0.1})
    na = StressScenario("na", "Rates only", {"rates": -0.02})
    snapshot = _priced_snapshot(stress_scenarios=[good, na])
    mixed = analyse_portfolio_candidate(snapshot, _candidate(snapshot)).service_evidence["scenarios"]
    assert [item["status"] for item in mixed["results"]] == ["available", "unavailable"]
    assert mixed["status"] == "unavailable"

    snapshot = _priced_snapshot(stress_scenarios=[na])
    only_unavailable = analyse_portfolio_candidate(snapshot, _candidate(snapshot)).service_evidence["scenarios"]
    assert only_unavailable["status"] == "unavailable"

    snapshot = _priced_snapshot(stress_scenarios=[good])
    only_good = analyse_portfolio_candidate(snapshot, _candidate(snapshot)).service_evidence["scenarios"]
    assert only_good["status"] == "available"


def test_d013_n005_exiting_disjoint_instrument_does_not_block_target_only_risk() -> None:
    snapshot = _priced_snapshot()
    snapshot.holdings = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.3, "market_value_eur": 30_000.0},
            {"etf_id": "LYP6", "current_weight": 0.3, "market_value_eur": 30_000.0},
            {"etf_id": "SPYK", "current_weight": 0.3, "market_value_eur": 30_000.0},
        ]
    )
    exit_rows = pd.DataFrame(
        [{"date": f"2026-06-{day:02d}", "etf_id": "SPYK", "adjusted_close": 60.0 + day} for day in range(1, 15)]
    )
    snapshot.prices = pd.concat([snapshot.prices, exit_rows], ignore_index=True)
    candidate = build_portfolio_candidate(
        snapshot, name="Exit SPYK", analysis_notional_eur=100_000, target_weights={"VWCE": 0.3, "LYP6": 0.3}, cash_weight=0.4
    )

    evidence = analyse_portfolio_candidate(snapshot, candidate).service_evidence

    for name in ("factor_risk", "risk", "correlation"):
        reason = str(evidence[name].get("reason", ""))
        assert "insufficient_joint_adjusted_returns" not in reason, name
    assert evidence["correlation"]["status"] == "available"
    # The optimiser still needs the exiting instrument's returns for its turnover claim.
    assert evidence["optimiser"]["status"] == "unavailable"


# --- D.C3.S09.N005 -------------------------------------------------------------------------------

def test_reverse_stress_with_no_applicable_exposure_is_unavailable_not_not_reached() -> None:
    allocation = pd.DataFrame([{"instrument_id": "EQ", "weight": 1.0, "asset_class": "equity"}])

    result = reverse_stress(allocation, shock_name="rates", loss_limit=10_000, notional=100_000)

    assert result["status"] == "unavailable"
    assert result["threshold"] is None
    assert result["reason"]


# --- C021-N003 -----------------------------------------------------------------------------------

def test_c021_n003_factor_report_labels_current_exposure_replay() -> None:
    prices, allocation, features = _factor_fixture()

    report = build_factor_risk_report(prices, allocation, features)

    assert report["status"] in {"available", "partial"}
    assert report["exposure_basis"] == "current_exposure_replay"
    assert report["diagnostics"]["exposure_basis"] == "current_exposure_replay"
    assert "current_exposure_replay" in report["warnings"]


# --- D004 (geographic categorisation) ---------------------------------------------------------------

def test_d004_country_dimension_uses_national_source_not_regional() -> None:
    allocation = pd.DataFrame([{"etf_id": "E1", "current_weight": 1.0, "region": "Europe", "country": "Germany"}])
    holdings = pd.DataFrame(
        [
            {"instrument_id": "E1", "weight": 0.6, "region": "Europe", "country": "Germany"},
            {"instrument_id": "E1", "weight": 0.4, "region": "Europe", "country": "France"},
        ]
    )

    exposures = build_factor_exposures(allocation, None, holdings)
    factors = set(exposures["factor"])
    assert {"country:Germany", "country:France"} <= factors
    assert "country:Europe" not in factors

    metadata_only = build_factor_exposures(allocation, None, None)
    assert "country:Germany" in set(metadata_only["factor"])
    assert "country:Europe" not in set(metadata_only["factor"])


def test_d004_regional_only_label_is_not_presented_as_a_country() -> None:
    allocation = pd.DataFrame([{"etf_id": "E1", "current_weight": 1.0, "region": "Europe"}])

    exposures = build_factor_exposures(allocation, None, None)

    country = exposures[exposures["factor"].astype(str).str.startswith("country:")]
    assert country.empty or set(country["descriptor"]) == {"region_proxy"}


# --- V8 intake: synthetic scenarios -----------------------------------------------------------------

def _synthetic():
    from etf_cockpit.features.synthetic_scenarios import SyntheticScenarioGenerator, SyntheticScenarioSpec

    return SyntheticScenarioGenerator, SyntheticScenarioGenerator().generate(SyntheticScenarioSpec(periods=40))


def test_c3_s23_n001_validate_recomputes_the_content_hash() -> None:
    from dataclasses import replace

    generator, dataset = _synthetic()
    assert generator.validate(dataset)["status"] == "pass"
    assert generator.validate(dataset)["dataset_hash_verified"] is True

    tampered_prices = dataset.prices.copy()
    tampered_prices.loc[tampered_prices.index[3], ["close", "adjusted_close"]] = 500.0
    evidence = generator.validate(replace(dataset, prices=tampered_prices))

    assert evidence["status"] == "fail"
    assert evidence["dataset_hash_verified"] is False


def test_c3_s23_n002_validate_requires_the_price_schema() -> None:
    from dataclasses import replace

    generator, dataset = _synthetic()
    no_columns = replace(dataset, prices=dataset.prices.drop(columns=["close", "adjusted_close"]))
    empty = replace(dataset, prices=dataset.prices.iloc[0:0])

    for broken in (no_columns, empty):
        evidence = generator.validate(broken)
        assert evidence["status"] == "fail"
        assert evidence["price_schema_complete"] is False


def test_c2_s23_n002_synthetic_dates_follow_a_session_calendar_not_calendar_days() -> None:
    _generator, dataset = _synthetic()

    dates = pd.to_datetime(dataset.prices["date"]).drop_duplicates()
    assert (dates.dt.dayofweek < 5).all()
