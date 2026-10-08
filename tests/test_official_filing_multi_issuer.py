from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from etf_cockpit.data.classification import read_instrument_context
from scripts.import_official_filing import NORWAY_ISSUER_TABLE, _validate_units, import_official_filing
from etf_cockpit.parsers.esef_ixbrl import XbrlFact


FIXTURE = Path(__file__).parent / "fixtures" / "official" / "esef_report_package" / "synthetic-ming-2025.xbri"
URL = "https://newsweb.oslobors.no/message/999999"
MING_LEI = "7V6Z97IO7R1SEAO84Q32"


def _import(output: Path, *, source: Path = FIXTURE, instrument_id: str = "MING", **kwargs: object) -> dict[str, object]:
    args: dict[str, object] = {
        "jurisdiction": "NO",
        "instrument_id": instrument_id,
        "source_url": URL,
        "expected_period": "2025-12-31",
        "published_at": "2026-03-05",
        "lei": MING_LEI,
        "output_dir": output,
    }
    args.update(kwargs)
    return import_official_filing(source, **args)  # type: ignore[arg-type]


def _fixture_for_issuer(path: Path, lei: str) -> Path:
    replaced = False
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename.lower().endswith((".xhtml", ".html")):
                payload, count = payload.replace(MING_LEI.encode("ascii"), lei.encode("ascii")), payload.count(MING_LEI.encode("ascii"))
                replaced = replaced or count > 0
            target.writestr(member, payload)
    assert replaced
    return path


def _fixture_with_scope_member(path: Path, member: str) -> Path:
    scope_markup = (
        '<xbrli:scenario><xbrldi:explicitMember dimension="'
        'ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">'
        f"{member}</xbrldi:explicitMember></xbrli:scenario>"
    ).encode("ascii")
    replaced = 0
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename.lower().endswith("reportpackage.json"):
                metadata = json.loads(payload.decode("utf-8"))
                metadata.pop("consolidationScope", None)
                payload = json.dumps(metadata).encode("utf-8")
            elif entry.filename.lower().endswith((".xhtml", ".html")):
                payload = payload.replace(
                    b"xmlns:ifrs-full=",
                    b'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:ifrs-full=',
                    1,
                )
                payload, count = payload.replace(
                    b"</xbrli:period></xbrli:context>",
                    b"</xbrli:period>" + scope_markup + b"</xbrli:context>",
                ), payload.count(b"</xbrli:period></xbrli:context>")
                replaced += count
            target.writestr(entry, payload)
    assert replaced
    return path


def test_nong_import_uses_issuer_table_identity_and_isin(tmp_path: Path) -> None:
    issuer = NORWAY_ISSUER_TABLE["NONG"]
    package = _fixture_for_issuer(tmp_path / "nong.xbri", str(issuer["lei"]))

    result = _import(tmp_path / "evidence", source=package, instrument_id="NONG", lei=issuer["lei"])

    identity = json.loads((tmp_path / "evidence" / "identity.json").read_text(encoding="utf-8"))
    assert issuer == {
        "ticker": "NONG",
        "isin": "NO0006000801",
        "name": "SpareBank 1 Nord-Norge",
        "lei": "549300SXM92LQ05OJQ76",
        "orgnr": None,
    }
    assert result["isin"] == "NO0006000801"
    assert identity["isin"] == "NO0006000801"
    assert identity["lei"] == issuer["lei"]
    assert identity["orgnr"] is None


def test_unknown_ticker_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown Norwegian issuer ticker"):
        _import(tmp_path / "unknown", instrument_id="UNKNOWN")


def test_issuer_table_lei_mismatch_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="LEI does not match the issuer table"):
        _import(tmp_path / "mismatch", lei="00000000000000000000")


def test_ticker_ol_suffix_normalises_to_bare_ticker(tmp_path: Path) -> None:
    result = _import(tmp_path / "ming", ticker="MING.OL")

    assert result["ticker"] == "MING"
    identity = json.loads((tmp_path / "ming" / "identity.json").read_text(encoding="utf-8"))
    assert identity["ticker"] == "MING"


def test_import_writes_financial_sector_classification(tmp_path: Path) -> None:
    _import(tmp_path)

    context = read_instrument_context(
        tmp_path,
        "MING",
        effective_at="2025-12-31T00:00:00Z",
        decision_time="2026-03-05T00:00:00Z",
    )

    assert context.sector == "financials"


def test_unknown_scope_axis_member_is_rejected(tmp_path: Path) -> None:
    package = _fixture_with_scope_member(tmp_path / "unknown-scope.xbri", "ifrs-full:UnknownMember")

    with pytest.raises(ValueError, match="filing consolidation scope is incomplete"):
        _import(tmp_path / "evidence", source=package)

    assert not (tmp_path / "evidence").exists()


def test_unitless_nonnumeric_facts_do_not_fail_unit_validation() -> None:
    narrative = XbrlFact(
        "7V6Z97IO7R1SEAO84Q32", "Disclosure", "Text", None, None, "c", None, None,
        "report.xhtml", "unmapped", is_numeric=False,
    )
    numeric = XbrlFact(
        "7V6Z97IO7R1SEAO84Q32", "Revenue", "100", None, "0", "c", None, None,
        "report.xhtml", "mapped",
    )
    amount = XbrlFact(
        "7V6Z97IO7R1SEAO84Q32", "Assets", "100", "NOK", "0", "c", None, None,
        "report.xhtml", "mapped",
    )
    per_share = XbrlFact(
        "7V6Z97IO7R1SEAO84Q32", "EarningsPerShare", "20", "AED/shares", "0", "c", None, None,
        "report.xhtml", "mapped",
    )

    _validate_units((narrative,))
    _validate_units((amount, per_share))
    with pytest.raises(ValueError, match="incomplete unit provenance"):
        _validate_units((numeric,))
