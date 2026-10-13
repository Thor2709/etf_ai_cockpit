from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from etf_cockpit.analysis.sparebank.claim import build_claim_state
from etf_cockpit.parsers.sec_facts import statement_facts_from_esef
from scripts.import_official_filing import (
    _extract_ec_facts,
    _map_issuer_extension_qname,
    _write_ec_facts,
)

# Fixture value: SpareBank 1 SMN 2024 ESEF extension namespace (issuer tables now live in data, not code).
MING_EXTENSION_NAMESPACE = "http://aarsrapport.smn.no/2024"


PERIOD = "2024-12-31"
SHA256 = "a" * 64


def _record(
    concept: str,
    value: str,
    *,
    namespace: str = MING_EXTENSION_NAMESPACE,
    period_start: str | None = None,
    context_id: str = "ctx-2024",
    mapping_status: str = "unmapped_extension",
) -> SimpleNamespace:
    return SimpleNamespace(
        concept=concept,
        namespace=namespace,
        value=value,
        unit="NOK",
        period_start=period_start,
        period_end=PERIOD,
        context_id=context_id,
        source_location="report.xhtml",
        mapping_status=mapping_status,
        context_dimensions=(),
        consolidation_scope="consolidated",
        is_numeric=True,
    )


def _write(output: Path, facts: dict[str, dict[str, object]]) -> dict[str, object]:
    archive = SimpleNamespace(sha256=SHA256)
    _write_ec_facts(
        facts,
        output,
        archive,
        "MING",
        PERIOD,
        "2025-02-27T00:00:00Z",
        "official-filing-source",
    )
    return json.loads(output.read_text(encoding="utf-8"))


def test_extension_mapping_accepts_issuer_prefix_and_rejects_foreign_prefix() -> None:
    assert _map_issuer_extension_qname("sb1smn:DividendEqualizationFund") == "utjevningsfond"
    assert _map_issuer_extension_qname("foreign:DividendEqualizationFund") is None

    mapped = statement_facts_from_esef(
        (_record("DividendEqualizationFund", "872100000"),),
        instrument_id="MING",
        source_sha256=SHA256,
        extension_namespace=MING_EXTENSION_NAMESPACE,
        extension_mappings={"DividendEqualizationFund": "utjevningsfond"},
    )[0]
    foreign = statement_facts_from_esef(
        (_record("DividendEqualizationFund", "872100000", namespace="http://foreign.example/2024"),),
        instrument_id="MING",
        source_sha256=SHA256,
        extension_namespace=MING_EXTENSION_NAMESPACE,
        extension_mappings={"DividendEqualizationFund": "utjevningsfond"},
    )[0]
    assert mapped.canonical_metric == "utjevningsfond"
    assert foreign.canonical_metric is None


def test_ec_pool_facts_are_written_with_provenance(tmp_path: Path) -> None:
    records = (
        _record("IssuedCapital", "2884000000", namespace="https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-full", mapping_status="mapped"),
        _record("SharePremium", "2422000000", namespace="https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-full", mapping_status="mapped"),
        _record("DividendEqualizationFund", "8721000000"),
        _record("OwnerlessCapital", "6984000000"),
        _record("GiftsAllocation", "896000000"),
        _record("EgenkapitalbeviseiernesAndelAvPeriodensResultat", "2970000000", period_start="2024-01-01"),
    )
    extracted = _extract_ec_facts(records, instrument_id="MING", period=PERIOD, sha256=SHA256)
    payload = _write(tmp_path / "ec_facts.json", extracted)

    fact = payload["facts"]["utjevningsfond"]
    assert fact["available"] is True
    assert fact["value"] == "8721000000"
    assert fact["concept"] == "sb1smn:DividendEqualizationFund"
    assert fact["context"] == "ctx-2024"
    assert fact["unit"] == "NOK"
    assert fact["period"] == PERIOD
    assert fact["sha256"] == SHA256


def test_unreported_input_stays_none_not_zero(tmp_path: Path) -> None:
    payload = _write(tmp_path / "ec_facts.json", {})

    fact = payload["facts"]["kompensasjonsfond"]
    assert fact["available"] is False
    assert fact["value"] is None


def test_gavefond_uses_cited_equity_pool_and_not_gifts_allocation(tmp_path: Path) -> None:
    provision_fact = _extract_ec_facts(
        (_record("GiftsAllocation", "896000000"),),
        instrument_id="MING",
        period=PERIOD,
        sha256=SHA256,
    )
    assert "gavefond" not in provision_fact
    unavailable_payload = _write(tmp_path / "unavailable_ec_facts.json", provision_fact)
    unavailable = unavailable_payload["facts"]["gavefond"]
    assert unavailable["available"] is False
    assert unavailable["value"] is None
    assert "not substituted" in unavailable["unavailable_reason"]

    equity_pool_fact = {
        "gavefond": {
            "value": "25",
            "source_locator": "synthetic:equity-statement-gavefond-pool",
            "concept": "synthetic:equity-statement-gavefond-pool",
            "context": "synthetic-equity-statement-context",
            "unit": "NOK",
            "period": PERIOD,
        }
    }
    payload = _write(tmp_path / "ec_facts.json", equity_pool_fact)
    fact = payload["facts"]["gavefond"]
    assert fact["available"] is True
    assert fact["value"] == "25"
    assert fact["source_locator"] == "synthetic:equity-statement-gavefond-pool"


def test_synthetic_pool_import_resolves_claim(tmp_path: Path) -> None:
    pools = {
        "ec_capital": "10",
        "overkursfond": "20",
        "utjevningsfond": "30",
        "sparebankens_fond": "15",
        "gavefond": "25",
        "kompensasjonsfond": "5",
        "ec_attributable_result": "2",
    }
    supplied = {
        name: {
            "value": value,
            "source_locator": f"synthetic:{name}",
            "concept": f"synthetic:{name}",
            "context": "synthetic-context",
            "unit": "NOK",
            "period": PERIOD,
        }
        for name, value in pools.items()
    }
    payload = _write(tmp_path / "ec_facts.json", supplied)
    claim = build_claim_state(
        {
            "facts": payload["facts"],
            "instrument_id": "MING",
            "source_id": "synthetic-source",
            "filing_version": SHA256,
            "known_at": "2025-02-27T00:00:00Z",
            "effective_at": PERIOD,
        },
        decision_time="2026-07-08T23:59:59Z",
    )

    assert claim.claim_status == "resolved"
    assert claim.reconstructed_eierbrok == 60 / 105
