"""Score gates (#939): critical-evidence eligibility, no silent reweighting, honest coverage display."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from etf_cockpit.analysis.decision import gates
from etf_cockpit.analysis.decision.contracts import ScoreAuthorityFlags
from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.analysis.sparebank.valuation import valuation
from etf_cockpit.application.score_views import (
    apply_missing_data_penalty,
    score_buy_eligible,
    score_card_values,
    score_display_values,
)
from etf_cockpit.signals import simple_scores as ss
from etf_cockpit.signals.canonical_scoring import CanonicalComponent, ScorePolicy, build_canonical_score, simple_quality_status


def _component(key: str, raw: float | None, role: str = "attractiveness", *, status: str = "ok") -> CanonicalComponent:
    return CanonicalComponent(
        key=key,
        raw_metric=raw,
        score_role=role,
        peer_group="synthetic",
        source_id=f"source:{key}",
        source_authority="vendor_unofficial",
        freshness_status="ok",
        uncertainty="low",
        status=status,
        explanation=f"{key} explanation",
    )


def _top_momentum() -> list[CanonicalComponent]:
    return [_component("momentum", 1.0), _component("trend", 1.0), _component("relative_strength", 1.0)]


def _simple(key: str, raw: float, *, used: tuple[str, ...] = (), configured: tuple[str, ...] = ()) -> ss.SimpleScoreComponent:
    return ss.SimpleScoreComponent(
        key=key,
        label=key,
        score_10=round((raw + 1.0) * 5.0, 1),
        raw_score=raw,
        status="ok",
        explanation="",
        good_score="",
        why="synthetic",
        source_id="yfinance:prices",
        as_of_date="2026-10-09",
        freshness_status="ok",
        inputs_used=used,
        inputs_configured=configured,
    )


def _strong_stock(*, with_solvency: bool, final_label: str = "strong_evidence_candidate") -> ss.SimpleInstrumentScore:
    quality_inputs = ("roe", "roic", "ebit_margin", "net_debt_to_ebitda", "fcf_conversion", "revenue_cagr")
    used = quality_inputs if with_solvency else ("roe", "roic", "ebit_margin", "revenue_cagr")
    components = [
        _simple("momentum", 0.9),
        _simple("trend", 0.9),
        _simple("relative_strength", 0.9),
        _simple("stock_value", 0.5, used=("earnings_yield", "market_cap")),
        _simple("stock_quality", 0.5, used=used, configured=quality_inputs),
    ]
    return ss.SimpleInstrumentScore(
        instrument_key="stock:ACME",
        display_id="ACME",
        source_group="primary",
        asset_type="Stock",
        name="Acme",
        yahoo_symbol="ACME",
        latest_date="2026-10-09",
        latest_price=10.0,
        final_score_10=8.9,
        decision="Strong Evidence Candidate",
        one_line_reason="Strong momentum.",
        components=components,
        warnings=[],
        final_label=final_label,
        final_action="add_candidate",
    )


# 1. Missing solvency gives insufficient evidence despite top momentum.
def test_missing_solvency_is_insufficient_despite_top_momentum() -> None:
    legacy = build_canonical_score(
        instrument_id="ACME", asset_type="STOCK", decision_time="2026-10-09", components=_top_momentum()
    )
    assert legacy.attractiveness_10 == 10.0  # control: momentum alone used to carry the group

    gated = build_canonical_score(
        instrument_id="ACME",
        asset_type="STOCK",
        decision_time="2026-10-09",
        components=_top_momentum(),
        critical_evidence=("market_cap",),  # owner claim present, solvency missing
    )
    assert gated.attractiveness_10 is None
    assert "attractiveness" in gated.insufficient_groups
    assert {gate.gate_id for gate in gated.critical_gates if not gate.passed} == {"solvency_liquidity"}
    assert any(warning.startswith("attractiveness_insufficient_evidence") for warning in gated.warnings)
    assert gated.authority is not None
    assert gated.authority.research_decision_status == "insufficient_evidence"
    assert gated.authority.score_rankable is False and gated.authority.financial_safety_verified is False
    assert gated.as_dict()["authority"]["execution_allowed"] is False

    held = build_canonical_score(
        instrument_id="ACME",
        asset_type="STOCK",
        decision_time="2026-10-09",
        components=_top_momentum(),
        critical_evidence=("market_cap", "net_debt_to_ebitda"),
        quality_status="complete",
    )
    assert held.attractiveness_10 == 10.0 and held.authority is not None and held.authority.score_rankable
    assert held.authority.financial_safety_verified is True


def test_missing_solvency_turns_a_buy_label_into_insufficient_evidence_and_keeps_the_scores() -> None:
    blocked = ss._with_critical_evidence(_strong_stock(with_solvency=False))
    assert blocked.final_label == "insufficient_evidence" and blocked.final_action == "manual_review"
    assert blocked.decision == "Insufficient evidence"
    assert blocked.final_score_10 == 8.9 and "critical_evidence_insufficient" in blocked.warnings
    passed = ss._with_critical_evidence(_strong_stock(with_solvency=True))
    assert passed.final_label == "strong_evidence_candidate" and passed.final_action == "add_candidate"


# 2. Coverage shrink cannot pass a gate.
def test_coverage_shrink_cannot_pass_a_gate() -> None:
    blocked = ss._with_canonical_score(ss._with_critical_evidence(_strong_stock(with_solvency=False)))
    assert blocked.score_coverage < 1.0
    shown = apply_missing_data_penalty(blocked)
    values = score_display_values(shown)
    assert values["research_score_10"] == 8.9
    assert values["display_adjusted_score_10"] == shown.final_score_10 != 8.9
    assert 0.0 < values["evidence_coverage"] < 1.0
    assert values["gate_failed"] is True and values["buy_eligible"] is False
    assert shown.final_label == "insufficient_evidence" and shown.final_action == "manual_review"
    assert "not a confidence or probability" in shown.one_line_reason
    assert "cannot make the instrument eligible" in shown.one_line_reason
    assert score_buy_eligible(shown) is False
    card = score_card_values(shown)
    assert card["critical_gates_failed"] == ("solvency_liquidity",)
    assert card["research_decision_status"] == "insufficient_evidence"

    clear = ss._with_canonical_score(ss._with_critical_evidence(_strong_stock(with_solvency=True)))
    assert score_buy_eligible(apply_missing_data_penalty(clear)) is True


# 3. An inapplicable bank metric correctly leaves the denominator.
def _two_input_policy() -> ScorePolicy:
    return ScorePolicy(
        "test-v1",
        "0" * 64,
        "1-3 months",
        "STOCK",
        {
            "attractiveness": {"stock_quality": 0.5, "net_debt_to_ebitda": 0.5},
            "expected_return": {"baseline": 1.0},
            "risk_implementation": {"risk": 1.0},
        },
    )


def test_inapplicable_bank_metric_leaves_the_denominator_only_for_banks() -> None:
    components = [_component("stock_quality", 0.6), _component("net_debt_to_ebitda", None, status="not_applicable")]
    kwargs = dict(
        instrument_id="BANK1", asset_type="STOCK", decision_time="2026-10-09", components=components, policy=_two_input_policy()
    )
    bank = build_canonical_score(**kwargs, business_model="bank")
    assert bank.coverage == pytest.approx(0.5 / 2.5, abs=1e-5)  # the exempt 0.5 weight left the configured total (3.0)
    bank_rows = {row["key"]: row for row in bank.components}
    assert bank_rows["net_debt_to_ebitda"]["score_eligible"] is False
    assert "not_applicable:net_debt_to_ebitda" in bank.warnings
    assert not any(warning.startswith("attractiveness_coverage") for warning in bank.warnings)

    plain = build_canonical_score(**kwargs)
    assert plain.coverage == pytest.approx(0.5 / 3.0, abs=1e-5)
    assert any(warning.startswith("attractiveness_coverage:0.500") for warning in plain.warnings)  # still a gap for others
    stock = build_canonical_score(**kwargs, business_model="operating_company")
    assert any(warning.startswith("attractiveness_coverage:0.500") for warning in stock.warnings)

    # A metric the sector definition does not forbid never leaves the denominator, even when it is reported n/a.
    unforbidden = build_canonical_score(
        instrument_id="BANK1",
        asset_type="STOCK",
        decision_time="2026-10-09",
        components=[_component("net_debt_to_ebitda", 0.4), _component("stock_quality", None, status="not_applicable")],
        policy=_two_input_policy(),
        business_model="bank",
    )
    assert any(warning.startswith("attractiveness_coverage:0.500") for warning in unforbidden.warnings)


def test_input_completeness_exempts_only_forbidden_bank_inputs() -> None:
    inputs = ("roe", "roic", "ebit_margin", "net_debt_to_ebitda", "fcf_conversion", "revenue_cagr")
    bank = gates.input_completeness(
        inputs,
        ("roe", "roic", "ebit_margin", "revenue_cagr"),
        not_applicable=("net_debt_to_ebitda", "fcf_conversion"),
        asset_class="BANK",
    )
    assert (bank.applicable, bank.coverage, bank.status) == (4, 1.0, "complete")
    stock = gates.input_completeness(
        inputs,
        ("roe", "roic", "ebit_margin", "revenue_cagr"),
        not_applicable=("net_debt_to_ebitda", "fcf_conversion"),
        asset_class="STOCK",
    )
    assert (stock.applicable, stock.coverage) == (6, pytest.approx(4 / 6))
    forbidden_only = gates.input_completeness(inputs, ("roe", "roic", "ebit_margin", "revenue_cagr"), not_applicable=("roe",), asset_class="BANK")
    assert forbidden_only.applicable == 6  # roe is applicable to a bank: n/a does not shrink the denominator


# 4. A Sparebank without a confirmed eierbrøk has no certified valuation.
def _teaching_bank() -> dict[str, object]:
    return json.loads((Path(__file__).parent / "fixtures" / "sparebank" / "teaching_bank.json").read_text(encoding="utf-8"))


def test_sparebank_without_confirmed_eierbrok_has_no_certified_valuation() -> None:
    confirmed = _teaching_bank()
    confirmed["facts"]["eierbrok"] = {"available": True, "value": 0.4}
    certified = valuation(build_claim_state(confirmed), price=100)
    assert certified["certified"] is True and certified["certification"]["gate_id"] == "owner_claim"

    unconfirmed = copy.deepcopy(_teaching_bank())
    del unconfirmed["facts"]["eierbrok"]
    result = valuation(build_claim_state(unconfirmed), price=100)
    assert result["certified"] is False
    assert result["certification"]["reason_code"] == "OWNER_CLAIM_NOT_CONFIRMED"
    assert result["execution_allowed"] is False

    invalid = _teaching_bank()
    invalid["facts"]["eierbrok"] = {"available": True, "value": 1.7}
    assert valuation(build_claim_state(invalid), price=100)["certified"] is False


def test_bank_gates_require_capital_and_owner_claim() -> None:
    assert gates.critical_asset_class("Stock", "bank") == "BANK"
    results = gates.evaluate_critical_gates("BANK", {"eierbrok"})
    assert {result.gate_id for result in gates.failed_gates(results)} == {"capital"}
    assert gates.blocks_buy_label(results)
    assert not gates.blocks_buy_label(gates.evaluate_critical_gates("BANK", {"cet1_ratio", "equity_certificates"}))


# 5. 2 of 6 quality inputs gives partial.
def test_two_of_six_quality_inputs_is_partial_and_not_safety_verified() -> None:
    inputs = ("roe", "roic", "ebit_margin", "net_debt_to_ebitda", "fcf_conversion", "revenue_cagr")
    result = gates.input_completeness(inputs, ("roe", "net_debt_to_ebitda"), asset_class="STOCK")
    assert (result.status, result.used, result.required) == ("partial", 2, 4)
    assert gates.load_critical_evidence_policy().quality_minimum_inputs == 4
    assert gates.input_completeness(inputs, inputs[:4], asset_class="STOCK").status == "complete"

    components = [_simple("stock_quality", 0.2, used=("roe", "net_debt_to_ebitda"), configured=inputs)]
    assert simple_quality_status(components, "Stock") == "partial"
    flags = gates.score_authority_flags(
        gates.evaluate_critical_gates("STOCK", {"market_cap", "net_debt_to_ebitda"}), score_present=True, quality_status="partial"
    )
    assert flags.score_rankable is True and flags.financial_safety_verified is False
    assert flags.research_decision_status == "partial"


# Remaining contract points.
def test_authority_flags_are_separate_and_fail_closed() -> None:
    assert ScoreAuthorityFlags() == ScoreAuthorityFlags(research_decision_status="insufficient_evidence")
    with pytest.raises(ValueError):
        ScoreAuthorityFlags(execution_allowed=True)
    flags = gates.score_authority_flags(
        gates.evaluate_critical_gates("ETF", {"identity", "liquidity_cost", "etf_exposure"}),
        score_present=True,
        quality_status=None,
        forecast_calibrated=False,
        benchmark_eligible=False,
    )
    assert flags.score_rankable is True and flags.forecast_calibrated is False and flags.benchmark_eligible is False
    assert gates.evaluate_critical_gates(None, {"identity"})[0].reason_code == "ASSET_CLASS_UNMAPPED"
    assert gates.evaluate_critical_gates("ETF", {"identity"})[0].passed
    assert {r.gate_id for r in gates.failed_gates(gates.evaluate_critical_gates("ETF", {"identity"}))} == {"cost", "exposure"}


def test_etf_without_exposure_loses_its_buy_label_but_not_its_score() -> None:
    components = [_simple("momentum", 0.9), _simple("liquidity_cost", 0.5)]
    score = ss.SimpleInstrumentScore(
        instrument_key="etf:ETF1",
        display_id="ETF1",
        source_group="primary",
        asset_type="ETF",
        name="Etf",
        yahoo_symbol="ETF1",
        latest_date="2026-10-09",
        latest_price=10.0,
        final_score_10=8.0,
        decision="Strong Evidence Candidate",
        one_line_reason="",
        components=components,
        warnings=[],
        isin="IE00TEST0001",
        final_label="positive_evidence_candidate",
        final_action="add_candidate",
    )
    blocked = ss._with_critical_evidence(score)
    assert blocked.final_label == "insufficient_evidence" and blocked.final_score_10 == 8.0
    with_exposure = ss._with_critical_evidence(
        ss.SimpleInstrumentScore(**{**score.__dict__, "components": [*components, _simple("etf_exposure", 0.4)]})
    )
    assert with_exposure.final_label == "positive_evidence_candidate"


# Review fix 1: banks and Sparebank ECs reach the BANK gate set in the production score path.
def test_listed_bank_without_capital_evidence_loses_its_buy_label() -> None:
    bank = ss.SimpleInstrumentScore(**{**_strong_stock(with_solvency=True).__dict__, "business_model": ss._business_model_for_sector("Banks")})
    assert bank.business_model == "bank"
    blocked = ss._with_critical_evidence(bank)  # passes the STOCK gates on debt/market cap alone, but has no CET1
    assert blocked.final_label == "insufficient_evidence" and blocked.final_score_10 == 8.9
    capital = _simple("stock_quality", 0.5, used=("cet1_ratio", "net_debt_to_ebitda"))
    still_blocked = ss._with_critical_evidence(
        ss.SimpleInstrumentScore(**{**bank.__dict__, "components": [*bank.components[:4], capital]})
    )
    assert still_blocked.final_label == "insufficient_evidence"  # capital present, owner claim (eierbrok) still missing
    canonical = ss._with_canonical_score(blocked).canonical_score
    assert canonical is not None and {gate.gate_id for gate in canonical.critical_gates} == {"capital", "owner_claim"}
    assert ss._business_model_for_sector("Technology") is None


def test_sparebank_ec_generic_score_needs_confirmed_owner_claim_and_capital(monkeypatch: pytest.MonkeyPatch) -> None:
    ec = ss.SimpleInstrumentScore(**{**_strong_stock(with_solvency=True).__dict__, "asset_type": "Equity certificate"})
    monkeypatch.setattr(ss, "latest_sparebank_scores", lambda: {})
    assert ss._with_critical_evidence(ec).final_label == "insufficient_evidence"  # no stored native row
    partial = {"ACME": {"final_combined_score_10": 6.0, "missing_components": "owner_claim_integrity|capital_liquidity_resilience"}}
    monkeypatch.setattr(ss, "latest_sparebank_scores", lambda: partial)
    assert ss._with_critical_evidence(ec).final_label == "insufficient_evidence"  # claim unresolved
    covered = {"ACME": {"final_combined_score_10": 6.0, "missing_components": "marketability"}}
    monkeypatch.setattr(ss, "latest_sparebank_scores", lambda: covered)
    assert ss._with_critical_evidence(ec).final_label == "strong_evidence_candidate"


# Review fix 2: a cyclical-sector candidate row keeps its solvency and owner-claim evidence.
def test_cyclical_candidate_row_keeps_solvency_and_owner_claim_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd
    from dataclasses import replace

    cyclical = [replace(_simple(key, 0.5), status="OK") for key in ("stock_value", "stock_quality")]
    monkeypatch.setattr(ss, "_etf_exposure_lookup", lambda: {})
    monkeypatch.setattr(ss, "_cyclical_stock_components", lambda *args, **kwargs: cyclical)

    def candidate(**evidence: object) -> ss.SimpleInstrumentScore:
        report = pd.DataFrame(
            [{"instrument_id": "OIL", "asset_type": "STOCK", "instrument_type": "stock", "sector": "energy",
              "latest_date": "2026-10-09", "latest_price": 50.0, **evidence}]
        )
        (result,) = ss.build_candidate_simple_scores(report, pd.DataFrame())
        return result

    covered = candidate(market_cap=5.0e9, debt_to_equity=0.8)
    assert {"market_cap", "debt_to_equity"} <= ss._critical_evidence_ids_of(covered)
    assert covered.canonical_score is not None and not covered.canonical_score.gate_failed
    bare = candidate()
    assert not ({"market_cap", "debt_to_equity"} & ss._critical_evidence_ids_of(bare))
    assert bare.canonical_score is not None and bare.canonical_score.gate_failed
    assert set(ss._candidate_critical_inputs(pd.Series({"market_cap": None, "debt_to_equity": float("nan")}))) == set()
