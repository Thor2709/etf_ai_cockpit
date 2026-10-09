"""SB2: lending, normalisation, valuation inputs, statements and the Pillar 3 confirm flow."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.bank_metric_facts import _financial_metric_facts
from etf_cockpit.analysis.sparebank import analyse_sparebank_ec, build_sparebank_scorecard
from etf_cockpit.analysis.sparebank.bank_economics import build_bank_economics, lending_economics, owner_normalisation
from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.analysis.sparebank.valuation import valuation
from etf_cockpit.application.financial_institution_views import _financial_rows_for_instrument
from etf_cockpit.application.sparebank_evidence import (
    pillar3_evidence,
    statement_series,
    with_derived_owner_earnings,
)
from etf_cockpit.data import pillar3_queue


def _statements() -> dict[str, object]:
    return {
        "period_end": "2024-12-31",
        "prior_period_end": "2023-12-31",
        "current": {
            "net_interest_income": 1100.0, "operating_expenses": 400.0, "impairment_losses": 10.0,
            "total_assets": 21000.0, "equity": 2200.0, "income_before_tax": 800.0, "income_tax": 200.0,
        },
        "prior": {"net_interest_income": 1000.0, "total_assets": 19000.0, "equity": 2000.0, "impairment_losses": 30.0},
    }


def test_lending_economics_golden_from_statements_and_metrics() -> None:
    metrics = {"net_interest_margin": 0.022, "cost_of_risk": 0.002, "loan_growth": 0.05, "deposit_growth": 0.03}
    result = lending_economics(metrics, _statements())
    assert result["risk_adjusted_margin"] == pytest.approx(0.020)  # book eq. 1.14: margin minus credit loss
    assert result["loan_minus_deposit_growth"] == pytest.approx(0.02)
    assert result["nii_growth"] == pytest.approx(0.10)
    assert result["nii_minus_loan_growth"] == pytest.approx(0.05)
    assert result["cost_to_average_assets"] == pytest.approx(400.0 / 20000.0)
    assert result["capital_self_funding_gap"] == pytest.approx(0.10 - (21000 / 19000 - 1))
    # No prior year in the filing: the gap stays unavailable, never zero.
    no_prior = lending_economics(metrics, {"current": _statements()["current"]})
    assert no_prior["nii_growth"] is None and no_prior["nii_minus_loan_growth"] is None


def _claim(**overrides: object):
    facts = {
        "ec_capital": {"available": True, "value": 100.0},
        "overkursfond": {"available": True, "value": 50.0},
        "utjevningsfond": {"available": True, "value": 250.0},
        "sparebankens_fond": {"available": True, "value": 600.0},
        "registered_ec_count": {"available": True, "value": 4.0},
        "ec_attributable_result": {"available": True, "value": 48.0},
    }
    facts.update(overrides)  # type: ignore[arg-type]
    return build_claim_state({"facts": facts, "known_at": "2025-03-01T00:00:00Z", "source_url": "synthetic"})


def test_owner_normalisation_haircuts_only_a_benign_loss_year_and_tax_effects_it() -> None:
    bank = build_bank_economics({"statements": _statements()}, bank_metrics=[])
    claim = _claim()
    assert claim.claim_status == "resolved"  # gavefond/kompensasjonsfond absent: flagged, not blocking
    result = owner_normalisation(bank, claim)
    norm = result.normalised
    # Current loss 10 is below the two-year average 20: extra loss 10, tax 25 %, owner share 400/1000.
    adjustment = norm["adjustments"][0]
    assert adjustment.amount == pytest.approx(-10 * 0.75 * 0.4)
    assert norm["normalised_roe"] == pytest.approx((48.0 - 3.0) / 400.0)
    assert norm["denominator_basis"].startswith("closing owner capital")
    assert norm["tax_rate"] == pytest.approx(0.25)  # 200 / 800 from the filing
    # A year with HIGHER losses than the average is not added back without evidence of a one-off (book 5.2.4).
    high = _statements()
    high["current"]["impairment_losses"] = 50.0  # type: ignore[index]
    high_bank = owner_normalisation(build_bank_economics({"statements": high}, bank_metrics=[]), claim)
    assert high_bank.normalised["adjustments"][0].amount == 0.0
    assert high_bank.normalised["normalised"] == pytest.approx(48.0)


def test_owner_normalisation_states_why_it_is_unavailable() -> None:
    bank = build_bank_economics({"statements": _statements()}, bank_metrics=[])
    claim = _claim(ec_attributable_result={"available": False, "value": None})
    result = owner_normalisation(bank, claim)
    assert result.normalised == {}
    assert "EC-attributable result" in result.reasons["normalised_roe_minus_cost_of_equity_pp"]


def test_valuation_reports_justified_value_and_reverse_inversion_with_labelled_assumptions() -> None:
    claim = _claim()
    result = valuation(
        claim,
        price=150.0,
        assumptions={"cost_of_equity": 0.09, "long_run_growth": 0.03, "sustainable_roe": 0.12, "assumption_source": "book p. 104"},
    )
    central = result["central_owner_value_per_ec"]
    book_per_ec = 1000.0 / 4.0  # pools 100 + 50 + 250 over 4 certificates... owner pool is 400
    assert central["justified_pb"] == pytest.approx(1.5)  # book p. 104: 12 % ROE, 9 % COE, 3 % g
    assert central["value_per_ec"] == pytest.approx(1.5 * (400.0 / 4.0))
    assert central["assumption_source"] == "book p. 104"
    reverse = result["reverse"]
    assert reverse["implied_r"] == pytest.approx(0.03 + (150.0 / 100.0) * (0.09 - 0.03))  # eq. 5.32
    assert reverse["expectations_gap"] == pytest.approx(0.12 - reverse["implied_r"])
    # Without an assumption the section is unavailable with a reason, never a default number.
    missing = valuation(claim, price=150.0, assumptions={})
    assert missing["central_owner_value_per_ec"]["reason_code"] == "COST_OF_EQUITY_OR_GROWTH_ASSUMPTION_MISSING"
    assert book_per_ec > 0


def test_display_only_inputs_do_not_count_toward_coverage_and_carry_a_reason() -> None:
    analysis = analyse_sparebank_ec(
        {
            "facts": _facts_payload(),
            "known_at": "2025-03-01T00:00:00Z",
            "source_url": "synthetic",
            "jurisdiction": "NO",
            "legal_form": "savings_bank",
            "instrument_subtype": "equity_certificate",
        },
        decision_time="2025-04-01T00:00:00Z",
        price=150.0,
        bank_economics_evidence={"statements": _statements(), "cet1_ratio": 0.17},
        valuation_assumptions={"cost_of_equity": 0.10, "long_run_growth": 0.03},
    )
    axes = analysis.scorecard.axes
    funding = {row["id"]: row for row in axes["funding_deposit_franchise"]["inputs"]}
    assert funding["deposit_beta"]["scored"] is False
    assert funding["deposit_beta"]["reason"]  # plain-language reason for the missing figure
    assert axes["funding_deposit_franchise"]["coverage"] == pytest.approx(0.0)  # no scored funding input present here
    headroom = {row["id"]: row for row in axes["capital_liquidity_resilience"]["inputs"]}["cet1_headroom_pp"]
    assert headroom["value"] is None and "Pillar 3" in headroom["reason"]
    assert build_sparebank_scorecard  # public entry point stays importable


def _facts_payload() -> dict[str, object]:
    return {
        "ec_capital": {"available": True, "value": 100.0},
        "overkursfond": {"available": True, "value": 50.0},
        "utjevningsfond": {"available": True, "value": 250.0},
        "sparebankens_fond": {"available": True, "value": 600.0},
        "registered_ec_count": {"available": True, "value": 4.0},
        "ec_attributable_result": {"available": True, "value": 48.0},
    }


def _rows(tmp_path: Path) -> list[dict[str, object]]:
    known = "2025-05-08T00:00:00Z"
    entries = []
    for metric, cur, prior in (
        ("net_interest_income", 1100.0, 1000.0), ("operating_expenses", 400.0, 380.0), ("impairment_losses", 10.0, 30.0),
        ("loans_to_customers", 21000.0, 20000.0), ("deposits_from_customers", 15000.0, 14000.0), ("total_assets", 24000.0, 22000.0),
        ("equity", 2200.0, 2000.0), ("net_profit", 700.0, 600.0),
    ):
        for period, value in (("2024-12-31", cur), ("2023-12-31", prior)):
            entries.append({"instrument_id": "TEST", "canonical_metric": metric, "concept": metric, "value": value, "unit": "NOK", "currency": "NOK", "end": period, "known_at": known, "effective_at": period, "source_id": f"fixture:{metric}:{period}", "dimensions": ""})
    entries.append({"instrument_id": "TEST", "canonical_metric": "net_interest_income", "concept": "x", "value": 999999.0, "unit": "NOK", "currency": "NOK", "end": "2024-12-31", "known_at": known, "effective_at": "2024-12-31", "source_id": "fixture:dimensioned", "dimensions": '{"axis":"member"}'})
    frame = pd.DataFrame(entries)
    return _financial_rows_for_instrument(frame, "TEST", pd.Timestamp("2025-06-01T00:00:00Z"))


def test_statement_series_takes_current_and_prior_year_and_ignores_dimensioned_rows(tmp_path: Path) -> None:
    series = statement_series(_rows(tmp_path))
    assert series["period_end"] == "2024-12-31" and series["prior_period_end"] == "2023-12-31"
    assert series["current"]["net_interest_income"] == 1100.0  # not the dimensioned 999999
    assert series["prior"]["net_interest_income"] == 1000.0
    assert series["current"]["equity"] == 2200.0
    assert statement_series([]) == {}


def test_metric_facts_use_prior_year_comparatives_for_growth_and_cost_of_risk(tmp_path: Path) -> None:
    facts = {item.metric: item for item in _financial_metric_facts(_rows(tmp_path), object(), "2025-06-01T00:00:00Z")}
    assert facts["loan_growth"].value == pytest.approx(21000 / 20000 - 1)
    assert facts["deposit_growth"].value == pytest.approx(15000 / 14000 - 1)
    # CoR = impairment / average net loans (eq. 4.59), stated as a proxy for gross loans.
    assert facts["cost_of_risk"].value == pytest.approx(10.0 / ((21000 + 20000) / 2))
    assert "net_loans_proxy_for_gross_loans" in facts["cost_of_risk"].limitations
    assert facts["net_interest_margin"].value == pytest.approx(1100.0 / ((24000 + 22000) / 2))


def test_missing_gavefond_is_flagged_not_blocking_and_ec_result_is_derived_with_a_label() -> None:
    claim = _claim(gavefond={"available": False, "value": None})
    assert claim.claim_status == "resolved"
    assert "GAVEFOND_NOT_REPORTED" in claim.reason_codes
    facts = {key: dict(value, known_at="2025-03-01T00:00:00Z") for key, value in _facts_payload().items()}
    facts["ec_attributable_result"] = {"available": False, "value": None}
    derived = with_derived_owner_earnings(facts, {"period_end": "2024-12-31", "current": {"profit_attributable_to_owners": 200.0}})
    # eierbrok 400 / (400 + 600) = 40 % of 200 (book eq. 1.19, p. 12-13)
    assert derived["ec_attributable_result"]["value"] == pytest.approx(80.0)
    assert derived["ec_attributable_result"]["derived"] is True
    assert "derived" in derived["ec_attributable_result"]["source_locator"]
    # A reported EC result is never overwritten.
    assert with_derived_owner_earnings(_facts_payload(), {"current": {"net_profit": 1.0}})["ec_attributable_result"]["value"] == 48.0


def test_pillar3_figures_are_used_only_after_the_owner_confirms_them(tmp_path: Path) -> None:
    document = {"document_id": "doc1", "source_url": "https://example.test/p3.pdf", "title": "Pillar 3 2024", "sha256": "a" * 64, "period": "2024-12-31"}
    figures = [
        {"metric": "cet1_ratio_pct", "label": "CET1 ratio", "value": 17.0, "unit": "percent", "period": "2024-12-31", "page": 4, "printed_text": "CET1 ratio 17,0 %"},
        {"metric": "cet1_requirement_pct", "label": "CET1 requirement", "value": 15.5, "unit": "percent", "period": "2024-12-31", "page": 6, "printed_text": "Krav ren kjernekapital 15,5 %"},
        {"metric": "stage3_pct_gross_loans", "label": "Stage 3", "value": 0.8, "unit": "percent", "period": "2024-12-31", "page": 9, "printed_text": "Trinn 3 0,8 %"},
    ]
    queue = pillar3_queue.merge_extraction(tmp_path, "TEST", document, figures)
    assert {item["status"] for item in queue["figures"]} == {"pending"}
    assert pillar3_evidence(tmp_path, "TEST", "2030-01-01T00:00:00Z") == {}  # pending figures are never evidence
    by_metric = {item["metric"]: item["figure_id"] for item in queue["figures"]}
    pillar3_queue.decide(tmp_path, "TEST", by_metric["cet1_ratio_pct"], "confirmed", decided_at="2025-06-10T00:00:00Z")
    pillar3_queue.decide(tmp_path, "TEST", by_metric["cet1_requirement_pct"], "confirmed", decided_at="2025-06-10T00:00:00Z")
    pillar3_queue.decide(tmp_path, "TEST", by_metric["stage3_pct_gross_loans"], "rejected", decided_at="2025-06-10T00:00:00Z")
    # Point in time: a decision made on 2025-06-10 cannot inform a score dated before it.
    assert pillar3_evidence(tmp_path, "TEST", "2025-06-01T00:00:00Z") == {}
    evidence = pillar3_evidence(tmp_path, "TEST", "2025-07-01T00:00:00Z")
    assert evidence["cet1_ratio"] == pytest.approx(0.17) and evidence["cet1_requirement_ratio"] == pytest.approx(0.155)
    assert "credit" not in evidence  # the rejected Stage 3 figure is not used
    assert "page 4" in evidence["cet1_ratio_provenance"]["source_locator"]
    bank = build_bank_economics(evidence, bank_metrics=[])
    assert bank.resilience["headroom_pp"] == pytest.approx(1.5)  # eq. 1.17: 17.0 % actual minus 15.5 % required
    # Re-extraction never resets an owner decision.
    again = pillar3_queue.merge_extraction(tmp_path, "TEST", document, figures)
    assert {item["metric"]: item["status"] for item in again["figures"]}["cet1_ratio_pct"] == "confirmed"
