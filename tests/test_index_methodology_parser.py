from __future__ import annotations

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
