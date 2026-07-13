from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

from etf_cockpit.parsers.priips_kid import parse_priips_kid


FIXTURE = Path("tests/fixtures/official/priips_kid/vanguard-ie000q4j3cw6-priips-kid.pdf")


def test_official_kid_extracts_identity_risk_and_holding_period() -> None:
    result = parse_priips_kid(FIXTURE, expected_isin="IE000Q4J3CW6")
    assert result.success is True
    record = result.records[0]
    assert record.isin == "IE000Q4J3CW6"
    assert record.sri == 4
    assert record.holding_period_years == 5
    assert record.document_date == "2026-04-14"
    assert record.source_sha256


def test_wrong_isin_is_a_controlled_failure(tmp_path: Path) -> None:
    result = parse_priips_kid(FIXTURE, expected_isin="IE0000000000")
    assert result.success is False
    assert result.records == ()
    assert any(item.code == "identity_mismatch" for item in result.warnings)


class _FakePdf:
    def __init__(self, pages: list[str]):
        self.pages = [SimpleNamespace(extract_text=lambda text=text: text) for text in pages]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _fake_pdfplumber(monkeypatch, pages: list[str]) -> None:
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: _FakePdf(pages)))


def test_missing_sri_and_malformed_cost_table_are_manual_review_with_page_warnings(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "kid.pdf"
    path.write_bytes(b"synthetic-kid")
    _fake_pdfplumber(
        monkeypatch,
        [
            "Key Information Document\nProduct: Example ETF\nIE000Q4J3CW6\nThis document is dated 14/04/2026.",
            "Recommended holding period: 5 years\nComposition of Costs\nEntry costs ??",
        ],
    )

    result = parse_priips_kid(path, expected_isin="IE000Q4J3CW6")

    assert result.records and result.success is False
    record = result.records[0]
    assert record.sri is None
    assert record.manual_review is True
    assert any(item.code == "sri_missing" and item.source_location == "page 1" for item in result.warnings)
    assert any(item.code == "cost_table_malformed" and item.source_location == "page 2" for item in result.warnings)
    assert record.source_pages == (1, 2)


def test_image_only_kid_is_explicitly_unavailable(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "image-only.pdf"
    path.write_bytes(b"%PDF-1.7 image")
    _fake_pdfplumber(monkeypatch, ["", ""])

    result = parse_priips_kid(path)

    assert result.success is False
    assert result.records == ()
    assert any(item.code == "image_only_document" for item in result.warnings)


def test_unsupported_language_is_manual_review(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "fr-kid.pdf"
    path.write_bytes(b"synthetic-kid")
    _fake_pdfplumber(monkeypatch, ["Document d'informations cles\nIE000Q4J3CW6"])

    result = parse_priips_kid(path, expected_isin="IE000Q4J3CW6")

    assert result.records and result.success is False
    assert any(item.code == "unsupported_language" for item in result.warnings)
