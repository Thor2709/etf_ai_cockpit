"""Regression tests for lane DEC (A09 F1, F3, F4, F6, F7, F8), PLAN-FIX-20261023."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from etf_cockpit.analysis.decision import gates
from etf_cockpit.analysis.decision import stock as stock_module
from etf_cockpit.analysis.decision.contracts import DomainSlot
from etf_cockpit.analysis.decision.opportunity import (
    _benchmark_scores,
    _candidate_state,
    build_opportunity_results,
    load_opportunity_policy,
)
from etf_cockpit.analysis.decision.stock import compose_stock_decision, load_stock_decision_map
from etf_cockpit.core.paths import CONFIG_DIR
from test_decision_opportunity import DECISION_TIME, _three_candidates
from test_decision_stock import DECISION_TIME as STOCK_TIME, _context, _report

ETF_DECISION = "2026-03-01T00:30:00+01:00"  # 2026-02-28T23:30:00Z


def _slot(domain: str, status: str = "AVAILABLE", z: float | None = 0.5) -> DomainSlot:
    return DomainSlot(domain, status, z, z, 1.0, 0.8, "AVAILABLE")


def test_f1_vehicle_domains_load_beside_exposure_domains() -> None:
    assessment = SimpleNamespace(
        domain_slots=(_slot("Vehicle"),),
        exposure_domain_slots=(_slot("Exposure"),),
        opportunity_slots=(),
        eligibility_results=(),
        gate_results=(),
        drivers=(),
        critical_domains=("Vehicle",),
        source_vintage_hash="h",
    )
    candidate = {
        "instrument": "ETF1",
        "asset_type": "ETF",
        "assessment": assessment,
        "vehicle_z_score": 1.0,
        "exposure_z_score": 0.5,
    }
    state = _candidate_state(candidate, DECISION_TIME, load_opportunity_policy())
    assert {name for name, _ in state["domain_scores"]} == {"Vehicle", "Exposure"}
    assert state["status"] == "" and state["rankable"] is True


def test_f3_partial_underwriting_domains_renormalise_and_critical_must_be_available() -> None:
    weights = {"a": 1.0, "b": 1.0, "c": 2.0}
    slots = (_slot("a", z=1.0), _slot("b", "UNAVAILABLE", None), _slot("c", z=4.0))
    assert stock_module._weighted_domain_z(slots, weights) == pytest.approx((1.0 + 8.0) / 3.0)
    assert stock_module._weighted_domain_z(slots, weights, ("b",)) is None
    assert stock_module._weighted_domain_z(slots, weights, ("a", "c")) == pytest.approx(3.0)
    assert stock_module._weighted_domain_z((), weights) is None  # never zero-filled


def test_f4_requirement_class_preserved_and_critical_domains_canonical(tmp_path) -> None:
    source = (CONFIG_DIR / "decision_domains_v1.yaml").read_text(encoding="utf-8")
    marker = "        - metric: npl_ratio\n"
    assert marker in source.replace("\r\n", "\n")
    patched = source.replace("\r\n", "\n").replace(
        marker, marker + "          requirement_class: CRITICAL\n", 1
    )
    path = tmp_path / "registry.yaml"
    path.write_text(patched, encoding="utf-8")
    metrics = {item.metric_id: item for item in load_stock_decision_map(path).registry.metrics}
    npl = next(item for key, item in metrics.items() if key.endswith(":npl_ratio"))
    assert npl.requirement_class == "CRITICAL"
    assert metrics[next(k for k in metrics if k.endswith(":stage_3_exposure"))].requirement_class == "CONDITIONAL"

    result = compose_stock_decision("ACME", _context("ACME"), STOCK_TIME, _report())
    assert "valuation" in result["critical_domains"]
    assert result["critical_underwriting_domains"] == result["critical_domains"]


def test_f6_composites_standardise_momentum_risk_growth_and_etf_uses_exposure_for_v() -> None:
    results = build_opportunity_results(_three_candidates(), decision_time=DECISION_TIME)
    rankers = {item.ranker: item for item in results["ACME"].benchmark_rankers}
    momentum_z = 4.0 / (32.0 / 3.0) ** 0.5
    assert rankers["QVM"].score == pytest.approx((2.0 + 0.0 + momentum_z) / 3.0)
    assert rankers["M"].score == 9.0  # the M ranker keeps the raw score; only composites standardise

    etf = {
        "asset_type": "ETF",
        "candidate": {"vehicle_z_score": 1.0, "exposure_z_score": 0.5},
        "assessment": None,
    }
    scores = _benchmark_scores(etf)
    assert scores["V"] == 0.5 and scores["QV"] == pytest.approx(0.75)


def test_f7_quarantined_metric_is_excluded_and_generic_context_is_populated() -> None:
    provenance = [{"source_id": "s", "effective_at": "2027-01-01T00:00:00Z", "known_at": "2027-01-02T00:00:00Z"}]
    definition = next(iter(load_stock_decision_map().registry.metrics))
    for status in ("quarantined", "unavailable", "missing"):
        raw = {"value": 1.0, "status": status, "source_provenance": provenance}
        assert stock_module._make_scored_metric("m", raw, definition, rank_authority=True) is None
    raw = {"value": None, "status": "available", "source_provenance": provenance}
    assert stock_module._make_scored_metric("m", raw, definition, rank_authority=True) is None
    raw = {"value": 1.0, "status": "available", "source_provenance": provenance}
    assert stock_module._make_scored_metric("m", raw, definition, rank_authority=True) is not None

    context = _context("ACME")
    scored, _ = stock_module._stock_scored_metrics(_report(), {}, load_stock_decision_map(), context)
    assert scored and {item.business_model for item in scored} == {"software"}


def test_f8_future_evidence_and_unavailable_quality_cannot_pass_or_rank() -> None:
    def identity(as_of: object):
        results = gates.evaluate_critical_gates(
            "ETF", {"identity": as_of}, decision_time=ETF_DECISION
        )
        return next(item for item in results if item.gate_id == "identity")

    assert identity("2026-02-28T23:00:00Z").passed  # before the decision instant
    assert not identity("2026-02-28T23:45:00Z").passed  # after it, though the same calendar date
    assert not identity("2027-01-01").passed  # static gate: future evidence is invalid
    assert gates.evaluate_critical_gates("ETF", {"identity"}, decision_time=ETF_DECISION)[0].passed  # undated static

    passing = gates.evaluate_critical_gates(
        "ETF",
        {"identity": None, "liquidity_cost": None, "etf_exposure": None},
        decision_time=ETF_DECISION,
    )
    unavailable = gates.score_authority_flags(passing, score_present=True, quality_status="unavailable")
    assert unavailable.score_rankable is False
    assert unavailable.research_decision_status == gates.INSUFFICIENT_LABEL
