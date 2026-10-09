from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.analysis.sparebank import analyse_sparebank_ec
from etf_cockpit.analysis.sparebank.bank_economics import build_bank_economics
from scripts.import_official_filing import _load_fact_sheet, _write_ec_facts


PERIOD = "2024-12-31"
SHA256 = "a" * 64
FIXTURES = Path("tests/fixtures/sparebank")


def _metric(value: float, name: str, *, source_citations: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "value": value,
        "unit": "percent",
        "period": PERIOD,
        "end": PERIOD,
        "source_url": f"https://example.test/{name}.pdf",
        "document_title": f"Synthetic {name} source",
        "page": 4,
        "printed_text": f"Synthetic printed {name}: {value}%",
        "source_locator": f"synthetic:{name}:page-4",
        **({"source_citations": source_citations} if source_citations is not None else {}),
    }


def _write_facts(tmp_path: Path, supplied: dict[str, object]) -> dict[str, object]:
    sheet = tmp_path / "fact_sheet.json"
    sheet.write_text(json.dumps(supplied), encoding="utf-8")
    loaded = _load_fact_sheet(sheet)
    destination = tmp_path / "ec_facts.json"
    _write_ec_facts(
        loaded,
        destination,
        SimpleNamespace(sha256=SHA256),
        "MING",
        PERIOD,
        "2025-05-08T00:00:00Z",
        "https://example.test/annual-report.zip",
    )
    return json.loads(destination.read_text(encoding="utf-8"))


def _scorecard_fixture():
    return json.loads((FIXTURES / "teaching_bank.json").read_text(encoding="utf-8"))


def test_bank_metric_factsheet_values_reach_scorecard_inputs_with_provenance(tmp_path: Path) -> None:
    supplied = {
        "cet1_ratio_pct": _metric(18.3, "cet1"),
        "lcr_pct": _metric(183.0, "lcr"),
        "nsfr_pct": _metric(125.0, "nsfr"),
        "deposit_to_loan_ratio_pct": _metric(57.0, "deposit-to-loan"),
        "stage3_pct_gross_loans": _metric(0.89, "stage3"),
    }
    payload = _write_facts(tmp_path, supplied)
    revision = payload["revisions"][0]
    evidence = revision["bank_economics_evidence"]
    analysis = analyse_sparebank_ec(
        _scorecard_fixture(),
        decision_time="2026-10-09T00:00:00Z",
        bank_economics_evidence=evidence,
    )

    capital_inputs = analysis.scorecard.axes["capital_liquidity_resilience"]["inputs"]
    credit_inputs = analysis.scorecard.axes["credit_concentration"]["inputs"]
    funding_inputs = analysis.scorecard.axes["funding_deposit_franchise"]["inputs"]
    assert {row["id"]: row["value"] for row in capital_inputs}["lcr_pct"] == 183.0
    assert {row["id"]: row["value"] for row in capital_inputs}["nsfr_pct"] == 125.0
    assert {row["id"]: row["value"] for row in credit_inputs}["stage_3_ratio_pct"] == 0.89
    assert {row["id"]: row["value"] for row in funding_inputs}["deposit_to_loan_ratio_pct"] == pytest.approx(57.0)
    assert analysis.bank_economics.resilience["cet1_ratio"] == 0.183
    assert analysis.bank_economics.funding["provenance"]["lcr"]["source_locator"] == "synthetic:lcr:page-4"
    assert analysis.bank_economics.credit["provenance"]["stage_3_ratio_pct"]["source_locator"] == "synthetic:stage3:page-4"
    assert analysis.bank_economics.evidence_ids


def test_pillar3_nsfr_wins_and_both_source_citations_are_kept(tmp_path: Path) -> None:
    citations = [
        {
            "source_url": "https://example.test/pillar3.pdf",
            "source_locator": "synthetic:pillar3:page-32",
            "printed_text": "Pillar 3 reports NSFR 119.8%.",
        },
        {
            "source_url": "https://example.test/annual-report.zip",
            "source_locator": "synthetic:annual-report:nsfr-row",
            "printed_text": "Annual report reports NSFR 117%.",
        },
    ]
    payload = _write_facts(tmp_path, {"nsfr_pct": _metric(119.8, "nsfr", source_citations=citations)})

    fact = payload["facts"]["nsfr_pct"]
    evidence = payload["revisions"][0]["bank_economics_evidence"]
    bank = build_bank_economics(evidence)
    assert fact["value"] == 119.8
    assert fact["source_citations"] == citations
    assert bank.funding["nsfr"] == 1.198
    assert bank.funding["provenance"]["nsfr"]["source_citations"] == citations


def test_missing_bank_metric_stays_none_and_is_not_zero_filled(tmp_path: Path) -> None:
    payload = _write_facts(tmp_path, {})

    for name in ("cet1_ratio_pct", "lcr_pct", "nsfr_pct", "deposit_to_loan_ratio_pct", "stage3_pct_gross_loans"):
        assert payload["facts"][name]["available"] is False
        assert payload["facts"][name]["value"] is None
    assert payload["revisions"][0]["bank_economics_evidence"] == {}
