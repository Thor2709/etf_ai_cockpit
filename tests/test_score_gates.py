"""Score gates (#939): critical-evidence eligibility, no silent reweighting, honest coverage display."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from etf_cockpit.analysis.decision import gates
from etf_cockpit.analysis.decision.opportunity import _benchmark_scores
from etf_cockpit.analysis.decision.contracts import ScoreAuthorityFlags
from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.analysis.sparebank.valuation import valuation
from etf_cockpit.application.score_views import (
    apply_missing_data_penalty,
    score_buy_eligible,
    score_card_values,
    score_display_values,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.signals import simple_scores as ss
from etf_cockpit.signals.canonical_scoring import (
    CanonicalComponent,
    ScorePolicy,
    build_canonical_score,
    canonical_score_from_signal_row,
    canonical_score_from_simple_components,
    simple_quality_status,
)


DECISION = "2026-10-09"


def _fresh(*ids: str, as_of: str = DECISION) -> dict[str, str]:
    """Evidence ids with an as-of date (the gates compare it with the decision date)."""

    return {item: as_of for item in ids}


def _component(
    key: str, raw: float | None, role: str = "attractiveness", *, status: str = "ok", as_of: str | None = DECISION
) -> CanonicalComponent:
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
        as_of_date=as_of,
    )


def _non_price() -> list[CanonicalComponent]:
    """Non-price evidence that lifts coverage above the 0.50 minimum: value, quality, a model and implementation."""

    return [
        _component("stock_value", 1.0),
        _component("stock_quality", 1.0),
        _component("baseline", 1.0, "expected_return"),
        _component("risk", 1.0, "risk_implementation"),
        _component("liquidity_cost", 1.0, "risk_implementation"),
    ]


def _top_momentum() -> list[CanonicalComponent]:
    return [_component("momentum", 1.0), _component("trend", 1.0), _component("relative_strength", 1.0)]


def _simple(
    key: str,
    raw: float,
    *,
    used: tuple[str, ...] = (),
    configured: tuple[str, ...] = (),
    role: str = "evidence",
    source_id: str = "yfinance:prices",
    as_of: str | None = DECISION,
) -> ss.SimpleScoreComponent:
    return ss.SimpleScoreComponent(
        key=key,
        label=key,
        score_10=round((raw + 1.0) * 5.0, 1),
        raw_score=raw,
        status="ok",
        explanation="",
        good_score="",
        why="synthetic",
        source_id=source_id,
        as_of_date=as_of,
        freshness_status="ok",
        score_role=role,
        inputs_used=used,
        inputs_configured=configured,
    )


def _implementation() -> list[ss.SimpleScoreComponent]:
    """Expected-return and implementation components: with them a simple stock clears the coverage minimum."""

    return [
        _simple("baseline", 0.5, role="model_confirmation", source_id="model:baseline"),
        _simple("risk", 0.5, role="risk_friction"),
        _simple("liquidity_cost", 0.5, role="risk_friction"),
    ]


def _strong_stock(
    *, with_solvency: bool, final_label: str = "strong_evidence_candidate", quality_as_of: str | None = DECISION
) -> ss.SimpleInstrumentScore:
    quality_inputs = ("roe", "roic", "ebit_margin", "net_debt_to_ebitda", "fcf_conversion", "revenue_cagr")
    used = quality_inputs if with_solvency else ("roe", "roic", "ebit_margin", "revenue_cagr")
    components = [
        _simple("momentum", 0.9),
        _simple("trend", 0.9),
        _simple("relative_strength", 0.9),
        _simple("stock_value", 0.5, used=("earnings_yield", "market_cap")),
        _simple("stock_quality", 0.5, used=used, configured=quality_inputs, as_of=quality_as_of),
        *_implementation(),
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
        critical_evidence=_fresh("market_cap"),  # owner claim present, solvency missing
    )
    assert gated.attractiveness_10 is None
    assert "attractiveness" in gated.insufficient_groups
    assert {gate.gate_id for gate in gated.critical_gates if not gate.passed} == {"solvency_liquidity"}
    assert any(warning.startswith("attractiveness_insufficient_evidence") for warning in gated.warnings)
    assert gated.authority is not None
    assert gated.authority.research_decision_status == "insufficient_evidence"
    assert gated.authority.score_rankable is False and gated.authority.financial_safety_verified is False
    assert gated.as_dict()["authority"]["execution_allowed"] is False
    # The discarded group's evidence is not counted: no coverage, confidence or contributions; rows stay visible.
    assert gated.coverage == 0.0 and gated.evidence_confidence_10 is None
    assert gated.contributions == ()
    assert gated.components and all(row["score_counted"] is False and row["contribution_raw"] is None for row in gated.components)

    held = build_canonical_score(
        instrument_id="ACME",
        asset_type="STOCK",
        decision_time="2026-10-09",
        components=[*_top_momentum(), *_non_price()],
        critical_evidence=_fresh("market_cap", "net_debt_to_ebitda"),
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
    results = gates.evaluate_critical_gates("BANK", _fresh("eierbrok"), decision_time=DECISION)
    assert {result.gate_id for result in gates.failed_gates(results)} == {"capital"}
    assert gates.blocks_buy_label(results)
    assert not gates.blocks_buy_label(
        gates.evaluate_critical_gates("BANK", _fresh("cet1_ratio", "equity_certificates"), decision_time=DECISION)
    )


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
        gates.evaluate_critical_gates("STOCK", _fresh("market_cap", "net_debt_to_ebitda"), decision_time=DECISION),
        score_present=True,
        quality_status="partial",
    )
    assert flags.score_rankable is True and flags.financial_safety_verified is False
    assert flags.research_decision_status == "partial"

    # A partial quality component adds no active weight and no coverage (review fix 1, decision item 4).
    evidence = _fresh("market_cap", "net_debt_to_ebitda")
    parts = [*_top_momentum(), *_non_price()]
    common = dict(instrument_id="Q", asset_type="STOCK", decision_time=DECISION, components=parts, critical_evidence=evidence)
    complete = build_canonical_score(**common, quality_status="complete")
    partial = build_canonical_score(**common, quality_status="partial")
    assert partial.coverage == pytest.approx(complete.coverage - 0.24 / 2.85, abs=1e-5)  # NS1: rebalance left the v3 risk group (3.0 -> 2.85)
    row = next(item for item in partial.components if item["key"] == "stock_quality")
    assert row["status"] == "partial" and row["score_eligible"] is False and row["contribution_raw"] is None
    assert all(item["key"] != "stock_quality" for item in partial.contributions)
    assert partial.authority is not None and partial.authority.financial_safety_verified is False
    full_stock = _strong_stock(with_solvency=True).components
    thin_quality = [
        _simple("stock_quality", 0.2, used=("roe", "net_debt_to_ebitda"), configured=inputs, as_of=DECISION)
        if item.key == "stock_quality"
        else item
        for item in full_stock
    ]
    simple_complete = canonical_score_from_simple_components("Q", "Stock", DECISION, full_stock)
    simple_partial = canonical_score_from_simple_components("Q", "Stock", DECISION, thin_quality)
    assert simple_partial.coverage < simple_complete.coverage


# Remaining contract points.
def test_authority_flags_are_separate_and_fail_closed() -> None:
    assert ScoreAuthorityFlags() == ScoreAuthorityFlags(research_decision_status="insufficient_evidence")
    with pytest.raises(ValueError):
        ScoreAuthorityFlags(execution_allowed=True)
    flags = gates.score_authority_flags(
        gates.evaluate_critical_gates("ETF", _fresh("identity", "liquidity_cost", "etf_exposure"), decision_time=DECISION),
        score_present=True,
        quality_status=None,
        forecast_calibrated=False,
        benchmark_eligible=False,
    )
    assert flags.score_rankable is True and flags.forecast_calibrated is False and flags.benchmark_eligible is False
    assert gates.evaluate_critical_gates(None, {"identity"}, decision_time=DECISION)[0].reason_code == "ASSET_CLASS_UNMAPPED"
    assert gates.evaluate_critical_gates("ETF", {"identity"}, decision_time=DECISION)[0].passed
    failed = gates.failed_gates(gates.evaluate_critical_gates("ETF", {"identity"}, decision_time=DECISION))
    assert {r.gate_id for r in failed} == {"cost", "exposure"}


def test_etf_without_exposure_loses_its_buy_label_but_not_its_score() -> None:
    components = [_simple("momentum", 0.9), _simple("trend", 0.9), _simple("relative_strength", 0.9), *_implementation()]
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
    covered = {"ACME": {"final_combined_score_10": 6.0, "missing_components": "marketability", "data_as_of_date": "2026-10-09"}}
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
    assert covered.canonical_score is not None and not gates.failed_gates(covered.canonical_score.critical_gates)
    # A candidate has no price/risk components: coverage stays below 0.50, so its v3 values are unavailable, never shrunk.
    assert covered.canonical_score.unavailable_reason == "insufficient_coverage"
    bare = candidate()
    assert not ({"market_cap", "debt_to_equity"} & ss._critical_evidence_ids_of(bare))
    assert bare.canonical_score is not None and gates.failed_gates(bare.canonical_score.critical_gates)
    assert set(ss._candidate_critical_inputs(pd.Series({"market_cap": None, "debt_to_equity": float("nan")}))) == set()


# Review fix 1 (decision item 2): a minimum-coverage rule makes the score unavailable, with no ranking.
def _unavailable_everywhere(score: object) -> bool:
    return (
        score.attractiveness_10 is None
        and score.expected_return_10 is None
        and score.risk_implementation_10 is None
        and score.evidence_confidence_10 is None
        and score.legacy_composite_raw is None
        and score.contributions == ()
        and score.authority is not None
        and score.authority.score_rankable is False
        and score.gate_failed
    )


def test_one_input_instrument_is_unavailable_for_insufficient_coverage() -> None:
    thin = build_canonical_score(
        instrument_id="THIN",
        asset_type="STOCK",
        decision_time=DECISION,
        components=_top_momentum(),
        legacy_component_weights={"momentum": 1.0},
        critical_evidence=_fresh("market_cap", "net_debt_to_ebitda"),  # momentum, trend + solvency evidence: coverage ~0.17
    )
    assert thin.unavailable_reason == "insufficient_coverage" and _unavailable_everywhere(thin)
    assert "score_unavailable:insufficient_coverage" in thin.warnings
    assert thin.as_dict()["unavailable_reason"] == "insufficient_coverage"
    single = build_canonical_score(
        instrument_id="ONE",
        asset_type="STOCK",
        decision_time=DECISION,
        components=[_component("momentum", 1.0)],
        critical_evidence=_fresh("market_cap", "net_debt_to_ebitda"),
    )
    assert single.unavailable_reason == "insufficient_coverage" and _unavailable_everywhere(single)


def test_price_only_components_are_unavailable_even_with_enough_coverage() -> None:
    policy = ScorePolicy(
        "test-v1",
        "0" * 64,
        "1-3 months",
        "STOCK",
        {"attractiveness": {"momentum": 0.5, "trend": 0.5}, "expected_return": {"baseline": 1.0}, "risk_implementation": {"risk": 1.0}},
    )
    components = [_component("momentum", 1.0), _component("trend", 1.0), _component("risk", 1.0, "risk_implementation")]
    kwargs = dict(
        instrument_id="PX", asset_type="STOCK", decision_time=DECISION, policy=policy, critical_evidence=_fresh("market_cap", "net_debt_to_ebitda")
    )
    price_only = build_canonical_score(components=components, **kwargs)
    assert price_only.coverage == pytest.approx(2.0 / 3.0, abs=1e-5)  # above 0.50, yet no non-price family
    assert price_only.unavailable_reason == "insufficient_coverage" and _unavailable_everywhere(price_only)
    with_model = build_canonical_score(components=[*components, _component("baseline", 1.0, "expected_return")], **kwargs)
    assert with_model.unavailable_reason is None and with_model.attractiveness_10 == 10.0


def test_missing_component_lowers_coverage_but_does_not_inflate_the_others() -> None:
    kwargs = dict(instrument_id="Q", asset_type="STOCK", decision_time=DECISION, critical_evidence=_fresh("market_cap", "net_debt_to_ebitda"))
    full = build_canonical_score(components=[*_top_momentum(), *_non_price()], **kwargs)
    without_risk = build_canonical_score(
        components=[*_top_momentum(), *[item for item in _non_price() if item.key != "risk"]], **kwargs
    )
    assert full.unavailable_reason is None and without_risk.unavailable_reason is None
    assert without_risk.coverage == pytest.approx(full.coverage - 0.45 / 2.85, abs=1e-5)  # NS1: rebalance left the v3 risk group (3.0 -> 2.85)
    assert without_risk.attractiveness_10 == full.attractiveness_10
    assert without_risk.expected_return_10 == full.expected_return_10
    rows = {item["key"]: item for item in without_risk.components}
    assert "risk" not in rows  # nothing was substituted or zero-filled for the missing component
    full_weights = {item["key"]: item["weight"] for item in full.components}
    assert {key: item["weight"] for key, item in rows.items()} == {key: full_weights[key] for key in rows}


# Review fix 2 (decision item 3): stale, undated or invalid critical evidence makes the score unavailable.
def _dated_stock(**evidence_dates: str | None) -> object:
    return build_canonical_score(
        instrument_id="DATED",
        asset_type="STOCK",
        decision_time=DECISION,
        components=[*_top_momentum(), *_non_price()],
        critical_evidence=evidence_dates,
    )


def test_stale_critical_evidence_makes_the_score_unavailable() -> None:
    fresh = _dated_stock(market_cap=DECISION, net_debt_to_ebitda=DECISION)
    assert fresh.unavailable_reason is None and fresh.attractiveness_10 == 10.0
    stale = _dated_stock(market_cap=DECISION, net_debt_to_ebitda="2022-12-31")  # a years-old solvency figure
    assert stale.unavailable_reason == "critical_domain_insufficient" and _unavailable_everywhere(stale)
    assert {gate.gate_id: gate.reason_code for gate in stale.critical_gates if not gate.passed} == {
        "solvency_liquidity": "CRITICAL_EVIDENCE_STALE"
    }
    assert gates.load_critical_evidence_policy().gates["STOCK"][0].max_age_days == 456
    edge = gates.evaluate_critical_gates("STOCK", _fresh("net_debt_to_ebitda", "market_cap", as_of="2025-07-10"), decision_time=DECISION)
    assert all(result.passed for result in edge)  # exactly 456 days old is still inside the limit
    over = gates.evaluate_critical_gates("STOCK", _fresh("net_debt_to_ebitda", "market_cap", as_of="2025-07-09"), decision_time=DECISION)
    assert {result.gate_id for result in gates.failed_gates(over)} == {"solvency_liquidity", "owner_claim"}


@pytest.mark.parametrize("as_of", [None, "", "not-a-date", "2026-10-10"], ids=["undated", "empty", "unparseable", "after-decision"])
def test_invalid_critical_evidence_makes_the_score_unavailable(as_of: str | None) -> None:
    invalid = _dated_stock(market_cap=DECISION, net_debt_to_ebitda=as_of)
    assert invalid.unavailable_reason == "critical_domain_insufficient" and _unavailable_everywhere(invalid)
    assert {gate.gate_id: gate.reason_code for gate in invalid.critical_gates if not gate.passed} == {
        "solvency_liquidity": "CRITICAL_EVIDENCE_INVALID"
    }
    # Plain ids carry no date: unverifiable, never a pass. Without a decision date nothing can be compared either.
    undated = gates.evaluate_critical_gates("STOCK", {"net_debt_to_ebitda", "market_cap"}, decision_time=DECISION)
    assert undated[0].reason_code == "CRITICAL_EVIDENCE_INVALID"
    no_decision = gates.evaluate_critical_gates("STOCK", _fresh("net_debt_to_ebitda", "market_cap"), decision_time=None)
    assert no_decision[0].reason_code == "CRITICAL_EVIDENCE_INVALID"


def test_stale_evidence_in_the_scoreboard_path_blocks_the_label_and_the_v3_values() -> None:
    stale = ss._with_critical_evidence(_strong_stock(with_solvency=True, quality_as_of="2022-12-31"))
    assert stale.final_label == "insufficient_evidence" and stale.final_action == "manual_review"
    assert stale.canonical_score is not None and stale.canonical_score.unavailable_reason == "critical_domain_insufficient"
    assert stale.canonical_score.attractiveness_10 is None and stale.final_score_10 == 8.9
    fresh = ss._with_critical_evidence(_strong_stock(with_solvency=True))
    assert fresh.final_label == "strong_evidence_candidate" and fresh.canonical_score.unavailable_reason is None


# Review fix 3 (decision item 1): every score path goes through the one gate before a 0-10 value is shown.
def _thin_stock() -> ss.SimpleInstrumentScore:
    base = _strong_stock(with_solvency=True)
    return ss.SimpleInstrumentScore(**{**base.__dict__, "components": base.components[:5]})  # no model / implementation


def test_every_score_path_applies_the_gate() -> None:
    # Scoreboard (label + attached v3 view): coverage 0.33 -> no Buy label, no 0-10 v3 values.
    board = ss._with_canonical_score(ss._with_critical_evidence(_thin_stock()))
    assert board.final_label == "insufficient_evidence"
    assert board.canonical_score is not None and board.canonical_score.unavailable_reason == "insufficient_coverage"
    assert board.canonical_score.attractiveness_10 is None and board.canonical_score.legacy_composite_raw is None

    # Default scoring entry point (simple components) is gated without the caller passing any evidence.
    default = canonical_score_from_simple_components("ACME", "Stock", DECISION, _thin_stock().components)
    assert default.unavailable_reason == "insufficient_coverage" and _unavailable_everywhere(default)

    # Signal-row path and the legacy composite it feeds.
    config = load_config()
    thin_row = pd.Series({"etf_id": "AAA", "price_freshness": "ok", "score_momentum": 0.4, "score_trend": 0.3})
    thin = canonical_score_from_signal_row(thin_row, config, DECISION)
    assert thin.unavailable_reason == "insufficient_coverage" and _unavailable_everywhere(thin)
    assert thin.legacy_composite_10 is None
    full_row = pd.Series(
        {
            "etf_id": "AAA",
            "price_freshness": "ok",
            "score_momentum": 0.4,
            "score_trend": 0.3,
            "score_relative_strength": 0.2,
            "score_risk": 0.1,
            "score_rebalance": 0.0,
            "cost_penalty": 0.01,
            "turnover_penalty": 0.0,
            "score_baseline_ml": 0.2,
            "score_etf_exposure": 0.3,
        }
    )
    full = canonical_score_from_signal_row(full_row, config, DECISION)
    assert full.unavailable_reason is None and full.attractiveness_10 is not None and full.legacy_composite_raw is not None
    assert {gate.gate_id for gate in full.critical_gates} == {"identity", "cost", "exposure"} and not full.gate_failed
    stock_row = pd.Series({**full_row.to_dict(), "asset_type": "Stock"})
    assert canonical_score_from_signal_row(stock_row, config, DECISION).gate_failed  # no solvency / owner-claim evidence

    # Decision layer: the benchmark v3 input reads the gated legacy composite, so an unavailable score is absent.
    state = {"candidate": {"signal": SimpleNamespace(canonical_score=thin, components=None)}}
    assert _benchmark_scores(state)["v3"] is None
    state = {"candidate": {"signal": SimpleNamespace(canonical_score=full, components=None)}}
    assert _benchmark_scores(state)["v3"] == full.legacy_composite_raw

    # v3 view: the display values flag the gate failure of an unavailable score.
    assert score_display_values(board)["gate_failed"] is True


# Review fix 5 (decision item 5): a malformed policy configuration fails at load time.
def _policy_text(mutate) -> str:
    parsed = yaml.safe_load(gates.POLICY_PATH.read_text(encoding="utf-8"))
    mutate(parsed)
    return yaml.safe_dump(parsed)


def _stock_gate(parsed: dict) -> dict:
    return parsed["critical_evidence"]["asset_classes"]["STOCK"]["gates"]["solvency_liquidity"]


_MALFORMED = {
    "missing_section": lambda parsed: parsed.pop("critical_evidence"),
    "empty_evidence_any_of": lambda parsed: _stock_gate(parsed).update(evidence_any_of=[]),
    "minimum_above_configured": lambda parsed: parsed["critical_evidence"]["quality_minimum_inputs"].update(minimum=7),
    "missing_asset_classes": lambda parsed: parsed["critical_evidence"].pop("asset_classes"),
    "missing_max_age": lambda parsed: _stock_gate(parsed).pop("max_age_days"),
    "zero_max_age": lambda parsed: _stock_gate(parsed).update(max_age_days=0),
    "text_max_age": lambda parsed: _stock_gate(parsed).update(max_age_days="old"),
    "missing_availability": lambda parsed: parsed["critical_evidence"].pop("score_availability"),
    "zero_minimum_coverage": lambda parsed: parsed["critical_evidence"]["score_availability"].update(minimum_coverage=0),
    "no_price_only_components": lambda parsed: parsed["critical_evidence"]["score_availability"].update(price_only_components=[]),
}


@pytest.mark.parametrize("case", sorted(_MALFORMED))
def test_malformed_policy_config_fails_at_load_time(case: str, tmp_path: Path) -> None:
    path = tmp_path / "decision_domains_v1.yaml"
    path.write_text(_policy_text(_MALFORMED[case]), encoding="utf-8")
    with pytest.raises(gates.CriticalEvidenceError):
        gates.load_critical_evidence_policy(path)
    assert gates.load_critical_evidence_policy().minimum_coverage == 0.5  # the shipped policy still loads


def test_unreadable_or_unparseable_policy_file_fails_at_load_time(tmp_path: Path) -> None:
    with pytest.raises(gates.CriticalEvidenceError):
        gates.load_critical_evidence_policy(tmp_path / "missing.yaml")
    with pytest.raises(gates.CriticalEvidenceError):
        gates.load_critical_evidence_policy(tmp_path)  # a directory is unreadable as a file
    broken = tmp_path / "broken.yaml"
    broken.write_text("critical_evidence: [unclosed", encoding="utf-8")
    with pytest.raises(gates.CriticalEvidenceError):
        gates.load_critical_evidence_policy(broken)
    broken.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(gates.CriticalEvidenceError):
        gates.load_critical_evidence_policy(broken)
