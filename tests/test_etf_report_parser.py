from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys
import time

import pytest

from etf_cockpit.parsers.etf_report import (
    REPORT_KINDS,
    configure_memory_limit,
    parse_etf_report,
    parse_etf_report_in_child,
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


def _hanging_child(*_args: object) -> None:
    time.sleep(30)


def _crashing_child(*_args: object) -> None:
    os._exit(71)


def _complete(kind: str) -> list[str]:
    title = {"prospectus": "ETF Prospectus", "annual_report": "Annual report", "half_year_report": "Half-year report"}[kind]
    return [
        f"{title}\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026\nLegal structure: Irish UCITS investment company",
        "Reporting period ended: 30 June 2026\nSecurities lending: Up to 50% of net assets.\nCollateral policy: Daily margining at 102%.\nOngoing charges: 0.22%\nNumber of holdings: 3612\nOperational risks: Depositary and settlement risk.",
    ]


@pytest.mark.parametrize("kind", REPORT_KINDS)
def test_three_explicit_kinds_return_page_bound_field_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"bounded local snapshot")
    _install_pdf(monkeypatch, _complete(kind))

    result = parse_etf_report(source, kind, expected_isin="IE00B4L5Y983")

    assert result.success is True
    record = result.records[0]
    assert record.document_kind == kind
    assert set(record.structured_fields) == {
        "fund_name", "isin", "document_date", "reporting_period_end", "legal_structure",
        "securities_lending", "collateral_policy", "ongoing_costs", "holdings_count", "operational_risks",
    }
    evidence = {item.field_name: item for item in record.field_evidence}
    assert evidence["legal_structure"].pages == (1,)
    assert evidence["securities_lending"].pages == (2,)
    assert evidence["operational_risks"].bounded_excerpt
    assert record.score_eligible is False
    assert record.execution_allowed is False


def test_missing_required_field_and_conflict_fail_closed_with_all_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "annual.pdf"
    source.write_bytes(b"annual report")
    _install_pdf(monkeypatch, [
        "Annual report\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026\nLegal structure: Unit trust",
        "Legal structure: Investment company\nReporting period ended: 30 June 2026",
    ])

    result = parse_etf_report(source, "annual_report", expected_isin="IE00B4L5Y983")

    legal = next(item for item in result.records[0].field_evidence if item.field_name == "legal_structure")
    assert result.success is False
    assert legal.status == "conflict"
    assert legal.candidates == ("Unit trust", "Investment company")
    assert legal.pages == (1, 2)


def test_language_template_and_page_bounds_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"report")
    _install_pdf(monkeypatch, ["Rapport annuel\nNom du fonds: Exemple"])
    assert parse_etf_report(source, "annual_report").warnings[0].code == "unsupported_language"

    _install_pdf(monkeypatch, _complete("prospectus"))
    bounded = parse_etf_report(source, "prospectus", max_pages=1)
    assert bounded.success is False
    assert "page_limit_applied" in {item.code for item in bounded.warnings}

    _install_pdf(monkeypatch, ["Factsheet\nFund name: Evidence ETF\nISIN: IE00B4L5Y983\nDocument date: 14 July 2026\nLegal structure: Irish UCITS"])
    mismatch = parse_etf_report(source, "prospectus")
    assert mismatch.success is False
    assert "template_mismatch" in {item.code for item in mismatch.warnings}


def test_bounded_child_returns_a_result_for_a_local_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "not-a-pdf.pdf"
    source.write_bytes(b"not a pdf")
    result = parse_etf_report_in_child(source, "prospectus", timeout_seconds=10, memory_limit_bytes=256 * 1024 * 1024)
    assert result.success is False
    assert result.parser_name == "etf_report"
    assert result.warnings


@pytest.mark.parametrize("child_target", [_hanging_child, _crashing_child])
def test_child_timeout_and_crash_fallback_hashes_only_with_bounded_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, child_target: object
) -> None:
    from etf_cockpit.parsers import etf_report

    source = tmp_path / "bounded.pdf"
    source.write_bytes(b"bounded fallback source")
    monkeypatch.setattr(etf_report, "_child_parse_entry", child_target)
    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(AssertionError("unbounded read_bytes")))

    result = parse_etf_report_in_child(source, "prospectus", timeout_seconds=0.2, max_file_bytes=1024)

    assert result.success is False
    assert result.source_sha256
    assert result.warnings[0].code == "resource_blocked"


def test_exported_child_api_rejects_oversized_file_before_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.parsers import etf_report

    source = tmp_path / "oversized.pdf"
    source.write_bytes(b"12345")
    monkeypatch.setattr(etf_report.mp, "get_context", lambda _method: (_ for _ in ()).throw(AssertionError("child spawned")))

    result = parse_etf_report_in_child(source, "prospectus", max_file_bytes=4)

    assert result.success is False
    assert result.warnings[0].code == "document_too_large"


def test_memory_limit_configuration_has_a_platform_specific_stdlib_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.parsers import etf_report

    assert etf_report.memory_limit_backend("posix") == "posix_rlimit_as"
    assert etf_report.memory_limit_backend("nt") == "windows_job_object"
    if sys.platform == "win32":
        pytest.skip("POSIX RLIMIT_AS setter is unavailable on Windows")
    import resource

    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _kind: (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    monkeypatch.setattr(resource, "setrlimit", lambda kind, values: calls.append((kind, values)))
    assert configure_memory_limit(128 * 1024 * 1024) == "posix_rlimit_as"
    assert calls == [(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))]
