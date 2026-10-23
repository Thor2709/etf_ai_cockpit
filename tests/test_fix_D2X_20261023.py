"""D2X: never-collected ETF exposure is non-blocking per owner decision D2; stale/invalid evidence still fails."""

from __future__ import annotations

import pytest

from etf_cockpit.analysis.decision import gates

DECISION = "2026-10-09T00:00:00+00:00"
FRESH = "2026-10-01"
STALE = "2024-01-01"


def _by_id(results):
    return {r.gate_id: r for r in results}


def test_absent_etf_exposure_passes_and_stays_visible() -> None:
    results = gates.evaluate_critical_gates("ETF", {"identity": None, "liquidity_cost": FRESH}, decision_time=DECISION)
    exposure = _by_id(results)["exposure"]
    assert exposure.passed and exposure.reason_code == gates.GATE_REASON_NOT_AVAILABLE and exposure.missing == ("etf_exposure",)
    assert not gates.blocks_buy_label(results) and not gates.failed_gates(results)


@pytest.mark.parametrize("as_of, reason", [(STALE, gates.GATE_REASON_STALE), ("2027-01-01", gates.GATE_REASON_INVALID), ("garbage", gates.GATE_REASON_INVALID)])
def test_present_but_stale_or_invalid_exposure_still_fails(as_of: str, reason: str) -> None:
    results = gates.evaluate_critical_gates(
        "ETF", {"identity": None, "liquidity_cost": FRESH, "etf_exposure": as_of}, decision_time=DECISION
    )
    exposure = _by_id(results)["exposure"]
    assert not exposure.passed and exposure.reason_code == reason
    assert gates.blocks_buy_label(results)


def test_etf_identity_and_cost_missing_still_fail() -> None:
    results = _by_id(gates.evaluate_critical_gates("ETF", {"etf_exposure": FRESH}, decision_time=DECISION))
    assert not results["identity"].passed and not results["cost"].passed
    assert results["identity"].reason_code == "CRITICAL_EVIDENCE_MISSING"
    assert results["exposure"].passed and results["exposure"].reason_code == "EVIDENCE_PRESENT"


def test_stock_gates_unchanged() -> None:
    policy = gates.load_critical_evidence_policy()
    assert all(d.blocking_when_missing for d in policy.gates["STOCK"] + policy.gates["BANK"])
    assert [d.gate_id for d in policy.gates["ETF"] if not d.blocking_when_missing] == ["exposure"]
    stock = gates.evaluate_critical_gates("STOCK", set(), decision_time=DECISION)
    assert stock and all(not r.passed and r.reason_code == "CRITICAL_EVIDENCE_MISSING" for r in stock)
