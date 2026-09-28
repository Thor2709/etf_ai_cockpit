from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.analysis.sparebank.valuation import (
    buyback_accretion,
    capital_release,
    days_to_trade,
    dividend_valuation,
    executable_order,
    implied_required_return,
    implied_roe,
    owner_valuation,
    residual_income_valuation,
    scenario_value,
    stable_pb,
    valuation,
)


FIXTURE = Path(__file__).parent / "fixtures" / "sparebank" / "valuation.json"


def _claim():
    payload = json.loads((Path(__file__).parent / "fixtures" / "sparebank" / "teaching_bank.json").read_text())
    payload["facts"]["eierbrok"] = {"available": True, "value": 0.4}
    return build_claim_state(payload)


def test_owner_claim_uses_matched_counts_and_rejects_mismatch():
    result = owner_valuation(_claim(), price=100)
    assert result["owner_pb"] == pytest.approx(1.0)
    assert result["owner_pe"] == pytest.approx(8.3333333333)
    with pytest.raises(ValueError):
        owner_valuation(_claim(), price=100, count_convention={"book": "weighted_average_ec_count", "earnings": "period_end_ec_count"})


def test_stable_model_and_clean_surplus_recovery():
    fixture = json.loads(FIXTURE.read_text())
    for raw_r, expected in fixture["stable"]["r"].items():
        assert stable_pb(float(raw_r), fixture["stable"]["k"], fixture["stable"]["g"])["pb"] == pytest.approx(expected, abs=0.01)
    with pytest.raises(ValueError):
        stable_pb(0.08, 0.03, 0.03)
    with pytest.raises(ValueError):
        stable_pb(0.08, 0.10, 0.09)
    dividend = dividend_valuation(100, (0.08, 0.10, 0.12), 0.60, required_return=0.10, terminal_return=0.12, terminal_growth=0.03)
    residual = residual_income_valuation(100, (0.08, 0.10, 0.12), 0.10, payout=0.60, terminal_return=0.12, terminal_growth=0.03)
    assert dividend["value"] == pytest.approx(residual["value"], abs=0.01)


def test_reverse_golden():
    fixture = json.loads(FIXTURE.read_text())["reverse"]
    assert implied_roe(fixture["pb"], fixture["k"], fixture["g"]) == pytest.approx(fixture["implied_r"])
    assert implied_required_return(fixture["pb"], fixture["r"], fixture["g"]) == pytest.approx(fixture["implied_k"], abs=0.0001)


def test_capital_release_and_buyback_accretion():
    release = capital_release(100, 9.90, 10, 0.20)
    assert release["earnings_after"] == pytest.approx(9.70)
    assert release["operating_value"] == pytest.approx(110)
    buyback = buyback_accretion(100, 120, 10, 2, 9)
    assert buyback["book_accretion"] > 0
    assert buyback["intrinsic_accretion_eligible"]


def test_scenarios_require_explicit_weights_and_marketability_is_an_input():
    assert scenario_value(None)["status"] == "unavailable"
    result = scenario_value([
        {"name": "weaker", "weight": 0.5, "value": 90},
        {"name": "operating", "weight": 0.5, "value": 110},
    ])
    assert result["value"] == pytest.approx(100)
    assert result["weight_semantics"] == "operator_supplied"


def test_order_size_and_days_to_trade_fallback():
    order = executable_order(2000, [{"price": 90, "quantity": 500}, {"price": 91, "quantity": 500}, {"price": 94, "quantity": 2000}], fees=200)
    assert order["vwap"] == pytest.approx(92.25)
    assert order["all_in_price"] == pytest.approx(92.35)
    assert days_to_trade(250000, 500000, 0.10) == pytest.approx(5.0)
    fallback = executable_order(2000, None)
    assert fallback["status"] == "unavailable"
    assert fallback["execution_cost_model"] == "execution-cost-v1"


def test_suite_valuation_assembles_four_state_recovery_policy_irr_and_decision_price() -> None:
    assumptions = {
        "timestamp": "2025-01-01T00:00:00Z",
        "currency": "NOK",
        "quantity": 4,
        "recovery": {"book_value": 100, "dividends": (8, 10), "terminal_value": 110, "required_return": 0.10},
        "four_state": {"weights": (0.25, 0.25, 0.25, 0.25), "values": (70, 99, 106, 113)},
        "marketability": {"with_marketability": 100, "without_marketability": 95},
        "capital_policy": {"book_value": 100, "earnings": 9.9, "release": 10, "earnings_on_released_capital": 0.2},
        "irr": {"price": 90, "cash_flows": (10, 110)},
        "decision_price": {"value": 100, "hurdle": 0.08, "years": 1, "exit_cost": 0.005},
    }
    result = valuation(_claim(), price=90, assumptions=assumptions)
    assert result["status"] == "resolved"
    assert result["four_state"]["value"] == pytest.approx(97)
    assert result["marketability"]["without_marketability"] == pytest.approx(95)
    assert result["capital_policy"]["operating_value"] == pytest.approx(110)
    assert result["irr"]["irr"] is not None
    assert result["decision_price"]["price"] == pytest.approx(92.1296296)
    assert result["timestamp"] == assumptions["timestamp"]
    assert valuation(_claim(), price=110, assumptions=assumptions)["four_state"]["value"] == result["four_state"]["value"]
