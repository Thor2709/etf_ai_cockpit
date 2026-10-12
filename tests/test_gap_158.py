from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from etf_cockpit.parsers.etf_report import (
    REPORT_KINDS,
    available_report_plugins,
    parse_etf_report,
)


class _Page:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class _Pdf:
    def __init__(self, pages: list[str]) -> None:
        self.pages = [_Page(page) for page in pages]

    def __enter__(self) -> _Pdf:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _install_pdf(monkeypatch: pytest.MonkeyPatch, pages: list[str]) -> None:
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: _Pdf(pages)))


def _complete_report(kind: str) -> list[str]:
    title = {
        "prospectus": "ETF Prospectus",
        "annual_report": "Annual report",
        "half_year_report": "Half-year report",
    }[kind]
    return [
        f"{title}\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026\nLegal structure: Irish UCITS investment company",
        "Reporting period ended: 30 June 2026",
    ]


def test_only_the_three_registered_english_report_kinds_are_advertised() -> None:
    plugins = available_report_plugins()

    assert {plugin.document_kind for plugin in plugins} == set(REPORT_KINDS)
    assert len(plugins) == len(REPORT_KINDS)
    assert {plugin.language for plugin in plugins} == {"en"}


@pytest.mark.parametrize("kind", REPORT_KINDS)
def test_synthetic_supported_templates_return_page_bound_required_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    source = tmp_path / "synthetic-report.pdf"
    source.write_bytes(b"synthetic report fixture")
    _install_pdf(monkeypatch, _complete_report(kind))

    result = parse_etf_report(source, kind, expected_isin="IE00B4L5Y983")

    assert result.success is True
    record = result.records[0]
    assert record.document_kind == kind
    assert record.structured_fields["fund_name"] == "Evidence ETF"
    evidence = {item.field_name: item for item in record.field_evidence}
    assert evidence["fund_name"].status == "extracted"
    assert evidence["fund_name"].value == "Evidence ETF"
    assert evidence["fund_name"].pages == (1,)
    assert record.score_eligible is False
    assert record.execution_allowed is False


def test_unsupported_language_returns_no_parsed_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "unsupported-language.pdf"
    source.write_bytes(b"synthetic report fixture")
    _install_pdf(monkeypatch, ["Rapport annuel\nNom du fonds: Exemple"])

    result = parse_etf_report(source, "annual_report")

    assert result.success is False
    assert result.records == ()
    assert result.warnings[0].code == "unsupported_language"


def test_missing_required_and_optional_evidence_is_unavailable_with_a_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "incomplete-report.pdf"
    source.write_bytes(b"synthetic report fixture")
    _install_pdf(monkeypatch, [
        "Annual report\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026",
    ])

    result = parse_etf_report(source, "annual_report")

    assert result.success is False
    record = result.records[0]
    evidence = {item.field_name: item for item in record.field_evidence}
    assert record.structured_fields["legal_structure"] is None
    assert evidence["legal_structure"].value is None
    assert evidence["legal_structure"].status == "unavailable"
    assert evidence["exposure"].value is None
    assert evidence["exposure"].status == "unavailable"
    reasons = {warning.code for warning in result.warnings}
    assert "required_field_missing" in reasons
    assert "field_evidence_unavailable" in reasons
