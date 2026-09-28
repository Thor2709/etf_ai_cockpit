from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_cockpit.analysis.sparebank import analyse_sparebank_ec
from etf_cockpit.analysis.sparebank.bank_economics import (
    capital_resilience,
    credit_reconciliation,
    deposit_beta,
    normalisation_bridge,
)


FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"


def _fixture() -> dict[str, object]:
    return json.loads((FIXTURES / "bank_economics.json").read_text(encoding="utf-8"))


def test_normalisation_and_pre_tax_goldens_reconcile() -> None:
    values = _fixture()["normalisation"]
    result = normalisation_bridge(values["reported"], [{"amount": value} for value in values["adjustments"]], equity_denominator=values["equity"], reported_pre_tax=values["reported_pre_tax"], pre_tax_adjustments=values["pre_tax_adjustments"], ec_share=values["ec_share"], ec_count=4)
    assert result.normalised == pytest.approx(99)
    assert result.normalised_pre_tax == pytest.approx(132)
    assert result.normalised_roe == pytest.approx(0.099)
    assert result.ec_eps == pytest.approx(9.9)


def test_stage_denominator_and_writeoff_are_separate() -> None:
    values = _fixture()["credit"]
    credit = {key: value for key, value in values.items() if key != "stage2"}
    result = credit_reconciliation(**credit, stage2_open=values["stage2"], stage2_close=values["stage2"])
    assert result.ratio_open == pytest.approx(0.1)
    assert result.ratio_close == pytest.approx(1 / 12)
    assert result.ratio_numerator_effect == pytest.approx(0)
    assert result.ratio_denominator_effect == pytest.approx(-1 / 60)
    assert result.writeoff_net_exposure == pytest.approx(75)
    assert result.new_expense_from_writeoff == pytest.approx(0)


def test_capital_golden_and_rwa_attribution() -> None:
    result = capital_resilience(1000, 110, 260, 5700, 0.17)
    assert result.closing_cet1 == pytest.approx(850)
    assert result.closing_ratio == pytest.approx(0.149122807)
    assert result.shortfall_nok == pytest.approx(-119)
    assert result.loss_capacity_to_target == pytest.approx(141)


def test_funding_beta_and_regulatory_missing_fields_fail_closed() -> None:
    unavailable = deposit_beta(0.02, 0.04)
    assert unavailable.status == "unavailable"
    resolved = deposit_beta(0.02, 0.04, reference_rate="NIBOR", window="2024", population="retail deposits")
    assert resolved.deposit_beta == pytest.approx(0.5)


def test_production_suite_populates_bank_economics() -> None:
    evidence = {"jurisdiction": "NO", "legal_form": "savings_bank", "instrument_subtype": "equity_certificate", "facts": {"ec_capital": 400, "sparebankens_fond": 600}}
    result = analyse_sparebank_ec(evidence, bank_metrics=({"metric": "cet1_ratio", "value": 0.18},))
    assert result.bank_economics.status == "partial"
    assert result.bank_economics.reported["metrics"]["cet1_ratio"] == pytest.approx(0.18)
