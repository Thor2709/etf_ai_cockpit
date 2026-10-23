"""Regression tests for lane SB (A17-F1..F8) of PLAN-FIX-20261023."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.analysis.sparebank import analyse_sparebank_ec
from etf_cockpit.analysis.sparebank.bank_economics import build_bank_economics
from etf_cockpit.analysis.sparebank.book_calcs import justified_price_to_book
from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.analysis.sparebank.events import analyse_events, conversion_event, deficit_coverage
from etf_cockpit.analysis.sparebank.models import ECClaimState
from etf_cockpit.analysis.sparebank.scorecard import _rating
from etf_cockpit.analysis.sparebank.valuation import capital_release

FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"
DECISION = "2025-01-02T00:00:00Z"
ASSUMPTIONS = {"cost_of_equity": 0.05, "sustainable_roe": 0.08, "long_run_growth": 0.02}


def _teaching_bank() -> dict[str, object]:
    return json.loads((FIXTURES / "teaching_bank.json").read_text(encoding="utf-8"))


def _analysis(*, funding: dict[str, object] | None = None, decision_time: str | None = DECISION):
    economics: dict[str, object] = {
        "reported_earnings": 100.0, "average_common_equity": 1000.0, "cet1": 150.0, "ppp": 0.0, "credit_loss": 0.0,
        "rwa": 1000.0, "target_ratio": 0.1,
        "funding": funding or {"lcr": 2.0, "nsfr": 1.2, "provenance": {"lcr": "fixture:lcr", "nsfr": "fixture:nsfr"}},
        "provenance": {name: f"fixture:{name}" for name in ("cet1", "ppp", "credit_loss", "rwa", "target_ratio")},
    }
    return analyse_sparebank_ec(
        _teaching_bank(),
        decision_time=decision_time,
        price=100.0,
        bank_metrics=({"metric": "cost_of_risk", "value": 0.001, "source_id": "fixture:cost-of-risk"},),
        bank_economics_evidence=economics,
        valuation_assumptions=dict(ASSUMPTIONS),
    )


def _inputs(scorecard) -> dict[str, dict[str, object]]:
    return {row["id"]: row for axis in scorecard.axes.values() for row in axis["inputs"]}


def test_scorecard_hard_gate_survives_missing_provenance() -> None:
    # A17-F1: a breached LCR without provenance is withheld from display but still caps the composite.
    result = _analysis(funding={"lcr": 0.8, "nsfr": 1.2}).scorecard
    rows = _inputs(result)
    assert rows["lcr_pct"]["value"] is None
    assert "LCR_BELOW_MINIMUM" in result.gate_reasons
    assert result.gate_cap_10 == 3.0
    # A resolved normalised ROE keeps its provenance, so the spread input is rated instead of wiped.
    assert rows["normalised_roe_minus_cost_of_equity_pp"]["value"] == pytest.approx(3.0)
    assert rows["normalised_roe_minus_cost_of_equity_pp"]["status"] == "rated"
    # Supplying a CET1 ratio provenance merges with, and never overwrites, the headroom provenance.
    bank = build_bank_economics({
        "cet1": 150.0, "ppp": 0.0, "credit_loss": 0.0, "rwa": 1000.0, "target_ratio": 0.1,
        "provenance": {name: f"fixture:{name}" for name in ("cet1", "ppp", "credit_loss", "rwa", "target_ratio")},
        "cet1_ratio": 0.15, "cet1_ratio_provenance": {"source_locator": "fixture:ratio"},
    })
    assert {"headroom_pp", "cet1_ratio"} <= set(bank.resilience["provenance"])


def test_sparebank_future_claim_is_unavailable() -> None:
    # A17-F2: a claim known after the decision time yields no owner normalisation, valuation or composite.
    result = _analysis(decision_time="2024-12-31T00:00:00Z")
    assert result.claim_state.claim_status == "stale"
    assert result.bank_economics.normalised["normalised_roe"] is None
    assert result.valuation["status"] == "unavailable"
    assert result.valuation["central_owner_value_per_ec"]["status"] == "unavailable"
    assert result.scorecard.composite_10 is None
    assert result.scorecard.composite_before_gate_cap_10 is None
    # Without a decision time the point-in-time check cannot be verified: owner values stay unavailable too.
    unverified = _analysis(decision_time=None)
    assert unverified.bank_economics.normalised["normalised_roe"] is None
    assert unverified.valuation["status"] == "unavailable"


def test_deficit_coverage_missing_pool_fails_closed() -> None:
    # A17-F3: a missing or negative pool is unavailable, never zero-filled; nominal absorption counts as owner share.
    assert deficit_coverage(100, owner_nominal=100, owner_premium_fund=0, self_owned_capital=None)["status"] == "unavailable"  # type: ignore[arg-type]
    assert deficit_coverage(100, owner_nominal=100, owner_premium_fund=-1, self_owned_capital=0)["status"] == "unavailable"
    covered = deficit_coverage(100, owner_nominal=100, owner_premium_fund=0, self_owned_capital=0)
    assert covered["status"] == "resolved"
    assert covered["owner_share_of_deficit"] == pytest.approx(1.0)


def test_justified_pb_rejects_growth_at_roe_and_capital_release_reduces_book() -> None:
    # A17-F4: growth at or above ROE has no stable value (was clamped to 0.0).
    assert justified_price_to_book(0.02, 0.10, 0.03) is None
    assert justified_price_to_book(0.03, 0.10, 0.03) is None
    assert justified_price_to_book(0.12, 0.09, 0.03) == pytest.approx(1.5)
    # A17-F5: released capital leaves the operating book.
    release = capital_release(book_value=500, earnings=52, release=100, earnings_on_released_capital=2)
    assert release["operating_value"] == pytest.approx(400)
    assert release["operating_return"] == pytest.approx(50 / 400)
    with pytest.raises(ValueError):
        capital_release(book_value=100, earnings=5, release=100, earnings_on_released_capital=0)


def test_conversion_and_buyback_dispatch() -> None:
    # A17-F6: unset dataclass fields fall back to the alternative count/eierbrok; buyback events are dispatched.
    event = conversion_event(ECClaimState(registered_ec_count=1000, reported_eierbrok=0.6), 200, converted_capital=100)
    assert event["post_state"]["outstanding_ec_count"] == pytest.approx(1200)
    assert event["allocation_weight_old_holders"] is not None
    analysis = analyse_events([{"event_type": "buyback", "quantity": 10, "price": 100, "pre_count": 1000}])
    assert [item["event_type"] for item in analysis.events] == ["buyback"]
    assert analysis.status != "partial"


def test_claim_period_conflict_for_ownerless_pool() -> None:
    # A17-F7: an ownerless pool from another statement period conflicts the claim.
    evidence = _teaching_bank()
    facts = evidence["facts"]
    facts["sparebankens_fond"]["period"] = "2023-12-31"
    claim = build_claim_state(evidence, decision_time=DECISION)
    assert "CLAIM_STATEMENT_PERIOD_CONFLICT" in claim.reason_codes
    assert claim.claim_status != "resolved"


def test_scorecard_display_axes_and_anchor_order() -> None:
    # A17-F8: display-only axes are covered by their display inputs; anchors sort by value, not rating.
    anchors = [{"value": 30, "rating": 0}, {"value": 0, "rating": 10}, {"value": 10, "rating": 6}]
    assert _rating(5, anchors) == pytest.approx(8.0)
    assert _rating(20, anchors) == pytest.approx(3.0)
    full = _analysis().scorecard
    assert "portfolio_context" not in full.missing_axes  # no inputs at all: excluded, not a coverage gap
    allocation = full.axes["capital_allocation"]
    shown = [row for row in allocation["inputs"] if row["value"] is not None]
    assert allocation["coverage"] == pytest.approx(len(shown) / len(allocation["inputs"]))
