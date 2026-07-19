from __future__ import annotations

from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.stress_lab import StressLabFacade, StressLabPersistenceError, build_stress_scenario
from etf_cockpit.data.local_storage import StorageRevisionConflict
from etf_cockpit.portfolio.stress_testing import StressScenario, StressScenarioError, reverse_stress, run_stress_scenario


def _allocation() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "etf_id": ["EQUITY", "BOND"],
            "current_weight": [0.6, 0.4],
            "asset_class": ["equity", "bond"],
        }
    )


def test_known_shock_reconciles_instrument_and_factor_pnl() -> None:
    scenario = StressScenario("known", "Known shock", {"equity": -0.10, "rates": -0.02, "credit": -0.03, "liquidity": 0.01})
    result = run_stress_scenario(
        scenario,
        _allocation(),
        notional=100_000,
        factor_exposures=pd.DataFrame(
            {"instrument_id": ["EQUITY"], "factor": ["market"], "exposure": [0.0]}
        ),
    )

    assert result.status == "available"
    assert result.total_pnl == pytest.approx(-9_000)
    assert sum(float(row["pnl"]) for row in result.instrument_contributions) == pytest.approx(result.total_pnl)
    assert sum(float(row["pnl"]) for row in result.factor_contributions) == pytest.approx(result.total_pnl)
    assert result.instrument_contributions[1]["source"] == "hypothetical_explicit_shock"


def test_factor_shock_and_wide_exposure_matrix_are_visible() -> None:
    scenario = StressScenario("factor", "Factor shock", {"factor:value": -0.2})
    allocation = pd.DataFrame({"instrument_id": ["EQUITY"], "weight": [1.0], "asset_class": ["equity"]})
    exposures = pd.DataFrame({"instrument_id": ["EQUITY"], "value": [0.5]})

    result = run_stress_scenario(scenario, allocation, factor_exposures=exposures, notional=100_000)

    assert result.total_pnl == pytest.approx(-10_000)
    assert result.instrument_contributions[0]["factor_components"] == {"factor:value": -0.1, "residual": 0.0}


def test_historical_replay_requires_exact_adjusted_return_date() -> None:
    scenario = StressScenario("historical", "Historical", {"equity": -0.5}, historical_date="2026-01-02")
    allocation = pd.DataFrame({"instrument_id": ["EQUITY"], "weight": [1.0], "asset_class": ["equity"]})
    returns = pd.DataFrame({"instrument_id": ["EQUITY"], "date": ["2026-01-02"], "adjusted_return": [-0.03]})

    result = run_stress_scenario(scenario, allocation, historical_returns=returns, notional=100_000)
    unavailable = run_stress_scenario(
        StressScenario("missing", "Missing", {"equity": -0.5}, historical_date="2026-01-03"),
        allocation,
        historical_returns=returns,
        notional=100_000,
    )

    assert result.total_pnl == pytest.approx(-3_000)
    assert result.instrument_contributions[0]["source"] == "historical_adjusted_return"
    assert unavailable.status == "unavailable"
    assert unavailable.total_pnl is None


def test_reverse_stress_returns_threshold_and_binding_instrument() -> None:
    allocation = pd.DataFrame({"instrument_id": ["EQUITY"], "weight": [1.0], "asset_class": ["equity"]})

    result = reverse_stress(allocation, shock_name="equity", loss_limit=10_000, notional=100_000)

    assert result["status"] == "available"
    assert result["threshold"] == pytest.approx(0.1, abs=1e-8)
    assert result["binding_exposure"]["instrument_id"] == "EQUITY"


def test_scenario_validation_and_persistence_are_versioned_and_no_execution(tmp_path: Path) -> None:
    with pytest.raises(StressScenarioError):
        StressScenario("", "invalid", {"equity": 0.1})
    with pytest.raises(StressScenarioError):
        StressScenario("bad", "invalid", {"equity": 0.1}, version=0)
    with pytest.raises(StressScenarioError, match="horizon_days"):
        build_stress_scenario(scenario_id="fractional", name="Invalid", shocks={"equity": -0.1}, horizon_days=1.5)
    scenario = build_stress_scenario(scenario_id="saved", name="Saved", shocks={"equity": -0.1})
    facade = StressLabFacade(SimpleNamespace(holdings=pd.DataFrame()), root=tmp_path)

    saved = facade.save(scenario)
    loaded = facade.load("saved")

    assert saved.revision == 1
    assert loaded.scenario.to_payload() == scenario.to_payload()
    assert scenario.to_payload()["execution_allowed"] is False
    with pytest.raises(StorageRevisionConflict):
        facade.save(scenario, expected_revision=0)

    record_path = tmp_path / "data" / "storage" / "cockpit.sqlite3"
    assert record_path.exists()
    with sqlite3.connect(record_path) as connection:
        connection.execute(
            "UPDATE transactional_records SET payload_json = ? WHERE entity_type = ? AND entity_id = ?",
            ('{"tampered":true}', "stress_scenario", "saved"),
        )
    with pytest.raises(StressLabPersistenceError, match="invalid field set"):
        facade.load("saved")
