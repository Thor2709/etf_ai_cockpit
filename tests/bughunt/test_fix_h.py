"""Extra focused tests for bug-hunt group H (S4-02 deficit waterfall, S4-07 percentage dilution)."""

from __future__ import annotations

import pytest

from etf_cockpit.analysis.innovation_sector_adapters import (
    InnovationMetricEvidence,
    build_innovation_projection,
    innovation_adapter_definitions,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.analysis.sparebank.events import analyse_events, deficit_coverage
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority as A

_T, _E = "2025-03-01T00:00:00Z", "2024-12-31T00:00:00Z"


def _projection(model, sector, metrics):
    values = {
        "instrument_type": "stock", "asset_class": "equity", "sector": sector,
        "industry": model, "business_model_tag": model,
    }
    facts = [
        ClassificationEvidence(
            f, "X", f, v, "issuer", A.OFFICIAL, "s" + f, 0.99, "2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for f, v in values.items()
    ]
    ctx = resolve_instrument_context(facts, instrument_id="X", effective_at=_E, decision_time=_T)
    evidence = [
        InnovationMetricEvidence(
            n, v, u, "FY2024", "IFRS", "AU", model, "issuer:" + n, A.ISSUER, _E,
            "2025-02-15T00:00:00Z",
        )
        for n, v, u in metrics
    ]
    return build_innovation_projection(
        ctx, evidence, registry=AdapterRegistry(innovation_adapter_definitions()), decision_time=_T
    )


def _software(dilution_percent):
    return _projection(
        "software", "technology",
        [("basic_shares", 100, "shares"), ("diluted_shares", 110, "shares"),
         ("dilution_rate", dilution_percent, "percent")],
    )


def _dilution(result):
    return next(m for m in result.metrics if m.metric == "dilution_rate")


def test_deficit_overflow_carries_to_nominal_and_reports_uncovered():
    r = deficit_coverage(300, owner_nominal=100, owner_premium_fund=50, self_owned_capital=100)
    assert r["self_owned_reduction"] == pytest.approx(100)
    assert r["owner_fund_reduction"] == pytest.approx(50)
    assert r["nominal_reduction"] == pytest.approx(100)
    assert r["uncovered_deficit"] == pytest.approx(50)
    assert dict(r["waterfall"])["nominal_ec_capital"] == pytest.approx(100)


def test_deficit_between_first_tier_and_nominal_is_split_without_overdraw():
    r = deficit_coverage(200, owner_nominal=100, owner_premium_fund=50, self_owned_capital=100)
    assert r["self_owned_reduction"] == pytest.approx(100)
    assert r["owner_fund_reduction"] == pytest.approx(50)
    assert r["nominal_reduction"] == pytest.approx(50)
    assert r["uncovered_deficit"] == 0
    assert r["owner_book_after"] == pytest.approx(50)


def test_percentage_dilution_mismatch_is_still_detected():
    # 25 percent disclosed against 110/100 shares (10 percent) must remain a mismatch.
    assert _dilution(_software(25)).status == "unavailable"


def test_percentage_dilution_check_value_is_a_fraction():
    check = next(c for c in _software(10).checks if c.check == "dilution_reconciliation")
    assert check.status == "available"
    assert check.value == pytest.approx(0.1)


def test_biotech_percentage_dilution_reconciles():
    r = _projection(
        "biotech", "healthcare",
        [("shares_outstanding", 100, "shares"), ("potential_dilution_shares", 20, "shares"),
         ("dilution_rate", 20, "percent")],
    )
    dilution = _dilution(r)
    assert dilution.status == "available"
    assert dilution.value == 20
    assert dilution.unit == "percent"


def test_uncovered_deficit_fails_closed_to_partial():
    covered = deficit_coverage(200, owner_nominal=100, owner_premium_fund=50, self_owned_capital=100)
    assert covered["status"] == "resolved"
    short = deficit_coverage(300, owner_nominal=100, owner_premium_fund=50, self_owned_capital=100)
    assert short["status"] == "partial"
    assert short["unknown_fields"] == ("uncovered_deficit",)
    analysis = analyse_events(
        [{"event_type": "deficit_coverage", "deficit": 300, "owner_nominal": 100,
          "owner_premium_fund": 50, "self_owned_capital": 100, "known_at": "2025-01-01T00:00:00Z"}],
        decision_time="2025-02-01T00:00:00Z",
    )
    assert analysis.events[0]["status"] == "partial"
    assert analysis.status == "partial"
