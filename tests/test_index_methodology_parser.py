from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

from etf_cockpit.parsers.index_methodology import parse_index_methodology


FIXTURE = Path("tests/fixtures/official/index_methodology/ftse-global-equity-index-series-ground-rules.pdf")


def test_official_methodology_extracts_version_provider_and_review_terms() -> None:
    result = parse_index_methodology(FIXTURE, "FTSE Russell")
    assert result.success is True
    record = result.records[0]
    assert record.provider == "FTSE Russell"
    assert record.version == "14.2"
    assert "FTSE Global Equity" in record.index_series
    assert record.source_pages


def test_empty_pdf_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF")
    result = parse_index_methodology(path, "FTSE Russell")
    assert result.success is False
    assert any(item.code == "empty_document" for item in result.warnings)


class _FakePdf:
    def __init__(self, pages: list[str]):
        self.pages = [SimpleNamespace(extract_text=lambda text=text: text) for text in pages]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _fake_pdfplumber(monkeypatch, pages: list[str]) -> None:
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: _FakePdf(pages)))


def test_missing_version_and_date_are_manual_review_with_source_pages(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "methodology.pdf"
    path.write_bytes(b"synthetic-methodology")
    _fake_pdfplumber(monkeypatch, ["FTSE Global Equity Index Series\nInclusion criteria and eligible securities."])

    result = parse_index_methodology(path, "FTSE Russell")

    assert result.records and result.success is False
    record = result.records[0]
    assert record.version is None and record.document_date is None
    assert record.manual_review is True
    assert record.source_pages == (1,)
    assert {item.code for item in result.warnings} >= {"methodology_version_missing", "methodology_date_missing"}


def test_unknown_provider_and_index_are_not_accepted(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "methodology.pdf"
    path.write_bytes(b"synthetic-methodology")
    _fake_pdfplumber(monkeypatch, ["Some unrelated benchmark rules\nv1.0\nJanuary 2026"])

    result = parse_index_methodology(path, "Unknown Provider")

    assert result.records and result.success is False
    assert result.records[0].manual_review is True
    assert {item.code for item in result.warnings} >= {"unknown_provider", "unknown_index"}


def test_methodology_conflict_warning_is_retained(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "methodology.pdf"
    path.write_bytes(b"synthetic-methodology")
    _fake_pdfplumber(
        monkeypatch,
        ["FTSE Global Equity Index Series v14.2\nJuly 2026\nconflict with holdings: cap 5%"],
    )

    result = parse_index_methodology(path, "FTSE Russell")

    assert result.records and any(item.code == "methodology_holdings_conflict" for item in result.warnings)
